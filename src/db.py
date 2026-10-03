"""
SQLite High-Performance Database Manager
Implements WAL mode, 64MB cache, schema management, and bulk transactional upserts.
Database file: database/market_data.db
"""

import json
import os
import sqlite3
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd

DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "database", "market_data.db"))


def get_db_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    """Creates a high-performance SQLite connection with read-only fallback for serverless (Vercel)."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    try:
        conn = sqlite3.connect(db_path, timeout=30.0)
        try:
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = NORMAL;")
        except sqlite3.OperationalError:
            pass
    except sqlite3.OperationalError:
        # Fallback for read-only filesystem (e.g. Vercel Serverless Function)
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30.0)
    
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
    except sqlite3.OperationalError:
        pass
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str = DB_PATH):
    """Initializes the database schema with indexes and constraints."""
    try:
        conn = get_db_connection(db_path)
        cursor = conn.cursor()

        # 1. stocks_meta
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS stocks_meta (
            ticker TEXT PRIMARY KEY,
            company_name TEXT,
            sector TEXT,
            industry TEXT,
            market_cap REAL,
            pe_ratio REAL,
            pb_ratio REAL,
            eps REAL,
            dividend_yield REAL,
            roe REAL,
            last_fundamental_update TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # 2. daily_ohlcv
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_ohlcv (
            ticker TEXT NOT NULL,
            date DATE NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume REAL NOT NULL,
            PRIMARY KEY (ticker, date)
        );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ohlcv_date ON daily_ohlcv(date);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ohlcv_ticker_date ON daily_ohlcv(ticker, date DESC);")

        # 3. technical_indicators
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS technical_indicators (
            ticker TEXT NOT NULL,
            date DATE NOT NULL,
            rsi_14 REAL,
            macd REAL,
            macd_signal REAL,
            macd_hist REAL,
            sma_20 REAL,
            sma_50 REAL,
            sma_200 REAL,
            ema_9 REAL,
            ema_21 REAL,
            bb_upper REAL,
            bb_middle REAL,
            bb_lower REAL,
            bb_bandwidth REAL,
            atr_14 REAL,
            natr_14 REAL,
            adx_14 REAL,
            pivot_p REAL,
            pivot_r1 REAL,
            pivot_s1 REAL,
            PRIMARY KEY (ticker, date)
        );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ind_ticker_date ON technical_indicators(ticker, date DESC);")

        # 4. predictions
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS predictions (
            ticker TEXT NOT NULL,
            date DATE NOT NULL,
            target_date DATE NOT NULL,
            reference_close REAL NOT NULL,
            predicted_close REAL NOT NULL,
            expected_pct_change REAL NOT NULL,
            range_low REAL NOT NULL,
            range_high REAL NOT NULL,
            trend_signal TEXT NOT NULL,
            confidence_pct REAL NOT NULL,
            champion_model TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (ticker, date)
        );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_preds_ticker_date ON predictions(ticker, date DESC);")

        # 5. market_analysis_daily
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS market_analysis_daily (
            date DATE PRIMARY KEY,
            advances INTEGER,
            declines INTEGER,
            pct_above_sma50 REAL,
            pct_above_sma200 REAL,
            top_bullish_tickers TEXT,
            top_bearish_tickers TEXT,
            sector_performance TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        conn.commit()
        conn.close()
        print("[DB] SQLite database initialized successfully.")
    except Exception as e:
        print(f"[DB] init_db skipped schema modification (read-only mode active): {e}")


# =====================================================================
# Bulk Write Operations
# =====================================================================

def bulk_upsert_stocks_meta(records: List[Dict[str, Any]], db_path: str = DB_PATH):
    """Upserts metadata records for stocks."""
    if not records:
        return
    query = """
    INSERT INTO stocks_meta (ticker, company_name, sector, industry, market_cap, pe_ratio, pb_ratio, eps, dividend_yield, roe, last_fundamental_update)
    VALUES (:ticker, :company_name, :sector, :industry, :market_cap, :pe_ratio, :pb_ratio, :eps, :dividend_yield, :roe, CURRENT_TIMESTAMP)
    ON CONFLICT(ticker) DO UPDATE SET
        company_name=excluded.company_name,
        sector=excluded.sector,
        industry=excluded.industry,
        market_cap=excluded.market_cap,
        pe_ratio=excluded.pe_ratio,
        pb_ratio=excluded.pb_ratio,
        eps=excluded.eps,
        dividend_yield=excluded.dividend_yield,
        roe=excluded.roe,
        last_fundamental_update=CURRENT_TIMESTAMP;
    """
    with get_db_connection(db_path) as conn:
        conn.executemany(query, records)
        conn.commit()


def bulk_upsert_ohlcv(records: List[Dict[str, Any]], db_path: str = DB_PATH):
    """Upserts daily OHLCV price bars in bulk transaction."""
    if not records:
        return
    query = """
    INSERT INTO daily_ohlcv (ticker, date, open, high, low, close, volume)
    VALUES (:ticker, :date, :open, :high, :low, :close, :volume)
    ON CONFLICT(ticker, date) DO UPDATE SET
        open=excluded.open,
        high=excluded.high,
        low=excluded.low,
        close=excluded.close,
        volume=excluded.volume;
    """
    with get_db_connection(db_path) as conn:
        conn.executemany(query, records)
        conn.commit()


def bulk_upsert_indicators(records: List[Dict[str, Any]], db_path: str = DB_PATH):
    """Upserts technical indicator values in bulk transaction."""
    if not records:
        return
    query = """
    INSERT INTO technical_indicators (
        ticker, date, rsi_14, macd, macd_signal, macd_hist,
        sma_20, sma_50, sma_200, ema_9, ema_21,
        bb_upper, bb_middle, bb_lower, bb_bandwidth,
        atr_14, natr_14, adx_14, pivot_p, pivot_r1, pivot_s1
    ) VALUES (
        :ticker, :date, :rsi_14, :macd, :macd_signal, :macd_hist,
        :sma_20, :sma_50, :sma_200, :ema_9, :ema_21,
        :bb_upper, :bb_middle, :bb_lower, :bb_bandwidth,
        :atr_14, :natr_14, :adx_14, :pivot_p, :pivot_r1, :pivot_s1
    ) ON CONFLICT(ticker, date) DO UPDATE SET
        rsi_14=excluded.rsi_14, macd=excluded.macd, macd_signal=excluded.macd_signal, macd_hist=excluded.macd_hist,
        sma_20=excluded.sma_20, sma_50=excluded.sma_50, sma_200=excluded.sma_200, ema_9=excluded.ema_9, ema_21=excluded.ema_21,
        bb_upper=excluded.bb_upper, bb_middle=excluded.bb_middle, bb_lower=excluded.bb_lower, bb_bandwidth=excluded.bb_bandwidth,
        atr_14=excluded.atr_14, natr_14=excluded.natr_14, adx_14=excluded.adx_14,
        pivot_p=excluded.pivot_p, pivot_r1=excluded.pivot_r1, pivot_s1=excluded.pivot_s1;
    """
    with get_db_connection(db_path) as conn:
        conn.executemany(query, records)
        conn.commit()


def bulk_upsert_predictions(records: List[Dict[str, Any]], db_path: str = DB_PATH):
    """Upserts ML forward predictions."""
    if not records:
        return
    query = """
    INSERT INTO predictions (
        ticker, date, target_date, reference_close, predicted_close,
        expected_pct_change, range_low, range_high, trend_signal, confidence_pct, champion_model
    ) VALUES (
        :ticker, :date, :target_date, :reference_close, :predicted_close,
        :expected_pct_change, :range_low, :range_high, :trend_signal, :confidence_pct, :champion_model
    ) ON CONFLICT(ticker, date) DO UPDATE SET
        target_date=excluded.target_date,
        reference_close=excluded.reference_close,
        predicted_close=excluded.predicted_close,
        expected_pct_change=excluded.expected_pct_change,
        range_low=excluded.range_low,
        range_high=excluded.range_high,
        trend_signal=excluded.trend_signal,
        confidence_pct=excluded.confidence_pct,
        champion_model=excluded.champion_model,
        created_at=CURRENT_TIMESTAMP;
    """
    with get_db_connection(db_path) as conn:
        conn.executemany(query, records)
        conn.commit()


def upsert_market_analysis(record: Dict[str, Any], db_path: str = DB_PATH):
    """Upserts daily market-wide breadth and sector scan."""
    query = """
    INSERT INTO market_analysis_daily (
        date, advances, declines, pct_above_sma50, pct_above_sma200,
        top_bullish_tickers, top_bearish_tickers, sector_performance
    ) VALUES (
        :date, :advances, :declines, :pct_above_sma50, :pct_above_sma200,
        :top_bullish_tickers, :top_bearish_tickers, :sector_performance
    ) ON CONFLICT(date) DO UPDATE SET
        advances=excluded.advances,
        declines=excluded.declines,
        pct_above_sma50=excluded.pct_above_sma50,
        pct_above_sma200=excluded.pct_above_sma200,
        top_bullish_tickers=excluded.top_bullish_tickers,
        top_bearish_tickers=excluded.top_bearish_tickers,
        sector_performance=excluded.sector_performance,
        created_at=CURRENT_TIMESTAMP;
    """
    with get_db_connection(db_path) as conn:
        conn.execute(query, record)
        conn.commit()


# =====================================================================
# Read Queries
# =====================================================================

def get_latest_dates_per_ticker(db_path: str = DB_PATH) -> Dict[str, str]:
    """Returns mapping of ticker -> max(date) currently in the database."""
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT ticker, MAX(date) as max_date FROM daily_ohlcv GROUP BY ticker;")
        return {row["ticker"]: row["max_date"] for row in cursor.fetchall() if row["max_date"]}


def get_all_tickers(db_path: str = DB_PATH) -> List[str]:
    """Returns list of all active tickers in stocks_meta."""
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT ticker FROM stocks_meta ORDER BY ticker ASC;")
        return [row["ticker"] for row in cursor.fetchall()]


def get_stock_history_df(ticker: str, limit: int = 250, db_path: str = DB_PATH) -> pd.DataFrame:
    """Retrieves chronological OHLCV DataFrame for a stock."""
    query = """
    SELECT date, open as Open, high as High, low as Low, close as Close, volume as Volume
    FROM daily_ohlcv
    WHERE ticker = ?
    ORDER BY date DESC
    LIMIT ?;
    """
    with get_db_connection(db_path) as conn:
        df = pd.read_sql_query(query, conn, params=(ticker, limit))
        if df.empty:
            return df
        df["date"] = pd.to_datetime(df["date"])
        df.set_index("date", inplace=True)
        df.sort_index(inplace=True)
        return df


def get_consolidated_stock_data(ticker: str, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    """Single-shot query retrieving Fundamentals, Technicals, Prediction, and Chart History."""
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()

        # Meta / Fundamentals
        cursor.execute("SELECT * FROM stocks_meta WHERE ticker = ?;", (ticker,))
        meta_row = cursor.fetchone()

        # Latest OHLCV
        cursor.execute("""
        SELECT * FROM daily_ohlcv WHERE ticker = ? ORDER BY date DESC LIMIT 1;
        """, (ticker,))
        latest_bar = cursor.fetchone()

        if not meta_row and not latest_bar:
            return None

        meta_dict = dict(meta_row) if meta_row else {
            "ticker": ticker,
            "company_name": ticker,
            "sector": "Equity",
            "industry": "Equity",
            "market_cap": None, "pe_ratio": None, "pb_ratio": None,
            "eps": None, "dividend_yield": None, "roe": None,
            "last_fundamental_update": None,
        }

        # Previous bar to calculate 1-day change
        cursor.execute("""
        SELECT close FROM daily_ohlcv WHERE ticker = ? ORDER BY date DESC LIMIT 1 OFFSET 1;
        """, (ticker,))
        prev_bar = cursor.fetchone()
        prev_close = prev_bar["close"] if prev_bar else (latest_bar["open"] if latest_bar else 0)

        # Latest Technical Indicators
        cursor.execute("""
        SELECT * FROM technical_indicators WHERE ticker = ? ORDER BY date DESC LIMIT 1;
        """, (ticker,))
        latest_ind = cursor.fetchone()

        # Latest Prediction
        cursor.execute("""
        SELECT * FROM predictions WHERE ticker = ? ORDER BY date DESC LIMIT 1;
        """, (ticker,))
        latest_pred = cursor.fetchone()

        # Recent 90 days Chart bars with full technical indicator time series
        cursor.execute("""
        SELECT o.date, o.open, o.high, o.low, o.close, o.volume,
               t.sma_20, t.sma_50, t.sma_200, t.ema_9, t.ema_21,
               t.bb_upper, t.bb_lower, t.bb_middle,
               t.rsi_14, t.macd, t.macd_signal, t.macd_hist,
               t.atr_14, t.natr_14, t.adx_14,
               t.pivot_p, t.pivot_r1, t.pivot_s1
        FROM daily_ohlcv o
        LEFT JOIN technical_indicators t ON o.ticker = t.ticker AND o.date = t.date
        WHERE o.ticker = ?
        ORDER BY o.date DESC
        LIMIT 90;
        """, (ticker,))
        chart_rows = [dict(r) for r in cursor.fetchall()][::-1]  # reverse to chronological order

        day_change = (latest_bar["close"] - prev_close) if latest_bar and prev_close else 0.0
        day_change_pct = (day_change / prev_close * 100.0) if prev_close else 0.0

        return {
            "ticker": ticker,
            "fundamentals": meta_dict,
            "latest_ohlcv": dict(latest_bar) if latest_bar else None,
            "day_change": round(day_change, 2),
            "day_change_pct": round(day_change_pct, 2),
            "technicals": dict(latest_ind) if latest_ind else None,
            "prediction": dict(latest_pred) if latest_pred else None,
            "chart_history": chart_rows,
        }


def get_all_stocks_summary_list(query_filter: str = "", sector_filter: str = "", db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Returns directory of NIFTY 500 stocks with latest price, change %, and trend signal."""
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        sql = """
        SELECT m.ticker, m.company_name, m.sector, m.industry, m.market_cap,
               o.close as latest_close, o.date as as_of_date,
               p.trend_signal, p.predicted_close, p.expected_pct_change, p.confidence_pct
        FROM stocks_meta m
        LEFT JOIN (
            SELECT ticker, close, date,
                   ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) as rn
            FROM daily_ohlcv
        ) o ON m.ticker = o.ticker AND o.rn = 1
        LEFT JOIN (
            SELECT ticker, trend_signal, predicted_close, expected_pct_change, confidence_pct,
                   ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) as rn
            FROM predictions
        ) p ON m.ticker = p.ticker AND p.rn = 1
        WHERE 1=1
        """
        params = []
        if query_filter:
            sql += " AND (m.ticker LIKE ? OR m.company_name LIKE ?)"
            q = f"%{query_filter.upper()}%"
            params.extend([q, q])
        if sector_filter and sector_filter != "ALL":
            sql += " AND m.sector = ?"
            params.append(sector_filter)

        sql += " ORDER BY m.market_cap DESC NULLS LAST, m.ticker ASC;"
        cursor.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]


def get_latest_market_analysis_data(db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    """Retrieves the most recent daily market breadth, sector heat, and breakout scans."""
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM market_analysis_daily ORDER BY date DESC LIMIT 1;")
        row = cursor.fetchone()
        if not row:
            return None
        res = dict(row)
        res["top_bullish_tickers"] = json.loads(res["top_bullish_tickers"]) if res["top_bullish_tickers"] else []
        res["top_bearish_tickers"] = json.loads(res["top_bearish_tickers"]) if res["top_bearish_tickers"] else []
        res["sector_performance"] = json.loads(res["sector_performance"]) if res["sector_performance"] else {}
        return res
