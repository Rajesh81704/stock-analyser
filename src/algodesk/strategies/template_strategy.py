"""
Template Strategy for AlgoDesk.

Use this boilerplate to develop custom intraday strategies.
Drop your Python file into strategies_user/ and its YAML config into configs/.
"""

from typing import Any, Dict, List
from pydantic import BaseModel, Field

from src.algodesk.strategies.base import BaseStrategy, OrderIntent


class TemplateParameters(BaseModel):
    """Pydantic schema for your strategy's configurable parameters."""
    fast_period: int = Field(default=9, description="Fast moving average period")
    slow_period: int = Field(default=21, description="Slow moving average period")
    stop_pct: float = Field(default=0.01, description="Stop loss percentage (1%)")
    risk_pct: float = Field(default=0.01, description="Risk percentage of SOD equity per trade")


class TemplateStrategy(BaseStrategy):
    """
    Template Strategy.
    
    Guidelines:
    - Never import kiteconnect or place live orders directly.
    - All data access is via ctx (StrategyContext) with strict point-in-time guarantees.
    - Return a list of OrderIntent objects from on_bar().
    """

    name: str = "template_strategy"
    version: str = "1.0.0"
    timeframe: str = "5m"
    description: str = "Starter template demonstrating point-in-time context and OrderIntent emission."
    parameter_schema = TemplateParameters

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.params = TemplateParameters(**self.parameters)

    def select_universe(self, ctx) -> List[str]:
        """Optional daily universe selection filter."""
        # By default, trade all available universe stocks
        return ctx.get_available_symbols()[:5]

    def on_session_start(self, ctx):
        """Called at market open (09:15 IST). Reset daily state variables here."""
        pass

    def on_bar(self, ctx, symbol: str, bar: Dict[str, Any]) -> List[OrderIntent]:
        """
        Main execution logic evaluated on each bar close.
        Returns a list of OrderIntent instances.
        """
        intents: List[OrderIntent] = []
        pos = ctx.get_position(symbol)

        # 1. Manage Active Positions
        if pos and pos.get("qty", 0) != 0:
            # Example time exit at 15:10
            if ctx.current_time.hour == 15 and ctx.current_time.minute >= 10:
                side = "SELL" if pos["qty"] > 0 else "BUY"
                intents.append(
                    OrderIntent(
                        symbol=symbol,
                        side=side,
                        qty=abs(pos["qty"]),
                        order_type="MARKET",
                        price=float(bar["close"]),
                        reason="TEMPLATE_TIME_EXIT",
                        strategy_name=self.name,
                        timestamp=ctx.current_time,
                    )
                )
            return intents

        # 2. Entry Logic (Point-in-Time History)
        history = ctx.get_history(symbol, n_bars=30)
        if len(history) < self.params.slow_period:
            return intents

        # Example indicator computation: Fast EMA vs Slow EMA
        close = history["close"]
        fast_ema = close.ewm(span=self.params.fast_period).mean().iloc[-1]
        slow_ema = close.ewm(span=self.params.slow_period).mean().iloc[-1]

        # Long entry crossover condition
        if fast_ema > slow_ema and close.iloc[-2] <= close.ewm(span=self.params.slow_period).mean().iloc[-2]:
            entry_price = float(bar["close"])
            stop_loss = entry_price * (1.0 - self.params.stop_pct)
            intents.append(
                OrderIntent(
                    symbol=symbol,
                    side="BUY",
                    risk_pct=self.params.risk_pct,
                    order_type="MARKET",
                    price=entry_price,
                    stop_loss=round(stop_loss, 2),
                    reason="TEMPLATE_FAST_EMA_CROSSOVER",
                    strategy_name=self.name,
                    timestamp=ctx.current_time,
                )
            )

        return intents
