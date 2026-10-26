"""
Synthetic Data Generator for Smoke-Testing and Pipeline Validation.

Generates realistic 5-minute intraday random-walk OHLCV candles
for ~30 symbols without requiring active Kite Connect credentials.

Note: Synthetic results ONLY validate code mechanics and data flow;
they DO NOT represent real market performance or strategy alpha.
"""

import os
from pathlib import Path
from typing import List, Optional
import numpy as np
import pandas as pd

DEFAULT_SYNTHETIC_SYMBOLS = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "SBIN", "BHARTIARTL", "ITC", "KOTAKBANK", "LT",
    "AXISBANK", "HINDUNILVR", "BAJFINANCE", "TATAMOTORS", "MARUTI",
    "SUNPHARMA", "TITAN", "ULTRACEMCO", "ASIANPAINT", "NTPC",
    "POWERGRID", "M&M", "TATASTEEL", "ADANIENT", "JSWSTEEL",
    "COALINDIA", "BAJAJFINSV", "WIPRO", "HCLTECH", "ONGC"
]


def generate_synthetic_symbol_data(
    symbol: str,
    trading_days: int = 70,
    end_date: Optional[str] = None,
    seed: Optional[int] = None,
) -> pd.DataFrame:
    """
    Generates synthetic 5-minute bars for a single symbol using geometric Brownian motion
    with intraday seasonality (U-shaped volume curve, morning volatility).
    """
    if seed is not None:
        np.random.seed(seed)

    # 75 bars per day (09:15 to 15:25, 5m candles ending at 15:30)
    bars_per_day = 75
    daily_vol = np.random.uniform(0.015, 0.035)  # 1.5% to 3.5% daily volatility
    bar_vol = daily_vol / np.sqrt(bars_per_day)

    base_price = np.random.uniform(150.0, 3000.0)
    base_volume = np.random.uniform(20000, 200000)

    if end_date is None:
        end_dt = pd.Timestamp.now().normalize()
    else:
        end_dt = pd.Timestamp(end_date).normalize()

    # Generate business days
    calendar_days = pd.bdate_range(end=end_dt, periods=trading_days)

    records = []
    current_close = base_price

    for day_idx, d in enumerate(calendar_days):
        # Morning gap
        gap_return = np.random.normal(0, daily_vol * 0.4)
        current_open = current_close * (1.0 + gap_return)

        # U-shaped intraday volume profile
        u_curve = np.linspace(-1, 1, bars_per_day) ** 2 + 0.3
        u_curve = u_curve / u_curve.mean()

        for b_idx in range(bars_per_day):
            bar_start = d + pd.Timedelta(hours=9, minutes=15 + b_idx * 5)

            # First bar has higher volatility
            multiplier = 2.0 if b_idx == 0 else 1.0
            ret = np.random.normal(0, bar_vol * multiplier)

            b_open = current_open if b_idx == 0 else current_close
            b_close = b_open * (1.0 + ret)

            # High and low bounds
            wick_high = abs(np.random.normal(0, bar_vol * 0.5))
            wick_low = abs(np.random.normal(0, bar_vol * 0.5))
            b_high = max(b_open, b_close) * (1.0 + wick_high)
            b_low = min(b_open, b_close) * (1.0 - wick_low)

            # Volume with spikes on OR bar
            vol_multiplier = 3.0 if b_idx == 0 and np.random.rand() > 0.4 else 1.0
            b_vol = int(base_volume * u_curve[b_idx] * vol_multiplier * np.random.uniform(0.6, 1.4))

            records.append({
                "date": bar_start.strftime("%Y-%m-%d %H:%M:%S"),
                "open": round(b_open, 2),
                "high": round(b_high, 2),
                "low": round(b_low, 2),
                "close": round(b_close, 2),
                "volume": max(100, b_vol)
            })

            current_close = b_close

    df = pd.DataFrame(records)
    return df


def generate_synthetic_universe(
    symbols: Optional[List[str]] = None,
    output_dir: str = "data",
    trading_days: int = 70,
) -> List[str]:
    """
    Generates synthetic 5-minute CSVs for a universe of symbols.
    Saves each to {output_dir}/{symbol}.csv.
    """
    symbols = symbols or DEFAULT_SYNTHETIC_SYMBOLS
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    saved_files = []
    print(f"\n[SYNTHETIC GENERATOR] Creating synthetic 5-minute data for {len(symbols)} symbols over {trading_days} days...")
    print(">>> NOTE: Synthetic results ONLY validate code mechanics and DO NOT represent real strategy returns! <<<\n")

    for idx, sym in enumerate(symbols, 1):
        df = generate_synthetic_symbol_data(sym, trading_days=trading_days, seed=idx * 42)
        csv_file = out_path / f"{sym}.csv"
        df.to_csv(csv_file, index=False)
        saved_files.append(str(csv_file))
        print(f"[{idx}/{len(symbols)}] {sym}: Generated {len(df)} bars -> {csv_file}")

    print(f"\n[SYNTHETIC GENERATOR] Completed generating {len(saved_files)} symbol CSVs in '{output_dir}'.\n")
    return saved_files
