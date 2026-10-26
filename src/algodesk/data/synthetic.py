"""
Synthetic 5-Minute Data Generator for Offline Pipeline Validation.

Generates realistic random-walk intraday candles for ~30 Nifty 500 stocks
with morning opening volatility, U-shaped intraday volume profiles,
and realistic price distributions.

CRITICAL NOTICE: Synthetic results ONLY prove that code mechanics, data flows,
and state machines run without crashes. They have ZERO alpha or predictive value.
"""

from pathlib import Path
from typing import List, Optional
import numpy as np
import pandas as pd

DEFAULT_BENCHMARK_SYMBOLS = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "SBIN", "BHARTIARTL", "ITC", "KOTAKBANK", "LT",
    "AXISBANK", "HINDUNILVR", "BAJFINANCE", "TATAMOTORS", "MARUTI",
    "SUNPHARMA", "TITAN", "ULTRACEMCO", "ASIANPAINT", "NTPC",
    "POWERGRID", "M&M", "TATASTEEL", "ADANIENT", "JSWSTEEL",
    "COALINDIA", "BAJAJFINSV", "WIPRO", "HCLTECH", "ONGC"
]


def generate_synthetic_candles_for_symbol(
    symbol: str,
    trading_days: int = 70,
    seed: Optional[int] = None,
) -> pd.DataFrame:
    """Generates 5-minute bars (75 bars per day, 09:15 to 15:30 IST)."""
    if seed is not None:
        np.random.seed(seed)

    bars_per_day = 75
    daily_vol = np.random.uniform(0.015, 0.035)
    bar_vol = daily_vol / np.sqrt(bars_per_day)

    base_price = np.random.uniform(150.0, 3200.0)
    base_volume = np.random.uniform(25000, 250000)

    end_dt = pd.Timestamp.now().normalize()
    calendar_days = pd.bdate_range(end=end_dt, periods=trading_days)

    records = []
    current_close = base_price

    for d in calendar_days:
        # Morning gap
        gap_ret = np.random.normal(0, daily_vol * 0.4)
        current_open = current_close * (1.0 + gap_ret)

        u_curve = np.linspace(-1, 1, bars_per_day) ** 2 + 0.3
        u_curve = u_curve / u_curve.mean()

        for b_idx in range(bars_per_day):
            bar_start = d + pd.Timedelta(hours=9, minutes=15 + b_idx * 5)

            # First bar has higher volatility
            vol_mult = 2.2 if b_idx == 0 else 1.0
            ret = np.random.normal(0, bar_vol * vol_mult)

            b_open = current_open if b_idx == 0 else current_close
            b_close = b_open * (1.0 + ret)

            wick_h = abs(np.random.normal(0, bar_vol * 0.5))
            wick_l = abs(np.random.normal(0, bar_vol * 0.5))
            b_high = max(b_open, b_close) * (1.0 + wick_h)
            b_low = min(b_open, b_close) * (1.0 - wick_l)

            v_spike = 3.5 if b_idx == 0 and np.random.rand() > 0.4 else 1.0
            b_vol = int(base_volume * u_curve[b_idx] * v_spike * np.random.uniform(0.7, 1.3))

            records.append({
                "timestamp": bar_start,
                "open": round(b_open, 2),
                "high": round(b_high, 2),
                "low": round(b_low, 2),
                "close": round(b_close, 2),
                "volume": max(100, b_vol),
            })
            current_close = b_close

    df = pd.DataFrame(records)
    return df


def generate_synthetic_dataset(
    symbols: Optional[List[str]] = None,
    output_dir: str = "data",
    trading_days: int = 70,
) -> List[str]:
    """Generates synthetic Parquet and CSV files for offline testing."""
    syms = symbols or DEFAULT_BENCHMARK_SYMBOLS
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    saved_files = []
    print(f"\n[SYNTHETIC GENERATOR] Creating synthetic 5m data for {len(syms)} symbols over {trading_days} days...")
    print(">>> NOTICE: Synthetic data ONLY proves code mechanics and DOES NOT represent real market edge! <<<\n")

    for idx, sym in enumerate(syms, 1):
        df = generate_synthetic_candles_for_symbol(sym, trading_days=trading_days, seed=idx * 77)
        parquet_file = out_dir / f"{sym}.parquet"
        csv_file = out_dir / f"{sym}.csv"

        df.to_parquet(parquet_file, index=False)
        df.rename(columns={"timestamp": "date"}).to_csv(csv_file, index=False)
        saved_files.append(str(parquet_file))
        print(f"[{idx}/{len(syms)}] {sym}: Generated {len(df)} bars -> {parquet_file.name}")

    print(f"\n[SYNTHETIC GENERATOR] Successfully created {len(saved_files)} synthetic datasets in '{output_dir}'.\n")
    return saved_files
