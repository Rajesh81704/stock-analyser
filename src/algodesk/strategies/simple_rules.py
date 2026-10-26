"""
Declarative Simple Rules Strategy Engine for AlgoDesk.

Allows prototyping strategies purely through YAML condition definitions
on standard indicators (RSI, SMA, EMA, Breakouts) without writing Python.
"""

from typing import Any, Dict, List, Optional
import pandas as pd
from pydantic import BaseModel, Field

from src.algodesk.strategies.base import BaseStrategy, OrderIntent


class SimpleRulesStrategy(BaseStrategy):
    """
    Declarative Rule-Based Strategy.
    Parses indicator conditions from YAML and executes entry/exit rules.
    """

    name: str = "simple_rules"
    version: str = "1.0.0"
    timeframe: str = "5m"
    description: str = "Declarative indicator condition strategy driven purely by YAML config."

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.entry_rules = self.parameters.get("entry_rules", [])
        self.exit_rules = self.parameters.get("exit_rules", [])
        self.stop_loss_pct = float(self.parameters.get("stop_loss_pct", 0.01))
        self.target_pct = float(self.parameters.get("target_pct", 0.02))
        self.risk_pct = float(self.parameters.get("risk_pct", 0.01))

    def _calculate_indicator(self, series: pd.Series, indicator_name: str) -> Optional[float]:
        """Computes basic technical indicator value on historical series."""
        name = indicator_name.lower()
        if name == "close":
            return float(series.iloc[-1])
        if name.startswith("sma_"):
            p = int(name.split("_")[1])
            return float(series.rolling(p).mean().iloc[-1]) if len(series) >= p else None
        if name.startswith("ema_"):
            p = int(name.split("_")[1])
            return float(series.ewm(span=p).mean().iloc[-1]) if len(series) >= p else None
        if name.startswith("rsi_"):
            p = int(name.split("_")[1])
            if len(series) <= p + 1:
                return None
            delta = series.diff()
            gain = delta.clip(lower=0).rolling(p).mean()
            loss = (-delta.clip(upper=0)).rolling(p).mean()
            rs = gain / loss.replace(0, 1e-9)
            rsi = 100.0 - (100.0 / (1.0 + rs))
            return float(rsi.iloc[-1])
        return None

    def _evaluate_condition(self, condition: Dict[str, Any], history: pd.DataFrame) -> bool:
        """Evaluates a single condition like: {indicator: 'rsi_14', op: '<', value: 30}."""
        indicator = condition.get("indicator", "close")
        op = condition.get("op", "==")
        target_val = condition.get("value", 0.0)

        curr_val = self._calculate_indicator(history["close"], indicator)
        if curr_val is None:
            return False

        if op == "<":
            return curr_val < target_val
        elif op == "<=":
            return curr_val <= target_val
        elif op == ">":
            return curr_val > target_val
        elif op == ">=":
            return curr_val >= target_val
        elif op == "==":
            return curr_val == target_val
        return False

    def on_bar(self, ctx, symbol: str, bar: Dict[str, Any]) -> List[OrderIntent]:
        intents: List[OrderIntent] = []
        pos = ctx.get_position(symbol)

        # 1. Manage Active Position (Exit)
        if pos and pos.get("qty", 0) != 0:
            qty = abs(pos["qty"])
            side = "SELL" if pos["qty"] > 0 else "BUY"

            # Check time exit
            if ctx.current_time.hour == 15 and ctx.current_time.minute >= 10:
                intents.append(
                    OrderIntent(
                        symbol=symbol,
                        side=side,
                        qty=qty,
                        order_type="MARKET",
                        price=float(bar["close"]),
                        reason="SIMPLE_RULES_TIME_EXIT",
                        strategy_name=self.name,
                        timestamp=ctx.current_time,
                    )
                )
            return intents

        # 2. Check Entry Conditions
        history = ctx.get_history(symbol, n_bars=50)
        if len(history) < 20 or not self.entry_rules:
            return intents

        all_passed = True
        for cond in self.entry_rules:
            if not self._evaluate_condition(cond, history):
                all_passed = False
                break

        if all_passed:
            entry_price = float(bar["close"])
            stop_loss = entry_price * (1.0 - self.stop_loss_pct)
            intents.append(
                OrderIntent(
                    symbol=symbol,
                    side="BUY",
                    risk_pct=self.risk_pct,
                    order_type="MARKET",
                    price=entry_price,
                    stop_loss=round(stop_loss, 2),
                    target=round(entry_price * (1.0 + self.target_pct), 2),
                    reason="SIMPLE_RULES_ENTRY_CONDITIONS_MET",
                    strategy_name=self.name,
                    timestamp=ctx.current_time,
                )
            )

        return intents
