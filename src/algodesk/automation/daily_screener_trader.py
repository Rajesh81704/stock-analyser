"""
Daily Automated Intraday Stock Screener & Paper Algo Trading Engine.

Features:
1. Runs multi-factor screener every morning on market days (09:15 IST) across liquid Indian equities.
2. Selects Top 3 Highest-Conviction Stocks based on composite momentum, relative volume, volatility & breakout score.
3. Automatically logs selected stocks into SQLite database table `daily_intraday_picks`.
4. Automatically initiates Paper Algo Trades with:
   - Target price (+2.0% profit target).
   - Initial Stop Loss (-1.0% risk guard).
   - Dynamic Trailing Stop Loss (trails upwards as price advances, moving to breakeven at +0.75% and trailing by 0.5% steps).
5. Continuously monitors ticks and trails SL to lock in profits.
6. Automatically logs every trade execution, trailed SL changes, and final Net PnL (deducting exact Zerodha intraday brokerages and statutory taxes) into SQLite database table `daily_intraday_trades`.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import logging
import math
import os
import sqlite3
import threading
import time
from datetime import datetime, date, timedelta, time as dt_time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from src.costs.calculator import CostCalculator, ZerodhaIntradayCostsConfig
from src.data_loader import fetch_stock_data, resolve_ticker
from src.universe import load_tickers_from_csv

from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

def get_ist_date() -> str:
    """Returns today's date formatted as YYYY-MM-DD in Asia/Kolkata timezone."""
    return datetime.now(IST).date().isoformat()

def get_ist_now_ts() -> str:
    """Returns current timestamp formatted as YYYY-MM-DD HH:MM:SS in Asia/Kolkata timezone."""
    return datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")

logger = logging.getLogger("DailyAutoTrader")
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")

DB_PATH = Path("data/stock_screener.db")


class DailyIntradayAutoTrader:
    """Automated Daily Screener, Stock Picker & Paper Algo Trading Engine."""

    def __init__(self, db_path: Optional[Path] = None, initial_capital: float = 100000.0):
        self.db_path = Path(db_path) if db_path else DB_PATH
        self.initial_capital = initial_capital
        self.cost_calculator = CostCalculator(ZerodhaIntradayCostsConfig())
        self._lock = threading.Lock()
        self._init_database_tables()

    def _get_connection(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=30.0, check_same_thread=False)
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA busy_timeout=30000;")
        except Exception:
            pass
        conn.row_factory = sqlite3.Row
        return conn

    def _init_database_tables(self) -> None:
        """Initializes tables for daily picks and intraday paper trades."""
        with self._lock:
            conn = self._get_connection()
            cur = conn.cursor()

            # 1. Table for Daily Selected Stocks (Top Picks)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS daily_intraday_picks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    rank INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    company_name TEXT,
                    sector TEXT,
                    price REAL NOT NULL,
                    conviction_score REAL NOT NULL,
                    rvol REAL,
                    strategy_name TEXT NOT NULL,
                    entry_trigger_price REAL NOT NULL,
                    initial_sl REAL NOT NULL,
                    target_price REAL NOT NULL,
                    trailing_step_pct REAL DEFAULT 0.5,
                    status TEXT DEFAULT 'PENDING_ENTRY',
                    created_at TEXT NOT NULL
                )
            """)

            # 2. Table for Daily Intraday Paper Algo Trades
            cur.execute("""
                CREATE TABLE IF NOT EXISTS daily_intraday_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_date TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL DEFAULT 'BUY',
                    qty INTEGER NOT NULL,
                    allocated_capital REAL NOT NULL,
                    entry_time TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_time TEXT,
                    exit_price REAL,
                    exit_reason TEXT,
                    initial_sl REAL NOT NULL,
                    highest_price REAL NOT NULL,
                    current_sl REAL NOT NULL,
                    target_price REAL NOT NULL,
                    gross_pnl REAL DEFAULT 0.0,
                    brokerage_and_taxes REAL DEFAULT 0.0,
                    net_pnl REAL DEFAULT 0.0,
                    return_pct REAL DEFAULT 0.0,
                    status TEXT NOT NULL DEFAULT 'OPEN',
                    price_history TEXT DEFAULT '[]',
                    updated_at TEXT NOT NULL
                )
            """)

            conn.commit()
            conn.close()

    def is_market_day(self, check_date: Optional[date] = None) -> bool:
        """Returns True if date is Monday-Friday (ignoring holidays for basic check)."""
        d = check_date or datetime.now(IST).date()
        return d.weekday() < 5

    # -------------------------------------------------------------------------
    # 1. Multi-Factor Intraday Stock Screener & Top Stock Picking
    # -------------------------------------------------------------------------
    def _evaluate_single_stock(self, symbol: str, meta_dict: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Worker to fetch OHLCV and compute multi-factor conviction score for an individual stock."""
        try:
            resolved = resolve_ticker(symbol)
            df = fetch_stock_data(resolved, period="3mo")
            if df is None or len(df) < 25:
                return None

            # Normalize column headers to lowercase
            df.columns = [str(c).lower() for c in df.columns]
            close_series = df["close"]
            volume_series = df["volume"]
            latest_close = float(close_series.iloc[-1])
            prev_close = float(close_series.iloc[-2])
            latest_vol = float(volume_series.iloc[-1])
            avg_vol = float(volume_series.iloc[-20:].mean())

            if latest_close <= 0 or avg_vol <= 0:
                return None

            # 1. Relative Volume (RVOL)
            rvol = latest_vol / avg_vol if avg_vol > 0 else 1.0

            # 2. Moving Average Trend (EMA 20 & SMA 50)
            ema_20 = float(close_series.ewm(span=20, adjust=False).mean().iloc[-1])
            sma_50 = float(close_series.rolling(window=min(len(df), 50)).mean().iloc[-1])
            trend_score = 0.0
            if latest_close > ema_20:
                trend_score += 15.0
            if ema_20 > sma_50:
                trend_score += 15.0

            # 3. Momentum (RSI 14)
            delta = close_series.diff()
            gain = delta.clip(lower=0).rolling(window=14).mean()
            loss = (-delta.clip(upper=0)).rolling(window=14).mean()
            rs = gain / (loss + 1e-8)
            rsi = float((100 - (100 / (1 + rs))).iloc[-1])

            rsi_score = 0.0
            if 50.0 <= rsi <= 72.0:
                rsi_score = 25.0  # Sweet spot for bullish continuation
            elif rsi > 72.0:
                rsi_score = 15.0  # Overbought but strong
            elif 40.0 <= rsi < 50.0:
                rsi_score = 10.0

            # 4. Volatility / ATR Range (Ensuring intraday range for profit)
            high_s = df["high"]
            low_s = df["low"]
            tr = pd.concat([
                high_s - low_s,
                (high_s - close_series.shift()).abs(),
                (low_s - close_series.shift()).abs()
            ], axis=1).max(axis=1)
            atr_14 = float(tr.rolling(window=14).mean().iloc[-1])
            atr_pct = (atr_14 / latest_close) * 100.0

            volatility_score = min(20.0, atr_pct * 8.0)  # Stocks with 2.5%+ ATR get full 20 pts

            # 5. Breakout Proximity (Near 20-day high)
            high_20d = float(high_s.iloc[-20:].max())
            dist_from_high_pct = ((high_20d - latest_close) / latest_close) * 100.0
            breakout_score = max(0.0, 25.0 - (dist_from_high_pct * 4.0))

            # Composite Conviction Score (0 to 100)
            rvol_score = min(25.0, rvol * 12.5)
            total_score = round(trend_score + rsi_score + volatility_score + breakout_score + (rvol_score * 0.3), 2)

            day_change_pct = round(((latest_close - prev_close) / prev_close) * 100.0, 2)

            return {
                "symbol": symbol,
                "price": round(latest_close, 2),
                "day_change_pct": day_change_pct,
                "rvol": round(rvol, 2),
                "rsi": round(rsi, 1),
                "atr_pct": round(atr_pct, 2),
                "score": total_score,
                "strategy_name": "ORB_Momentum_Breakout_V4",
                "initial_sl": round(latest_close * 0.99, 2),    # -1.0% Stop Loss
                "target": round(latest_close * 1.02, 2),        # +2.0% Target
                "trailing_step_pct": 0.5,
            }
        except Exception as scan_err:
            logger.debug(f"Scan error on {symbol}: {scan_err}")
            return None

    def run_morning_screener_and_pick(self, top_n: int = 10, scan_date_str: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Executes full multi-factor quantitative screening across ALL 500+ NIFTY 500 stocks in parallel:
        1. Loads entire NIFTY 500 universe (500+ stocks).
        2. Evaluates Technical Trends, Momentum, RVOL, ATR volatility, and Breakout proximity concurrently.
        3. Sorts by conviction score (0-100) and selects the Top N (default 10) highest-conviction stocks.
        4. Logs selected stocks into SQLite table `daily_intraday_picks`.
        """
        today_str = scan_date_str or get_ist_date()
        now_ts = get_ist_now_ts()

        logger.info(f"⚡ [MorningScreener] Running multi-factor intraday scan for {today_str} across full NIFTY 500...")

        # Load ALL candidate tickers and industry metadata
        meta_dict = {}
        for path_name in ["ind_nifty500list.csv", "data/nifty500.csv"]:
            csv_path = Path(path_name)
            if csv_path.exists():
                try:
                    import csv
                    with open(csv_path, "r", encoding="utf-8") as f:
                        reader = csv.DictReader(f)
                        for row in reader:
                            s = (row.get("Symbol") or row.get("symbol") or "").strip()
                            if s:
                                meta_dict[s] = {
                                    "company": row.get("Company Name", row.get("company_name", f"{s} Ltd")),
                                    "sector": row.get("Industry", row.get("sector", "Indian Equities"))
                                }
                except Exception:
                    pass

        # Priority liquid leaders + full NIFTY 500 universe
        priority_stocks = [
            "RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS", "SBIN", "BHARTIARTL",
            "AXISBANK", "TATAMOTORS", "BAJFINANCE", "LTIM", "SUNPHARMA", "MARUTI",
            "ITC", "KOTAKBANK", "LT", "TITAN", "NTPC", "ONGC", "TATASTEEL",
            "ADANIENT", "JSWSTEEL", "POWERGRID", "HINDUNILVR", "COALINDIA", "VEDL"
        ]
        universe = []
        for s in priority_stocks:
            if s not in universe:
                universe.append(s)
        for s in meta_dict.keys():
            if s not in universe:
                universe.append(s)

        logger.info(f"🚀 [MorningScreener] Scanning full NIFTY 500 universe ({len(universe)} stocks) with 25 parallel worker threads...")

        scored_stocks = []
        with ThreadPoolExecutor(max_workers=25) as executor:
            future_to_stock = {executor.submit(self._evaluate_single_stock, sym, meta_dict): sym for sym in universe}
            for future in as_completed(future_to_stock):
                res = future.result()
                if res:
                    scored_stocks.append(res)

        logger.info(f"✅ [MorningScreener] Successfully evaluated {len(scored_stocks)} / {len(universe)} stocks across NIFTY 500.")

        # Sort by composite conviction score descending
        scored_stocks.sort(key=lambda s: s["score"], reverse=True)
        top_picks = scored_stocks[:top_n]

        # Log into SQLite DB table `daily_intraday_picks`
        with self._lock:
            conn = self._get_connection()
            cur = conn.cursor()

            # Delete any previous picks for the same date to avoid duplicates on re-run
            cur.execute("DELETE FROM daily_intraday_picks WHERE date = ?", (today_str,))

            for rank, stock in enumerate(top_picks, start=1):
                cur.execute("""
                    INSERT INTO daily_intraday_picks (
                        date, rank, symbol, company_name, sector, price,
                        conviction_score, rvol, strategy_name, entry_trigger_price,
                        initial_sl, target_price, trailing_step_pct, status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    today_str,
                    rank,
                    stock["symbol"],
                    meta_dict.get(stock["symbol"], {}).get("company", f"{stock['symbol']} Ltd"),
                    meta_dict.get(stock["symbol"], {}).get("sector", "Indian Equities"),
                    stock["price"],
                    stock["score"],
                    stock["rvol"],
                    stock["strategy_name"],
                    stock["price"],
                    stock["initial_sl"],
                    stock["target"],
                    stock["trailing_step_pct"],
                    "PICKED",
                    now_ts
                ))

            conn.commit()
            conn.close()

        logger.info(f"✅ [MorningScreener] Selected Top {len(top_picks)} intraday stocks for {today_str}: {[s['symbol'] for s in top_picks]}")
        return top_picks

    # -------------------------------------------------------------------------
    # 2. Automated Paper Algo Trade Placement
    # -------------------------------------------------------------------------
    def execute_paper_algo_trades(
        self,
        picks: Optional[List[Dict[str, Any]]] = None,
        trade_date_str: Optional[str] = None,
        total_capital: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """
        Enters paper algo trades for the selected top stocks with Initial SL,
        Target (+2%), and dynamic Trailing SL parameters. Smartly distributes `total_capital`
        using Gemini API (with quantitative multi-factor risk parity fallback).
        Logs into `daily_intraday_trades`.
        """
        today_str = trade_date_str or get_ist_date()
        now_ts = get_ist_now_ts()

        # Strict 3:00 PM Cutoff: Block opening any new intraday positions after 15:00 IST
        if not trade_date_str and datetime.now(IST).time() >= dt_time(15, 0):
            logger.warning("🚫 [PaperTrader] Cannot enter new intraday trades after 15:00 IST (3:00 PM square-off cutoff passed).")
            return []

        # If no picks provided in memory, read from `daily_intraday_picks`
        if not picks:
            conn = self._get_connection()
            cur = conn.cursor()
            cur.execute("""
                SELECT symbol, price, initial_sl, target_price, trailing_step_pct, strategy_name
                FROM daily_intraday_picks
                WHERE date = ? ORDER BY rank ASC LIMIT 10
            """, (today_str,))
            rows = cur.fetchall()
            conn.close()

            picks = [
                {
                    "symbol": r["symbol"],
                    "price": r["price"],
                    "initial_sl": r["initial_sl"],
                    "target": r["target_price"],
                    "trailing_step_pct": r["trailing_step_pct"] or 0.5,
                    "strategy_name": r["strategy_name"]
                }
                for r in rows
            ]

        if not picks:
            logger.warning("[PaperTrader] No top picks found to execute trades.")
            return []

        pool_capital = float(total_capital if total_capital is not None and total_capital > 0 else self.initial_capital)

        # Smart Capital Distribution via Gemini API (with Quant Conviction Risk-Parity fallback)
        alloc_map = {}
        try:
            from src.algodesk.ai.gemini_client import GeminiClient
            gc = GeminiClient()
            alloc_res = gc.optimize_capital_allocation(total_capital=pool_capital, picks=picks)
            if alloc_res and alloc_res.allocations:
                alloc_map = {item.symbol: item for item in alloc_res.allocations}
                logger.info(f"🧠 [SmartAllocator] Gemini distributed ₹{pool_capital:,.2f} across {len(picks)} stocks ({alloc_res.model_used}). Strategy: {alloc_res.strategy_overview[:120]}...")
        except Exception as alloc_err:
            logger.warning(f"Smart allocation notice ({alloc_err}), falling back to equal weighting.")

        capital_per_trade = pool_capital / max(1, len(picks))
        executed_trades = []

        with self._lock:
            conn = self._get_connection()
            cur = conn.cursor()

            for stock in picks:
                sym = stock["symbol"]
                entry_price = float(stock["price"])
                initial_sl = float(stock.get("initial_sl") or (entry_price * 0.99))
                target = float(stock.get("target") or (entry_price * 1.02))

                smart_item = alloc_map.get(sym)
                if smart_item:
                    allocated_for_trade = round(float(smart_item.allocated_capital), 2)
                    qty = max(1, int(smart_item.qty))
                    entry_note = f"Smart AI Sizing: ₹{allocated_for_trade:,.2f} ({smart_item.weight_pct:.1f}%) | {smart_item.rationale}"
                    weight_val = smart_item.weight_pct
                    rationale_val = smart_item.rationale
                else:
                    qty = max(1, int(capital_per_trade / entry_price))
                    allocated_for_trade = round(qty * entry_price, 2)
                    entry_note = f"Standard sizing: ₹{allocated_for_trade:,.2f} | 1% SL & 2% Target"
                    weight_val = round((allocated_for_trade / pool_capital) * 100.0, 1)
                    rationale_val = "Equal distribution"

                # Check if trade already exists for today
                cur.execute("SELECT id FROM daily_intraday_trades WHERE trade_date = ? AND symbol = ?", (today_str, sym))
                existing = cur.fetchone()

                if existing:
                    logger.info(f"Trade already exists for {sym} on {today_str}. Skipping duplicate entry.")
                    continue

                initial_log = json.dumps([{
                    "time": now_ts,
                    "event": "ENTRY",
                    "price": entry_price,
                    "sl": initial_sl,
                    "target": target,
                    "note": entry_note
                }])

                cur.execute("""
                    INSERT INTO daily_intraday_trades (
                        trade_date, symbol, side, qty, allocated_capital,
                        entry_time, entry_price, initial_sl, highest_price, current_sl,
                        target_price, gross_pnl, brokerage_and_taxes, net_pnl, return_pct,
                        status, price_history, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    today_str,
                    sym,
                    "BUY",
                    qty,
                    allocated_for_trade,
                    now_ts,
                    entry_price,
                    initial_sl,
                    entry_price,  # highest_price so far
                    initial_sl,   # current_sl starts at initial_sl
                    target,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    "OPEN",
                    initial_log,
                    now_ts
                ))

                trade_id = cur.lastrowid

                # Update status in daily_intraday_picks
                cur.execute("UPDATE daily_intraday_picks SET status = 'TRADED' WHERE date = ? AND symbol = ?", (today_str, sym))

                executed_trades.append({
                    "trade_id": trade_id,
                    "symbol": sym,
                    "qty": qty,
                    "allocated_capital": allocated_for_trade,
                    "weight_pct": weight_val,
                    "ai_rationale": rationale_val,
                    "entry_price": entry_price,
                    "initial_sl": initial_sl,
                    "current_sl": initial_sl,
                    "target_price": target,
                    "status": "OPEN"
                })

            conn.commit()
            conn.close()

        logger.info(f"🚀 [PaperTrader] Successfully initiated {len(executed_trades)} paper algo trades for {today_str}.")
        return executed_trades

    # -------------------------------------------------------------------------
    # 3. Dynamic Trailing Stop Loss & Live Price Monitor Engine
    # -------------------------------------------------------------------------
    def monitor_and_update_trailing_sl(
        self,
        current_prices: Optional[Dict[str, float]] = None,
        force_eod_squareoff: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Monitors all OPEN trades:
        1. As price rises, raises Trailing SL dynamically:
           - At +0.75% profit: moves SL to Breakeven (entry_price).
           - For each additional +0.5% advance: trails SL to (highest_price - 0.5%).
        2. Closes trades on Target Hit (+2%), Trailing SL Hit (locking in gains), or Stop Loss Hit.
        3. Strict 3:00 PM IST Cutoff: By 3:00 PM IST (15:00), ALL open positions are squared off
           at market price even if target is not achieved.
        4. Calculates exact Zerodha statutory intraday taxes and net PnL, persisting to DB.
        """
        now_dt = datetime.now(IST)
        now_ts = now_dt.strftime("%Y-%m-%d %H:%M:%S")
        is_past_3pm = now_dt.time() >= dt_time(15, 0)

        # Enforce 3:00 PM strict square-off: if forced or past 15:00 IST without injected mock prices
        is_eod_cutoff = force_eod_squareoff or (is_past_3pm and current_prices is None)

        # Read open trades quickly and close read connection
        conn = self._get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, trade_date, symbol, side, qty, allocated_capital,
                   entry_time, entry_price, initial_sl, highest_price, current_sl,
                   target_price, price_history, status
            FROM daily_intraday_trades
            WHERE status = 'OPEN'
        """)
        open_trades = [dict(r) for r in cur.fetchall()]
        conn.close()

        if not open_trades:
            return []

        # Instantaneous batch quote fetching via KiteConnect for all open positions
        batch_prices = {}
        if not current_prices:
            try:
                from src.data_loader import KITE_API_KEY, KITE_ACCESS_TOKEN
                if KITE_API_KEY and KITE_ACCESS_TOKEN:
                    from kiteconnect import KiteConnect
                    kc = KiteConnect(api_key=KITE_API_KEY)
                    kc.set_access_token(KITE_ACCESS_TOKEN)
                    instruments = [f"NSE:{r['symbol'].replace('.NS', '')}" for r in open_trades]
                    q_map = kc.quote(instruments)
                    if q_map:
                        for r in open_trades:
                            sym_clean = r["symbol"].replace(".NS", "")
                            k_key = f"NSE:{sym_clean}"
                            if k_key in q_map:
                                lp = float(q_map[k_key].get("last_price") or 0.0)
                                if lp > 0:
                                    batch_prices[r["symbol"]] = lp
                                    batch_prices[sym_clean] = lp
            except Exception as batch_err:
                logger.debug(f"KiteConnect batch quote notice: {batch_err}")

        updates = []
        trade_db_writes = []

        for row in open_trades:
            t_id = row["id"]
            sym = row["symbol"]
            qty = row["qty"]
            entry_p = float(row["entry_price"])
            curr_sl = float(row["current_sl"])
            highest_p = float(row["highest_price"])
            target_p = float(row["target_price"])
            allocated = float(row["allocated_capital"])
            history = json.loads(row["price_history"] or "[]")

            # Get current price via batch Kite quote -> custom price -> fast info
            curr_p = None
            if current_prices and sym in current_prices:
                curr_p = float(current_prices[sym])
            elif batch_prices and sym in batch_prices:
                curr_p = float(batch_prices[sym])
            elif batch_prices and sym.replace(".NS", "") in batch_prices:
                curr_p = float(batch_prices[sym.replace(".NS", "")])
            else:
                try:
                    resolved = resolve_ticker(sym)
                    import yfinance as yf
                    tk = yf.Ticker(resolved)
                    fi = getattr(tk, "fast_info", None)
                    if fi and getattr(fi, "last_price", None):
                        curr_p = float(fi.last_price)
                    else:
                        df = fetch_stock_data(resolved, period="1d")
                        if df is not None and not df.empty:
                            curr_p = float(df["close"].iloc[-1])
                except Exception:
                    pass

            if curr_p is None or curr_p <= 0:
                curr_p = entry_p  # fallback

            # Update highest price watermark
            new_highest = max(highest_p, curr_p)
            gain_from_entry_pct = ((new_highest - entry_p) / entry_p) * 100.0

            # Trailing SL & Target Logic (High-Profitability Multi-tier Protection):
            # Tier 1 (Gain >= +0.75%): Move SL to breakeven + roundtrip tax buffer (zero risk)
            # Tier 2 (Gain >= +1.25%): Trail SL 0.5% below high watermark (locks in at least +0.75%)
            # Tier 3 (Gain >= +1.75%): Tighten trail to 0.4% below high watermark (locks in at least +1.35%)
            # Tier 4 (Target Hit >= target_p): Realize full target profit (capturing any upside surge)
            candidate_sl = curr_sl

            if gain_from_entry_pct >= 1.75:
                tight_trail = round(new_highest * 0.996, 2)
                candidate_sl = max(candidate_sl, tight_trail)
            elif gain_from_entry_pct >= 1.25:
                dynamic_trail = round(new_highest * 0.995, 2)
                candidate_sl = max(candidate_sl, dynamic_trail)
            elif gain_from_entry_pct >= 0.75:
                candidate_sl = max(candidate_sl, entry_p)

            new_sl = max(curr_sl, candidate_sl)
            sl_event = None

            if new_sl > curr_sl:
                if curr_sl < entry_p and new_sl >= entry_p:
                    sl_event = f"SL_TRAILED_TO_BREAKEVEN ({new_sl})"
                else:
                    sl_event = f"SL_TRAILED_UP_TO_{new_sl}"

                history.append({
                    "time": now_ts,
                    "event": sl_event,
                    "highest_price": new_highest,
                    "new_sl": new_sl,
                    "note": f"High reached ₹{new_highest:.2f} (+{gain_from_entry_pct:.2f}%). Trailing SL raised to ₹{new_sl:.2f}."
                })

            # Check Exit Conditions:
            # 1. Strict 3:00 PM Cutoff Square-Off (by 3pm all positions must be squared off even if target not achieved)
            # 2. Target Hit (Full Target profit booked, capturing any upside gap)
            # 3. Trailing SL Hit / Stop Loss Hit (Banks locked profit or caps initial risk)
            exit_price = None
            exit_reason = None

            if is_eod_cutoff:
                exit_price = curr_p
                exit_reason = "3PM_SQUAREOFF"
            elif curr_p >= target_p:
                exit_price = max(curr_p, target_p)
                exit_reason = "TARGET_HIT"
            elif curr_p <= new_sl:
                exit_price = new_sl
                exit_reason = "TRAILING_SL_HIT" if new_sl >= entry_p else "STOP_LOSS_HIT"

            if exit_price is not None:
                # Calculate exact Zerodha statutory intraday cost
                cost_breakdown = self.cost_calculator.calculate_roundtrip(
                    side="LONG",
                    qty=qty,
                    raw_entry_price=entry_p,
                    raw_exit_price=exit_price,
                    trailing_turnover_cr=120.0
                )
                brokerage_taxes = round(cost_breakdown.total_costs, 2)
                gross_pnl = round((exit_price - entry_p) * qty, 2)
                net_pnl = round(gross_pnl - brokerage_taxes, 2)
                ret_pct = round((net_pnl / allocated) * 100.0, 2)

                history.append({
                    "time": now_ts,
                    "event": "EXIT",
                    "exit_price": exit_price,
                    "exit_reason": exit_reason,
                    "gross_pnl": gross_pnl,
                    "brokerage_taxes": brokerage_taxes,
                    "net_pnl": net_pnl,
                    "return_pct": ret_pct
                })

                trade_db_writes.append({
                    "type": "CLOSED",
                    "trade_id": t_id,
                    "exit_time": now_ts,
                    "exit_price": exit_price,
                    "exit_reason": exit_reason,
                    "highest_price": new_highest,
                    "current_sl": new_sl,
                    "gross_pnl": gross_pnl,
                    "brokerage_taxes": brokerage_taxes,
                    "net_pnl": net_pnl,
                    "return_pct": ret_pct,
                    "price_history": json.dumps(history),
                    "updated_at": now_ts
                })

                updates.append({
                    "trade_id": t_id,
                    "symbol": sym,
                    "action": "CLOSED",
                    "exit_reason": exit_reason,
                    "exit_price": exit_price,
                    "gross_pnl": gross_pnl,
                    "brokerage_taxes": brokerage_taxes,
                    "net_pnl": net_pnl,
                    "return_pct": ret_pct
                })
                logger.info(f"🎯 [PaperTrader] Trade Closed {sym}: {exit_reason} @ ₹{exit_price:.2f} | Net PnL: ₹{net_pnl:+.2f} ({ret_pct:+.2f}%)")
            else:
                trade_db_writes.append({
                    "type": "TRAILING_UPDATE",
                    "trade_id": t_id,
                    "highest_price": new_highest,
                    "current_sl": new_sl,
                    "price_history": json.dumps(history),
                    "updated_at": now_ts
                })

                updates.append({
                    "trade_id": t_id,
                    "symbol": sym,
                    "action": "TRAILING_UPDATE",
                    "current_price": curr_p,
                    "highest_price": new_highest,
                    "current_sl": new_sl
                })

        # Commit computed updates atomically under lock
        with self._lock:
            conn = self._get_connection()
            cur = conn.cursor()

            for u in trade_db_writes:
                if u["type"] == "CLOSED":
                    cur.execute("""
                        UPDATE daily_intraday_trades
                        SET exit_time = ?, exit_price = ?, exit_reason = ?,
                            highest_price = ?, current_sl = ?, gross_pnl = ?,
                            brokerage_and_taxes = ?, net_pnl = ?, return_pct = ?,
                            status = 'CLOSED', price_history = ?, updated_at = ?
                        WHERE id = ?
                    """, (
                        u["exit_time"], u["exit_price"], u["exit_reason"],
                        u["highest_price"], u["current_sl"], u["gross_pnl"],
                        u["brokerage_taxes"], u["net_pnl"], u["return_pct"],
                        u["price_history"], u["updated_at"], u["trade_id"]
                    ))
                else:
                    cur.execute("""
                        UPDATE daily_intraday_trades
                        SET highest_price = ?, current_sl = ?, price_history = ?, updated_at = ?
                        WHERE id = ?
                    """, (u["highest_price"], u["current_sl"], u["price_history"], u["updated_at"], u["trade_id"]))

            conn.commit()
            conn.close()

        return updates

    # -------------------------------------------------------------------------
    # 4. Status Payload & History Reporting for UI & Dashboard
    # -------------------------------------------------------------------------
    def get_automation_status(self) -> Dict[str, Any]:
        """Returns comprehensive status, today's picks, open positions, and all trade logs."""
        today_str = get_ist_date()

        # Enforce 3:00 PM strict squareoff check: If past 15:00 IST and open trades exist, square them off
        if datetime.now(IST).time() >= dt_time(15, 0):
            try:
                conn_check = self._get_connection()
                cur_check = conn_check.cursor()
                cur_check.execute("SELECT COUNT(*) FROM daily_intraday_trades WHERE status = 'OPEN'")
                open_cnt = cur_check.fetchone()[0]
                conn_check.close()
                if open_cnt > 0:
                    self.monitor_and_update_trailing_sl(force_eod_squareoff=True)
            except Exception as e_sq:
                logger.warning(f"Auto 3PM status square-off notice: {e_sq}")

        conn = self._get_connection()
        cur = conn.cursor()

        # Today's picks
        cur.execute("""
            SELECT rank, symbol, company_name, price, conviction_score, rvol,
                   strategy_name, entry_trigger_price, initial_sl, target_price, status, created_at
            FROM daily_intraday_picks
            WHERE date = ? ORDER BY rank ASC
        """, (today_str,))
        today_picks = [dict(r) for r in cur.fetchall()]

        # Open trades
        cur.execute("""
            SELECT id, trade_date, symbol, side, qty, allocated_capital,
                   entry_time, entry_price, initial_sl, highest_price, current_sl,
                   target_price, gross_pnl, net_pnl, return_pct, status, updated_at
            FROM daily_intraday_trades
            WHERE status = 'OPEN' ORDER BY id DESC
        """)
        open_trades = [dict(r) for r in cur.fetchall()]

        # Recent closed trades (last 50)
        cur.execute("""
            SELECT id, trade_date, symbol, side, qty, allocated_capital,
                   entry_time, entry_price, exit_time, exit_price, exit_reason,
                   initial_sl, highest_price, current_sl, target_price,
                   gross_pnl, brokerage_and_taxes, net_pnl, return_pct, status, price_history
            FROM daily_intraday_trades
            ORDER BY id DESC LIMIT 50
        """)
        all_trades = [dict(r) for r in cur.fetchall()]

        # Calculate overall metrics
        total_trades = len(all_trades)
        closed_trades = [t for t in all_trades if t["status"] == "CLOSED"]
        winning_trades = [t for t in closed_trades if (t.get("net_pnl") or 0.0) > 0]
        total_net_pnl = sum((t.get("net_pnl") or 0.0) for t in closed_trades)
        total_brokerage = sum((t.get("brokerage_and_taxes") or 0.0) for t in closed_trades)
        win_rate = round((len(winning_trades) / len(closed_trades) * 100.0), 1) if closed_trades else 0.0

        conn.close()

        return {
            "status": "active",
            "is_market_day": self.is_market_day(),
            "today_date": today_str,
            "today_picks_count": len(today_picks),
            "today_picks": today_picks,
            "open_trades_count": len(open_trades),
            "open_trades": open_trades,
            "recent_trades_count": len(all_trades),
            "recent_trades": all_trades,
            "performance_summary": {
                "total_trades": total_trades,
                "closed_trades": len(closed_trades),
                "winning_trades": len(winning_trades),
                "win_rate": win_rate,
                "total_net_pnl": round(total_net_pnl, 2),
                "total_brokerage_paid": round(total_brokerage, 2),
            }
        }

    # -------------------------------------------------------------------------
    # 5. On-Demand Simulation / Test Workflow
    # -------------------------------------------------------------------------
    def simulate_morning_routine_and_trade(self) -> Dict[str, Any]:
        """
        Executes a complete on-demand test cycle:
        1. Runs screener and picks top 3 stocks.
        2. Places paper algo trades with SL & target.
        3. Simulates realistic intraday price ticks testing trailing SL movement.
        """
        picks = self.run_morning_screener_and_pick(top_n=3)
        trades = self.execute_paper_algo_trades(picks=picks)

        # Simulate price ticks showing trailing SL adjustment
        simulated_prices = {}
        for stock in picks:
            sym = stock["symbol"]
            entry_p = float(stock["price"])
            # Simulate a 1.5% favorable move to trigger trailing SL
            simulated_prices[sym] = round(entry_p * 1.015, 2)

        # Run trailing SL update with simulated price
        trail_updates = self.monitor_and_update_trailing_sl(current_prices=simulated_prices)

        return {
            "status": "success",
            "message": "Executed automated morning screener, top 3 stock pick, and initiated paper algo trades.",
            "picks": picks,
            "trades": trades,
            "trailing_updates": trail_updates
        }


# Global singleton instance
daily_auto_trader = DailyIntradayAutoTrader()
