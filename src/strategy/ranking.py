"""
Candidate Filtering & RVOL Ranking Module.

Filters universe constituents each day using precomputed features
and ranks eligible stocks by RVOL to select the Top N 'Stocks in Play'.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Dict, List, Optional
import pandas as pd

if TYPE_CHECKING:
    from src.data.loader import SymbolDataStore

from src.strategy.config import StrategyConfig


@dataclass
class DailyCandidate:
    """Represents a qualified stock candidate for intraday trading on a specific date."""
    date: date
    symbol: str
    direction: str            # 'LONG' or 'SHORT'
    rvol: float
    or_high: float
    or_low: float
    or_open: float
    or_close: float
    or_volume: float
    atr14_known: float
    avg_turnover_20d_cr: float
    prev_close: float


def filter_and_rank_candidates(
    current_date: date,
    data_stores: Dict[str, SymbolDataStore],
    config: StrategyConfig,
) -> List[DailyCandidate]:
    """
    Selects and ranks the top N eligible stocks for the day by RVOL.
    All criteria strictly use information known at or before OR close.
    """
    eligible: List[DailyCandidate] = []

    for symbol, store in data_stores.items():
        if current_date not in store.daily_df.index:
            continue

        row = store.daily_df.loc[current_date]

        # 1. Price filter (prev day close >= min_price)
        prev_close = row.get("prev_close")
        if pd.isna(prev_close) or prev_close < config.min_price:
            continue

        # 2. Liquidity filter (trailing 20d avg turnover >= min_turnover_cr)
        turnover_cr = row.get("avg_turnover_20d_cr")
        if pd.isna(turnover_cr) or turnover_cr < config.min_turnover_cr:
            continue

        # 3. ATR validity
        atr = row.get("atr14_known")
        if pd.isna(atr) or atr <= 0:
            continue

        # 4. RVOL filter
        rvol = row.get("rvol")
        if pd.isna(rvol) or rvol < config.min_rvol:
            continue

        # 5. OR Direction
        direction = row.get("or_direction")
        if direction not in ("LONG", "SHORT"):
            # Skip DOJI or invalid
            continue

        if config.direction_mode == "long_only" and direction != "LONG":
            continue
        if config.direction_mode == "short_only" and direction != "SHORT":
            continue

        # Check OR levels validity
        or_high = row.get("or_high")
        or_low = row.get("or_low")
        if pd.isna(or_high) or pd.isna(or_low) or or_high <= or_low:
            continue

        eligible.append(
            DailyCandidate(
                date=current_date,
                symbol=symbol,
                direction=direction,
                rvol=float(rvol),
                or_high=float(or_high),
                or_low=float(or_low),
                or_open=float(row.get("or_open")),
                or_close=float(row.get("or_close")),
                or_volume=float(row.get("or_volume")),
                atr14_known=float(atr),
                avg_turnover_20d_cr=float(turnover_cr),
                prev_close=float(prev_close),
            )
        )

    # Rank by RVOL descending (highest relative volume first)
    eligible.sort(key=lambda c: c.rvol, reverse=True)

    # Keep top N
    return eligible[: config.top_n]
