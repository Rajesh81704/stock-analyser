"""
Unit tests for DailyIntradayAutoTrader, Trailing SL logic, and IST timezone handling.
"""

import pytest
import sqlite3
import tempfile
import os
from zoneinfo import ZoneInfo
from datetime import datetime
from src.algodesk.automation.daily_screener_trader import (
    DailyIntradayAutoTrader,
    get_ist_date,
    get_ist_now_ts,
    IST
)


def test_ist_timezone_helper():
    """Validates that IST helpers return valid date and timestamp in Asia/Kolkata."""
    date_str = get_ist_date()
    now_ts = get_ist_now_ts()
    
    assert len(date_str) == 10
    assert date_str.count("-") == 2
    assert len(now_ts) == 19
    
    # Check that now_ts parses to datetime
    dt = datetime.strptime(now_ts, "%Y-%m-%d %H:%M:%S")
    assert dt.year >= 2026


def test_trader_database_initialization():
    """Verifies SQLite tables creation in DailyIntradayAutoTrader."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        trader = DailyIntradayAutoTrader(db_path=db_path)
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        
        tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        assert "daily_intraday_picks" in tables
        assert "daily_intraday_trades" in tables
        conn.close()
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


def test_trailing_sl_rules():
    """Tests the trailing stop-loss progression logic."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        trader = DailyIntradayAutoTrader(db_path=db_path)
        
        # Insert a sample trade: Entry 100, SL 99 (-1%), Target 102 (+2%)
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO daily_intraday_trades (
                trade_date, symbol, side, qty, allocated_capital, entry_time,
                entry_price, initial_sl, highest_price, current_sl, target_price,
                gross_pnl, brokerage_and_taxes, net_pnl, return_pct, status, price_history, updated_at
            ) VALUES (
                '2026-10-26', 'TESTSTOCK', 'BUY', 100, 10000.0, '2026-10-26 10:00:00',
                100.0, 99.0, 100.0, 99.0, 102.0,
                0.0, 0.0, 0.0, 0.0, 'OPEN', '[]', '2026-10-26 10:00:00'
            )
        """)
        conn.commit()
        conn.close()

        # Step 1: Small move (+0.4% to 100.4) -> SL stays at initial SL 99.0
        updates = trader.monitor_and_update_trailing_sl(current_prices={"TESTSTOCK": 100.4})
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        row = cur.execute("SELECT current_sl, highest_price, status FROM daily_intraday_trades WHERE symbol='TESTSTOCK'").fetchone()
        conn.close()
        assert row[0] == 99.0
        assert row[1] == 100.4
        assert row[2] == "OPEN"

        # Step 2: Price moves to +0.8% (100.8) -> Trailing SL raised to breakeven (100.0)
        updates = trader.monitor_and_update_trailing_sl(current_prices={"TESTSTOCK": 100.8})
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        row = cur.execute("SELECT current_sl, highest_price, status FROM daily_intraday_trades WHERE symbol='TESTSTOCK'").fetchone()
        conn.close()
        assert row[0] == 100.0  # Breakeven
        assert row[1] == 100.8
        assert row[2] == "OPEN"

        # Step 3: Price moves to +1.5% (101.5) -> Trailing SL raised to 0.5% below high watermark (101.5 * 0.995 = 100.99)
        updates = trader.monitor_and_update_trailing_sl(current_prices={"TESTSTOCK": 101.5})
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        row = cur.execute("SELECT current_sl, highest_price, status FROM daily_intraday_trades WHERE symbol='TESTSTOCK'").fetchone()
        conn.close()
        assert row[0] == 100.99
        assert row[1] == 101.5
        assert row[2] == "OPEN"

        # Step 4: Price reaches target +2.0% (102.0) -> Trade exits with TARGET_HIT
        updates = trader.monitor_and_update_trailing_sl(current_prices={"TESTSTOCK": 102.05})
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        row = cur.execute("SELECT current_sl, status, exit_reason, net_pnl FROM daily_intraday_trades WHERE symbol='TESTSTOCK'").fetchone()
        conn.close()
        assert row[1] == "CLOSED"
        assert row[2] == "TARGET_HIT"
        assert row[3] > 0  # Net profit after brokerage and taxes
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


def test_3pm_force_squareoff_rule():
    """Verifies that all open positions are squared off by 3 PM even if target is not achieved."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        trader = DailyIntradayAutoTrader(db_path=db_path)

        # Insert a sample trade: Entry 100, SL 99 (-1%), Target 102 (+2%)
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO daily_intraday_trades (
                trade_date, symbol, side, qty, allocated_capital, entry_time,
                entry_price, initial_sl, highest_price, current_sl, target_price,
                gross_pnl, brokerage_and_taxes, net_pnl, return_pct, status, price_history, updated_at
            ) VALUES (
                '2026-10-26', 'STOCK_3PM', 'BUY', 50, 5000.0, '2026-10-26 14:00:00',
                100.0, 99.0, 100.5, 99.0, 102.0,
                0.0, 0.0, 0.0, 0.0, 'OPEN', '[]', '2026-10-26 14:00:00'
            )
        """)
        conn.commit()
        conn.close()

        # At 3:00 PM: target (102.0) is NOT achieved (price is only 100.5)
        # force_eod_squareoff triggers:
        updates = trader.monitor_and_update_trailing_sl(
            current_prices={"STOCK_3PM": 100.5},
            force_eod_squareoff=True
        )

        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        row = cur.execute("SELECT status, exit_reason, exit_price FROM daily_intraday_trades WHERE symbol='STOCK_3PM'").fetchone()
        conn.close()

        assert row[0] == "CLOSED"
        assert row[1] == "3PM_SQUAREOFF"
        assert row[2] == 100.5
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)

