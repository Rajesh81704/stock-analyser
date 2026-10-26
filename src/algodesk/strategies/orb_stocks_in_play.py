"""
Opening Range Breakout on Stocks in Play (ORB Reference Strategy).

Rules:
- Opening range: 5, 15, or 30 min (default 5m)
- RVOL: OR volume today / 14-day trailing OR volume average (shifted)
- Daily ATR(14) shifted by 1 day
- Liquidity filter: 20-day turnover >= Rs 20 Crore, price >= 50
- Rank eligible stocks by RVOL >= 1.0, keep Top N (default 5)
- Long on green OR candle, Short on red OR candle, skip Doji
- Stop entry at OR high/low, gap filled at open
- Stop loss: stop_atr * ATR14 (default 0.10)
- Conservative intrabar stop: if entry bar touches stop, exit immediately
- Time exit: close of last bar before 15:15 (15:10 IST)
"""

import math
from datetime import datetime, time
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from src.algodesk.strategies.base import BaseStrategy, OrderIntent


class ORBParameters(BaseModel):
    """Pydantic schema for ORB parameters."""
    or_minutes: int = Field(default=5, description="Duration of Opening Range in minutes (5, 15, or 30)")
    rvol_window: int = Field(default=14, description="Trailing trading days for RVOL baseline")
    min_rvol: float = Field(default=1.0, description="Minimum relative volume threshold")
    atr_window: int = Field(default=14, description="Daily ATR window (shifted 1 day)")
    stop_atr: float = Field(default=0.10, description="Stop distance multiplier = stop_atr * ATR14")
    min_turnover_cr: float = Field(default=20.0, description="Minimum trailing 20d turnover in Rs Crore")
    min_price: float = Field(default=50.0, description="Minimum previous day close price")
    top_n: int = Field(default=5, description="Max candidate stocks to trade per day")
    direction: str = Field(default="both", description="Trading direction: both, long_only, or short_only")
    risk_pct: float = Field(default=0.01, description="Risk percentage of SOD equity per trade (0.01 = 1%)")
    max_leverage: float = Field(default=5.0, description="Max gross leverage across all N slots")
    conservative_intrabar: bool = Field(default=True, description="Assume stop hit if entry bar touches stop")


class ORBStocksInPlay(BaseStrategy):
    """Reference Implementation of Opening Range Breakout on Stocks in Play."""

    name: str = "orb_stocks_in_play"
    version: str = "1.0.0"
    timeframe: str = "5m"
    description: str = "Intraday momentum breakout on high RVOL Nifty 500 equities with ATR stop loss."
    parameter_schema = ORBParameters

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.params = ORBParameters(**self.parameters)
        self._traded_today: Dict[str, bool] = {}
        self._candidates: List[str] = []

    def on_session_start(self, ctx):
        """Reset intraday trade ledger at start of each trading session."""
        self._traded_today.clear()
        self._candidates.clear()

    def select_universe(self, ctx) -> List[str]:
        """
        Ranks all eligible universe stocks by RVOL (>= 1.0) and selects the Top N.
        All filters strictly use precomputed point-in-time features known at market open.
        """
        all_symbols = ctx.get_available_symbols()
        eligible = []

        for sym in all_symbols:
            prev_close = ctx.get_daily_feature(sym, "prev_close")
            if prev_close is None or prev_close < self.params.min_price:
                continue

            turnover_cr = ctx.get_daily_feature(sym, "avg_turnover_20d_cr")
            if turnover_cr is None or turnover_cr < self.params.min_turnover_cr:
                continue

            atr = ctx.get_daily_feature(sym, "atr14_known")
            if atr is None or atr <= 0:
                continue

            rvol = ctx.get_daily_feature(sym, "rvol")
            if rvol is None or rvol < self.params.min_rvol:
                continue

            or_dir = ctx.get_daily_feature(sym, "or_direction")
            if or_dir not in ("LONG", "SHORT"):
                continue

            if self.params.direction == "long_only" and or_dir != "LONG":
                continue
            if self.params.direction == "short_only" and or_dir != "SHORT":
                continue

            eligible.append((sym, rvol))

        # Rank descending by RVOL
        eligible.sort(key=lambda x: x[1], reverse=True)
        self._candidates = [item[0] for item in eligible[: self.params.top_n]]
        return self._candidates

    def on_bar(self, ctx, symbol: str, bar: Dict[str, Any]) -> List[OrderIntent]:
        """
        Evaluates bar-by-bar execution logic:
        - Scans after OR duration
        - Stop order trigger at OR high/low with gap open handling
        - Sizing risk / stop distance capped by max leverage per slot
        - Stop-loss and 15:10 time exit
        """
        intents: List[OrderIntent] = []
        bar_time = ctx.current_time.time()

        # Check existing position
        pos = ctx.get_position(symbol)

        # 1. Manage Active Position (Exit Logic)
        if pos and pos.get("qty", 0) != 0:
            qty = abs(pos["qty"])
            side = "SELL" if pos["qty"] > 0 else "BUY"
            stop_loss = pos.get("stop_loss")
            open_price = float(bar["open"])
            high_price = float(bar["high"])
            low_price = float(bar["low"])
            close_price = float(bar["close"])

            # A. Check Stop-Loss
            if stop_loss is not None:
                if pos["qty"] > 0:  # Long Position
                    if low_price <= stop_loss:
                        # Gap open beyond stop
                        exit_price = open_price if open_price <= stop_loss else stop_loss
                        intents.append(
                            OrderIntent(
                                symbol=symbol,
                                side="SELL",
                                qty=qty,
                                order_type="MARKET",
                                price=exit_price,
                                reason="STOP_LOSS_HIT",
                                strategy_name=self.name,
                                timestamp=ctx.current_time,
                            )
                        )
                        return intents
                else:  # Short Position
                    if high_price >= stop_loss:
                        exit_price = open_price if open_price >= stop_loss else stop_loss
                        intents.append(
                            OrderIntent(
                                symbol=symbol,
                                side="BUY",
                                qty=qty,
                                order_type="MARKET",
                                price=exit_price,
                                reason="STOP_LOSS_HIT",
                                strategy_name=self.name,
                                timestamp=ctx.current_time,
                            )
                        )
                        return intents

            # B. Check Time Exit (15:10 IST)
            square_off_time = time(15, 10, 0)
            if bar_time >= square_off_time:
                intents.append(
                    OrderIntent(
                        symbol=symbol,
                        side=side,
                        qty=qty,
                        order_type="MARKET",
                        price=close_price,
                        reason="INTRADAY_TIME_EXIT_1510",
                        strategy_name=self.name,
                        timestamp=ctx.current_time,
                    )
                )
                return intents

            return intents

        # 2. Entry Logic (Only if candidate and not traded today)
        if symbol not in self._candidates or self._traded_today.get(symbol, False):
            return intents

        # Must be past OR cutoff
        or_start_min = 15 + self.params.or_minutes
        or_cutoff = time(9, or_start_min, 0) if or_start_min < 60 else time(10, or_start_min - 60, 0)
        cutoff_entry = time(14, 45, 0)

        if bar_time < or_cutoff or bar_time >= cutoff_entry:
            return intents

        or_high = ctx.get_daily_feature(symbol, "or_high")
        or_low = ctx.get_daily_feature(symbol, "or_low")
        or_dir = ctx.get_daily_feature(symbol, "or_direction")
        atr = ctx.get_daily_feature(symbol, "atr14_known")

        if or_high is None or or_low is None or atr is None or atr <= 0:
            return intents

        stop_dist = self.params.stop_atr * atr
        if stop_dist <= 0:
            return intents

        high = float(bar["high"])
        low = float(bar["low"])
        open_p = float(bar["open"])

        # Check Long Entry
        if or_dir == "LONG" and high >= or_high:
            raw_entry = open_p if open_p > or_high else or_high
            stop_loss = raw_entry - stop_dist

            # Conservative intrabar rule: if entry bar touched stop, ignore or exit
            if self.params.conservative_intrabar and low <= stop_loss:
                self._traded_today[symbol] = True
                return intents

            # Sizing
            risk_cap = ctx.equity * self.params.risk_pct
            qty_risk = math.floor(risk_cap / stop_dist)
            slot_cap = (ctx.equity * self.params.max_leverage) / self.params.top_n
            qty_lev = math.floor(slot_cap / raw_entry)
            qty = min(qty_risk, qty_lev)

            if qty >= 1:
                self._traded_today[symbol] = True
                intents.append(
                    OrderIntent(
                        symbol=symbol,
                        side="BUY",
                        qty=qty,
                        order_type="SL",
                        price=raw_entry,
                        trigger_price=or_high,
                        stop_loss=round(stop_loss, 2),
                        reason="ORB_LONG_BREAKOUT",
                        strategy_name=self.name,
                        timestamp=ctx.current_time,
                    )
                )

        # Check Short Entry
        elif or_dir == "SHORT" and low <= or_low:
            raw_entry = open_p if open_p < or_low else or_low
            stop_loss = raw_entry + stop_dist

            if self.params.conservative_intrabar and high >= stop_loss:
                self._traded_today[symbol] = True
                return intents

            risk_cap = ctx.equity * self.params.risk_pct
            qty_risk = math.floor(risk_cap / stop_dist)
            slot_cap = (ctx.equity * self.params.max_leverage) / self.params.top_n
            qty_lev = math.floor(slot_cap / raw_entry)
            qty = min(qty_risk, qty_lev)

            if qty >= 1:
                self._traded_today[symbol] = True
                intents.append(
                    OrderIntent(
                        symbol=symbol,
                        side="SELL",
                        qty=qty,
                        order_type="SL",
                        price=raw_entry,
                        trigger_price=or_low,
                        stop_loss=round(stop_loss, 2),
                        reason="ORB_SHORT_BREAKOUT",
                        strategy_name=self.name,
                        timestamp=ctx.current_time,
                    )
                )

        return intents
