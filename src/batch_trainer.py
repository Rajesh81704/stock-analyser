"""
Batch Model Training & Daily Top-Up Engine
Manages:
1. Full Batch Creation of all 500 NIFTY Logistic Regression models with historical data up to today.
2. Trailing Daily Top-Up: Fetches today's missing bar and refits models + updates forward predictions.
3. Thread-safe progress tracking and status reporting for REST API consumers.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
import datetime
import os
import threading
import time
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
from src.models_registry import REGISTRY_DIR, load_or_init_model, train_and_predict_stock
from src.universe import fetch_nifty500_constituents, get_nifty500_tickers_list


class BatchManager:
    """Thread-safe singleton tracking batch training and top-up operations."""
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(BatchManager, cls).__new__(cls)
                cls._instance._init_state()
            return cls._instance

    def _init_state(self):
        self.state_lock = threading.Lock()
        self.state = {
            "task_type": "idle",
            "status": "idle",  # "idle" | "running" | "completed" | "failed"
            "progress_pct": 0.0,
            "total_stocks": 0,
            "completed_stocks": 0,
            "failed_stocks": 0,
            "current_ticker": None,
            "started_at": None,
            "completed_at": None,
            "elapsed_seconds": 0.0,
            "last_error": None,
            "message": "System idle. Ready to initiate model training or daily top-up.",
            "details": {},
        }

    def get_status(self) -> Dict[str, Any]:
        with self.state_lock:
            current_state = dict(self.state)
            if current_state["status"] == "running" and current_state["started_at"]:
                start_dt = datetime.datetime.fromisoformat(current_state["started_at"])
                current_state["elapsed_seconds"] = round((datetime.datetime.now() - start_dt).total_seconds(), 1)
            return current_state

    def set_running(self, task_type: str, total_stocks: int, message: str):
        with self.state_lock:
            self.state.update({
                "task_type": task_type,
                "status": "running",
                "progress_pct": 0.0,
                "total_stocks": total_stocks,
                "completed_stocks": 0,
                "failed_stocks": 0,
                "current_ticker": None,
                "started_at": datetime.datetime.now().isoformat(),
                "completed_at": None,
                "elapsed_seconds": 0.0,
                "last_error": None,
                "message": message,
                "details": {},
            })

    def update_progress(self, completed: int, failed: int, current_ticker: Optional[str] = None):
        with self.state_lock:
            self.state["completed_stocks"] = completed
            self.state["failed_stocks"] = failed
            self.state["current_ticker"] = current_ticker
            total = max(self.state["total_stocks"], 1)
            self.state["progress_pct"] = round(((completed + failed) / total) * 100.0, 1)

    def set_completed(self, message: str, details: Optional[Dict[str, Any]] = None):
        with self.state_lock:
            now = datetime.datetime.now()
            start_dt = datetime.datetime.fromisoformat(self.state["started_at"]) if self.state["started_at"] else now
            elapsed = round((now - start_dt).total_seconds(), 1)
            self.state.update({
                "status": "completed",
                "progress_pct": 100.0,
                "completed_at": now.isoformat(),
                "elapsed_seconds": elapsed,
                "message": message,
                "details": details or {},
            })

    def set_failed(self, error_message: str):
        with self.state_lock:
            now = datetime.datetime.now()
            start_dt = datetime.datetime.fromisoformat(self.state["started_at"]) if self.state["started_at"] else now
            elapsed = round((now - start_dt).total_seconds(), 1)
            self.state.update({
                "status": "failed",
                "completed_at": now.isoformat(),
                "elapsed_seconds": elapsed,
                "last_error": error_message,
                "message": f"Operation failed: {error_message}",
            })

    def reset(self):
        with self.state_lock:
            self._init_state()


batch_manager = BatchManager()


def _ensure_historical_ohlcv_chunks(tickers: List[str], period: str = "5y", chunk_size: int = 25) -> int:
    """Downloads historical OHLCV in chunks for any tickers that lack data in SQLite."""
    latest_dates = get_latest_dates_per_ticker()
    missing_tickers = [t for t in tickers if t not in latest_dates]
    if not missing_tickers:
        return 0

    print(f"[BatchTrainer] Downloading {period} historical data for {len(missing_tickers)} tickers in chunks of {chunk_size}...")
    total_bars_inserted = 0
    all_chunks = [missing_tickers[i:i + chunk_size] for i in range(0, len(missing_tickers), chunk_size)]

    for chunk_idx, chunk in enumerate(all_chunks, 1):
        try:
            batch_df = yf.download(
                chunk,
                period=period,
                auto_adjust=True,
                group_by="ticker",
                progress=False,
                threads=True,
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
                total_bars_inserted += len(records)
                print(f"[BatchTrainer] Batch {chunk_idx}/{len(all_chunks)}: Ingested {len(records)} bars.")

        except Exception as e:
            print(f"[BatchTrainer] Batch {chunk_idx} download error: {e}")

    return total_bars_inserted


def train_single_stock_logistic_model(ticker: str) -> Tuple[Optional[Dict], Optional[Dict]]:
    """Loads trailing bars for a stock, computes indicators, fits Logistic Regression model, saves model artifact."""
    try:
        df = get_stock_history_df(ticker, limit=350)
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

        # Train Logistic Regression classifier & Ridge regressor and save to models_registry/{ticker}.joblib
        pred_record = train_and_predict_stock(ticker, df, mode="next_day")
        return ind_record, pred_record
    except Exception as e:
        print(f"[BatchTrainer] Error training model for {ticker}: {e}")
        return None, None


def run_init_all_models_sync(limit: Optional[int] = None, period: str = "5y", max_workers: int = 8) -> Dict[str, Any]:
    """
    Synchronous worker executing full batch model creation across NIFTY 500 constituents.
    Called directly or as a background task.
    """
    init_db()
    all_tickers = get_all_tickers()
    if not all_tickers or len(all_tickers) < 100:
        all_tickers = get_nifty500_tickers_list()

    if limit and limit > 0:
        all_tickers = all_tickers[:limit]

    total_count = len(all_tickers)
    batch_manager.set_running(
        task_type="init_all_models",
        total_stocks=total_count,
        message=f"Initializing {total_count} Logistic Regression models with historical data up to today..."
    )

    try:
        # Step 1: Ingest missing historical bars in chunks
        bars_added = _ensure_historical_ohlcv_chunks(all_tickers, period=period, chunk_size=25)

        # Step 2: Parallel training of all models
        completed = 0
        failed = 0
        all_indicators = []
        all_predictions = []

        print(f"[BatchTrainer] Training Logistic Regression models for {total_count} stocks with {max_workers} threads...")
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_ticker = {
                executor.submit(train_single_stock_logistic_model, ticker): ticker
                for ticker in all_tickers
            }
            for future in as_completed(future_to_ticker):
                ticker = future_to_ticker[future]
                try:
                    ind_rec, pred_rec = future.result()
                    if ind_rec:
                        all_indicators.append(ind_rec)
                    if pred_rec:
                        all_predictions.append(pred_rec)
                        completed += 1
                    else:
                        failed += 1
                except Exception:
                    failed += 1

                batch_manager.update_progress(completed=completed, failed=failed, current_ticker=ticker)

        # Bulk upsert into SQLite
        if all_indicators:
            bulk_upsert_indicators(all_indicators)
        if all_predictions:
            bulk_upsert_predictions(all_predictions)

        # Step 3: Compute daily market-wide breadth and opportunity analysis
        market_report = compute_daily_market_analysis()

        details = {
            "total_stocks": total_count,
            "models_created_count": completed,
            "failed_count": failed,
            "bars_downloaded": bars_added,
            "models_registry_dir": REGISTRY_DIR,
            "market_analysis_date": market_report.get("date") if market_report else None,
        }

        batch_manager.set_completed(
            message=f"Successfully initialized and saved {completed} Logistic Regression models in models_registry/.",
            details=details,
        )

        return {
            "status": "success",
            "message": f"Successfully created {completed} Logistic Regression models.",
            "details": details,
        }

    except Exception as e:
        batch_manager.set_failed(str(e))
        raise e


def run_topup_and_update_models_sync(ticker: Optional[str] = None, max_workers: int = 8) -> Dict[str, Any]:
    """
    Synchronous worker executing trailing top-up:
    1. Downloads missing recent bars up to today.
    2. Recomputes indicators.
    3. Retrains/updates Logistic Regression models with today's new data.
    4. Generates updated forward prediction.
    5. Re-runs market breadth scan.
    """
    init_db()
    start_time = datetime.datetime.now()
    today_str = datetime.date.today().strftime("%Y-%m-%d")

    if ticker:
        # Single stock top-up
        clean_ticker = ticker.strip().upper()
        if not clean_ticker.startswith("^") and "." not in clean_ticker:
            clean_ticker = f"{clean_ticker}.NS"

        batch_manager.set_running(
            task_type="topup_and_update",
            total_stocks=1,
            message=f"Topping up today's data and updating model for {clean_ticker}..."
        )

        try:
            latest_dates = get_latest_dates_per_ticker()
            last_date = latest_dates.get(clean_ticker)

            new_bars = []
            if not last_date:
                start_d = (datetime.date.today() - datetime.timedelta(days=365)).strftime("%Y-%m-%d")
            else:
                start_d = (pd.to_datetime(last_date) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")

            stock = yf.Ticker(clean_ticker)
            df_new = stock.history(start=start_d, auto_adjust=True)
            if df_new is None or df_new.empty:
                df_new = yf.download(clean_ticker, start=start_d, auto_adjust=True, multi_level_index=False, progress=False)

            if df_new is not None and not df_new.empty:
                if df_new.index.tz is not None:
                    df_new.index = df_new.index.tz_localize(None)
                for idx, row in df_new.iterrows():
                    vol = float(row.get("Volume", 1.0))
                    new_bars.append({
                        "ticker": clean_ticker,
                        "date": idx.strftime("%Y-%m-%d"),
                        "open": round(float(row["Open"]), 2),
                        "high": round(float(row["High"]), 2),
                        "low": round(float(row["Low"]), 2),
                        "close": round(float(row["Close"]), 2),
                        "volume": max(vol, 1.0),
                    })
                bulk_upsert_ohlcv(new_bars)

            # Recompute indicators and update model
            ind_rec, pred_rec = train_single_stock_logistic_model(clean_ticker)
            if ind_rec:
                bulk_upsert_indicators([ind_rec])
            if pred_rec:
                bulk_upsert_predictions([pred_rec])

            elapsed = round((datetime.datetime.now() - start_time).total_seconds(), 2)
            result = {
                "status": "success",
                "ticker": clean_ticker,
                "new_bars_count": len(new_bars),
                "model_updated": pred_rec is not None,
                "latest_prediction": pred_rec,
                "elapsed_seconds": elapsed,
            }
            batch_manager.set_completed(
                message=f"Topped up {len(new_bars)} bars and updated model for {clean_ticker}.",
                details=result
            )
            return result

        except Exception as e:
            batch_manager.set_failed(str(e))
            raise e

    else:
        # Full universe top-up
        all_tickers = get_all_tickers()
        if not all_tickers:
            all_tickers = get_nifty500_tickers_list()

        total_count = len(all_tickers)
        batch_manager.set_running(
            task_type="topup_and_update",
            total_stocks=total_count,
            message=f"Topping up today's latest data and updating models for {total_count} stocks..."
        )

        try:
            from src.cron_worker import run_trailing_daily_cron
            cron_result = run_trailing_daily_cron(max_workers=max_workers)

            batch_manager.set_completed(
                message=f"Successfully topped up today's data and updated models for {total_count} stocks.",
                details=cron_result
            )
            return cron_result
        except Exception as e:
            batch_manager.set_failed(str(e))
            raise e
