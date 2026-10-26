"""
Intraday Trade Execution Simulator.

Simulates bar-by-bar execution for candidate stocks according to exact ORB rules:
- Stop entry at OR high/low with open gap fills
- Conservative intrabar stop assumption if entry bar touches stop
- Gap stop exit at open if market opens beyond stop
- 15:10 time exit before broker MIS square-off
- Sizing based on risk_pct and leverage cap per slot
"""

import math
from dataclasses import dataclass
from datetime import datetime, time
from typing import Optional, List
import pandas as pd

from src.costs.calculator import CostCalculator, CostBreakdown
from src.strategy.config import StrategyConfig
from src.strategy.ranking import DailyCandidate


@dataclass
class TradeRecord:
    """Complete record of an executed intraday trade."""
    date: str
    symbol: str
    side: str
    entry_time: str
    entry_price: float
    raw_entry_price: float
    exit_time: str
    exit_price: float
    raw_exit_price: float
    qty: int
    stop_loss: float
    gross_pnl: float
    costs: float
    net_pnl: float
    exit_reason: str          # 'STOP_LOSS', 'GAP_STOP', 'TIME_EXIT'
    rvol: float
    statutory_costs: float
    slippage_cost: float
    turnover: float
    return_pct: float


class IntradaySimulator:
    """Simulates intraday orders on 5-minute bars for a single candidate."""

    def __init__(self, config: StrategyConfig, cost_calculator: CostCalculator):
        self.config = config
        self.cost_calculator = cost_calculator

    def simulate_candidate(
        self,
        candidate: DailyCandidate,
        bars_df: pd.DataFrame,
        sod_equity: float,
        cost_multiplier: float = 1.0,
        slippage_multiplier: float = 1.0,
    ) -> Optional[TradeRecord]:
        """
        Simulates the trade lifecycle for a candidate on its trading day.
        Returns a TradeRecord if a trade was triggered and executed, else None.
        """
        # Filter bars for candidate's date
        day_bars = bars_df[bars_df.index.date == candidate.date]
        if day_bars.empty:
            return None

        # OR cutoff time: e.g. 09:15 + 5 mins = 09:20:00
        or_cutoff = (pd.to_datetime(self.config.market_open_time) + pd.Timedelta(minutes=self.config.or_minutes)).time()
        square_off_time = pd.to_datetime(self.config.square_off_time).time()

        # Bars available for scanning entry: start time >= or_cutoff
        scanning_bars = day_bars[day_bars.index.time >= or_cutoff]
        if scanning_bars.empty:
            return None

        side = candidate.direction
        trigger_price = candidate.or_high if side == "LONG" else candidate.or_low

        entry_bar_idx = None
        raw_entry_price = 0.0
        entry_timestamp = None

        # 1. Scan for entry
        for idx, (ts, bar) in enumerate(scanning_bars.iterrows()):
            # Do not enter at or after square-off time
            if ts.time() >= square_off_time:
                break

            if side == "LONG":
                if bar["high"] >= trigger_price:
                    # Gapped open above trigger vs regular touch
                    raw_entry_price = float(bar["open"]) if bar["open"] > trigger_price else float(trigger_price)
                    entry_bar_idx = idx
                    entry_timestamp = ts
                    break
            elif side == "SHORT":
                if bar["low"] <= trigger_price:
                    # Gapped open below trigger vs regular touch
                    raw_entry_price = float(bar["open"]) if bar["open"] < trigger_price else float(trigger_price)
                    entry_bar_idx = idx
                    entry_timestamp = ts
                    break

        if entry_bar_idx is None or raw_entry_price <= 0:
            return None  # No breakout occurred

        # 2. Stop-loss level
        stop_dist = self.config.stop_atr * candidate.atr14_known
        if stop_dist <= 0:
            return None

        if side == "LONG":
            stop_loss = raw_entry_price - stop_dist
        else:
            stop_loss = raw_entry_price + stop_dist

        # 3. Position Sizing
        # Risk capital = risk_pct * sod_equity
        risk_capital = sod_equity * self.config.risk_pct
        qty_from_risk = math.floor(risk_capital / stop_dist)

        # Max leverage per slot
        max_slot_capital = (sod_equity * self.config.max_leverage) / self.config.top_n
        qty_from_leverage = math.floor(max_slot_capital / raw_entry_price)

        qty = min(qty_from_risk, qty_from_leverage)
        if qty < 1:
            return None  # Position size too small to trade

        # 4. Intrabar check on entry bar (Conservative rule)
        entry_bar = scanning_bars.iloc[entry_bar_idx]
        is_stopped_out = False
        raw_exit_price = 0.0
        exit_timestamp = None
        exit_reason = ""

        if self.config.conservative_intrabar:
            if side == "LONG" and entry_bar["low"] <= stop_loss:
                is_stopped_out = True
                if entry_bar["open"] <= stop_loss:
                    raw_exit_price = float(entry_bar["open"])
                    exit_reason = "GAP_STOP"
                else:
                    raw_exit_price = float(stop_loss)
                    exit_reason = "STOP_LOSS"
                exit_timestamp = entry_timestamp
            elif side == "SHORT" and entry_bar["high"] >= stop_loss:
                is_stopped_out = True
                if entry_bar["open"] >= stop_loss:
                    raw_exit_price = float(entry_bar["open"])
                    exit_reason = "GAP_STOP"
                else:
                    raw_exit_price = float(stop_loss)
                    exit_reason = "STOP_LOSS"
                exit_timestamp = entry_timestamp

        # 5. Scan subsequent bars if not stopped out on entry bar
        if not is_stopped_out:
            remaining_bars = scanning_bars.iloc[entry_bar_idx + 1 :]
            for ts, bar in remaining_bars.iterrows():
                b_time = ts.time()

                # Check Stop Loss
                if side == "LONG":
                    if bar["low"] <= stop_loss:
                        is_stopped_out = True
                        if bar["open"] <= stop_loss:
                            raw_exit_price = float(bar["open"])
                            exit_reason = "GAP_STOP"
                        else:
                            raw_exit_price = float(stop_loss)
                            exit_reason = "STOP_LOSS"
                        exit_timestamp = ts
                        break
                elif side == "SHORT":
                    if bar["high"] >= stop_loss:
                        is_stopped_out = True
                        if bar["open"] >= stop_loss:
                            raw_exit_price = float(bar["open"])
                            exit_reason = "GAP_STOP"
                        else:
                            raw_exit_price = float(stop_loss)
                            exit_reason = "STOP_LOSS"
                        exit_timestamp = ts
                        break

                # Check Square-Off Time Exit (last bar before 15:15 is the 15:10 bar)
                if b_time >= square_off_time:
                    raw_exit_price = float(bar["close"])
                    exit_reason = "TIME_EXIT"
                    exit_timestamp = ts
                    break

            # If still open after all scanning bars, exit at final bar close
            if exit_timestamp is None:
                last_bar = scanning_bars.iloc[-1]
                raw_exit_price = float(last_bar["close"])
                exit_reason = "TIME_EXIT"
                exit_timestamp = scanning_bars.index[-1]

        # 6. Costs and Net P&L
        costs_breakdown = self.cost_calculator.calculate_roundtrip(
            side=side,
            qty=qty,
            raw_entry_price=raw_entry_price,
            raw_exit_price=raw_exit_price,
            trailing_turnover_cr=candidate.avg_turnover_20d_cr,
            cost_multiplier=cost_multiplier,
            slippage_multiplier=slippage_multiplier,
        )

        eff_entry = costs_breakdown.effective_entry_price
        eff_exit = costs_breakdown.effective_exit_price

        # Gross P&L before slippage and statutory costs:
        if side == "LONG":
            raw_gross_pnl = qty * (raw_exit_price - raw_entry_price)
        else:
            raw_gross_pnl = qty * (raw_entry_price - raw_exit_price)

        total_costs = costs_breakdown.total_costs
        net_pnl = raw_gross_pnl - total_costs
        turnover = costs_breakdown.turnover_total
        return_pct = (net_pnl / (qty * raw_entry_price)) * 100.0 if raw_entry_price > 0 else 0.0

        return TradeRecord(
            date=candidate.date.strftime("%Y-%m-%d"),
            symbol=candidate.symbol,
            side=side,
            entry_time=entry_timestamp.strftime("%H:%M:%S") if entry_timestamp else "",
            entry_price=round(eff_entry, 2),
            raw_entry_price=round(raw_entry_price, 2),
            exit_time=exit_timestamp.strftime("%H:%M:%S") if exit_timestamp else "",
            exit_price=round(eff_exit, 2),
            raw_exit_price=round(raw_exit_price, 2),
            qty=qty,
            stop_loss=round(stop_loss, 2),
            gross_pnl=round(raw_gross_pnl, 2),
            costs=round(total_costs, 2),
            net_pnl=round(net_pnl, 2),
            exit_reason=exit_reason,
            rvol=round(candidate.rvol, 2),
            statutory_costs=round(costs_breakdown.statutory_costs, 2),
            slippage_cost=round(costs_breakdown.slippage_cost, 2),
            turnover=round(turnover, 2),
            return_pct=round(return_pct, 4),
        )
