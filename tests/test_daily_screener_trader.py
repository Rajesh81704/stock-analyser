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


def test_smart_capital_allocation_and_execution():
    """Verifies that an allocated amount X is smartly distributed across picks using Gemini/Quant engine."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        trader = DailyIntradayAutoTrader(db_path=db_path)
        sample_picks = [
            {"symbol": "ALPHA", "price": 1000.0, "conviction_score": 92.0, "rvol": 2.5, "sector": "IT", "strategy_name": "Momentum"},
            {"symbol": "BETA", "price": 500.0, "conviction_score": 82.0, "rvol": 1.8, "sector": "Banking", "strategy_name": "Breakout"},
            {"symbol": "GAMMA", "price": 250.0, "conviction_score": 72.0, "rvol": 1.1, "sector": "Pharma", "strategy_name": "Volume_Surge"},
        ]

        total_capital = 150000.0  # ₹1.5 Lakhs
        trades = trader.execute_paper_algo_trades(
            picks=sample_picks,
            trade_date_str="2026-10-27",
            total_capital=total_capital
        )

        assert len(trades) == 3
        total_allocated = sum(t["allocated_capital"] for t in trades)
        assert abs(total_allocated - total_capital) < 1.0  # Within ₹1 rounding

        # Higher conviction stock (ALPHA) should receive more capital than lower conviction (GAMMA)
        alpha_trade = next(t for t in trades if t["symbol"] == "ALPHA")
        gamma_trade = next(t for t in trades if t["symbol"] == "GAMMA")
        assert alpha_trade["allocated_capital"] > gamma_trade["allocated_capital"]
        assert alpha_trade["weight_pct"] > gamma_trade["weight_pct"]
        assert "ai_rationale" in alpha_trade
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


def test_datewise_segregation_and_today_summary():
    """Verifies that get_automation_status segregates trades day-datewise and isolates today's section."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        trader = DailyIntradayAutoTrader(db_path=db_path)
        from src.algodesk.automation.daily_screener_trader import get_ist_date
        today_str = get_ist_date()
        yesterday_str = "2026-10-26"

        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        # Insert 2 trades for today (1 winning closed, 1 open)
        cur.execute("""
            INSERT INTO daily_intraday_trades
            (trade_date, symbol, side, qty, allocated_capital, entry_time, entry_price,
             exit_time, exit_price, exit_reason, initial_sl, highest_price, current_sl,
             target_price, gross_pnl, brokerage_and_taxes, net_pnl, return_pct, status, updated_at)
            VALUES
            (?, 'TODAY_WIN', 'BUY', 10, 25000.0, ? || ' 09:16:00', 100.0,
             ? || ' 10:15:00', 105.0, 'TARGET_HIT', 98.0, 105.0, 104.0, 105.0, 50.0, 10.0, 40.0, 5.0, 'CLOSED', ? || ' 10:15:00'),
            (?, 'TODAY_OPEN', 'BUY', 5, 15000.0, ? || ' 09:16:00', 200.0,
             NULL, NULL, NULL, 196.0, 202.0, 198.0, 208.0, 0.0, 0.0, 0.0, 0.0, 'OPEN', ? || ' 09:30:00')
        """, (today_str, today_str, today_str, today_str, today_str, today_str, today_str))

        # Insert 2 trades for yesterday (1 winning closed, 1 losing closed)
        cur.execute("""
            INSERT INTO daily_intraday_trades
            (trade_date, symbol, side, qty, allocated_capital, entry_time, entry_price,
             exit_time, exit_price, exit_reason, initial_sl, highest_price, current_sl,
             target_price, gross_pnl, brokerage_and_taxes, net_pnl, return_pct, status, updated_at)
            VALUES
            (?, 'YEST_WIN', 'BUY', 10, 20000.0, ? || ' 09:16:00', 50.0,
             ? || ' 11:30:00', 52.0, 'TRAILING_SL_HIT', 49.0, 53.0, 52.0, 54.0, 20.0, 8.0, 12.0, 4.0, 'CLOSED', ? || ' 11:30:00'),
            (?, 'YEST_LOSS', 'BUY', 10, 20000.0, ? || ' 09:16:00', 50.0,
             ? || ' 09:45:00', 49.0, 'STOP_LOSS_HIT', 49.0, 50.0, 49.0, 52.0, -10.0, 8.0, -18.0, -2.0, 'CLOSED', ? || ' 09:45:00')
        """, (yesterday_str, yesterday_str, yesterday_str, yesterday_str, yesterday_str, yesterday_str, yesterday_str, yesterday_str))

        conn.commit()
        conn.close()

        status = trader.get_automation_status()

        # 1. Today's isolation
        assert status["today_date"] == today_str
        assert status["today_trades_count"] == 2
        assert len(status["today_trades"]) == 2
        assert {t["symbol"] for t in status["today_trades"]} == {"TODAY_WIN", "TODAY_OPEN"}

        # 2. Today's summary
        today_sum = status["today_summary"]
        assert today_sum["total_trades"] == 2
        assert today_sum["open_trades"] == 1
        assert today_sum["closed_trades"] == 1
        assert today_sum["winning_trades"] == 1
        assert today_sum["win_rate"] == 100.0
        assert today_sum["net_pnl"] == 40.0
        assert today_sum["total_allocated"] == 40000.0

        # 3. Date-wise segregation
        assert yesterday_str in status["trades_by_date"]
        yest_sum = status["trades_by_date"][yesterday_str]
        assert yest_sum["total_trades"] == 2
        assert yest_sum["closed_trades"] == 2
        assert yest_sum["winning_trades"] == 1
        assert yest_sum["losing_trades"] == 1
        assert yest_sum["win_rate"] == 50.0
        assert yest_sum["net_pnl"] == -6.0  # 12.0 - 18.0
        assert status["historical_dates"] == [yesterday_str]

    finally:
        if os.path.exists(db_path):
            os.remove(db_path)



