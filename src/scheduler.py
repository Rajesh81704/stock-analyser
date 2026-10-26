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
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

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
    """Worker function to pull OHLCV and evaluate all 5 registered screener nodes per stock."""
    try:
        resolved = resolve_ticker(ticker)
        df = fetch_stock_data(resolved, period="6mo")
        if df is None or df.empty:
            return None
        
        # Save OHLCV bars into SQLite DB
        save_ohlcv_to_db(resolved, df)

        # Pre-fetch fundamentals for fundamental growth nodes
        f = {}
        try:
            from src.data_loader import fetch_stock_fundamentals
            f = fetch_stock_fundamentals(resolved)
        except Exception:
            pass

        from src.screener import get_screener_node_by_id

        node_ids = [
            "NODE_01_BULLISH_TRENDING",
            "NODE_02_BULLISH_MOMENTUM",
            "NODE_03_PROFIT_JUMP_200",
            "NODE_04_HIGH_SALES_GROWTH",
            "NODE_05_BEARISH_TRENDING",
        ]

        node_evals = {}
        for nid in node_ids:
            try:
                screener = get_screener_node_by_id(nid, df, fundamentals=f)
                res = screener.evaluate_latest()
                latest_bar = res.get("latest_bar", {})
                node_evals[nid] = {
                    "ticker": ticker,
                    "resolved_ticker": resolved,
                    "passed_all": res.get("passed_all", False),
                    "passed_count": res.get("passed_count", 0),
                    "pass_percentage": res.get("pass_percentage", 0.0),
                    "close": latest_bar.get("close", 0.0),
                    "volume": latest_bar.get("volume", 0),
                    "rsi_14": latest_bar.get("rsi_14"),
                    "macd": latest_bar.get("macd"),
                    "details": res,
                }
            except Exception as n_err:
                logger.warning(f"Error evaluating node {nid} for {ticker}: {n_err}")

        return {
            "ticker": ticker,
            "resolved_ticker": resolved,
            "node_evaluations": node_evals
        }
    except Exception as e:
        logger.warning(f"Error processing stock '{ticker}': {e}")
        return None


def run_automatic_scheduled_scan(trigger_name: str = "AUTOMATED_SCHEDULER") -> Dict[str, Any]:
    """
    Executes an automatic end-to-end data pull & screening scan across NIFTY 500 for ALL screener nodes.
    Saves all results strictly automatically into the SQLite database.
    """
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info(f"⚡ Starting automatic scheduled multi-node scan [{trigger_name}] at {now_str}...")

    csv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "nifty500.csv")
    tickers = load_tickers_from_csv(csv_path)
    logger.info(f"Loaded {len(tickers)} tickers from NIFTY 500 universe.")

    raw_results = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(_single_stock_scan_worker, t): t for t in tickers}
        for future in as_completed(futures):
            res = future.result()
            if res:
                raw_results.append(res)

    node_ids = [
        "NODE_01_BULLISH_TRENDING",
        "NODE_02_BULLISH_MOMENTUM",
        "NODE_03_PROFIT_JUMP_200",
        "NODE_04_HIGH_SALES_GROWTH",
        "NODE_05_BEARISH_TRENDING",
    ]

    saved_summary = {}

    for nid in node_ids:
        node_results = []
        for r in raw_results:
            ne = r.get("node_evaluations", {}).get(nid)
            if ne:
                node_results.append(ne)

        if nid == "NODE_05_BEARISH_TRENDING":
            node_results.sort(key=lambda x: (-x.get("pass_percentage", 0.0), x.get("details", {}).get("latest_bar", {}).get("change_pct", 0.0)))
        else:
            node_results.sort(key=lambda x: (-x.get("pass_percentage", 0.0), -x.get("details", {}).get("latest_bar", {}).get("change_pct", 0.0)))
        matched = [item for item in node_results if item.get("passed_all")]

        try:
            run_id = save_screener_run_to_db(
                node_id=nid,
                universe="nifty500",
                scanned_count=len(node_results),
                matched_count=len(matched),
                stock_results=node_results
            )
            saved_summary[nid] = {"count": len(node_results), "matched": len(matched)}
            logger.info(f"✅ [SQLite DB] Saved screener run for {nid} #{run_id} ({len(node_results)} stocks evaluated, {len(matched)} 100% matched).")
        except Exception as db_err:
            logger.error(f"❌ Failed to persist {nid} screener run to SQLite: {db_err}")

    return {
        "status": "success",
        "timestamp": now_str,
        "trigger": trigger_name,
        "total_stocks_evaluated": len(raw_results),
        "nodes_persisted": saved_summary,
    }


def is_market_hours() -> bool:
    """Checks if current time is within Indian Stock Market hours (Mon-Fri 09:15 to 15:30 IST)."""
    now = datetime.now(IST)
    # Monday = 0, Sunday = 6
    if now.weekday() >= 5:
        return False
    current_time = now.time()
    market_open = time(9, 15)
    market_close = time(15, 30)
    return market_open <= current_time <= market_close


def _morning_intraday_screener_and_trade_job():
    """Triggered Mon-Fri at 09:16 IST to screen top 10 stocks and execute paper algo trades."""
    try:
        from src.algodesk.automation.daily_screener_trader import daily_auto_trader
        if daily_auto_trader.is_market_day():
            logger.info("🌅 [09:16 AM IST] Running Morning Screener & Picking Top 10 Stocks across NIFTY 500 for Intraday Algo Trading...")
            picks = daily_auto_trader.run_morning_screener_and_pick(top_n=10)
            trades = daily_auto_trader.execute_paper_algo_trades(picks=picks)
            logger.info(f"✅ [Morning Screener] Picked {len(picks)} stocks and initiated {len(trades)} algo trades.")
        else:
            logger.info("Skipping morning screener: Weekend or non-market day.")
    except Exception as e:
        logger.error(f"❌ Error during morning screener and trade job: {e}")


def _intraday_trailing_sl_job():
    """Triggered every 2 minutes during market hours to trail SLs and monitor targets/stops."""
    try:
        if is_market_hours():
            from src.algodesk.automation.daily_screener_trader import daily_auto_trader
            updates = daily_auto_trader.monitor_and_update_trailing_sl(force_eod_squareoff=False)
            if updates:
                logger.info(f"📈 [Trailing SL Monitor] Checked {len(updates)} active positions.")
    except Exception as e:
        logger.error(f"❌ Error during intraday trailing SL monitor: {e}")


def _eod_intraday_squareoff_job():
    """Triggered Mon-Fri at 15:15 IST to square off any open intraday positions before market close."""
    try:
        from src.algodesk.automation.daily_screener_trader import daily_auto_trader
        logger.info("🔔 [15:15 PM IST] Closing all open intraday positions at EOD...")
        daily_auto_trader.monitor_and_update_trailing_sl(force_eod_squareoff=True)
    except Exception as e:
        logger.error(f"❌ Error during EOD square-off: {e}")


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

    # 2. Morning Screener & Top Stock Algo Trade: Mon-Fri at 09:16 IST
    scheduler.add_job(
        _morning_intraday_screener_and_trade_job,
        trigger=CronTrigger(day_of_week="mon-fri", hour=9, minute=16),
        id="job_morning_top_stock_screener",
        name="Daily Morning Top 10 Stock Screener & Algo Trade",
        replace_existing=True
    )

    # 3. Intraday Trailing SL Monitor: Every 2 minutes
    scheduler.add_job(
        _intraday_trailing_sl_job,
        trigger=IntervalTrigger(minutes=2),
        id="job_intraday_trailing_sl_monitor",
        name="Intraday Trailing SL Real-Time Monitor",
        replace_existing=True
    )

    # 4. Intraday EOD Square-Off: Mon-Fri at 15:15 IST
    scheduler.add_job(
        _eod_intraday_squareoff_job,
        trigger=CronTrigger(day_of_week="mon-fri", hour=15, minute=15),
        id="job_eod_squareoff",
        name="Daily EOD 15:15 Intraday Square-off",
        replace_existing=True
    )

    # 5. Post-Market Close Job: Mon-Fri at 16:00 (4:00 PM IST)
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
    logger.info("  • Morning Screener & Top Picks: Daily Mon-Fri 09:16 IST")
    logger.info("  • Intraday Trailing SL Engine: Every 2 mins (09:15-15:30 IST)")
    logger.info("  • EOD Square-off: Mon-Fri 15:15 IST")
    logger.info("  • General 30-min Technical Scan: Every 30 mins during market hours")
    logger.info("  • Post-Market Scan: Daily at 16:00 IST (EOD)")
    return scheduler
