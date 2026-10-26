"""
AlgoDesk Risk Management & Kill Switch Engine.

Enforces strict risk limits, price band validation, order rate limiting,
entry cutoffs, and emergency kill switch functionality.
"""

from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class RiskLimits:
    """Configurable global and per-strategy risk limits."""
    max_daily_loss: float = 5000.0            # Hard daily loss stop in INR
    max_loss_per_trade: float = 1500.0        # Max permissible loss per trade
    max_open_positions: int = 5               # Max concurrent active positions
    max_notional_per_order: float = 200000.0  # Max value per order in INR
    max_orders_per_minute: int = 30           # Well below Zerodha Kite's 10 req/s limit
    entry_cutoff_time: time = time(14, 45, 0) # No new entries after 14:45 IST
    square_off_time: time = time(15, 10, 0)   # Mandatory intraday square off
    max_price_deviation_pct: float = 0.05     # Sanity check: price within 5% of last quote
    exclusion_list: List[str] = field(default_factory=list)


class RiskEngine:
    """Evaluates every OrderIntent and maintains global kill-switch status."""

    def __init__(self, limits: Optional[RiskLimits] = None):
        self.limits = limits or RiskLimits()
        self.kill_switch_active: bool = False
        self.kill_switch_reason: str = ""
        self.kill_switch_activated_at: Optional[datetime] = None

        self._order_timestamps: List[datetime] = []
        self._daily_realized_loss: float = 0.0
        self._open_positions_count: int = 0

    def activate_kill_switch(self, reason: str, actor: str = "user"):
        """Activates emergency kill switch: blocks all orders immediately."""
        self.kill_switch_active = True
        self.kill_switch_reason = f"[{actor.upper()}] {reason}"
        self.kill_switch_activated_at = datetime.utcnow()

    def reset_kill_switch(self, actor: str = "user"):
        """Resets the kill switch allowing trading to resume if conditions permit."""
        self.kill_switch_active = False
        self.kill_switch_reason = ""
        self.kill_switch_activated_at = None

    def record_pnl(self, realized_pnl: float):
        """Updates cumulative daily realized loss."""
        if realized_pnl < 0:
            self._daily_realized_loss += abs(realized_pnl)
            if self._daily_realized_loss >= self.limits.max_daily_loss:
                self.activate_kill_switch(
                    f"Max daily loss breached (Rs {self._daily_realized_loss:,.2f} >= Rs {self.limits.max_daily_loss:,.2f})",
                    actor="risk_engine",
                )

    def validate_order(
        self,
        intent,
        current_time: datetime,
        portfolio_state: Dict[str, Any],
        last_quote_price: Optional[float] = None,
    ) -> Tuple[bool, str]:
        """
        Validates an order intent against all risk rules.
        Returns (True, "APPROVED") or (False, "REJECTION_REASON").
        """
        # 1. Kill Switch
        if self.kill_switch_active:
            return False, f"VETO: Kill switch active ({self.kill_switch_reason})"

        # 2. Daily Loss Limit
        if self._daily_realized_loss >= self.limits.max_daily_loss:
            return False, f"VETO: Daily loss limit reached (Rs {self._daily_realized_loss:,.2f})"

        # 3. Exclusion List
        if intent.symbol in self.limits.exclusion_list:
            return False, f"VETO: Symbol '{intent.symbol}' is on the restricted exclusion list."

        # 4. Entry Cutoff Time
        t_curr = current_time.time()
        is_closing_order = intent.reason and ("EXIT" in intent.reason or "STOP" in intent.reason)
        if not is_closing_order and t_curr >= self.limits.entry_cutoff_time:
            return False, f"VETO: Current time {t_curr} past entry cutoff {self.limits.entry_cutoff_time} IST."

        # 5. Order Rate Limiter (orders per minute)
        now = current_time
        one_min_ago = now.timestamp() - 60
        self._order_timestamps = [ts for ts in self._order_timestamps if ts.timestamp() > one_min_ago]
        if len(self._order_timestamps) >= self.limits.max_orders_per_minute:
            return False, f"VETO: Order rate limit exceeded ({len(self._order_timestamps)} orders in last 60s)."

        # 6. Max Open Positions (for new entries)
        positions = portfolio_state.get("positions", {})
        active_positions_count = len([p for p in positions.values() if p.get("qty", 0) != 0])
        if not is_closing_order and active_positions_count >= self.limits.max_open_positions:
            return False, f"VETO: Max open positions limit reached ({active_positions_count}/{self.limits.max_open_positions})."

        # 7. Notional Limit
        order_price = intent.price or last_quote_price or 100.0
        qty = intent.qty or 1
        notional = qty * order_price
        if notional > self.limits.max_notional_per_order:
            return False, f"VETO: Order notional Rs {notional:,.2f} exceeds cap Rs {self.limits.max_notional_per_order:,.2f}."

        # 8. Price Band Sanity Check
        if last_quote_price and order_price:
            deviation = abs(order_price - last_quote_price) / last_quote_price
            if deviation > self.limits.max_price_deviation_pct:
                return False, f"VETO: Order price Rs {order_price:.2f} deviates {deviation*100:.1f}% from last tick Rs {last_quote_price:.2f}."

        # Record timestamp of approved order
        self._order_timestamps.append(now)
        return True, "APPROVED"
