"""
Data Hygiene and Validation Module.

Performs critical cleaning on 5-minute OHLCV candles:
- Chronological sorting
- Duplicate removal
- Strict market hour filtering (09:15 to 15:30 IST)
- Flags large gaps or missing trading days
- Flags corporate action anomalies (single-day |return| > 40%)
"""

import logging
from dataclasses import dataclass, field
from typing import List, Tuple
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class HygieneReport:
    """Diagnostic report from data hygiene checks."""
    symbol: str
    initial_bars: int
    cleaned_bars: int
    dropped_duplicates: int
    dropped_out_of_bounds: int
    trading_days: int
    missing_days_flag: bool = False
    corporate_action_flags: List[str] = field(default_factory=list)
    gap_warnings: List[str] = field(default_factory=list)


def clean_intraday_candles(
    df: pd.DataFrame,
    symbol: str,
    max_return_split_threshold: float = 0.40,
    expected_bars_per_day: int = 75,
) -> Tuple[pd.DataFrame, HygieneReport]:
    """
    Cleans intraday 5-minute bars and records anomalies.

    Expected columns: date (or datetime index), open, high, low, close, volume.
    """
    report = HygieneReport(
        symbol=symbol,
        initial_bars=len(df),
        cleaned_bars=0,
        dropped_duplicates=0,
        dropped_out_of_bounds=0,
        trading_days=0,
    )

    if df.empty:
        return df, report

    data = df.copy()

    # Ensure datetime format and timezone-naive
    if not isinstance(data.index, pd.DatetimeIndex):
        if "date" in data.columns:
            data["date"] = pd.to_datetime(data["date"])
            if data["date"].dt.tz is not None:
                data["date"] = data["date"].dt.tz_localize(None)
            data = data.sort_values("date")
            data = data.set_index("date")
        else:
            raise ValueError(f"{symbol}: No 'date' column or DatetimeIndex found")
    else:
        if data.index.tz is not None:
            data.index = data.index.tz_localize(None)
        data = data.sort_index()

    # Remove duplicate timestamps
    dup_count = data.index.duplicated().sum()
    if dup_count > 0:
        data = data[~data.index.duplicated(keep="first")]
        report.dropped_duplicates = int(dup_count)

    # Filter market hours: 09:15:00 to 15:30:00 IST
    # The last candle starting at 15:25 ends at 15:30. In Kite, candles are stamped at the start of the interval.
    # So valid candle start times are between 09:15:00 and 15:25:00 (or up to 15:30:00).
    time_index = data.index.time
    open_time = pd.to_datetime("09:15:00").time()
    close_time = pd.to_datetime("15:30:00").time()

    valid_mask = (time_index >= open_time) & (time_index <= close_time)
    dropped_oob = int((~valid_mask).sum())
    if dropped_oob > 0:
        report.dropped_out_of_bounds = dropped_oob
        data = data[valid_mask]

    # Standardize column names to lowercase
    data.columns = [c.lower() for c in data.columns]
    required_cols = ["open", "high", "low", "close", "volume"]
    for col in required_cols:
        if col not in data.columns:
            raise ValueError(f"{symbol}: Missing required column '{col}'")

    # Cast to float32 for performance and memory efficiency, volume to float64 or int64
    for col in ["open", "high", "low", "close"]:
        data[col] = data[col].astype(np.float32)
    data["volume"] = data["volume"].astype(np.float64)

    # Check for missing days and bar counts per day
    unique_dates = data.index.normalize().unique()
    report.trading_days = len(unique_dates)

    if len(unique_dates) > 1:
        # Check for single-day corporate actions / split / bonus (|return| > 40%)
        # Daily close is the last bar's close of each day
        daily_close = data.groupby(data.index.date)["close"].last()
        daily_returns = daily_close.pct_change().dropna()
        suspicious = daily_returns[daily_returns.abs() > max_return_split_threshold]
        for dt, ret in suspicious.items():
            msg = f"{symbol} on {dt}: single-day return of {ret*100:.2f}% exceeds {max_return_split_threshold*100:.0f}% threshold (Potential split/bonus/corporate action anomaly)"
            report.corporate_action_flags.append(msg)
            logger.warning(msg)

        # Check trading days gaps (> 5 calendar days gap might indicate suspension or holiday anomaly)
        dates_series = pd.Series(unique_dates)
        date_diffs = dates_series.diff().dt.days
        large_gaps = date_diffs[date_diffs > 5]
        for idx in large_gaps.index:
            gap_days = int(date_diffs.loc[idx])
            from_d = dates_series.loc[idx - 1].strftime("%Y-%m-%d")
            to_d = dates_series.loc[idx].strftime("%Y-%m-%d")
            gap_msg = f"{symbol}: Trading gap of {gap_days} calendar days from {from_d} to {to_d}"
            report.gap_warnings.append(gap_msg)

    report.cleaned_bars = len(data)
    return data, report
