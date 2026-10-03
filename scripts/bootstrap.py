"""
Initial Bootstrapping Script
Populates SQLite database with official NIFTY 500 constituents,
downloads 5-year OHLCV in chunked batches, extracts fundamental ratios,
and triggers the initial indicator & model training pipeline.

Usage:
    python scripts/bootstrap.py --limit 30   # Rapid test with top 30 stocks
    python scripts/bootstrap.py              # Full NIFTY 500 bootstrap
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import datetime
import os
import sys
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
import yfinance as yf

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.cron_worker import run_trailing_daily_cron
from src.db import bulk_upsert_ohlcv, bulk_upsert_stocks_meta, init_db
from src.universe import fetch_nifty500_constituents


def fetch_stock_fundamentals(ticker: str) -> Dict[str, Any]:
    """Fetches fundamental valuation ratios via yfinance."""
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
        market_cap_cr = round(info.get("marketCap", 0) / 1e7, 2) if info.get("marketCap") else None
        return {
            "ticker": ticker,
            "company_name": info.get("shortName") or info.get("longName"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "market_cap": market_cap_cr,
            "pe_ratio": round(float(info.get("trailingPE", 0)), 2) if info.get("trailingPE") else None,
            "pb_ratio": round(float(info.get("priceToBook", 0)), 2) if info.get("priceToBook") else None,
            "eps": round(float(info.get("trailingEps", 0)), 2) if info.get("trailingEps") else None,
            "dividend_yield": round(float(info.get("dividendYield", 0)) * 100.0, 2) if info.get("dividendYield") else None,
            "roe": round(float(info.get("returnOnEquity", 0)) * 100.0, 2) if info.get("returnOnEquity") else None,
        }
    except Exception:
        return {"ticker": ticker}


def bootstrap_database(limit: int = None, chunk_size: int = 25, period: str = "5y"):
    start_time = datetime.datetime.now()
    print("""
========================================================================
           NIFTY 500 QUANTITATIVE DATABASE BOOTSTRAPPER
========================================================================
""")
    # 1. Initialize SQLite Schema
    init_db()

    # 2. Ingest NIFTY 500 constituents
    uni_df = fetch_nifty500_constituents()
    if limit:
        uni_df = uni_df.head(limit)
        print(f"[Bootstrap] Limited to first {limit} constituents for fast execution.")

    tickers = uni_df["Ticker"].tolist()
    total_tickers = len(tickers)
    print(f"[Bootstrap] Initializing {total_tickers} NIFTY 500 stocks...")

    # 3. Seed initial stocks_meta from universe CSV
    initial_meta = []
    for _, row in uni_df.iterrows():
        initial_meta.append({
            "ticker": row["Ticker"],
            "company_name": row.get("Company_Name", row["Ticker"]),
            "sector": row.get("Industry", "General"),
            "industry": row.get("Industry", "General"),
            "market_cap": None,
            "pe_ratio": None,
            "pb_ratio": None,
            "eps": None,
            "dividend_yield": None,
            "roe": None,
        })
    bulk_upsert_stocks_meta(initial_meta)
    print(f"[Bootstrap] Seeded metadata for {len(initial_meta)} stocks.")

    # 4. Fetch Fundamental Ratios in background thread pool
    print(f"[Bootstrap] Fetching fundamental ratios for {total_tickers} stocks...")
    updated_meta = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_ticker = {executor.submit(fetch_stock_fundamentals, t): t for t in tickers}
        for future in as_completed(future_to_ticker):
            meta = future.result()
            if meta:
                # Merge with universe info
                t_match = uni_df[uni_df["Ticker"] == meta["ticker"]]
                if not t_match.empty:
                    meta.setdefault("company_name", t_match.iloc[0].get("Company_Name"))
                    meta.setdefault("sector", t_match.iloc[0].get("Industry"))
                    meta.setdefault("industry", t_match.iloc[0].get("Industry"))
                updated_meta.append(meta)

    bulk_upsert_stocks_meta(updated_meta)
    print(f"[Bootstrap] Saved fundamental ratios for {len(updated_meta)} stocks.")

    # 5. Chunked Batch Download of 5-Year OHLCV
    print(f"\n[Bootstrap] Downloading {period} historical daily data in chunks of {chunk_size}...")
    total_bars = 0
    all_chunks = [tickers[i:i + chunk_size] for i in range(0, total_tickers, chunk_size)]

    for chunk_idx, chunk in enumerate(all_chunks, 1):
        print(f"[Bootstrap] Processing batch {chunk_idx}/{len(all_chunks)} ({len(chunk)} tickers)...")
        try:
            # Batch download from Yahoo Finance
            batch_df = yf.download(
                chunk,
                period=period,
                auto_adjust=True,
                group_by="ticker",
                progress=False,
                threads=True
            )

            records = []
            for t in chunk:
                try:
                    if len(chunk) == 1:
                        df_t = batch_df.copy()
                    elif t in batch_df.columns.levels[0]:
                        df_t = batch_df[t].dropna(subset=["Close"]).copy()
                    else:
                        continue

                    if df_t.empty:
                        continue

                    if df_t.index.tz is not None:
                        df_t.index = df_t.index.tz_localize(None)

                    for idx, row in df_t.iterrows():
                        vol = float(row.get("Volume", 1.0))
                        records.append({
                            "ticker": t,
                            "date": idx.strftime("%Y-%m-%d"),
                            "open": round(float(row["Open"]), 2),
                            "high": round(float(row["High"]), 2),
                            "low": round(float(row["Low"]), 2),
                            "close": round(float(row["Close"]), 2),
                            "volume": max(vol, 1.0),
                        })
                except Exception:
                    continue

            if records:
                bulk_upsert_ohlcv(records)
                total_bars += len(records)
                print(f"[Bootstrap] Batch {chunk_idx}: Inserted {len(records)} bars.")

        except Exception as batch_err:
            print(f"[Bootstrap] Batch {chunk_idx} error: {batch_err}")

    print(f"\n[Bootstrap] Successfully ingested a total of {total_bars} historical OHLCV bars.")

    # 6. Trigger Indicator Computation, Model Retraining, and Market Breadth Scan
    print("\n[Bootstrap] Triggering initial technical indicator computation, model training, and market scan...")
    run_trailing_daily_cron(max_workers=8)

    elapsed = (datetime.datetime.now() - start_time).total_seconds()
    print(f"\n[Bootstrap] FULL BOOTSTRAP COMPLETE in {elapsed:.1f} seconds!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bootstrap NIFTY 500 SQLite Database")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of stocks for testing (e.g. 25)")
    parser.add_argument("--chunk", type=int, default=25, help="Batch download chunk size")
    parser.add_argument("--period", type=str, default="5y", help="Historical data period (default: 5y)")
    args = parser.parse_args()

    bootstrap_database(limit=args.limit, chunk_size=args.chunk, period=args.period)
