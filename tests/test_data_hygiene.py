"""
Unit tests for AlgoDesk Data Hygiene, Sorting, Market Hours, and Split Anomaly Detection.
"""

from datetime import datetime
import pandas as pd
import pytest

from src.algodesk.data.hygiene import clean_intraday_candles


def test_clean_intraday_candles_dedup_and_sort():
    """Validates that duplicate timestamps are removed and bars are sorted chronologically."""
    raw = [
        {"timestamp": "2026-01-15 09:25:00", "open": 102.0, "high": 103.0, "low": 101.5, "close": 102.5, "volume": 1000},
        {"timestamp": "2026-01-15 09:15:00", "open": 100.0, "high": 101.0, "low": 99.5, "close": 100.5, "volume": 2000},
        {"timestamp": "2026-01-15 09:15:00", "open": 100.0, "high": 101.0, "low": 99.5, "close": 100.5, "volume": 2000}, # duplicate
        {"timestamp": "2026-01-15 09:20:00", "open": 100.5, "high": 102.0, "low": 100.0, "close": 101.8, "volume": 1500},
    ]
    df = pd.DataFrame(raw)
    cleaned, report = clean_intraday_candles(df, symbol="TESTSTOCK")

    assert report.dropped_duplicates == 1
    assert len(cleaned) == 3
    # First bar must be 09:15:00
    assert cleaned.index[0] == pd.Timestamp("2026-01-15 09:15:00")


def test_market_hours_filtering():
    """Bars outside 09:15-15:30 IST must be dropped."""
    raw = [
        {"timestamp": "2026-01-15 09:00:00", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 500}, # pre-market
        {"timestamp": "2026-01-15 09:15:00", "open": 100.0, "high": 101.0, "low": 99.5, "close": 100.5, "volume": 2000},
        {"timestamp": "2026-01-15 15:35:00", "open": 102.0, "high": 103.0, "low": 102.0, "close": 102.5, "volume": 300}, # post-market
    ]
    df = pd.DataFrame(raw)
    cleaned, report = clean_intraday_candles(df, symbol="TESTSTOCK")

    assert report.dropped_out_of_bounds == 2
    assert len(cleaned) == 1
    assert cleaned.index[0] == pd.Timestamp("2026-01-15 09:15:00")


def test_corporate_action_split_detection():
    """Detects single-day returns exceeding 40% (suspected stock split / bonus)."""
    raw = [
        # Day 1: Close = 1000.0
        {"timestamp": "2026-01-15 09:15:00", "open": 990.0, "high": 1010.0, "low": 980.0, "close": 1000.0, "volume": 5000},
        {"timestamp": "2026-01-15 15:25:00", "open": 995.0, "high": 1005.0, "low": 990.0, "close": 1000.0, "volume": 5000},
        # Day 2: 1:5 Split occurs -> Close drops to 200.0 (-80% return)
        {"timestamp": "2026-01-16 09:15:00", "open": 200.0, "high": 205.0, "low": 195.0, "close": 200.0, "volume": 25000},
        {"timestamp": "2026-01-16 15:25:00", "open": 199.0, "high": 202.0, "low": 198.0, "close": 200.0, "volume": 25000},
    ]
    df = pd.DataFrame(raw)
    cleaned, report = clean_intraday_candles(df, symbol="SPLITSTOCK")

    assert len(report.corporate_action_flags) > 0
    assert "exceeds 40%" in report.corporate_action_flags[0]
