"""
Automated Stock Data Puller & Quantitative Screener Scheduler
Schedules automatic data pulling and NIFTY 500 technical screening:
1. Every 30 minutes during Indian stock market hours (Mon-Fri 09:15 to 15:30 IST).
2. Daily post-market end-of-day run after market closes (16:00 IST).
3. Strictly automatic with automatic SQLite DB persistence.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, time
import logging
import os
from typing import Any, Dict, List, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.data_loader import fetch_stock_data, resolve_ticker
from src.database import save_ohlcv_to_db, save_screener_run_to_db
from src.screener import BullishTrendingScreenerNode
from src.universe import load_tickers_from_csv

# Setup logger
logger = logging.getLogger("StockScheduler")
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")


def _single_stock_scan_worker(ticker: str) -> Optional[Dict[str, Any]]:
    """Worker function to pull OHLCV and run 26-rule technical evaluation per stock."""
    try:
        resolved = resolve_ticker(ticker)
        df = fetch_stock_data(resolved, period="6mo")
        if df is None or df.empty:
            return None
        
        # Save OHLCV bars into SQLite DB
        save_ohlcv_to_db(resolved, df)

        # Evaluate 26-rule technical filter node
        screener = BullishTrendingScreenerNode(df)
        res = screener.evaluate_latest()
        latest_bar = res.get("latest_bar", {})

        return {
            "ticker": ticker,
            "resolved_ticker": resolved,
            "passed_all": res["passed_all"],
            "passed_count": res["passed_count"],
            "pass_percentage": res["pass_percentage"],
            "close": latest_bar.get("close", 0.0),
            "volume": latest_bar.get("volume", 0),
            "rsi_14": latest_bar.get("rsi_14"),
            "macd": latest_bar.get("macd"),
            "details": res,
        }
    except Exception as e:
        logger.warning(f"Error processing stock '{ticker}': {e}")
        return None


def run_automatic_scheduled_scan(trigger_name: str = "AUTOMATED_SCHEDULER") -> Dict[str, Any]:
    """
    Executes an automatic end-to-end data pull & screening scan across NIFTY 500.
    Saves all results strictly automatically into the SQLite database.
    """
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info(f"⚡ Starting automatic scheduled scan [{trigger_name}] at {now_str}...")

    csv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "nifty500.csv")
    tickers = load_tickers_from_csv(csv_path)
    logger.info(f"Loaded {len(tickers)} tickers from NIFTY 500 universe.")

    scanned_results = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(_single_stock_scan_worker, t): t for t in tickers}
        for future in as_completed(futures):
            res = future.result()
            if res:
                scanned_results.append(res)

    scanned_results.sort(key=lambda x: x["pass_percentage"], reverse=True)
    matched = [item for item in scanned_results if item["passed_all"]]

    # Save run results into SQLite DB
    try:
        run_id = save_screener_run_to_db(
            node_id="NODE_01_BULLISH_TRENDING",
            universe="nifty500",
            scanned_count=len(scanned_results),
            matched_count=len(matched),
            stock_results=scanned_results
        )
        logger.info(f"✅ [SQLite DB] Saved automatic screener run #{run_id} ({len(scanned_results)} stocks evaluated, {len(matched)} 100% matched).")
    except Exception as db_err:
        logger.error(f"❌ Failed to persist automatic screener run to SQLite: {db_err}")

    return {
        "status": "success",
        "timestamp": now_str,
        "trigger": trigger_name,
        "scanned_count": len(scanned_results),
        "matched_count": len(matched),
        "matched_stocks": [m["ticker"] for m in matched],
    }


def is_market_hours() -> bool:
    """Checks if current time is within Indian Stock Market hours (Mon-Fri 09:15 to 15:30 IST)."""
    now = datetime.now()
    # Monday = 0, Sunday = 6
    if now.weekday() >= 5:
        return False
    current_time = now.time()
    market_open = time(9, 15)
    market_close = time(15, 30)
    return market_open <= current_time <= market_close


def _market_hours_job():
    """Triggered every 30 mins; checks if market is open before running."""
    if is_market_hours():
        logger.info("Market hours active (09:15-15:30 IST). Running 30-min automated scan...")
        run_automatic_scheduled_scan(trigger_name="30MIN_MARKET_HOURS_SCAN")
    else:
        logger.info("Outside market hours. Skipping 30-min intra-day scan.")


def _post_market_job():
    """Triggered daily post-market close at 16:00 IST."""
    logger.info("Post-market close trigger (16:00 IST). Running full EOD data pull & scan...")
    run_automatic_scheduled_scan(trigger_name="EOD_POST_MARKET_SCAN")


_global_scheduler: Optional[BackgroundScheduler] = None

def start_automated_scheduler() -> BackgroundScheduler:
    """Starts the background APScheduler daemon with intraday 30-min & EOD post-market jobs."""
    global _global_scheduler
    if _global_scheduler and _global_scheduler.running:
        return _global_scheduler

    scheduler = BackgroundScheduler(timezone="Asia/Kolkata")

    # 1. Market Hours Job: Runs every 30 minutes
    scheduler.add_job(
        _market_hours_job,
        trigger=IntervalTrigger(minutes=30),
        id="job_market_hours_30m",
        name="Market Hours 30-Min Auto Scan",
        replace_existing=True
    )

    # 2. Post-Market Close Job: Mon-Fri at 16:00 (4:00 PM IST)
    scheduler.add_job(
        _post_market_job,
        trigger=CronTrigger(day_of_week="mon-fri", hour=16, minute=0),
        id="job_post_market_eod",
        name="Daily EOD Post-Market Scan",
        replace_existing=True
    )

    scheduler.start()
    _global_scheduler = scheduler
    logger.info("🚀 Automated Stock Scheduler started successfully!")
    logger.info("  • Intraday Job: Every 30 mins during market hours (09:15-15:30 IST)")
    logger.info("  • Post-Market Job: Daily at 16:00 IST (EOD)")
    return scheduler
