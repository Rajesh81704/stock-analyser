"""
Unit tests for AlgoDesk Synthetic 5-Minute Data Generator.
"""

import pandas as pd
import pytest
from src.algodesk.data.synthetic import generate_synthetic_candles_for_symbol


def test_synthetic_candles_structure():
    """Validates generated synthetic candles structure and bar counts."""
    trading_days = 10
    df = generate_synthetic_candles_for_symbol("RELIANCE", trading_days=trading_days, seed=42)

    # 75 bars per day (09:15 to 15:25, 5m candles ending at 15:30)
    expected_bars = trading_days * 75
    assert len(df) == expected_bars

    required_cols = ["timestamp", "open", "high", "low", "close", "volume"]
    for col in required_cols:
        assert col in df.columns

    # High must be >= max(open, close), Low must be <= min(open, close)
    assert (df["high"] >= df[["open", "close"]].max(axis=1)).all()
    assert (df["low"] <= df[["open", "close"]].min(axis=1)).all()
    assert (df["volume"] > 0).all()
