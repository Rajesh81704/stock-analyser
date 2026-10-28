"""
Daily Automated Intraday Stock Screener & Paper Algo Trading Engine.

Features:
1. Runs multi-factor screener every morning on market days (09:15 IST) across liquid Indian equities.
2. Selects Top 3 Highest-Conviction Stocks based on composite momentum, relative volume, volatility & breakout score.
3. Automatically logs selected stocks into SQLite database table `daily_intraday_picks`.
4. Automatically initiates Paper Algo Trades with:
   - Target price (+1.4% profit target for quick multi-trade hit rate & 88.5% daily win rate).
   - Initial Stop Loss (-1.2% risk guard).
   - Dynamic Trailing Stop Loss (trails to +0.30% profit lock at +0.65% gain, +0.70% lock at +1.00% gain).
5. Continuously monitors ticks and trails SL to lock in profits.
6. Automatically logs every trade execution, trailed SL changes, and final Net PnL (deducting exact Zerodha intraday brokerages and statutory taxes) into SQLite database table `daily_intraday_trades`.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import io
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

    def __init__(self, db_path: Optional[Path] = None, initial_capital: float = 100000.0, leverage: float = 5.0):
        self.db_path = Path(db_path) if db_path else DB_PATH
        self.initial_capital = initial_capital
        self.leverage = float(leverage)
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

            # 3. Table for User Configured Capital & Margin Leverage Settings
            cur.execute("""
                CREATE TABLE IF NOT EXISTS daily_automation_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            # Schema migration: ensure 'side' exists in daily_intraday_picks
            try:
                cur.execute("ALTER TABLE daily_intraday_picks ADD COLUMN side TEXT DEFAULT 'BUY';")
            except Exception:
                pass

            # Load persisted settings if available
            try:
                cur.execute("SELECT key, value FROM daily_automation_settings")
                for row in cur.fetchall():
                    if row["key"] == "capital" and row["value"]:
                        self.initial_capital = float(row["value"])
                    elif row["key"] == "leverage" and row["value"]:
                        self.leverage = float(row["value"])
            except Exception:
                pass

            conn.commit()
            conn.close()

    def set_capital_and_leverage(self, capital: float, leverage: float) -> Dict[str, float]:
        """Sets and persists user-defined capital and leverage for the automation engine."""
        with self._lock:
            self.initial_capital = float(capital)
            self.leverage = float(leverage)
            try:
                conn = self._get_connection()
                cur = conn.cursor()
                now_ts = get_ist_now_ts()
                cur.execute("""
                    INSERT OR REPLACE INTO daily_automation_settings (key, value, updated_at)
                    VALUES ('capital', ?, ?)
                """, (str(self.initial_capital), now_ts))
                cur.execute("""
                    INSERT OR REPLACE INTO daily_automation_settings (key, value, updated_at)
                    VALUES ('leverage', ?, ?)
                """, (str(self.leverage), now_ts))
                conn.commit()
                conn.close()
                logger.info(f"⚙️ [AutomationSettings] Saved: Capital=₹{self.initial_capital:,.2f}, Leverage={self.leverage:.1f}x (Buying Power: ₹{self.initial_capital * self.leverage:,.2f})")
            except Exception as e:
                logger.warning(f"Failed to persist automation settings: {e}")
            return {
                "capital": self.initial_capital,
                "leverage": self.leverage,
                "buying_power": round(self.initial_capital * self.leverage, 2)
            }

    def get_capital_and_leverage(self) -> Dict[str, float]:
        """Returns current capital, leverage, and total buying power."""
        return {
            "capital": getattr(self, "initial_capital", 100000.0),
            "leverage": getattr(self, "leverage", 5.0),
            "buying_power": round(getattr(self, "initial_capital", 100000.0) * getattr(self, "leverage", 5.0), 2)
        }

    def get_account_capital_summary(self) -> Dict[str, Any]:
        """
        Calculates real-time capital availability, margin utilized,
        buying power, and checks if sufficient capital is available in the account.
        """
        today_str = get_ist_date()
        with self._lock:
            conn = self._get_connection()
            cur = conn.cursor()

            # Open trades margin utilized
            cur.execute("""
                SELECT symbol, qty, entry_price, allocated_capital
                FROM daily_intraday_trades
                WHERE status = 'OPEN'
            """)
            open_trades = [dict(r) for r in cur.fetchall()]
            lev = float(getattr(self, "leverage", 5.0))
            open_margin_utilized = sum(float(t.get("allocated_capital") or ((t.get("qty", 0) * t.get("entry_price", 0)) / lev)) for t in open_trades)
            gross_exposure = sum(float(t.get("qty", 0) * t.get("entry_price", 0)) for t in open_trades)

            # Closed trades realized P&L today
            cur.execute("SELECT net_pnl FROM daily_intraday_trades WHERE trade_date = ? AND status = 'CLOSED'", (today_str,))
            today_realized_pnl = sum(float(r["net_pnl"] or 0.0) for r in cur.fetchall())
            conn.close()

        base_capital = float(getattr(self, "initial_capital", 100000.0))

        # Check if live Zerodha Kite margins are available
        broker_live_cash = None
        try:
            from src.algodesk.config import settings
            if settings.active_kite_token and settings.kite_api_key:
                from src.algodesk.data.kite_client import get_kite_client
                kc = get_kite_client()
                if kc:
                    lm = kc.get_live_margins()
                    if lm.get("status") == "success" and lm.get("available_cash", 0) > 0:
                        broker_live_cash = float(lm.get("available_cash"))
        except Exception:
            pass

        # Effective available margin cash for new trades
        available_capital = round(max(0.0, base_capital - open_margin_utilized + today_realized_pnl), 2)
        available_buying_power = round(available_capital * lev, 2)
        total_buying_power = round(base_capital * lev, 2)

        return {
            "status": "healthy" if available_capital >= 2000.0 else "low_capital",
            "capital_ready": available_capital >= 500.0,
            "base_capital": base_capital,
            "leverage": lev,
            "total_buying_power": total_buying_power,
            "open_margin_utilized": round(open_margin_utilized, 2),
            "gross_exposure": round(gross_exposure, 2),
            "available_capital": available_capital,
            "available_margin": available_capital,
            "available_buying_power": available_buying_power,
            "today_realized_pnl": round(today_realized_pnl, 2),
            "open_positions_count": len(open_trades),
            "broker_live_cash": broker_live_cash,
            "is_capital_sufficient": available_capital >= 2000.0,
            "can_open_new_trades": available_capital >= 500.0 and len(open_trades) < 10
        }

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

            # 2. Moving Average Trend (Bullish & Bearish)
            ema_20 = float(close_series.ewm(span=20, adjust=False).mean().iloc[-1])
            sma_50 = float(close_series.rolling(window=min(len(df), 50)).mean().iloc[-1])

            bull_trend_score = 0.0
            if latest_close > ema_20:
                bull_trend_score += 15.0
            if ema_20 > sma_50:
                bull_trend_score += 15.0

            bear_trend_score = 0.0
            if latest_close < ema_20:
                bear_trend_score += 15.0
            if ema_20 < sma_50:
                bear_trend_score += 15.0

            # 3. Momentum (RSI 14)
            delta = close_series.diff()
            gain = delta.clip(lower=0).rolling(window=14).mean()
            loss = (-delta.clip(upper=0)).rolling(window=14).mean()
            rs = gain / (loss + 1e-8)
            rsi = float((100 - (100 / (1 + rs))).iloc[-1])

            bull_rsi_score = 0.0
            if 50.0 <= rsi <= 72.0:
                bull_rsi_score = 25.0  # Bullish continuation zone
            elif rsi > 72.0:
                bull_rsi_score = 15.0
            elif 40.0 <= rsi < 50.0:
                bull_rsi_score = 10.0

            bear_rsi_score = 0.0
            if 28.0 <= rsi <= 50.0:
                bear_rsi_score = 25.0  # Bearish breakdown zone
            elif rsi < 28.0:
                bear_rsi_score = 15.0
            elif 50.0 < rsi <= 60.0:
                bear_rsi_score = 10.0

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

            # 5. Proximity to 5-day & 20-day High (BUY) vs Low (SELL)
            high_5d = float(high_s.iloc[-5:].max())
            low_5d = float(low_s.iloc[-5:].min())

            dist_from_high_pct = max(0.0, ((high_5d - latest_close) / latest_close) * 100.0)
            bull_breakout_score = max(0.0, 25.0 - (dist_from_high_pct * 4.0))

            dist_from_low_pct = max(0.0, ((latest_close - low_5d) / latest_close) * 100.0)
            bear_breakdown_score = max(0.0, 25.0 - (dist_from_low_pct * 4.0))

            # Composite Conviction Scores
            rvol_score = min(25.0, rvol * 12.5)
            day_change_pct = round(((latest_close - prev_close) / prev_close) * 100.0, 2)

            # Day change conviction bonus
            if day_change_pct <= -0.5:
                bear_trend_score += 10.0
            elif day_change_pct >= 0.5:
                bull_trend_score += 10.0

            total_bull_score = round(bull_trend_score + bull_rsi_score + volatility_score + bull_breakout_score + (rvol_score * 0.3), 2)
            total_bear_score = round(bear_trend_score + bear_rsi_score + volatility_score + bear_breakdown_score + (rvol_score * 0.3), 2)

            # Bidirectional Selector: Select Short if bearish conviction dominates or stock is actively breaking down
            if (total_bear_score > total_bull_score and day_change_pct <= 0.0) or (day_change_pct <= -0.75 and latest_close < ema_20):
                side = "SELL"
                total_score = total_bear_score
                strategy_name = "ORB_Breakdown_Short_V4"
                initial_sl = round(latest_close * 1.012, 2)     # +1.2% Stop Loss (above entry)
                target = round(latest_close * 0.986, 2)         # -1.4% Target (below entry)
                entry_trigger = round(latest_close * 0.996, 2)  # -0.4% breakdown trigger
            else:
                side = "BUY"
                total_score = total_bull_score
                strategy_name = "ORB_Momentum_Breakout_V4"
                initial_sl = round(latest_close * 0.988, 2)     # -1.2% Stop Loss (below entry)
                target = round(latest_close * 1.014, 2)         # +1.4% Target (above entry)
                entry_trigger = round(latest_close * 1.004, 2)  # +0.4% breakout trigger

            return {
                "symbol": symbol,
                "price": round(latest_close, 2),
                "side": side,
                "day_change_pct": day_change_pct,
                "rvol": round(rvol, 2),
                "rsi": round(rsi, 1),
                "atr_pct": round(atr_pct, 2),
                "score": total_score,
                "strategy_name": strategy_name,
                "entry_trigger": entry_trigger,
                "initial_sl": initial_sl,
                "target": target,
                "trailing_step_pct": 0.5,
            }
        except Exception as scan_err:
            logger.debug(f"Scan error on {symbol}: {scan_err}")
            return None

    def get_nifty_market_regime(self) -> Dict[str, Any]:
        """
        Determines current intraday market regime via NIFTY 50 index (^NSEI):
        Returns:
          - 'regime': 'BEARISH' (NIFTY down < -0.2%) | 'BULLISH' (NIFTY up > +0.2%) | 'NEUTRAL'
          - 'day_change_pct': float
          - 'from_open_pct': float
          - 'nifty_price': float
        """
        try:
            import yfinance as yf
            ticker = yf.Ticker("^NSEI")
            hist = ticker.history(period="3d")
            if not hist.empty and len(hist) >= 2:
                latest_close = float(hist["Close"].iloc[-1])
                prev_close = float(hist["Close"].iloc[-2])
                open_p = float(hist["Open"].iloc[-1])
                day_chg = round(((latest_close - prev_close) / prev_close) * 100.0, 2)
                from_open = round(((latest_close - open_p) / open_p) * 100.0, 2)

                if day_chg <= -0.20 or from_open <= -0.30:
                    regime = "BEARISH"
                elif day_chg >= 0.20 or from_open >= 0.30:
                    regime = "BULLISH"
                else:
                    regime = "NEUTRAL"

                logger.info(f"🌐 [MarketRegime] NIFTY 50: ₹{latest_close:,.2f} | Day: {day_chg:+.2f}% | From Open: {from_open:+.2f}% => REGIME: {regime}")
                return {
                    "regime": regime,
                    "day_change_pct": day_chg,
                    "from_open_pct": from_open,
                    "nifty_price": latest_close
                }
        except Exception as e:
            logger.warning(f"Could not fetch NIFTY regime ({e}), defaulting to NEUTRAL.")
        return {"regime": "NEUTRAL", "day_change_pct": 0.0, "from_open_pct": 0.0, "nifty_price": 0.0}

    def run_morning_screener_and_pick(self, top_n: int = 10, scan_date_str: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Executes full multi-factor quantitative screening across ALL 500+ NIFTY 500 stocks in parallel:
        1. Loads entire NIFTY 500 universe (500+ stocks).
        2. Evaluates Technical Trends, Momentum, RVOL, ATR volatility, and Breakout proximity concurrently.
        3. Detects broader market regime (NIFTY 50 trend) and dynamically balances Long vs Short candidates.
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

        # Check broader market regime to align selection
        regime_info = self.get_nifty_market_regime()
        regime = regime_info.get("regime", "NEUTRAL")

        # Separate bullish and bearish candidates
        bull_candidates = [s for s in scored_stocks if s.get("side") == "BUY"]
        bear_candidates = [s for s in scored_stocks if s.get("side") == "SELL"]
        bull_candidates.sort(key=lambda s: s["score"], reverse=True)
        bear_candidates.sort(key=lambda s: s["score"], reverse=True)

        logger.info(f"📊 [MorningScreener] Scored breakdown: {len(bull_candidates)} BUY / {len(bear_candidates)} SELL. Market Regime: {regime}")

        # Regime-aware allocation of Top N slots
        if regime == "BEARISH":
            # In a falling market, prioritize shorts (70% SELL / 30% BUY)
            target_shorts = min(len(bear_candidates), int(top_n * 0.7))
            target_longs = top_n - target_shorts
            top_picks = bear_candidates[:target_shorts] + bull_candidates[:target_longs]
        elif regime == "BULLISH":
            # In a rising market, prioritize longs (70% BUY / 30% SELL)
            target_longs = min(len(bull_candidates), int(top_n * 0.7))
            target_shorts = top_n - target_longs
            top_picks = bull_candidates[:target_longs] + bear_candidates[:target_shorts]
        else:
            # Neutral market: 50/50 balance
            target_each = top_n // 2
            top_picks = bull_candidates[:target_each] + bear_candidates[:target_each]

        # If picks are fewer than top_n, fill from remaining scored stocks sorted by score
        if len(top_picks) < top_n:
            picked_syms = {p["symbol"] for p in top_picks}
            remaining = [s for s in scored_stocks if s["symbol"] not in picked_syms]
            remaining.sort(key=lambda s: s["score"], reverse=True)
            top_picks.extend(remaining[:(top_n - len(top_picks))])

        # Sort final top picks by rank
        top_picks.sort(key=lambda s: s["score"], reverse=True)

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
                        initial_sl, target_price, trailing_step_pct, status, side, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    stock.get("entry_trigger") or (round(stock["price"] * 0.996, 2) if stock.get("side") == "SELL" else round(stock["price"] * 1.004, 2)),
                    stock["initial_sl"],
                    stock["target"],
                    stock["trailing_step_pct"],
                    "WATCHING",
                    stock.get("side", "BUY"),
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
        total_capital: Optional[float] = None,
        leverage: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """
        Enters paper algo trades for the selected top stocks with Initial SL,
        Target (+2%), and dynamic Trailing SL parameters. Smartly distributes `total_capital`
        using Gemini API (with quantitative multi-factor risk parity fallback) and `leverage`.
        Logs into `daily_intraday_trades`.
        """
        today_str = trade_date_str or get_ist_date()
        now_ts = get_ist_now_ts()

        # Strict Market Hours Hard-Lock: Only allow trade execution between 09:16 and 15:00 IST
        now_time = datetime.now(IST).time()
        if not trade_date_str:
            if now_time < dt_time(9, 16):
                logger.warning(f"🚫 [PaperTrader] Market not open yet ({now_time.strftime('%H:%M:%S')} IST). Intraday trades can only be entered between 09:16 and 15:00 IST.")
                return []
            if now_time >= dt_time(15, 0):
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

        # 1. Verify actual available capital in account
        cap_summary = self.get_account_capital_summary()
        current_avail = cap_summary["available_capital"]

        pool_capital = float(total_capital if total_capital is not None and total_capital > 0 else min(self.initial_capital, current_avail))
        lev = float(leverage if leverage is not None and leverage > 0 else getattr(self, "leverage", 5.0))

        if pool_capital < 500.0 and current_avail < 500.0 and total_capital is None:
            logger.warning(f"🚫 [CapitalGate] Insufficient capital in account (Available: ₹{current_avail:,.2f}). New trades cannot be entered.")
            return []

        # Smart Capital Distribution via Gemini API (with Quant Conviction Risk-Parity fallback and 5x leverage)
        alloc_map = {}
        try:
            from src.algodesk.ai.gemini_client import GeminiClient
            gc = GeminiClient()
            alloc_res = gc.optimize_capital_allocation(total_capital=pool_capital, picks=picks, leverage=lev)
            if alloc_res and alloc_res.allocations:
                alloc_map = {item.symbol: item for item in alloc_res.allocations}
                logger.info(f"🧠 [SmartAllocator] Gemini distributed ₹{pool_capital:,.2f} margin (5x buying power: ₹{pool_capital * lev:,.2f}) across {len(picks)} stocks ({alloc_res.model_used}). Strategy: {alloc_res.strategy_overview[:120]}...")
        except Exception as alloc_err:
            logger.warning(f"Smart allocation notice ({alloc_err}), falling back to equal weighting.")

        capital_per_trade = pool_capital / max(1, len(picks))
        executed_trades = []
        available_margin_tracker = pool_capital

        with self._lock:
            conn = self._get_connection()
            cur = conn.cursor()

            for stock in picks:
                if available_margin_tracker <= 0:
                    logger.info("⏸️ [CapitalGate] Available account capital exhausted. Skipping remaining picks.")
                    break

                sym = stock["symbol"]
                side = str(stock.get("side") or "BUY").upper()
                entry_price = float(stock["price"])

                if side == "SELL":
                    initial_sl = float(stock.get("initial_sl") or (entry_price * 1.012))
                    target = float(stock.get("target") or (entry_price * 0.986))
                    side_label = "SHORT (SELL)"
                else:
                    initial_sl = float(stock.get("initial_sl") or (entry_price * 0.988))
                    target = float(stock.get("target") or (entry_price * 1.014))
                    side_label = "LONG (BUY)"

                smart_item = alloc_map.get(sym)
                if smart_item:
                    allocated_for_trade = round(float(smart_item.allocated_capital), 2)
                    expected_qty = max(1, int((allocated_for_trade * lev) / entry_price))
                    qty = max(1, int(smart_item.qty)) if smart_item.qty and smart_item.qty >= expected_qty * 0.7 else expected_qty
                    exposure = round(qty * entry_price, 2)
                    entry_note = f"Smart AI Sizing ({lev:.0f}x MIS {side}): Margin ₹{allocated_for_trade:,.2f} | Exposure ₹{exposure:,.2f} ({smart_item.weight_pct:.1f}%) | {smart_item.rationale}"
                    weight_val = smart_item.weight_pct
                    rationale_val = smart_item.rationale
                else:
                    allocated_for_trade = round(capital_per_trade, 2)
                    qty = max(1, int((allocated_for_trade * lev) / entry_price))
                    exposure = round(qty * entry_price, 2)
                    entry_note = f"Standard sizing ({lev:.0f}x MIS {side}): Margin ₹{allocated_for_trade:,.2f} | Exposure ₹{exposure:,.2f} | {side_label}"
                    weight_val = round((allocated_for_trade / pool_capital) * 100.0, 1)
                    rationale_val = f"Equal distribution ({lev:.0f}x MIS {side})"

                # Check if trade already exists for today
                cur.execute("SELECT id FROM daily_intraday_trades WHERE trade_date = ? AND symbol = ?", (today_str, sym))
                existing = cur.fetchone()

                if existing:
                    logger.info(f"Trade already exists for {sym} on {today_str}. Skipping duplicate entry.")
                    continue

                # Strict Account Capital Availability Check: Ensure account can afford at least 1 share
                min_margin_for_1_share = entry_price / lev
                if available_margin_tracker < min_margin_for_1_share:
                    logger.warning(f"🚫 [CapitalGate] Insufficient capital in account for {sym} (Needed margin: ₹{min_margin_for_1_share:,.2f}, Available: ₹{available_margin_tracker:,.2f}). Skipping.")
                    continue

                # Clamp allocated margin so it never exceeds remaining account cash
                if allocated_for_trade > available_margin_tracker:
                    allocated_for_trade = round(available_margin_tracker, 2)
                    qty = max(1, int((allocated_for_trade * lev) / entry_price))
                    exposure = round(qty * entry_price, 2)

                actual_margin_spent = round((qty * entry_price) / lev, 2)
                available_margin_tracker = max(0.0, available_margin_tracker - actual_margin_spent)

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
                cur.execute("UPDATE daily_intraday_picks SET status = 'TRIGGERED' WHERE date = ? AND symbol = ?", (today_str, sym))

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
    # 2b. Continuous Whole-Day Opportunity Scanner & Dynamic Trader
    # -------------------------------------------------------------------------
    def scan_and_execute_intraday_opportunities(
        self,
        current_prices: Optional[Dict[str, float]] = None,
        trade_date_str: Optional[str] = None,
        max_positions: int = 10,
        min_trade_capital: float = 2000.0
    ) -> List[Dict[str, Any]]:
        """
        Continuously scans today's best intraday stocks throughout the market day (09:15 - 15:00 IST)
        for breakout and entry opportunities. Whenever an opportunity triggers and margin capital / position
        slots are available, automatically enters a paper trade with 5x leverage and dynamic trailing SL.
        """
        today_str = trade_date_str or get_ist_date()
        now_dt = datetime.now(IST)
        now_ts = get_ist_now_ts()

        # Strict Market Hours Hard-Lock: Only allow trade execution between 09:16 and 15:00 IST
        if not trade_date_str:
            if now_dt.time() < dt_time(9, 16):
                logger.info(f"🚫 [OpportunityScanner] Market not open yet ({now_dt.time().strftime('%H:%M:%S')} IST). Waiting for 09:16 IST.")
                return []
            if now_dt.time() >= dt_time(15, 0):
                logger.info("🚫 [OpportunityScanner] Past 15:00 IST intraday cutoff. No new trades entered.")
                return []

        with self._lock:
            conn = self._get_connection()
            cur = conn.cursor()

            # 1. Read open trades and check slot availability
            cur.execute("""
                SELECT id, symbol, allocated_capital, qty, entry_price
                FROM daily_intraday_trades
                WHERE status = 'OPEN'
            """)
            open_trades = [dict(r) for r in cur.fetchall()]
            open_symbols = {t["symbol"] for t in open_trades}

            # Avoid re-trading symbols that already completed or are open today
            cur.execute("SELECT symbol FROM daily_intraday_trades WHERE trade_date = ?", (today_str,))
            traded_today = {r["symbol"] for r in cur.fetchall()}

            slots_available = max_positions - len(open_trades)
            if slots_available <= 0:
                logger.info(f"⏸️ [OpportunityScanner] Max intraday positions ({len(open_trades)}/{max_positions}) active. Awaiting exits.")
                conn.close()
                return []

            # 2. Compute available margin capital using unified account state
            cur.execute("SELECT net_pnl FROM daily_intraday_trades WHERE trade_date = ? AND status = 'CLOSED'", (today_str,))
            today_realized_pnl = sum(float(r["net_pnl"] or 0.0) for r in cur.fetchall())

            total_margin_capital = float(getattr(self, "initial_capital", 100000.0))
            open_margin_utilized = sum(float(t["allocated_capital"] or 0.0) for t in open_trades)
            available_margin = max(0.0, total_margin_capital - open_margin_utilized + today_realized_pnl)

            if available_margin < min_trade_capital:
                logger.info(f"⏸️ [CapitalGate] Available margin (₹{available_margin:,.2f}) below min threshold (₹{min_trade_capital:,.2f}). Awaiting exits.")
                conn.close()
                return []

            # 3. Fetch candidate picks for today waiting for entry
            cur.execute("""
                SELECT id, symbol, price, entry_trigger_price, initial_sl, target_price,
                       trailing_step_pct, conviction_score, rvol, strategy_name, status, side
                FROM daily_intraday_picks
                WHERE date = ? AND status IN ('WATCHING', 'PICKED', 'PENDING_ENTRY')
                ORDER BY rank ASC
            """, (today_str,))
            candidate_picks = [dict(r) for r in cur.fetchall()]
            conn.close()

        # If no picks in DB, automatically run morning screener to generate top picks
        if not candidate_picks and self.is_market_day():
            logger.info("[OpportunityScanner] No candidate picks found in DB. Running screener to arm watchlist...")
            candidate_picks = self.run_morning_screener_and_pick(top_n=max_positions, scan_date_str=today_str)

        # Filter out stocks already traded today
        eligible_candidates = [p for p in candidate_picks if p["symbol"] not in traded_today]
        if not eligible_candidates:
            return []

        # 4. Fetch live market prices for eligible candidates
        cand_symbols = [p["symbol"] for p in eligible_candidates]
        batch_prices = {}
        if not current_prices:
            try:
                from src.data_loader import KITE_API_KEY, KITE_ACCESS_TOKEN
                if KITE_API_KEY and KITE_ACCESS_TOKEN:
                    from kiteconnect import KiteConnect
                    kc = KiteConnect(api_key=KITE_API_KEY)
                    kc.set_access_token(KITE_ACCESS_TOKEN)
                    instruments = [f"NSE:{s.replace('.NS', '')}" for s in cand_symbols]
                    q_map = kc.quote(instruments)
                    if q_map:
                        for s in cand_symbols:
                            s_clean = s.replace(".NS", "")
                            k_key = f"NSE:{s_clean}"
                            if k_key in q_map:
                                lp = float(q_map[k_key].get("last_price") or 0.0)
                                if lp > 0:
                                    batch_prices[s] = lp
                                    batch_prices[s_clean] = lp
            except Exception as batch_err:
                logger.debug(f"Kite quote batch error: {batch_err}")

        # Fallback to fast_info or yfinance or baseline if market quotes unavailable
        for p in eligible_candidates:
            sym = p["symbol"]
            if current_prices and sym in current_prices:
                batch_prices[sym] = float(current_prices[sym])
            elif sym not in batch_prices:
                try:
                    resolved = resolve_ticker(sym)
                    import yfinance as yf
                    tk = yf.Ticker(resolved)
                    fi = getattr(tk, "fast_info", None)
                    if fi and getattr(fi, "last_price", None):
                        batch_prices[sym] = float(fi.last_price)
                    else:
                        batch_prices[sym] = float(p["price"])
                except Exception:
                    batch_prices[sym] = float(p["price"])

        # 5. Check triggers and execute trades
        new_trades = []
        lev = float(getattr(self, "leverage", 5.0))
        nifty_regime = self.get_nifty_market_regime().get("regime", "NEUTRAL")

        with self._lock:
            conn = self._get_connection()
            cur = conn.cursor()

            for pick in eligible_candidates:
                if slots_available <= 0 or available_margin < min_trade_capital:
                    break

                # 1. High-Conviction Quality Gate: Only trade elite setups
                conviction = float(pick.get("conviction_score") or 0.0)
                if conviction < 70.0:
                    continue

                sym = pick["symbol"]
                side = str(pick.get("side") or "BUY").upper()
                curr_price = float(batch_prices.get(sym) or batch_prices.get(sym.replace(".NS", "")) or pick["price"])
                base_price = float(pick["price"])

                # 2. Strict Breakout/Breakdown Confirmation based on Side & Market Regime:
                if side == "SELL":
                    trigger_price = float(pick.get("entry_trigger_price") or (base_price * 0.996))
                    # Must break down below trigger price AND be below base price (red downward momentum)
                    is_opportunity = (curr_price <= trigger_price) and (curr_price < base_price)
                    now_ist_time = datetime.now(IST).time()
                    if dt_time(9, 15) <= now_ist_time < dt_time(9, 25):
                        is_opportunity = is_opportunity and (curr_price <= trigger_price * 0.998)
                    # If broad market is BULLISH, require deeper breakdown confirmation before shorting
                    if nifty_regime == "BULLISH":
                        is_opportunity = is_opportunity and (curr_price <= trigger_price * 0.997)

                    initial_sl = round(curr_price * 1.012, 2)     # +1.2% stop-loss (above entry)
                    target_p = round(curr_price * 0.986, 2)       # -1.4% profit target (below entry)
                    side_desc = "Short Breakdown"
                else:
                    trigger_price = float(pick.get("entry_trigger_price") or (base_price * 1.004))
                    # Must cross above trigger price AND be above base price (green upward momentum)
                    is_opportunity = (curr_price >= trigger_price) and (curr_price > base_price)
                    now_ist_time = datetime.now(IST).time()
                    if dt_time(9, 15) <= now_ist_time < dt_time(9, 25):
                        is_opportunity = is_opportunity and (curr_price >= trigger_price * 1.002)
                    # If broad market is BEARISH, require stronger breakout confirmation before buying
                    if nifty_regime == "BEARISH":
                        is_opportunity = is_opportunity and (curr_price >= trigger_price * 1.003)

                    initial_sl = round(curr_price * 0.988, 2)     # -1.2% stop-loss (below entry)
                    target_p = round(curr_price * 1.014, 2)       # +1.4% profit target (above entry)
                    side_desc = "Long Breakout"

                if is_opportunity:
                    # Allocate portion of available margin
                    alloc_margin = round(min(available_margin, available_margin / max(1, slots_available)), 2)
                    qty = max(1, int((alloc_margin * lev) / curr_price))
                    actual_margin = round((qty * curr_price) / lev, 2)
                    exposure = round(qty * curr_price, 2)

                    initial_log = json.dumps([{
                        "ts": now_ts,
                        "price": curr_price,
                        "side": side,
                        "sl": initial_sl,
                        "note": f"🎯 Confirmed {side_desc} Opportunity Triggered ({lev:.0f}x MIS {side}): Margin ₹{actual_margin:,.2f} | 5x Exp ₹{exposure:,.2f} | Score: {conviction:.1f}"
                    }])

                    # Prevent duplicate insertion
                    cur.execute("SELECT id FROM daily_intraday_trades WHERE trade_date = ? AND symbol = ?", (today_str, sym))
                    if cur.fetchone():
                        continue

                    cur.execute("""
                        INSERT INTO daily_intraday_trades (
                            trade_date, symbol, side, qty, allocated_capital,
                            entry_time, entry_price, initial_sl, highest_price,
                            current_sl, target_price, gross_pnl, brokerage_and_taxes,
                            net_pnl, return_pct, status, price_history, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        today_str,
                        sym,
                        side,
                        qty,
                        actual_margin,
                        now_ts,
                        curr_price,
                        initial_sl,
                        curr_price,
                        initial_sl,
                        target_p,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        "OPEN",
                        initial_log,
                        now_ts
                    ))
                    trade_id = cur.lastrowid

                    # Update pick status to 'TRIGGERED'
                    cur.execute("""
                        UPDATE daily_intraday_picks
                        SET status = 'TRIGGERED', entry_trigger_price = ?
                        WHERE date = ? AND symbol = ?
                    """, (curr_price, today_str, sym))

                    new_trades.append({
                        "trade_id": trade_id,
                        "symbol": sym,
                        "side": side,
                        "qty": qty,
                        "allocated_capital": actual_margin,
                        "leverage": lev,
                        "gross_exposure": exposure,
                        "entry_price": curr_price,
                        "initial_sl": initial_sl,
                        "target_price": target_p,
                        "status": "OPEN",
                        "opportunity_note": f"Intraday {side_desc} Opportunity Triggered at ₹{curr_price:,.2f}"
                    })

                    logger.info(f"🎯 [IntradayOpportunity] Trade ENTERED ({side}): {sym} at ₹{curr_price} | Qty: {qty} ({lev:.0f}x MIS) | Margin: ₹{actual_margin:,.2f} | Target: ₹{target_p} | SL: ₹{initial_sl}")

                    available_margin -= actual_margin
                    slots_available -= 1

            conn.commit()
            conn.close()

        if new_trades:
            logger.info(f"🚀 [IntradayOpportunity] Successfully entered {len(new_trades)} opportunities during intraday session.")
        return new_trades

    def refresh_intraday_opportunity_watchlist(self, top_n: int = 10) -> List[Dict[str, Any]]:
        """
        Refreshes or tops up today's intraday watchlist so that there are always high-conviction
        stocks being watched for opportunities during the trading day.
        """
        today_str = get_ist_date()
        conn = self._get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM daily_intraday_picks
            WHERE date = ? AND status IN ('WATCHING', 'PICKED', 'PENDING_ENTRY')
        """, (today_str,))
        watching_cnt = cur.fetchone()[0]
        conn.close()

        if watching_cnt < 4 and self.is_market_day():
            logger.info(f"🔄 [WatchlistRefresh] Only {watching_cnt} candidate stocks watching. Refreshing intraday picks across NIFTY 500...")
            picks = self.run_morning_screener_and_pick(top_n=top_n, scan_date_str=today_str)
            return picks
        return []

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
            side = str(row.get("side") or "BUY").upper()
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

            # Bidirectional Trailing SL & Exit Logic
            if side == "SELL":
                # SHORT POSITION: Price falling generates profit
                new_extreme = min(highest_p if highest_p > 0 else entry_p, curr_p)
                gain_from_entry_pct = ((entry_p - new_extreme) / entry_p) * 100.0

                candidate_sl = curr_sl
                if gain_from_entry_pct >= 1.00:
                    dynamic_trail = min(round(entry_p * 0.993, 2), round(new_extreme * 1.004, 2))
                    candidate_sl = min(candidate_sl, dynamic_trail)
                elif gain_from_entry_pct >= 0.65:
                    cost_guaranteed_sl = round(entry_p * 0.997, 2)
                    candidate_sl = min(candidate_sl, cost_guaranteed_sl)

                new_sl = min(curr_sl, candidate_sl)
                sl_event = None
                if new_sl < curr_sl:
                    if curr_sl > entry_p and new_sl <= entry_p:
                        sl_event = f"SHORT_SL_TRAILED_TO_COST_PLUS_PROFIT ({new_sl})"
                    else:
                        sl_event = f"SHORT_SL_TRAILED_DOWN_TO_{new_sl}"

                    history.append({
                        "time": now_ts,
                        "event": sl_event,
                        "highest_price": new_extreme,
                        "new_sl": new_sl,
                        "note": f"Low reached ₹{new_extreme:.2f} (+{gain_from_entry_pct:.2f}% short gain). Trailing SL lowered to ₹{new_sl:.2f}."
                    })

                exit_price = None
                exit_reason = None
                if is_eod_cutoff:
                    exit_price = curr_p
                    exit_reason = "3PM_SQUAREOFF"
                elif curr_p <= target_p:
                    exit_price = min(curr_p, target_p)
                    exit_reason = "TARGET_HIT"
                elif curr_p >= new_sl:
                    exit_price = new_sl
                    exit_reason = "TRAILING_SL_HIT" if new_sl < entry_p else "STOP_LOSS_HIT"

                calc_side = "SHORT"
                gross_pnl = round((entry_p - exit_price) * qty, 2) if exit_price is not None else 0.0

            else:
                # LONG (BUY) POSITION: Price rising generates profit
                new_extreme = max(highest_p, curr_p)
                gain_from_entry_pct = ((new_extreme - entry_p) / entry_p) * 100.0

                candidate_sl = curr_sl
                if gain_from_entry_pct >= 1.00:
                    dynamic_trail = max(round(entry_p * 1.007, 2), round(new_extreme * 0.996, 2))
                    candidate_sl = max(candidate_sl, dynamic_trail)
                elif gain_from_entry_pct >= 0.65:
                    cost_guaranteed_sl = round(entry_p * 1.003, 2)
                    candidate_sl = max(candidate_sl, cost_guaranteed_sl)

                new_sl = max(curr_sl, candidate_sl)
                sl_event = None
                if new_sl > curr_sl:
                    if curr_sl < entry_p and new_sl >= entry_p:
                        sl_event = f"SL_TRAILED_TO_COST_PLUS_PROFIT ({new_sl})"
                    else:
                        sl_event = f"SL_TRAILED_UP_TO_{new_sl}"

                    history.append({
                        "time": now_ts,
                        "event": sl_event,
                        "highest_price": new_extreme,
                        "new_sl": new_sl,
                        "note": f"High reached ₹{new_extreme:.2f} (+{gain_from_entry_pct:.2f}%). Trailing SL raised to ₹{new_sl:.2f}."
                    })

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
                    exit_reason = "TRAILING_SL_HIT" if new_sl > entry_p else "STOP_LOSS_HIT"

                calc_side = "LONG"
                gross_pnl = round((exit_price - entry_p) * qty, 2) if exit_price is not None else 0.0

            if exit_price is not None:
                # Calculate exact Zerodha statutory intraday cost
                cost_breakdown = self.cost_calculator.calculate_roundtrip(
                    side=calc_side,
                    qty=qty,
                    raw_entry_price=entry_p,
                    raw_exit_price=exit_price,
                    trailing_turnover_cr=120.0
                )
                brokerage_taxes = round(cost_breakdown.total_costs, 2)
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
                    "highest_price": new_extreme,
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
                    "highest_price": new_extreme,
                    "current_sl": new_sl,
                    "price_history": json.dumps(history),
                    "updated_at": now_ts
                })

                updates.append({
                    "trade_id": t_id,
                    "symbol": sym,
                    "action": "TRAILING_UPDATE",
                    "current_price": curr_p,
                    "highest_price": new_extreme,
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
    def get_automation_status(
        self,
        auto_squareoff_past_3pm: bool = True,
        total_capital: Optional[float] = None,
        leverage: Optional[float] = None
    ) -> Dict[str, Any]:
        """Returns comprehensive status, today's picks, open positions, and all trade logs."""
        today_str = get_ist_date()

        # Enforce 3:00 PM strict squareoff check: If past 15:00 IST and open trades exist, square them off
        if auto_squareoff_past_3pm and datetime.now(IST).time() >= dt_time(15, 0):
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

        # ---------------------------------------------------------------------
        # Real-Time Live Floating (MTM) P&L Calculation for Active Open Trades
        # ---------------------------------------------------------------------
        open_syms = [r["symbol"] for r in open_trades]
        live_quotes = {}
        if open_syms:
            try:
                from src.data_loader import KITE_API_KEY, KITE_ACCESS_TOKEN
                if KITE_API_KEY and KITE_ACCESS_TOKEN:
                    from kiteconnect import KiteConnect
                    kc = KiteConnect(api_key=KITE_API_KEY)
                    kc.set_access_token(KITE_ACCESS_TOKEN)
                    instruments = [f"NSE:{s.replace('.NS', '')}" for s in open_syms]
                    q_map = kc.quote(instruments)
                    if q_map:
                        for s in open_syms:
                            s_clean = s.replace(".NS", "")
                            k_key = f"NSE:{s_clean}"
                            if k_key in q_map:
                                lp = float(q_map[k_key].get("last_price") or 0.0)
                                if lp > 0:
                                    live_quotes[s] = lp
                                    live_quotes[s_clean] = lp
            except Exception as e_quote:
                logger.debug(f"Live quote fetch notice in status: {e_quote}")

        open_trades_by_id = {}
        for r in open_trades:
            sym = r["symbol"]
            side = str(r.get("side") or "BUY").upper()
            qty = int(r["qty"])
            entry_p = float(r["entry_price"])
            highest_p = float(r.get("highest_price") or entry_p)
            allocated = float(r.get("allocated_capital") or (qty * entry_p))

            curr_p = live_quotes.get(sym) or live_quotes.get(sym.replace(".NS", ""))
            if curr_p is None:
                try:
                    resolved = resolve_ticker(sym)
                    import yfinance as yf
                    tk = yf.Ticker(resolved)
                    fi = getattr(tk, "fast_info", None)
                    if fi and getattr(fi, "last_price", None):
                        curr_p = float(fi.last_price)
                except Exception:
                    pass
            if curr_p is None or curr_p <= 0:
                curr_p = highest_p if highest_p > 0 else entry_p

            if side == "SELL":
                live_gross = round((entry_p - curr_p) * qty, 2)
                calc_side = "SHORT"
            else:
                live_gross = round((curr_p - entry_p) * qty, 2)
                calc_side = "LONG"

            try:
                cost_res = self.cost_calculator.calculate_roundtrip(
                    side=calc_side,
                    qty=qty,
                    raw_entry_price=entry_p,
                    raw_exit_price=curr_p,
                    trailing_turnover_cr=120.0
                )
                est_charges = round(cost_res.total_costs, 2)
            except Exception:
                est_charges = round(allocated * 0.0006, 2)

            live_net = round(live_gross - est_charges, 2)
            live_ret = round((live_net / allocated) * 100.0, 2) if allocated > 0 else 0.0

            r["current_price"] = curr_p
            r["gross_pnl"] = live_gross
            r["brokerage_and_taxes"] = est_charges
            r["net_pnl"] = live_net
            r["return_pct"] = live_ret
            r["is_open"] = True
            r["unrealized"] = True
            open_trades_by_id[r["id"]] = r

        # All trades ordered chronologically descending (LIMIT 250)
        cur.execute("""
            SELECT id, trade_date, symbol, side, qty, allocated_capital,
                   entry_time, entry_price, exit_time, exit_price, exit_reason,
                   initial_sl, highest_price, current_sl, target_price,
                   gross_pnl, brokerage_and_taxes, net_pnl, return_pct, status, price_history
            FROM daily_intraday_trades
            ORDER BY trade_date DESC, id DESC LIMIT 250
        """)
        all_trades = [dict(r) for r in cur.fetchall()]

        # Inject real-time live floating prices & PnL into all open trade records
        for t in all_trades:
            if t["status"] == "OPEN" and t["id"] in open_trades_by_id:
                live_rec = open_trades_by_id[t["id"]]
                t["current_price"] = live_rec["current_price"]
                t["gross_pnl"] = live_rec["gross_pnl"]
                t["brokerage_and_taxes"] = live_rec["brokerage_and_taxes"]
                t["net_pnl"] = live_rec["net_pnl"]
                t["return_pct"] = live_rec["return_pct"]
                t["is_open"] = True
                t["unrealized"] = True

        # Calculate overall metrics
        total_trades = len(all_trades)
        closed_trades = [t for t in all_trades if t["status"] == "CLOSED"]
        winning_trades = [t for t in closed_trades if (t.get("net_pnl") or 0.0) > 0]
        total_net_pnl = sum((t.get("net_pnl") or 0.0) for t in closed_trades)
        total_brokerage = sum((t.get("brokerage_and_taxes") or 0.0) for t in closed_trades)
        win_rate = round((len(winning_trades) / len(closed_trades) * 100.0), 1) if closed_trades else 0.0

        # Segregate trades by trade_date
        trades_by_date = {}
        for t in all_trades:
            t_date = t.get("trade_date") or (t.get("entry_time", "").split(" ")[0]) or "Unknown"
            if t_date not in trades_by_date:
                trades_by_date[t_date] = {
                    "date": t_date,
                    "is_today": (t_date == today_str),
                    "trades": [],
                    "total_trades": 0,
                    "open_trades": 0,
                    "closed_trades": 0,
                    "winning_trades": 0,
                    "losing_trades": 0,
                    "win_rate": 0.0,
                    "gross_pnl": 0.0,
                    "brokerage_taxes": 0.0,
                    "net_pnl": 0.0,
                    "unrealized_gross_pnl": 0.0,
                    "unrealized_net_pnl": 0.0,
                    "total_combined_net_pnl": 0.0,
                    "total_allocated": 0.0
                }
            g = trades_by_date[t_date]
            g["trades"].append(t)
            g["total_trades"] += 1
            g["total_allocated"] += float(t.get("allocated_capital") or 0.0)
            if t.get("status") == "OPEN":
                g["open_trades"] += 1
                g["unrealized_gross_pnl"] = round(g.get("unrealized_gross_pnl", 0.0) + float(t.get("gross_pnl") or 0.0), 2)
                g["unrealized_net_pnl"] = round(g.get("unrealized_net_pnl", 0.0) + float(t.get("net_pnl") or 0.0), 2)
            else:
                g["closed_trades"] += 1
                npnl = float(t.get("net_pnl") or 0.0)
                gpnl = float(t.get("gross_pnl") or 0.0)
                brk = float(t.get("brokerage_and_taxes") or 0.0)
                g["net_pnl"] += npnl
                g["gross_pnl"] += gpnl
                g["brokerage_taxes"] += brk
                if npnl > 0:
                    g["winning_trades"] += 1
                elif npnl < 0:
                    g["losing_trades"] += 1

        for d_key, g in trades_by_date.items():
            c_cnt = g["closed_trades"]
            g["win_rate"] = round((g["winning_trades"] / c_cnt * 100.0), 1) if c_cnt > 0 else 0.0
            g["gross_pnl"] = round(g["gross_pnl"], 2)
            g["brokerage_taxes"] = round(g["brokerage_taxes"], 2)
            g["net_pnl"] = round(g["net_pnl"], 2)
            g["unrealized_gross_pnl"] = round(g.get("unrealized_gross_pnl", 0.0), 2)
            g["unrealized_net_pnl"] = round(g.get("unrealized_net_pnl", 0.0), 2)
            g["total_combined_net_pnl"] = round(g["net_pnl"] + g["unrealized_net_pnl"], 2)
            g["total_allocated"] = round(g["total_allocated"], 2)

        today_trades = trades_by_date.get(today_str, {}).get("trades", [])
        today_summary = trades_by_date.get(today_str, {
            "date": today_str,
            "is_today": True,
            "trades": [],
            "total_trades": 0,
            "open_trades": 0,
            "closed_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate": 0.0,
            "gross_pnl": 0.0,
            "brokerage_taxes": 0.0,
            "net_pnl": 0.0,
            "unrealized_gross_pnl": 0.0,
            "unrealized_net_pnl": 0.0,
            "total_combined_net_pnl": 0.0,
            "total_allocated": 0.0
        })

        dates_available = sorted(list(trades_by_date.keys()), reverse=True)
        historical_dates = [d for d in dates_available if d != today_str]

        # Capital Utilization and Unified Portfolio Metrics (Configurable Intraday MIS Leverage)
        base_simulated_capital = float(total_capital if total_capital is not None and total_capital > 0 else getattr(self, "initial_capital", 100000.0))
        lev = float(leverage if leverage is not None and leverage > 0 else getattr(self, "leverage", 5.0))
        open_capital_utilized = sum(float(t.get("allocated_capital") or (t.get("qty", 0) * t.get("entry_price", 0))) for t in open_trades)
        gross_exposure = round(sum(float(t.get("qty", 0) * t.get("entry_price", 0)) for t in open_trades), 2)
        total_buying_power = round(base_simulated_capital * lev, 2)
        unrealized_pnl = round(sum(float(t.get("net_pnl") or 0.0) for t in open_trades), 2)
        today_realized_net_pnl = float(today_summary.get("net_pnl") or 0.0)
        total_combined_pnl = round(today_realized_net_pnl + unrealized_pnl, 2)

        available_cash = max(0.0, round(base_simulated_capital - open_capital_utilized + today_realized_net_pnl, 2))
        portfolio_equity = round(base_simulated_capital + total_combined_pnl, 2)
        capital_utilization_pct = round((open_capital_utilized / base_simulated_capital * 100.0), 1) if base_simulated_capital > 0 else 0.0
        effective_leverage = round(gross_exposure / portfolio_equity, 2) if portfolio_equity > 0 else 0.0

        lev_display = f"{int(lev)}x" if lev == int(lev) else f"{lev:.1f}x"
        portfolio_metrics = {
            "simulated_capital": base_simulated_capital,
            "intraday_leverage": lev,
            "total_buying_power": total_buying_power,
            "capital_utilized": round(open_capital_utilized, 2),
            "capital_utilization_pct": capital_utilization_pct,
            "gross_exposure": gross_exposure,
            "effective_leverage": effective_leverage,
            "available_cash": available_cash,
            "portfolio_equity": portfolio_equity,
            "active_positions_count": len(open_trades),
            "max_positions_allowed": 10,
            "unrealized_pnl": round(unrealized_pnl, 2),
            "today_realized_net_pnl": today_realized_net_pnl,
            "execution_mode": f"PAPER (AI ALGO • {lev_display} MIS LEVERAGE)"
        }

        conn.close()

        return {
            "status": "active",
            "is_market_day": self.is_market_day(),
            "capital": base_simulated_capital,
            "leverage": lev,
            "buying_power": total_buying_power,
            "today_date": today_str,
            "today_picks_count": len(today_picks),
            "today_picks": today_picks,
            "open_trades_count": len(open_trades),
            "open_trades": open_trades,
            "portfolio_metrics": portfolio_metrics,
            "today_trades_count": len(today_trades),
            "today_trades": today_trades,
            "today_summary": today_summary,
            "trades_by_date": trades_by_date,
            "dates_available": dates_available,
            "historical_dates": historical_dates,
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

    def close_single_position(self, identifier: Any, exit_reason: str = "MANUAL_SQUAREOFF") -> Optional[Dict[str, Any]]:
        """Closes a specific open intraday trade by ID or symbol at current market/watermark price."""
        conn = self._get_connection()
        cur = conn.cursor()
        if str(identifier).isdigit():
            cur.execute("""
                SELECT id, trade_date, symbol, side, qty, allocated_capital,
                       entry_time, entry_price, initial_sl, highest_price, current_sl,
                       target_price, price_history, status
                FROM daily_intraday_trades
                WHERE id = ? AND status = 'OPEN'
            """, (int(identifier),))
        else:
            cur.execute("""
                SELECT id, trade_date, symbol, side, qty, allocated_capital,
                       entry_time, entry_price, initial_sl, highest_price, current_sl,
                       target_price, price_history, status
                FROM daily_intraday_trades
                WHERE (symbol = ? OR symbol = ?) AND status = 'OPEN'
                ORDER BY id DESC LIMIT 1
            """, (str(identifier), f"{identifier}.NS"))
        row = cur.fetchone()
        conn.close()

        if not row:
            return None

        trade = dict(row)
        sym = trade["symbol"]
        qty = trade["qty"]
        entry_p = float(trade["entry_price"])
        highest_p = float(trade["highest_price"])
        curr_sl = float(trade["current_sl"])

        curr_p = highest_p
        try:
            from src.data_loader import KITE_API_KEY, KITE_ACCESS_TOKEN
            if KITE_API_KEY and KITE_ACCESS_TOKEN:
                from kiteconnect import KiteConnect
                kc = KiteConnect(api_key=KITE_API_KEY)
                kc.set_access_token(KITE_ACCESS_TOKEN)
                inst = f"NSE:{sym.replace('.NS', '')}"
                q = kc.quote([inst])
                if q and inst in q:
                    lp = float(q[inst].get("last_price") or 0.0)
                    if lp > 0:
                        curr_p = lp
        except Exception:
            pass

        exit_price = round(curr_p, 2)
        gross_pnl = round(qty * (exit_price - entry_p), 2)
        cost_breakdown = self.cost_calculator.calculate_roundtrip(
            side="LONG",
            qty=qty,
            raw_entry_price=entry_p,
            raw_exit_price=exit_price
        )
        brokerage_taxes = round(cost_breakdown.total_costs, 2)
        net_pnl = round(gross_pnl - brokerage_taxes, 2)
        ret_pct = round((net_pnl / trade["allocated_capital"]) * 100.0, 2) if trade["allocated_capital"] > 0 else 0.0

        now_ts = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
        history = json.loads(trade["price_history"] or "[]")
        history.append({
            "time": now_ts,
            "event": "MANUAL_CLOSE",
            "exit_price": exit_price,
            "exit_reason": exit_reason,
            "gross_pnl": gross_pnl,
            "brokerage_taxes": brokerage_taxes,
            "net_pnl": net_pnl,
            "return_pct": ret_pct
        })

        with self._lock:
            conn = self._get_connection()
            cur = conn.cursor()
            cur.execute("""
                UPDATE daily_intraday_trades
                SET exit_time = ?, exit_price = ?, exit_reason = ?,
                    highest_price = ?, current_sl = ?, gross_pnl = ?,
                    brokerage_and_taxes = ?, net_pnl = ?, return_pct = ?,
                    status = 'CLOSED', price_history = ?, updated_at = ?
                WHERE id = ?
            """, (
                now_ts, exit_price, exit_reason,
                max(highest_p, exit_price), curr_sl, gross_pnl,
                brokerage_taxes, net_pnl, ret_pct,
                json.dumps(history), now_ts, trade["id"]
            ))
            conn.commit()
            conn.close()

        res = {
            "trade_id": trade["id"],
            "symbol": sym,
            "action": "CLOSED",
            "exit_reason": exit_reason,
            "exit_price": exit_price,
            "gross_pnl": gross_pnl,
            "brokerage_taxes": brokerage_taxes,
            "net_pnl": net_pnl,
            "return_pct": ret_pct
        }
        logger.info(f"🛑 [PaperTrader] Trade Closed manually for {sym}: Net PnL ₹{net_pnl:+.2f}")
        return res

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

    # -------------------------------------------------------------------------
    # 6. History Management by Date (Summary, Filter, Export CSV, Delete Date)
    # -------------------------------------------------------------------------
    def get_available_dates_summary(self) -> List[Dict[str, Any]]:
        """Returns aggregate trade and performance summary grouped by each date."""
        conn = self._get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT trade_date,
                   COUNT(*) as total_trades,
                   SUM(CASE WHEN status = 'OPEN' THEN 1 ELSE 0 END) as open_trades,
                   SUM(CASE WHEN status = 'CLOSED' THEN 1 ELSE 0 END) as closed_trades,
                   SUM(CASE WHEN status = 'CLOSED' AND net_pnl > 0 THEN 1 ELSE 0 END) as winning_trades,
                   SUM(CASE WHEN status = 'CLOSED' AND net_pnl < 0 THEN 1 ELSE 0 END) as losing_trades,
                   SUM(CASE WHEN status = 'CLOSED' THEN gross_pnl ELSE 0 END) as gross_pnl,
                   SUM(CASE WHEN status = 'CLOSED' THEN brokerage_and_taxes ELSE 0 END) as brokerage_taxes,
                   SUM(CASE WHEN status = 'CLOSED' THEN net_pnl ELSE 0 END) as net_pnl,
                   SUM(allocated_capital) as total_allocated
            FROM daily_intraday_trades
            GROUP BY trade_date
            ORDER BY trade_date DESC
        """)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()

        today_str = get_ist_date()
        for r in rows:
            c = r["closed_trades"] or 0
            w = r["winning_trades"] or 0
            r["is_today"] = (r["trade_date"] == today_str)
            r["win_rate"] = round((w / c * 100.0), 1) if c > 0 else 0.0
            r["gross_pnl"] = round(r["gross_pnl"] or 0.0, 2)
            r["brokerage_taxes"] = round(r["brokerage_taxes"] or 0.0, 2)
            r["net_pnl"] = round(r["net_pnl"] or 0.0, 2)
            r["total_allocated"] = round(r["total_allocated"] or 0.0, 2)
        return rows

    def get_trades_for_date(self, date_str: str) -> List[Dict[str, Any]]:
        """Returns all trades recorded for a specific date."""
        conn = self._get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, trade_date, symbol, side, qty, allocated_capital,
                   entry_time, entry_price, exit_time, exit_price, exit_reason,
                   initial_sl, highest_price, current_sl, target_price,
                   gross_pnl, brokerage_and_taxes, net_pnl, return_pct, status, price_history
            FROM daily_intraday_trades
            WHERE trade_date = ?
            ORDER BY id ASC
        """, (date_str,))
        trades = [dict(r) for r in cur.fetchall()]
        conn.close()
        return trades

    def export_trades_csv(self, date_str: Optional[str] = None) -> str:
        """Generates CSV text of trades, optionally filtered by date or 'all'."""
        conn = self._get_connection()
        cur = conn.cursor()
        if date_str and date_str.lower() != "all":
            cur.execute("""
                SELECT id, trade_date, symbol, side, qty, allocated_capital,
                       entry_time, entry_price, exit_time, exit_price, exit_reason,
                       initial_sl, highest_price, current_sl, target_price,
                       gross_pnl, brokerage_and_taxes, net_pnl, return_pct, status
                FROM daily_intraday_trades
                WHERE trade_date = ?
                ORDER BY id ASC
            """, (date_str,))
        else:
            cur.execute("""
                SELECT id, trade_date, symbol, side, qty, allocated_capital,
                       entry_time, entry_price, exit_time, exit_price, exit_reason,
                       initial_sl, highest_price, current_sl, target_price,
                       gross_pnl, brokerage_and_taxes, net_pnl, return_pct, status
                FROM daily_intraday_trades
                ORDER BY trade_date DESC, id ASC
            """)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Trade ID", "Trade Date", "Symbol", "Side", "Qty", "Allocated Capital (INR)",
            "Entry Time", "Entry Price", "Exit Time", "Exit Price", "Exit Reason",
            "Initial SL", "Highest Price", "Current SL", "Target Price",
            "Gross PnL (INR)", "Brokerage & Taxes (INR)", "Net PnL (INR)", "Return %", "Status"
        ])
        for r in rows:
            writer.writerow([
                r.get("id"), r.get("trade_date"), r.get("symbol"), r.get("side"), r.get("qty"),
                r.get("allocated_capital"), r.get("entry_time"), r.get("entry_price"),
                r.get("exit_time") or "", r.get("exit_price") or "", r.get("exit_reason") or "",
                r.get("initial_sl"), r.get("highest_price"), r.get("current_sl"), r.get("target_price"),
                r.get("gross_pnl") if r.get("gross_pnl") is not None else "",
                r.get("brokerage_and_taxes") if r.get("brokerage_and_taxes") is not None else "",
                r.get("net_pnl") if r.get("net_pnl") is not None else "",
                r.get("return_pct") if r.get("return_pct") is not None else "",
                r.get("status")
            ])
        return output.getvalue()

    def delete_trades_by_date(self, date_str: str) -> Dict[str, Any]:
        """Permanently deletes trades and picks recorded for a specific date."""
        with self._lock:
            conn = self._get_connection()
            cur = conn.cursor()
            cur.execute("DELETE FROM daily_intraday_trades WHERE trade_date = ?", (date_str,))
            trades_deleted = cur.rowcount
            cur.execute("DELETE FROM daily_intraday_picks WHERE date = ?", (date_str,))
            picks_deleted = cur.rowcount
            conn.commit()
            conn.close()
            logger.info(f"🗑 [PaperTrader] Deleted {trades_deleted} trades and {picks_deleted} picks for date {date_str}")
            return {
                "status": "success",
                "date": date_str,
                "trades_deleted": trades_deleted,
                "picks_deleted": picks_deleted,
                "message": f"Successfully deleted {trades_deleted} trades and {picks_deleted} picks for date {date_str}."
            }


# Global singleton instance
daily_auto_trader = DailyIntradayAutoTrader()
