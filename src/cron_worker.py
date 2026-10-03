"""
Trailing Incremental Cron Worker
Executes automated daily ingestion:
1. Trailing Delta Ingestion (downloads only missing recent trading bars)
2. Trailing Technical Indicator Computation
3. Incremental Model Training & Forecast Generation
4. Market-Wide Breadth & Opportunity Scan
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
import datetime
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
import yfinance as yf

from src.db import (
    bulk_upsert_indicators,
    bulk_upsert_ohlcv,
    bulk_upsert_predictions,
    get_all_tickers,
    get_latest_dates_per_ticker,
    get_stock_history_df,
    init_db,
)
from src.indicators import add_all_indicators
from src.market_analyzer import compute_daily_market_analysis
from src.models_registry import train_and_predict_stock
from src.universe import get_nifty500_tickers_list


def fetch_ticker_trailing_bars(ticker: str, start_date: str) -> List[Dict[str, Any]]:
    """Fetches trailing missing daily bars for a single ticker."""
    try:
        stock = yf.Ticker(ticker)
        df = stock.history(start=start_date, auto_adjust=True)
        if df is None or df.empty:
            df = yf.download(ticker, start=start_date, auto_adjust=True, multi_level_index=False, progress=False)

        if df is None or df.empty:
            return []

        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)

        records = []
        for idx, row in df.iterrows():
            vol = float(row.get("Volume", 1.0))
            records.append({
                "ticker": ticker,
                "date": idx.strftime("%Y-%m-%d"),
                "open": round(float(row["Open"]), 2),
                "high": round(float(row["High"]), 2),
                "low": round(float(row["Low"]), 2),
                "close": round(float(row["Close"]), 2),
                "volume": max(vol, 1.0),
            })
        return records
    except Exception as e:
        return []


def process_single_stock_pipeline(ticker: str) -> Tuple[Optional[Dict], Optional[Dict]]:
    """Loads trailing bars, recomputes indicators, updates model, and generates prediction."""
    try:
        # Load trailing 250 bars from SQLite
        df = get_stock_history_df(ticker, limit=250)
        if df.empty or len(df) < 30:
            return None, None

        # Compute technical indicators
        df_ind = add_all_indicators(df)
        last_date = df.index[-1].strftime("%Y-%m-%d")
        latest_row = df_ind.iloc[-1]

        ind_record = {
            "ticker": ticker,
            "date": last_date,
            "rsi_14": round(float(latest_row.get("RSI_14", 50.0)), 2),
            "macd": round(float(latest_row.get("MACD", 0.0)), 3),
            "macd_signal": round(float(latest_row.get("MACD_Signal", 0.0)), 3),
            "macd_hist": round(float(latest_row.get("MACD_Hist", 0.0)), 3),
            "sma_20": round(float(latest_row.get("SMA_20", 0.0)), 2),
            "sma_50": round(float(latest_row.get("SMA_50", 0.0)), 2),
            "sma_200": round(float(latest_row.get("SMA_200", 0.0)), 2),
            "ema_9": round(float(latest_row.get("EMA_9", 0.0)), 2),
            "ema_21": round(float(latest_row.get("EMA_21", 0.0)), 2),
            "bb_upper": round(float(latest_row.get("BB_Upper", 0.0)), 2),
            "bb_middle": round(float(latest_row.get("BB_Middle", 0.0)), 2),
            "bb_lower": round(float(latest_row.get("BB_Lower", 0.0)), 2),
            "bb_bandwidth": round(float(latest_row.get("BB_Bandwidth", 0.0)), 4),
            "atr_14": round(float(latest_row.get("ATR_14", 0.0)), 2),
            "natr_14": round(float(latest_row.get("NATR_14", 0.0)), 2),
            "adx_14": round(float(latest_row.get("ADX_14", 0.0)), 2),
            "pivot_p": round(float(latest_row.get("Pivot", 0.0)), 2),
            "pivot_r1": round(float(latest_row.get("Pivot_R1", 0.0)), 2),
            "pivot_s1": round(float(latest_row.get("Pivot_S1", 0.0)), 2),
        }

        # Model update & prediction
        pred_record = train_and_predict_stock(ticker, df, mode="next_day")

        return ind_record, pred_record
    except Exception as e:
        return None, None


def run_trailing_daily_cron(max_workers: int = 8) -> Dict[str, Any]:
    """
    Orchestrates the trailing daily cron workflow across all NIFTY 500 stocks.
    """
    start_time = datetime.datetime.now()
    print(f"\n=======================================================")
    print(f"[CronWorker] Starting Trailing Ingestion Pipeline at {start_time}")
    print(f"=======================================================")

    init_db()

    # 1. Check latest date per ticker in database
    latest_dates = get_latest_dates_per_ticker()
    all_tickers = get_all_tickers()
    if not all_tickers:
        all_tickers = get_nifty500_tickers_list()

    today_str = datetime.date.today().strftime("%Y-%m-%d")
    tickers_to_update = {}

    for t in all_tickers:
        last_date = latest_dates.get(t)
        if not last_date:
            # New ticker: default to 1 year of trailing bars
            start_d = (datetime.date.today() - datetime.timedelta(days=365)).strftime("%Y-%m-%d")
            tickers_to_update[t] = start_d
        elif last_date < today_str:
            # Trailing update: start from day after last bar
            next_d = (pd.to_datetime(last_date) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
            tickers_to_update[t] = next_d

    print(f"[CronWorker] Identified {len(tickers_to_update)} tickers requiring trailing updates.")

    # 2. Parallel Trailing Ingestion
    new_ohlcv_bars = []
    if tickers_to_update:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_ticker = {
                executor.submit(fetch_ticker_trailing_bars, ticker, start_d): ticker
                for ticker, start_d in tickers_to_update.items()
            }
            for future in as_completed(future_to_ticker):
                bars = future.result()
                if bars:
                    new_ohlcv_bars.extend(bars)

        if new_ohlcv_bars:
            bulk_upsert_ohlcv(new_ohlcv_bars)
            print(f"[CronWorker] Ingested {len(new_ohlcv_bars)} new trailing OHLCV bars into SQLite.")

    # 3. Parallel Indicator & Model Update Pipeline
    print(f"[CronWorker] Updating technical indicators and retraining models for {len(all_tickers)} stocks...")
    all_indicators = []
    all_predictions = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_ticker = {
            executor.submit(process_single_stock_pipeline, ticker): ticker
            for ticker in all_tickers
        }
        for future in as_completed(future_to_ticker):
            ind_rec, pred_rec = future.result()
            if ind_rec:
                all_indicators.append(ind_rec)
            if pred_rec:
                all_predictions.append(pred_rec)

    if all_indicators:
        bulk_upsert_indicators(all_indicators)
        print(f"[CronWorker] Updated {len(all_indicators)} indicator snapshots.")

    if all_predictions:
        bulk_upsert_predictions(all_predictions)
        print(f"[CronWorker] Generated and stored {len(all_predictions)} fresh predictions.")

    # 4. Market-Wide Breadth & Opportunity Scan
    market_report = compute_daily_market_analysis()

    elapsed = (datetime.datetime.now() - start_time).total_seconds()
    print(f"[CronWorker] Trailing Pipeline completed in {elapsed:.1f}s.")
    print(f"=======================================================\n")

    return {
        "status": "success",
        "updated_tickers_count": len(tickers_to_update),
        "new_bars_count": len(new_ohlcv_bars),
        "predictions_count": len(all_predictions),
        "elapsed_seconds": round(elapsed, 1),
        "market_analysis": market_report,
    }


if __name__ == "__main__":
    run_trailing_daily_cron()
