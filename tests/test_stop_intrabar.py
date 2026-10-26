"""
Unit tests for Conservative Intrabar Stop and Gap Stop Rules.

Tests that:
1. When an entry bar also touches the stop level, it is assumed stopped out immediately.
2. When a bar opens beyond the stop level, it exits at the open price, not the stop price.
"""

from datetime import date
import pandas as pd
import pytest

from src.costs.calculator import CostCalculator
from src.engine.simulator import IntradaySimulator
from src.strategy.config import StrategyConfig
from src.strategy.ranking import DailyCandidate


def test_conservative_intrabar_stop_on_entry_bar():
    """If the entry bar touches the stop, conservative rule assumes stopped out immediately."""
    config = StrategyConfig(or_minutes=5, stop_atr=0.10, conservative_intrabar=True)
    calc = CostCalculator()
    sim = IntradaySimulator(config, calc)

    today = date(2026, 1, 15)
    cand = DailyCandidate(
        date=today,
        symbol="TESTINTRABAR",
        direction="LONG",
        rvol=2.0,
        or_high=500.0,
        or_low=490.0,
        or_open=492.0,
        or_close=498.0,
        or_volume=100000.0,
        atr14_known=20.0,  # stop distance = 0.10 * 20 = 2.0 -> stop loss = 498.0
        avg_turnover_20d_cr=120.0,
        prev_close=490.0,
    )

    times = pd.date_range("2026-01-15 09:15", "2026-01-15 15:15", freq="5min")
    bars = []
    for ts in times:
        t_str = ts.strftime("%H:%M")
        if t_str == "09:15":
            bars.append({"open": 492.0, "high": 500.0, "low": 490.0, "close": 498.0, "volume": 100000})
        elif t_str == "09:20":
            # Entry occurs (high 502 >= 500), but within this same bar, price plunges to low 497.0!
            # Stop loss is 500.0 - 2.0 = 498.0. Since low (497) <= 498.0, intrabar stop must trigger!
            bars.append({"open": 499.0, "high": 502.0, "low": 497.0, "close": 501.0, "volume": 80000})
        elif t_str == "15:10":
            bars.append({"open": 520.0, "high": 525.0, "low": 519.0, "close": 524.0, "volume": 10000})
        else:
            # Even if price later rallied massively, conservative rule already exited!
            bars.append({"open": 505.0, "high": 515.0, "low": 504.0, "close": 510.0, "volume": 20000})

    df = pd.DataFrame(bars, index=times)
    trade = sim.simulate_candidate(candidate=cand, bars_df=df, sod_equity=100000.0)

    assert trade is not None
    assert trade.raw_entry_price == 500.0
    assert trade.stop_loss == 498.0
    # Must be stopped out on entry bar:
    assert trade.exit_reason == "STOP_LOSS"
    assert trade.raw_exit_price == 498.0
    assert trade.entry_time == "09:20:00"
    assert trade.exit_time == "09:20:00"
    assert trade.net_pnl < 0


def test_gap_open_beyond_stop():
    """If a subsequent bar opens beyond the stop, exit must be at open, not at the stop."""
    config = StrategyConfig(or_minutes=5, stop_atr=0.10)
    calc = CostCalculator()
    sim = IntradaySimulator(config, calc)

    today = date(2026, 1, 15)
    cand = DailyCandidate(
        date=today,
        symbol="TESTGAPSTOP",
        direction="LONG",
        rvol=2.0,
        or_high=1000.0,
        or_low=990.0,
        or_open=992.0,
        or_close=998.0,
        or_volume=50000.0,
        atr14_known=50.0,  # stop distance = 5.0 -> stop loss = 995.0
        avg_turnover_20d_cr=120.0,
        prev_close=990.0,
    )

    times = pd.date_range("2026-01-15 09:15", "2026-01-15 15:15", freq="5min")
    bars = []
    for ts in times:
        t_str = ts.strftime("%H:%M")
        if t_str == "09:15":
            bars.append({"open": 992.0, "high": 1000.0, "low": 990.0, "close": 998.0, "volume": 50000})
        elif t_str == "09:20":
            # Clean entry
            bars.append({"open": 999.0, "high": 1003.0, "low": 998.0, "close": 1001.0, "volume": 40000})
        elif t_str == "09:25":
            # FLASH CRASH GAP: opens at 990.0 (way below stop loss of 995.0)
            bars.append({"open": 990.0, "high": 992.0, "low": 985.0, "close": 988.0, "volume": 60000})
        else:
            bars.append({"open": 988.0, "high": 990.0, "low": 985.0, "close": 987.0, "volume": 10000})

    df = pd.DataFrame(bars, index=times)
    trade = sim.simulate_candidate(candidate=cand, bars_df=df, sod_equity=100000.0)

    assert trade is not None
    assert trade.stop_loss == 995.0
    # Must exit at open price (990.0), NOT 995.0!
    assert trade.raw_exit_price == 990.0
    assert trade.exit_reason == "GAP_STOP"
