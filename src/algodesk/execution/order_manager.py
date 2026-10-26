"""
Single OrderManager: Central Gateway for Order Routing, Risk Veto, and Idempotency.

NON-NEGOTIABLE SAFETY MANDATES:
1. NO code path may call broker order endpoints except OrderManager.
2. Every order passes through RiskEngine. Orders rejected by RiskEngine are never sent.
3. Idempotent order tags prevent duplicate orders on retries or reconnects.
4. LIVE mode is strictly blocked unless all 3 safety gates are met.
"""

import hashlib
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from src.algodesk.config.settings import settings, ExecutionMode
from src.algodesk.execution.paper_broker import PaperBroker
from src.algodesk.risk.engine import RiskEngine

logger = logging.getLogger(__name__)


class OrderManager:
    """Central order execution manager enforcing risk checks, tags, and broker routing."""

    def __init__(
        self,
        risk_engine: RiskEngine,
        paper_broker: Optional[PaperBroker] = None,
        db_session=None,
    ):
        self.risk_engine = risk_engine
        self.paper_broker = paper_broker or PaperBroker()
        self.db = db_session

        self._processed_tags: set = set()
        self._order_ledger: Dict[str, Dict] = {}
        self._reconciliation_healthy: bool = True
        self._last_reconciliation_time: Optional[datetime] = None

    def generate_idempotent_tag(self, intent_id: str, symbol: str, side: str) -> str:
        """Generates a deterministic 16-character broker order tag."""
        raw = f"{intent_id}:{symbol}:{side}"
        h = hashlib.sha256(raw.encode()).hexdigest()[:12]
        return f"ad_{h}"

    def submit_order_intent(
        self,
        intent,
        mode: ExecutionMode = ExecutionMode.PAPER,
        strategy_live_enabled: bool = False,
        daily_confirmed: bool = False,
        last_quote_price: Optional[float] = None,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Processes an OrderIntent through Risk Engine and routes to Paper or Live broker.
        """
        now = datetime.utcnow()
        if not intent.intent_id:
            intent.intent_id = str(uuid.uuid4())

        tag = self.generate_idempotent_tag(intent.intent_id, intent.symbol, intent.side)

        # 1. Idempotency Check (Duplicate Intent Guard)
        if tag in self._processed_tags:
            return False, f"DUPLICATE: Order tag '{tag}' already executed. Ignoring duplicate intent.", {}

        # 2. Reconciliation Check
        if not self._reconciliation_healthy:
            return False, "HALTED: OrderManager in emergency halt due to reconciliation mismatch.", {}

        # 3. Risk Engine Validation
        portfolio_state = self.paper_broker.get_portfolio_state()
        approved, risk_reason = self.risk_engine.validate_order(
            intent=intent,
            current_time=now,
            portfolio_state=portfolio_state,
            last_quote_price=last_quote_price,
        )

        if not approved:
            logger.warning(f"Order rejected by Risk Engine: {risk_reason}")
            return False, risk_reason, {}

        # 4. Enforce Safety Gate if mode == LIVE
        if mode == ExecutionMode.LIVE:
            permitted, live_reason = settings.is_live_execution_permitted(
                strategy_live_enabled=strategy_live_enabled,
                daily_confirmed=daily_confirmed,
            )
            if not permitted:
                logger.warning(f"LIVE Execution blocked by Safety Gates: {live_reason}. Simulating in PAPER mode.")
                mode = ExecutionMode.PAPER

        # 5. Execute Order
        self._processed_tags.add(tag)

        if mode == ExecutionMode.PAPER or mode == ExecutionMode.BACKTEST:
            # Execute in Paper Broker
            exec_price = intent.price or last_quote_price or 100.0
            order_res = self.paper_broker.execute_order(
                symbol=intent.symbol,
                side=intent.side,
                qty=intent.qty or 1,
                price=exec_price,
                stop_loss=intent.stop_loss,
                target=intent.target,
            )
            order_res["tag"] = tag
            order_res["intent_id"] = intent.intent_id
            order_res["mode"] = mode.value
            self._order_ledger[tag] = order_res
            return True, "EXECUTED_PAPER", order_res

        elif mode == ExecutionMode.LIVE:
            # Under strict safety rules, KiteBroker live order placement is handled here
            # and is only reached if all 3 safety gates are met.
            return False, "LIVE_ORDER_GATEWAY: Live API execution requires VPS broker adapter initialization.", {}

        return False, "UNKNOWN_MODE", {}

    def reconcile_positions(self, broker_positions: Dict[str, int]) -> Tuple[bool, str]:
        """
        Compares internal portfolio positions with broker positions.
        On mismatch, halts new orders and activates alert.
        """
        internal_pos = {
            s: p["qty"] for s, p in self.paper_broker.get_portfolio_state()["positions"].items()
        }

        mismatches = []
        all_symbols = set(internal_pos.keys()).union(set(broker_positions.keys()))
        for sym in all_symbols:
            int_qty = internal_pos.get(sym, 0)
            brk_qty = broker_positions.get(sym, 0)
            if int_qty != brk_qty:
                mismatches.append(f"{sym}: internal={int_qty}, broker={brk_qty}")

        self._last_reconciliation_time = datetime.utcnow()

        if mismatches:
            self._reconciliation_healthy = False
            self.risk_engine.activate_kill_switch(
                f"Reconciliation Mismatch Detected: {', '.join(mismatches)}",
                actor="reconciliation_engine",
            )
            return False, f"MISMATCH: {'; '.join(mismatches)}"

        self._reconciliation_healthy = True
        return True, "RECONCILED: Internal positions match broker positions perfectly."
