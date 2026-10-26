#!/usr/bin/env python3
"""
CLI Helper: Scaffold a new strategy and configuration.
Usage: python scripts/create_strategy.py --name my_strategy
"""

import argparse
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.algodesk.config.settings import settings


STRATEGY_TEMPLATE = '''"""
{class_name} Strategy.
Created via AlgoDesk Strategy Generator.
"""

from typing import Any, Dict, List
from pydantic import BaseModel, Field

from src.algodesk.strategies.base import BaseStrategy, OrderIntent


class {class_name}Params(BaseModel):
    """Configurable parameters for {strategy_name}."""
    fast_period: int = Field(default=9, description="Fast indicator period")
    slow_period: int = Field(default=21, description="Slow indicator period")
    risk_pct: float = Field(default=0.01, description="Risk pct of SOD equity per trade")
    stop_pct: float = Field(default=0.01, description="Stop loss percentage")


class {class_name}(BaseStrategy):
    """Custom User Strategy: {strategy_name}."""

    name: str = "{strategy_name}"
    version: str = "1.0.0"
    timeframe: str = "5m"
    description: str = "Custom strategy created by user."
    parameter_schema = {class_name}Params

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.params = {class_name}Params(**self.parameters)

    def select_universe(self, ctx) -> List[str]:
        """Filter daily candidates from available universe."""
        return ctx.get_available_symbols()[:5]

    def on_session_start(self, ctx):
        """Called at market open (09:15 IST)."""
        pass

    def on_bar(self, ctx, symbol: str, bar: Dict[str, Any]) -> List[OrderIntent]:
        """Evaluates entry/exit on each bar close."""
        intents: List[OrderIntent] = []
        pos = ctx.get_position(symbol)

        # 1. Manage Active Position Exit
        if pos and pos.get("qty", 0) != 0:
            if ctx.current_time.hour == 15 and ctx.current_time.minute >= 10:
                side = "SELL" if pos["qty"] > 0 else "BUY"
                intents.append(
                    OrderIntent(
                        symbol=symbol,
                        side=side,
                        qty=abs(pos["qty"]),
                        order_type="MARKET",
                        price=float(bar["close"]),
                        reason="TIME_EXIT_1510",
                        strategy_name=self.name,
                        timestamp=ctx.current_time,
                    )
                )
            return intents

        # 2. Entry Logic
        history = ctx.get_history(symbol, n_bars=30)
        if len(history) < self.params.slow_period:
            return intents

        close = history["close"]
        if close.iloc[-1] > close.iloc[-2]:
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
                    reason="{strategy_name}_BUY_TRIGGER",
                    strategy_name=self.name,
                    timestamp=ctx.current_time,
                )
            )

        return intents
'''

YAML_TEMPLATE = '''name: "{strategy_name}"
version: "1.0.0"
strategy_class: "{strategy_name}"
timeframe: "5m"
mode: "PAPER"
live_enabled: false

universe:
  source: "nifty500"
  min_turnover_cr: 20.0
  min_price: 50.0
  max_symbols_per_day: 5

parameters:
  fast_period: 9
  slow_period: 21
  risk_pct: 0.01
  stop_pct: 0.01

risk:
  risk_pct_per_trade: 0.01
  max_leverage: 5.0
  max_open_positions: 5
  entry_cutoff_time: "14:45:00"
  square_off_time: "15:10:00"
'''


def to_pascal_case(name: str) -> str:
    return "".join(word.capitalize() for word in name.replace("-", "_").split("_"))


def main():
    parser = argparse.ArgumentParser(description="Create a new AlgoDesk strategy scaffold.")
    parser.add_argument("--name", type=str, required=True, help="Strategy identifier (e.g. mean_reversion)")
    args = parser.parse_args()

    strat_name = args.name.strip().lower().replace("-", "_")
    class_name = to_pascal_case(strat_name)

    user_strat_dir = settings.strategies_user_dir
    user_strat_dir.mkdir(parents=True, exist_ok=True)
    configs_dir = settings.configs_dir
    configs_dir.mkdir(parents=True, exist_ok=True)

    py_file = user_strat_dir / f"{strat_name}.py"
    yaml_file = configs_dir / f"{strat_name}.yaml"

    if py_file.exists():
        print(f"[ERROR] Strategy file already exists: {py_file}", file=sys.stderr)
        sys.exit(1)

    py_content = STRATEGY_TEMPLATE.format(strategy_name=strat_name, class_name=class_name)
    with open(py_file, "w", encoding="utf-8") as f:
        f.write(py_content)

    yaml_content = YAML_TEMPLATE.format(strategy_name=strat_name)
    with open(yaml_file, "w", encoding="utf-8") as f:
        f.write(yaml_content)

    print("\n" + "=" * 65)
    print(f"🎉 NEW STRATEGY CREATED: {strat_name}")
    print("=" * 65)
    print(f"  • Strategy Code: {py_file}")
    print(f"  • Configuration: {yaml_file}")
    print("\nNext Steps:")
    print(f"  1. Edit logic in: {py_file}")
    print(f"  2. Tune parameters in: {yaml_file}")
    print(f"  3. Run backtest: python scripts/run_backtest.py --strategy {strat_name}")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
