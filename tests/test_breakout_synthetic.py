"""
Unit tests for Synthetic Deterministic Breakout Execution.

Tests that a known breakout pattern triggers exactly at the expected price,
assigns the correct stop level, and executes the expected exit.
"""

from datetime import date
import pandas as pd
import pytest

from src.costs.calculator import CostCalculator
from src.engine.simulator import IntradaySimulator
from src.strategy.config import StrategyConfig
from src.strategy.ranking import DailyCandidate


def test_deterministic_long_breakout():
    """A known long breakout scenario produces expected entry price, stop, and time exit."""
    config = StrategyConfig(or_minutes=5, stop_atr=0.10)
    calc = CostCalculator()
    sim = IntradaySimulator(config, calc)

    today = date(2026, 1, 15)

    # Candidate with known OR High = 105.0, ATR14 = 10.0 -> Stop dist = 1.0
    cand = DailyCandidate(
        date=today,
        symbol="TESTSTOCK",
        direction="LONG",
        rvol=2.5,
        or_high=105.0,
        or_low=99.0,
        or_open=100.0,
        or_close=104.0,
        or_volume=100000.0,
        atr14_known=10.0,
        avg_turnover_20d_cr=150.0,
        prev_close=100.0,
    )

    # Construct synthetic bars
    times = pd.date_range("2026-01-15 09:15", "2026-01-15 15:15", freq="5min")
    bars = []
    for ts in times:
        t_str = ts.strftime("%H:%M")
        if t_str == "09:15":
            # OR Bar
            bars.append({"open": 100.0, "high": 105.0, "low": 99.0, "close": 104.0, "volume": 100000})
        elif t_str == "09:20":
            # Consolidation
            bars.append({"open": 104.0, "high": 104.8, "low": 103.5, "close": 104.2, "volume": 20000})
        elif t_str == "09:25":
            # Breakout bar: opens 104.5, breaks 105.0 up to 107.0, low 104.5
            bars.append({"open": 104.5, "high": 107.0, "low": 104.5, "close": 106.5, "volume": 50000})
        elif t_str == "15:10":
            # Last bar before 15:15
            bars.append({"open": 109.0, "high": 111.0, "low": 108.5, "close": 110.0, "volume": 30000})
        else:
            # Drifting sideways safely above stop
            bars.append({"open": 106.0, "high": 107.5, "low": 105.5, "close": 107.0, "volume": 10000})

    df = pd.DataFrame(bars, index=times)

    trade = sim.simulate_candidate(candidate=cand, bars_df=df, sod_equity=100000.0)

    assert trade is not None
    # 1. Trigger price was 105.0 (since open 104.5 <= 105.0)
    assert trade.raw_entry_price == 105.0
    # 2. Stop loss = 105.0 - (0.10 * 10.0) = 104.0
    assert trade.stop_loss == 104.0
    # 3. Exited at 15:10 bar close = 110.0
    assert trade.raw_exit_price == 110.0
    assert trade.exit_reason == "TIME_EXIT"
    assert trade.side == "LONG"
    assert trade.gross_pnl > 0


def test_gap_open_through_trigger():
    """If the breakout bar opens above the trigger, fill must be at open price."""
    config = StrategyConfig(or_minutes=5, stop_atr=0.10)
    calc = CostCalculator()
    sim = IntradaySimulator(config, calc)

    today = date(2026, 1, 15)
    cand = DailyCandidate(
        date=today,
        symbol="TESTGAP",
        direction="LONG",
        rvol=3.0,
        or_high=200.0,
        or_low=195.0,
        or_open=196.0,
        or_close=199.0,
        or_volume=50000.0,
        atr14_known=5.0,
        avg_turnover_20d_cr=120.0,
        prev_close=195.0,
    )

    times = pd.date_range("2026-01-15 09:15", "2026-01-15 15:15", freq="5min")
    bars = []
    for ts in times:
        t_str = ts.strftime("%H:%M")
        if t_str == "09:15":
            bars.append({"open": 196.0, "high": 200.0, "low": 195.0, "close": 199.0, "volume": 50000})
        elif t_str == "09:20":
            # Bar GAPS open to 202.0 (above trigger 200.0)
            bars.append({"open": 202.0, "high": 204.0, "low": 201.8, "close": 203.0, "volume": 40000})
        elif t_str == "15:10":
            bars.append({"open": 205.0, "high": 206.0, "low": 204.0, "close": 205.5, "volume": 15000})
        else:
            bars.append({"open": 203.0, "high": 204.0, "low": 202.0, "close": 203.5, "volume": 10000})

    df = pd.DataFrame(bars, index=times)
    trade = sim.simulate_candidate(candidate=cand, bars_df=df, sod_equity=100000.0)

    assert trade is not None
    # Must fill at open 202.0, NOT 200.0
    assert trade.raw_entry_price == 202.0
    # Stop loss: 202.0 - 0.10 * 5.0 = 201.5
    assert trade.stop_loss == 201.5
