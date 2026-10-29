"""
Paper Broker Adapter for Simulated Real-Time Execution.

Simulates fills against live tick / bar prices applying exact Zerodha intraday
statutory transaction taxes, brokerages, and liquidity-tiered slippage.
Enforces Zerodha MIS margin unblocking and immediate capital recycling into new opportunities.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
from typing import Any, Callable, Dict, List, Optional
import uuid

from src.costs.calculator import CostCalculator, ZerodhaIntradayCostsConfig, CostBreakdown

logger = logging.getLogger(__name__)


@dataclass
class Position:
    symbol: str
    qty: int
    entry_price: float
    current_price: float
    stop_loss: Optional[float] = None
    target: Optional[float] = None
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    blocked_margin: float = 0.0
    entry_time: Optional[datetime] = None


class PaperBroker:
    """Simulated execution engine maintaining virtual portfolio and orders with Zerodha margin rules."""

    def __init__(self, initial_capital: float = 100000.0, leverage: float = 5.0):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.leverage = leverage
        self.positions: Dict[str, Position] = {}
        self.cost_calculator = CostCalculator(ZerodhaIntradayCostsConfig())
        self.trades_history: List[Dict] = []
        self.on_trade_closed_callbacks: List[Callable[[str, float], Any]] = []

    @property
    def equity(self) -> float:
        unrealized = sum(p.unrealized_pnl for p in self.positions.values())
        return round(self.cash + unrealized, 2)

    @property
    def total_blocked_margin(self) -> float:
        """Total margin currently blocked across all open positions."""
        return round(sum(p.blocked_margin for p in self.positions.values()), 2)

    @property
    def available_margin(self) -> float:
        """Margin available for opening new positions (Zerodha intraday MIS)."""
        return round(max(0.0, self.cash - self.total_blocked_margin), 2)

    @property
    def buying_power(self) -> float:
        """Total purchasing power based on available margin and leverage."""
        return round(self.available_margin * self.leverage, 2)

    def get_portfolio_state(self) -> Dict:
        return {
            "cash": round(self.cash, 2),
            "equity": round(self.equity, 2),
            "available_margin": self.available_margin,
            "total_blocked_margin": self.total_blocked_margin,
            "buying_power": self.buying_power,
            "leverage": self.leverage,
            "positions": {
                s: {
                    "qty": p.qty,
                    "entry_price": p.entry_price,
                    "current_price": p.current_price,
                    "stop_loss": p.stop_loss,
                    "target": p.target,
                    "unrealized_pnl": round(p.unrealized_pnl, 2),
                    "blocked_margin": p.blocked_margin,
                }
                for s, p in self.positions.items()
            },
        }

    def update_price(self, symbol: str, price: float):
        """Updates current price and unrealized P&L for open positions."""
        if symbol in self.positions:
            pos = self.positions[symbol]
            pos.current_price = price
            if pos.qty > 0:
                pos.unrealized_pnl = round(pos.qty * (price - pos.entry_price), 2)
            else:
                pos.unrealized_pnl = round(abs(pos.qty) * (pos.entry_price - price), 2)

    def execute_order(
        self,
        symbol: str,
        side: str,
        qty: int,
        price: float,
        stop_loss: Optional[float] = None,
        target: Optional[float] = None,
        trailing_turnover_cr: float = 120.0,
    ) -> Dict:
        """Executes a simulated buy or sell order applying Zerodha margin terms, slippage, and statutory fees."""
        side = side.upper()
        calc_side = "LONG" if side == "BUY" else "SHORT"

        # Calculate roundtrip costs and slippage
        breakdown = self.cost_calculator.calculate_roundtrip(
            side=calc_side,
            qty=qty,
            raw_entry_price=price,
            raw_exit_price=price,
            trailing_turnover_cr=trailing_turnover_cr,
        )

        fill_price = breakdown.effective_entry_price
        fill_time = datetime.now(timezone.utc)
        order_id = f"paper_ord_{uuid.uuid4().hex[:12]}"

        # 1. Opening a new position
        if symbol not in self.positions:
            blocked_margin = round((abs(qty) * fill_price) / self.leverage, 2)
            if self.available_margin < blocked_margin:
                logger.warning(
                    f"⛔ [PaperBrokerMarginGate] Insufficient margin for {symbol} {side} x{qty} @ ₹{fill_price:.2f}. "
                    f"Required: ₹{blocked_margin:,.2f}, Available: ₹{self.available_margin:,.2f}."
                )
                return {
                    "order_id": order_id,
                    "symbol": symbol,
                    "side": side,
                    "qty": qty,
                    "price": fill_price,
                    "status": "REJECTED",
                    "reason": f"Insufficient margin: Required ₹{blocked_margin:,.2f}, Available ₹{self.available_margin:,.2f}",
                    "costs": 0.0,
                }

            signed_qty = qty if side == "BUY" else -qty
            self.positions[symbol] = Position(
                symbol=symbol,
                qty=signed_qty,
                entry_price=fill_price,
                current_price=fill_price,
                stop_loss=stop_loss,
                target=target,
                blocked_margin=blocked_margin,
                entry_time=fill_time,
            )
            logger.info(
                f"🛒 [PaperBroker] Opened {side} {qty}x {symbol} @ ₹{fill_price:.2f}. "
                f"Blocked Margin ({self.leverage:.0f}x): ₹{blocked_margin:,.2f} | Remaining Available Margin: ₹{self.available_margin:,.2f}"
            )

        # 2. Closing or adjusting an existing position
        else:
            pos = self.positions[symbol]
            is_closing = (pos.qty > 0 and side == "SELL") or (pos.qty < 0 and side == "BUY")

            if is_closing:
                if pos.qty > 0:
                    gross_pnl = qty * (fill_price - pos.entry_price)
                    close_calc_side = "LONG"
                else:
                    gross_pnl = qty * (pos.entry_price - fill_price)
                    close_calc_side = "SHORT"

                cost_breakdown = self.cost_calculator.calculate_roundtrip(
                    side=close_calc_side,
                    qty=qty,
                    raw_entry_price=pos.entry_price,
                    raw_exit_price=fill_price,
                    trailing_turnover_cr=trailing_turnover_cr,
                )
                total_costs = cost_breakdown.total_costs
                net_pnl = round(gross_pnl - total_costs, 2)
                unblocked_margin = pos.blocked_margin
                margin_credit = round(unblocked_margin + net_pnl, 2)

                # Zerodha intraday equity MIS rule:
                # 100% of blocked margin is unblocked and net realized P&L is credited to cash
                self.cash = round(self.cash + net_pnl, 2)
                del self.positions[symbol]

                logger.info(
                    f"💰 [PaperBrokerZerodhaMarginRelease] Position {symbol} CLOSED. "
                    f"Unblocked Margin: ₹{unblocked_margin:,.2f} | Net P&L: ₹{net_pnl:+,.2f} | "
                    f"Total Credited to Margin: ₹{margin_credit:,.2f}. Available Margin: ₹{self.available_margin:,.2f}."
                )

                self.trades_history.append({
                    "symbol": symbol,
                    "side": side,
                    "qty": qty,
                    "entry_price": pos.entry_price,
                    "exit_price": fill_price,
                    "gross_pnl": round(gross_pnl, 2),
                    "costs": round(total_costs, 2),
                    "net_pnl": net_pnl,
                    "unblocked_margin": unblocked_margin,
                    "margin_credited": margin_credit,
                    "closed_at": fill_time,
                })

                # Immediately deploy released margin into new opportunities
                self._trigger_opportunity_recycling(closed_symbol=symbol, margin_credit=margin_credit)
            else:
                # Additional position in same direction
                additional_margin = round((abs(qty) * fill_price) / self.leverage, 2)
                if self.available_margin < additional_margin:
                    return {
                        "order_id": order_id,
                        "symbol": symbol,
                        "side": side,
                        "qty": qty,
                        "price": fill_price,
                        "status": "REJECTED",
                        "reason": f"Insufficient margin: Required ₹{additional_margin:,.2f}, Available ₹{self.available_margin:,.2f}",
                        "costs": 0.0,
                    }
                total_qty = pos.qty + (qty if side == "BUY" else -qty)
                pos.entry_price = round(((abs(pos.qty) * pos.entry_price) + (qty * fill_price)) / abs(total_qty), 2)
                pos.qty = total_qty
                pos.blocked_margin = round(pos.blocked_margin + additional_margin, 2)

        return {
            "order_id": order_id,
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "price": fill_price,
            "status": "COMPLETE",
            "filled_at": fill_time,
            "costs": breakdown.total_costs,
        }

    def _trigger_opportunity_recycling(self, closed_symbol: str, margin_credit: float):
        """Immediately deploys newly freed margin into new breakout/breakdown opportunities."""
        logger.info(
            f"🔄 [PaperBrokerRecycling] Margin of ₹{margin_credit:,.2f} released per Zerodha terms. "
            f"Immediately scanning for new breakout/breakdown opportunities..."
        )
        # 1. Fire custom registered callbacks
        for cb in self.on_trade_closed_callbacks:
            try:
                cb(closed_symbol, margin_credit)
            except Exception as cb_err:
                logger.debug(f"PaperBroker callback notice: {cb_err}")

        # 2. Trigger Daily Screener & Auto Trader if available
        try:
            from src.algodesk.automation.daily_screener_trader import daily_auto_trader
            new_opps = daily_auto_trader.scan_and_execute_intraday_opportunities()
            if new_opps:
                logger.info(
                    f"🚀 [PaperOpportunityDeployed] Deployed newly released margin into {len(new_opps)} new paper trade(s): "
                    f"{[t['symbol'] for t in new_opps]}"
                )
        except Exception as err:
            logger.debug(f"PaperBroker opportunity recycling notice: {err}")

    def flatten_all(self, current_prices: Dict[str, float]) -> List[Dict]:
        """Emergency flatten all active positions at current prices."""
        orders = []
        for sym, pos in list(self.positions.items()):
            p = current_prices.get(sym, pos.current_price)
            side = "SELL" if pos.qty > 0 else "BUY"
            res = self.execute_order(sym, side, abs(pos.qty), p)
            orders.append(res)
        return orders
