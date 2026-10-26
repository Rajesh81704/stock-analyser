"""
Data Hygiene and Quality Auditing Module for AlgoDesk.

Performs critical cleaning on 5-minute OHLCV candles:
- Chronological sorting
- Duplicate timestamp removal
- Strict market hour filtering (09:15 to 15:30 IST)
- Flags large gaps or missing trading days
- Flags corporate action anomalies (single-day |return| > 40%)
"""

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class QualityReport:
    """Summary of data cleaning actions and detected anomalies for a symbol."""
    symbol: str
    initial_bars: int
    cleaned_bars: int
    dropped_duplicates: int
    dropped_out_of_bounds: int
    trading_days: int
    corporate_action_flags: List[str] = field(default_factory=list)
    gap_warnings: List[str] = field(default_factory=list)


def clean_intraday_candles(
    df: pd.DataFrame,
    symbol: str,
    max_return_split_threshold: float = 0.40,
) -> Tuple[pd.DataFrame, QualityReport]:
    """
    Cleans intraday 5-minute bars and records anomalies.
    Returns cleaned dataframe and diagnostic QualityReport.
    """
    report = QualityReport(
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

    # Normalize datetime index
    if not isinstance(data.index, pd.DatetimeIndex):
        if "date" in data.columns:
            data["date"] = pd.to_datetime(data["date"])
            if data["date"].dt.tz is not None:
                data["date"] = data["date"].dt.tz_localize(None)
            data = data.sort_values("date").set_index("date")
        elif "timestamp" in data.columns:
            data["timestamp"] = pd.to_datetime(data["timestamp"])
            if data["timestamp"].dt.tz is not None:
                data["timestamp"] = data["timestamp"].dt.tz_localize(None)
            data = data.sort_values("timestamp").set_index("timestamp")
        else:
            raise ValueError(f"{symbol}: No timestamp/date column found.")
    else:
        if data.index.tz is not None:
            data.index = data.index.tz_localize(None)
        data = data.sort_index()

    # Drop duplicate timestamps
    dups = data.index.duplicated().sum()
    if dups > 0:
        data = data[~data.index.duplicated(keep="first")]
        report.dropped_duplicates = int(dups)

    # Filter market hours: 09:15:00 to 15:30:00 IST
    # Candle start times in Kite are 09:15 to 15:25 (each 5m bar ending at 15:30)
    time_idx = data.index.time
    open_time = pd.to_datetime("09:15:00").time()
    close_time = pd.to_datetime("15:30:00").time()

    valid_mask = (time_idx >= open_time) & (time_idx <= close_time)
    dropped_oob = int((~valid_mask).sum())
    if dropped_oob > 0:
        report.dropped_out_of_bounds = dropped_oob
        data = data[valid_mask]

    data.columns = [c.lower() for c in data.columns]
    for col in ["open", "high", "low", "close"]:
        data[col] = data[col].astype(np.float32)
    data["volume"] = data["volume"].astype(np.float64)

    # Check for missing days and corporate action returns
    unique_dates = data.index.normalize().unique()
    report.trading_days = len(unique_dates)

    if len(unique_dates) > 1:
        daily_close = data.groupby(data.index.date)["close"].last()
        daily_returns = daily_close.pct_change().dropna()
        suspicious = daily_returns[daily_returns.abs() > max_return_split_threshold]

        for dt, ret in suspicious.items():
            msg = (
                f"{symbol} on {dt}: single-day return of {ret*100:.2f}% exceeds "
                f"{max_return_split_threshold*100:.0f}% threshold (Potential split/bonus anomaly)"
            )
            report.corporate_action_flags.append(msg)
            logger.warning(msg)

        # Gaps > 5 calendar days
        dates_series = pd.Series(unique_dates)
        diffs = dates_series.diff().dt.days
        gaps = diffs[diffs > 5]
        for idx in gaps.index:
            gap_days = int(diffs.loc[idx])
            from_d = dates_series.loc[idx - 1].strftime("%Y-%m-%d")
            to_d = dates_series.loc[idx].strftime("%Y-%m-%d")
            msg = f"{symbol}: Trading gap of {gap_days} calendar days from {from_d} to {to_d}"
            report.gap_warnings.append(msg)

    report.cleaned_bars = len(data)
    return data, report
