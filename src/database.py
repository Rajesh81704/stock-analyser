"""
SQLite Database Storage Module for Stock Analyser
Maintains persistent SQLite storage for:
1. Daily OHLCV stock price history per ticker.
2. Screener Node execution logs and individual stock filter results.
"""

from datetime import datetime, time, timedelta
import json
import os
import sqlite3
from typing import Any, Dict, List, Optional
import pandas as pd

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "stock_screener.db")


def get_db_connection() -> sqlite3.Connection:
    """Returns a SQLite database connection with row factory enabled."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Initializes SQLite tables for OHLCV data and Screener Node results if they do not exist."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # 1. Table for Daily OHLCV data
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ohlcv_data (
                ticker TEXT NOT NULL,
                date TEXT NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume INTEGER NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ticker, date)
            )
        """)

        # Index on ticker and date for fast range queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_ohlcv_ticker_date 
            ON ohlcv_data (ticker, date)
        """)

        # 2. Table for Screener Run metadata
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS screener_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                node_id TEXT NOT NULL,
                universe TEXT NOT NULL,
                scanned_count INTEGER NOT NULL,
                matched_count INTEGER NOT NULL
            )
        """)

        # 3. Table for Screener Run Results per stock
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS screener_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                ticker TEXT NOT NULL,
                passed_all INTEGER NOT NULL,
                passed_count INTEGER NOT NULL,
                total_rules INTEGER NOT NULL,
                pass_percentage REAL NOT NULL,
                latest_close REAL,
                latest_volume INTEGER,
                rsi_14 REAL,
                macd_hist REAL,
                change_pct REAL,
                filter_details_json TEXT,
                scanned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (run_id) REFERENCES screener_runs (id) ON DELETE CASCADE
            )
        """)

        # Migration: ensure change_pct column exists if DB was created previously
        cursor.execute("PRAGMA table_info(screener_results)")
        columns = [column[1] for column in cursor.fetchall()]
        if "change_pct" not in columns:
            cursor.execute("ALTER TABLE screener_results ADD COLUMN change_pct REAL")

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_screener_results_ticker 
            ON screener_results (ticker)
        """)

        # 4. Table for Screener Filter Nodes
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS screener_nodes (
                node_id TEXT PRIMARY KEY,
                node_name TEXT NOT NULL,
                category TEXT NOT NULL,
                description TEXT NOT NULL,
                rule_count INTEGER NOT NULL,
                rules_spec_json TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.commit()


# Initialize database schema on import
init_db()


def save_ohlcv_to_db(ticker: str, df: pd.DataFrame) -> int:
    """
    Saves or updates daily OHLCV bars for a stock in the SQLite database.
    Expects DataFrame indexed by Date with columns ['Open', 'High', 'Low', 'Close', 'Volume'].
    """
    if df is None or df.empty:
        return 0

    clean_ticker = ticker.strip().upper()
    rows_to_insert = []

    for idx, row in df.iterrows():
        # Format date as YYYY-MM-DD string
        if isinstance(idx, (pd.Timestamp, str)):
            date_str = str(idx).split(" ")[0]
        else:
            date_str = str(idx)

        rows_to_insert.append((
            clean_ticker,
            date_str,
            float(row.get("Open", 0.0)),
            float(row.get("High", 0.0)),
            float(row.get("Low", 0.0)),
            float(row.get("Close", 0.0)),
            int(row.get("Volume", 0)),
        ))

    if not rows_to_insert:
        return 0

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.executemany("""
            INSERT INTO ohlcv_data (ticker, date, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ticker, date) DO UPDATE SET
                open = excluded.open,
                high = excluded.high,
                low = excluded.low,
                close = excluded.close,
                volume = excluded.volume,
                updated_at = CURRENT_TIMESTAMP
        """, rows_to_insert)
        conn.commit()

    return len(rows_to_insert)


def load_ohlcv_from_db(ticker: str, min_bars: int = 5) -> Optional[pd.DataFrame]:
    """
    Loads OHLCV bars for a stock from SQLite database.
    Returns pd.DataFrame or None if insufficient cached data exists.
    """
    clean_ticker = ticker.strip().upper()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT date, open, high, low, close, volume 
            FROM ohlcv_data 
            WHERE ticker = ? 
            ORDER BY date ASC
        """, (clean_ticker,))
        rows = cursor.fetchall()

    if not rows or len(rows) < min_bars:
        return None

    data = [dict(row) for row in rows]
    df = pd.DataFrame(data)
    df["Date"] = pd.to_datetime(df["date"])
    df.set_index("Date", inplace=True)
    df.rename(columns={
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume"
    }, inplace=True)
    
    return df[["Open", "High", "Low", "Close", "Volume"]]


def get_latest_ohlcv_date_from_db(ticker: str) -> Optional[str]:
    """
    Returns the latest stored OHLCV date (YYYY-MM-DD) for a ticker in SQLite database.
    Returns None if no data is stored yet.
    """
    clean_ticker = ticker.strip().upper()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(date) FROM ohlcv_data WHERE ticker = ?", (clean_ticker,))
        res = cursor.fetchone()
        if res and res[0]:
            return str(res[0])
    return None


def save_screener_run_to_db(
    node_id: str,
    universe: str,
    scanned_count: int,
    matched_count: int,
    stock_results: List[Dict[str, Any]]
) -> int:
    """
    Saves a complete Screener Node run and its individual stock filtering results into SQLite.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # 1. Insert parent run
        cursor.execute("""
            INSERT INTO screener_runs (node_id, universe, scanned_count, matched_count)
            VALUES (?, ?, ?, ?)
        """, (node_id, universe, scanned_count, matched_count))
        
        run_id = cursor.lastrowid

        # 2. Insert individual stock results
        result_rows = []
        for item in stock_results:
            details = item.get("details", item)
            latest_bar = details.get("latest_bar", {})
            
            result_rows.append((
                run_id,
                item.get("ticker", details.get("ticker", "UNKNOWN")),
                1 if details.get("passed_all", False) else 0,
                int(details.get("passed_count", 0)),
                int(details.get("total_rules", 26)),
                float(details.get("pass_percentage", 0.0)),
                float(latest_bar.get("close", 0.0)) if latest_bar.get("close") is not None else None,
                int(latest_bar.get("volume", 0)) if latest_bar.get("volume") is not None else None,
                float(latest_bar.get("rsi_14")) if latest_bar.get("rsi_14") is not None else None,
                float(latest_bar.get("macd")) if latest_bar.get("macd") is not None else None,
                float(latest_bar.get("change_pct")) if latest_bar.get("change_pct") is not None else 0.0,
                json.dumps(details.get("filter_results", [])),
            ))

        if result_rows:
            cursor.executemany("""
                INSERT INTO screener_results (
                    run_id, ticker, passed_all, passed_count, total_rules, 
                    pass_percentage, latest_close, latest_volume, rsi_14, macd_hist, change_pct, filter_details_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, result_rows)

        conn.commit()
def get_latest_screener_results_from_db(node_id: str = "NODE_01_BULLISH_TRENDING", limit: int = 500) -> List[Dict[str, Any]]:
    """
    Retrieves the latest screened stock results for a given node from SQLite.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT r.*, sr.run_timestamp, sr.node_id, sr.universe
            FROM screener_results r
            JOIN screener_runs sr ON r.run_id = sr.id
            WHERE r.run_id = (
                SELECT id FROM screener_runs WHERE node_id = ? ORDER BY id DESC LIMIT 1
            )
            ORDER BY r.pass_percentage DESC, r.change_pct DESC
            LIMIT ?
        """, (node_id, limit))
        rows = cursor.fetchall()

    results = []
    for row in rows:
        d = dict(row)
        d["close"] = d.get("latest_close", 0.0)
        d["volume"] = d.get("latest_volume", 0)
        d["details"] = {
            "ticker": d.get("ticker"),
            "latest_close": d.get("latest_close"),
            "latest_volume": d.get("latest_volume"),
            "change_pct": d.get("change_pct"),
            "rsi_14": d.get("rsi_14"),
            "passed_count": d.get("passed_count"),
            "filter_details_json": d.get("filter_details_json")
        }
        results.append(d)

    return results


def get_expected_market_date() -> str:
    """
    Returns the target market date string (YYYY-MM-DD) for screening data:
    - If today is Saturday/Sunday, target is Friday.
    - If today is weekday & time is after 15:30 IST (3:30 PM), target is today.
    - If today is weekday & time is before 15:30 IST, target is previous trading day.
    """
    now = datetime.now()
    market_close = time(15, 30)

    if now.weekday() == 5:  # Saturday
        target = now - timedelta(days=1)
    elif now.weekday() == 6:  # Sunday
        target = now - timedelta(days=2)
    else:  # Monday - Friday
        if now.time() >= market_close:
            target = now
        else:
            if now.weekday() == 0:  # Monday morning -> Friday
                target = now - timedelta(days=3)
            else:
                target = now - timedelta(days=1)

    return target.strftime("%Y-%m-%d")


def get_latest_screener_run_timestamp(node_id: str = "NODE_01_BULLISH_TRENDING") -> Optional[str]:
    """Retrieves the timestamp of the latest screener run for a node from SQLite DB."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT run_timestamp FROM screener_runs WHERE node_id = ? ORDER BY id DESC LIMIT 1", (node_id,))
        res = cursor.fetchone()
        if res and res[0]:
            return str(res[0])
    return None


def is_db_screener_updated_for_date(node_id: str = "NODE_01_BULLISH_TRENDING", target_date_str: Optional[str] = None) -> bool:
    """
    Checks if SQLite DB contains a screener run for node_id matching or newer than target_date_str.
    Defaults to get_expected_market_date() if target_date_str is None.
    """
    if not target_date_str:
        target_date_str = get_expected_market_date()

    latest_ts = get_latest_screener_run_timestamp(node_id)
    if not latest_ts:
        return False

    run_date = latest_ts.split(" ")[0]
    return run_date >= target_date_str


def save_screener_node_to_db(
    node_id: str,
    node_name: str,
    category: str,
    description: str,
    rule_count: int,
    rules_spec: List[Dict[str, Any]]
) -> None:
    """Saves or updates a Screener Filter Node definition in SQLite database."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO screener_nodes (node_id, node_name, category, description, rule_count, rules_spec_json)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(node_id) DO UPDATE SET
                node_name = excluded.node_name,
                category = excluded.category,
                description = excluded.description,
                rule_count = excluded.rule_count,
                rules_spec_json = excluded.rules_spec_json
        """, (node_id, node_name, category, description, rule_count, json.dumps(rules_spec)))
        conn.commit()


def get_all_screener_nodes_from_db() -> List[Dict[str, Any]]:
    """Retrieves all active Screener Filter Nodes from SQLite database."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT node_id, node_name, category, description, rule_count, rules_spec_json, is_active, created_at
            FROM screener_nodes
            WHERE is_active = 1
            ORDER BY created_at ASC
        """)
        rows = cursor.fetchall()

    nodes = []
    for r in rows:
        item = dict(r)
        try:
            item["rules_spec"] = json.loads(item.get("rules_spec_json", "[]"))
        except Exception:
            item["rules_spec"] = []
        nodes.append(item)
    return nodes


def seed_default_screener_nodes() -> None:
    """Seeds default quantitative screener nodes (Node #1, Node #2, Node #3, Node #4) into SQLite DB."""
    from src.screener import FILTER_RULES_SPEC_NODE_1, FILTER_RULES_SPEC_NODE_2, FILTER_RULES_SPEC_NODE_3, FILTER_RULES_SPEC_NODE_4
    
    save_screener_node_to_db(
        node_id="NODE_01_BULLISH_TRENDING",
        node_name="Bullish Trending Stocks",
        category="Bullish Scan",
        description="26-Rule Algorithmic Technical Filter Engine for Cash Segment Stocks (Ichimoku, Parabolic SAR, RSI, StochRSI, CCI, MFI, Aroon, MACD, Bollinger Bands).",
        rule_count=len(FILTER_RULES_SPEC_NODE_1),
        rules_spec=FILTER_RULES_SPEC_NODE_1
    )

    save_screener_node_to_db(
        node_id="NODE_02_BULLISH_MOMENTUM",
        node_name="Pure Bullish Momentum Scan",
        category="Momentum Scan",
        description="26-Rule Algorithmic Technical Filter Engine for Cash Segment Stocks",
        rule_count=len(FILTER_RULES_SPEC_NODE_2),
        rules_spec=FILTER_RULES_SPEC_NODE_2
    )

    save_screener_node_to_db(
        node_id="NODE_03_PROFIT_JUMP_200",
        node_name="Profit Jump by 200%",
        category="Fundamental & Growth Scan",
        description="Algorithmic Fundamental & Growth Filter Engine: Net Profit increased by 100%+ (2x) YoY with positive volume & technical trend.",
        rule_count=len(FILTER_RULES_SPEC_NODE_3),
        rules_spec=FILTER_RULES_SPEC_NODE_3
    )

    save_screener_node_to_db(
        node_id="NODE_04_HIGH_SALES_GROWTH",
        node_name="High Sales Growth (QoQ & YoY)",
        category="Fundamental & Growth Scan",
        description="Algorithmic Fundamental & Top-Line Growth Filter Engine: Tracks stocks with significant sales expansion compared to previous quarter (QoQ) and same quarter last year (YoY).",
        rule_count=len(FILTER_RULES_SPEC_NODE_4),
        rules_spec=FILTER_RULES_SPEC_NODE_4
    )


# Automatically seed default nodes into SQLite DB on initialization
seed_default_screener_nodes()
