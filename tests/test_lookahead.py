"""
Unit tests for No-Lookahead Bias Verification.

Validates that modifying or altering future data (days after day T)
has ZERO impact on Day T's features, indicators, or candidate selection.
"""

import copy
import numpy as np
import pandas as pd
import pytest

from src.data.loader import process_symbol_candles
from src.data.synthetic import generate_synthetic_symbol_data
from src.strategy.config import StrategyConfig
from src.strategy.ranking import filter_and_rank_candidates


def test_no_lookahead_bias():
    """Modifying future bars must not change today's features, RVOL, ATR, or rank."""
    config = StrategyConfig()
    symbols = ["SYM1", "SYM2", "SYM3", "SYM4", "SYM5"]

    # Generate 50 days of data for each symbol
    raw_stores = {}
    for idx, s in enumerate(symbols):
        raw_df = generate_synthetic_symbol_data(s, trading_days=50, seed=idx * 100)
        raw_stores[s] = raw_df

    # Process baseline
    baseline_stores = {}
    for s, df in raw_stores.items():
        st = process_symbol_candles(s, df, config)
        assert st is not None
        baseline_stores[s] = st

    # Pick reference day T (day 35)
    sample_sym = symbols[0]
    dates = list(baseline_stores[sample_sym].daily_df.index)
    test_date = dates[35]

    # Baseline candidates for Day T
    baseline_cands = filter_and_rank_candidates(test_date, baseline_stores, config)

    # Record baseline values for Day T
    baseline_records = {}
    for s in symbols:
        row = baseline_stores[s].daily_df.loc[test_date]
        baseline_records[s] = {
            "atr14_known": row["atr14_known"],
            "avg_turnover_20d_cr": row["avg_turnover_20d_cr"],
            "rvol": row["rvol"],
            "or_high": row["or_high"],
            "or_low": row["or_low"],
        }

    # Now mutate FUTURE data (days > test_date):
    # Alter prices and volumes massively in the future
    corrupted_stores = {}
    for s, raw_df in raw_stores.items():
        df_copy = raw_df.copy()
        df_copy["dt"] = pd.to_datetime(df_copy["date"])
        # Mutate future
        future_mask = df_copy["dt"].dt.date > test_date
        df_copy.loc[future_mask, "close"] = df_copy.loc[future_mask, "close"] * 50.0
        df_copy.loc[future_mask, "high"] = df_copy.loc[future_mask, "high"] * 50.0
        df_copy.loc[future_mask, "volume"] = df_copy.loc[future_mask, "volume"] * 100.0
        df_copy = df_copy.drop(columns=["dt"])

        st = process_symbol_candles(s, df_copy, config)
        assert st is not None
        corrupted_stores[s] = st

    # Candidate ranking on mutated dataset for Day T
    corrupted_cands = filter_and_rank_candidates(test_date, corrupted_stores, config)

    # 1. Verify candidate list and ordering is strictly identical
    assert len(baseline_cands) == len(corrupted_cands)
    for b_c, c_c in zip(baseline_cands, corrupted_cands):
        assert b_c.symbol == c_c.symbol
        assert b_c.direction == c_c.direction
        assert pytest.approx(b_c.rvol, rel=1e-5) == c_c.rvol

    # 2. Verify all underlying Day T indicators are exactly invariant
    for s in symbols:
        new_row = corrupted_stores[s].daily_df.loc[test_date]
        old = baseline_records[s]
        assert pytest.approx(new_row["atr14_known"], rel=1e-5) == old["atr14_known"]
        assert pytest.approx(new_row["avg_turnover_20d_cr"], rel=1e-5) == old["avg_turnover_20d_cr"]
        assert pytest.approx(new_row["rvol"], rel=1e-5) == old["rvol"]
        assert pytest.approx(new_row["or_high"], rel=1e-5) == old["or_high"]
        assert pytest.approx(new_row["or_low"], rel=1e-5) == old["or_low"]
