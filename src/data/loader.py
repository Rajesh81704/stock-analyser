"""
Data Loader & Daily Feature Precomputation Engine.

Reads Nifty 500 universe and historical candle data, applies hygiene cleaning,
and precomputes daily features (ATR14, 20d Turnover, ORV baseline, RVOL)
with strict no-lookahead shifts.
"""

import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd

from src.data.hygiene import clean_intraday_candles, HygieneReport
from src.strategy.config import StrategyConfig


def load_universe_symbols(csv_path: str = "ind_nifty500list.csv") -> List[str]:
    """
    Loads symbols from the Nifty 500 constituents CSV.
    Searches both in workspace root and data/ directory.
    """
    candidate_paths = [
        Path(csv_path),
        Path("data") / Path(csv_path).name,
        Path("data/ind_nifty500list.csv"),
    ]

    found_path = None
    for p in candidate_paths:
        if p.exists():
            found_path = p
            break

    if not found_path:
        raise FileNotFoundError(f"Universe file '{csv_path}' not found in root or data/ directory.")

    df = pd.read_csv(found_path)
    if "Symbol" not in df.columns:
        # Fallback to first column
        col = df.columns[0]
    else:
        col = "Symbol"

    symbols = df[col].dropna().astype(str).str.strip().tolist()
    # Remove any headers or duplicates
    clean_symbols = [s for s in symbols if s and s.upper() != "SYMBOL"]
    return sorted(list(set(clean_symbols)))


def compute_wilder_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Computes standard Average True Range (ATR) with Wilder's smoothing."""
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    # Wilder's exponential smoothing (alpha = 1 / period)
    atr = tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    return atr


class SymbolDataStore:
    """
    Stores 5-minute bars and precomputed daily metadata for a symbol.
    """
    def __init__(self, symbol: str, bars_5m: pd.DataFrame, daily_df: pd.DataFrame, hygiene_report: HygieneReport):
        self.symbol = symbol
        self.bars_5m = bars_5m          # DataFrame indexed by datetime
        self.daily_df = daily_df        # Daily features indexed by date
        self.hygiene_report = hygiene_report


def process_symbol_candles(
    symbol: str,
    raw_df: pd.DataFrame,
    config: StrategyConfig,
) -> Optional[SymbolDataStore]:
    """
    Performs hygiene checks and precomputes daily indicators for a single stock.
    Strictly shifts all trailing features so today's trading decisions
    have ZERO knowledge of future or same-day bars.
    """
    if raw_df.empty:
        return None

    cleaned_df, report = clean_intraday_candles(raw_df, symbol)
    if cleaned_df.empty:
        return None

    # Group by date for daily aggregation
    grouped = cleaned_df.groupby(cleaned_df.index.date)

    daily_agg = grouped.agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    })

    if len(daily_agg) < max(config.atr_window, config.turnover_window, config.rvol_window) + 2:
        # Not enough history for warm-up
        return None

    # 1. Daily ATR(14) - Wilder's RMA
    daily_atr = compute_wilder_atr(
        daily_agg["high"], daily_agg["low"], daily_agg["close"], period=config.atr_window
    )
    # STRICT NO-LOOKAHEAD: Shift by 1 day so today's ATR is strictly from yesterday's close
    daily_agg["atr14_known"] = daily_atr.shift(1)
    daily_agg["prev_close"] = daily_agg["close"].shift(1)

    # 2. Trailing 20-day Average Turnover in Rs Crore
    # turnover = close * volume (Rs) / 10,000,000 (Rs Crore)
    daily_turnover_cr = (daily_agg["close"] * daily_agg["volume"]) / 1e7
    # STRICT NO-LOOKAHEAD: Shift by 1 day so today's trailing turnover excludes today
    daily_agg["avg_turnover_20d_cr"] = daily_turnover_cr.rolling(
        window=config.turnover_window, min_periods=config.turnover_window
    ).mean().shift(1)

    # 3. Opening Range calculations (5, 15, or 30 minutes)
    # The market opens at 09:15.
    # For or_minutes=5, it's bar 09:15:00.
    # For or_minutes=15, bars are 09:15, 09:20, 09:25 (start times < 09:30).
    # For or_minutes=30, bars start before 09:45.
    or_minutes = config.or_minutes
    or_cutoff_time = (pd.to_datetime("09:15:00") + pd.Timedelta(minutes=or_minutes)).time()

    or_bars = cleaned_df[cleaned_df.index.time < or_cutoff_time]
    or_grouped = or_bars.groupby(or_bars.index.date)

    or_stats = or_grouped.agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).rename(columns={
        "open": "or_open",
        "high": "or_high",
        "low": "or_low",
        "close": "or_close",
        "volume": "or_volume",
    })

    daily_agg = daily_agg.join(or_stats, how="left")

    # 4. RVOL calculation: OR volume today / average OR volume of prior 14 days
    # STRICT NO-LOOKAHEAD: Shift prior OR volume baseline by 1 day
    or_vol_baseline = daily_agg["or_volume"].rolling(
        window=config.rvol_window, min_periods=config.rvol_window
    ).mean().shift(1)
    daily_agg["or_vol_baseline_14"] = or_vol_baseline
    daily_agg["rvol"] = daily_agg["or_volume"] / daily_agg["or_vol_baseline_14"]

    # 5. OR Direction
    # Close > Open => Long; Close < Open => Short; Close == Open => Doji
    conditions = [
        daily_agg["or_close"] > daily_agg["or_open"],
        daily_agg["or_close"] < daily_agg["or_open"],
    ]
    choices = ["LONG", "SHORT"]
    daily_agg["or_direction"] = np.select(conditions, choices, default="DOJI")

    return SymbolDataStore(
        symbol=symbol,
        bars_5m=cleaned_df,
        daily_df=daily_agg,
        hygiene_report=report,
    )


def load_dataset(
    data_dir: str = "data",
    symbols: Optional[List[str]] = None,
    config: Optional[StrategyConfig] = None,
) -> Tuple[Dict[str, SymbolDataStore], List[HygieneReport]]:
    """
    Loads all symbol CSVs from data_dir, performs hygiene checks,
    and returns precomputed data stores.
    """
    config = config or StrategyConfig()
    dir_path = Path(data_dir)
    data_stores: Dict[str, SymbolDataStore] = {}
    reports: List[HygieneReport] = []

    if symbols is None:
        csv_files = list(dir_path.glob("*.csv"))
        # Exclude universe index files
        csv_files = [f for f in csv_files if not f.name.startswith("ind_") and f.name != "nifty500.csv"]
    else:
        csv_files = [dir_path / f"{s}.csv" for s in symbols if (dir_path / f"{s}.csv").exists()]

    total_files = len(csv_files)
    if total_files == 0:
        return data_stores, reports

    for idx, f in enumerate(csv_files, 1):
        sym = f.stem
        try:
            df = pd.read_csv(f)
            store = process_symbol_candles(sym, df, config)
            if store is not None:
                data_stores[sym] = store
                reports.append(store.hygiene_report)
        except Exception as e:
            pass

    return data_stores, reports
