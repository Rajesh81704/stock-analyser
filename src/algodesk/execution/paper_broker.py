"""
Paper Broker Adapter for Simulated Real-Time Execution.

Simulates fills against live tick / bar prices applying exact Zerodha intraday
statutory transaction taxes, brokerages, and liquidity-tiered slippage.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional
import uuid

from src.costs.calculator import CostCalculator, ZerodhaIntradayCostsConfig, CostBreakdown


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


class PaperBroker:
    """Simulated execution engine maintaining virtual portfolio and orders."""

    def __init__(self, initial_capital: float = 100000.0):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.positions: Dict[str, Position] = {}
        self.cost_calculator = CostCalculator(ZerodhaIntradayCostsConfig())
        self.trades_history: List[Dict] = []

    @property
    def equity(self) -> float:
        unrealized = sum(p.unrealized_pnl for p in self.positions.values())
        return self.cash + unrealized

    def get_portfolio_state(self) -> Dict:
        return {
            "cash": self.cash,
            "equity": self.equity,
            "positions": {
                s: {
                    "qty": p.qty,
                    "entry_price": p.entry_price,
                    "current_price": p.current_price,
                    "stop_loss": p.stop_loss,
                    "target": p.target,
                    "unrealized_pnl": p.unrealized_pnl,
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
                pos.unrealized_pnl = pos.qty * (price - pos.entry_price)
            else:
                pos.unrealized_pnl = abs(pos.qty) * (pos.entry_price - price)

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
        """Executes a simulated buy or sell order applying slippage and fees."""
        # Calculate roundtrip costs and slippage
        breakdown = self.cost_calculator.calculate_roundtrip(
            side="LONG" if side == "BUY" else "SHORT",
            qty=qty,
            raw_entry_price=price,
            raw_exit_price=price,
            trailing_turnover_cr=trailing_turnover_cr,
        )

        fill_price = breakdown.effective_entry_price
        fill_time = datetime.utcnow()
        order_id = f"paper_ord_{uuid.uuid4().hex[:12]}"

        # Position updates
        if symbol not in self.positions:
            if side == "BUY":
                self.positions[symbol] = Position(
                    symbol=symbol,
                    qty=qty,
                    entry_price=fill_price,
                    current_price=fill_price,
                    stop_loss=stop_loss,
                    target=target,
                )
            else:
                self.positions[symbol] = Position(
                    symbol=symbol,
                    qty=-qty,
                    entry_price=fill_price,
                    current_price=fill_price,
                    stop_loss=stop_loss,
                    target=target,
                )
        else:
            pos = self.positions[symbol]
            # Closing position
            if (pos.qty > 0 and side == "SELL") or (pos.qty < 0 and side == "BUY"):
                # Realize P&L
                if pos.qty > 0:
                    gross_pnl = qty * (fill_price - pos.entry_price)
                else:
                    gross_pnl = qty * (pos.entry_price - fill_price)

                net_pnl = gross_pnl - breakdown.total_costs
                self.cash += net_pnl
                del self.positions[symbol]

                self.trades_history.append({
                    "symbol": symbol,
                    "side": side,
                    "qty": qty,
                    "entry_price": pos.entry_price,
                    "exit_price": fill_price,
                    "gross_pnl": gross_pnl,
                    "costs": breakdown.total_costs,
                    "net_pnl": net_pnl,
                    "closed_at": fill_time,
                })

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

    def flatten_all(self, current_prices: Dict[str, float]) -> List[Dict]:
        """Emergency flatten all active positions at current prices."""
        orders = []
        for sym, pos in list(self.positions.items()):
            p = current_prices.get(sym, pos.current_price)
            side = "SELL" if pos.qty > 0 else "BUY"
            res = self.execute_order(sym, side, abs(pos.qty), p)
            orders.append(res)
        return orders
