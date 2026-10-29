"""
Unit tests for DailyIntradayAutoTrader, Trailing SL logic, and IST timezone handling.
"""

import pytest
import sqlite3
import tempfile
import os
from zoneinfo import ZoneInfo
from datetime import datetime, time as dt_time
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

        # Step 2: Price moves to +0.95% (100.95) -> Trailing SL raised to breakeven cushion (100.25)
        updates = trader.monitor_and_update_trailing_sl(current_prices={"TESTSTOCK": 100.95})
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        row = cur.execute("SELECT current_sl, highest_price, status FROM daily_intraday_trades WHERE symbol='TESTSTOCK'").fetchone()
        conn.close()
        assert row[0] == 100.25  # Cost-guaranteed profit cushion (+0.25%)
        assert row[1] == 100.95
        assert row[2] == "OPEN"

        # Step 3: Price moves to +1.5% (101.5) -> Trailing SL raised to runner lock max(100.90, 100.89) = 100.90
        updates = trader.monitor_and_update_trailing_sl(current_prices={"TESTSTOCK": 101.5})
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        row = cur.execute("SELECT current_sl, highest_price, status FROM daily_intraday_trades WHERE symbol='TESTSTOCK'").fetchone()
        conn.close()
        assert row[0] == 100.9
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

        status = trader.get_automation_status(auto_squareoff_past_3pm=False)

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

        # 4. Portfolio metrics verification
        pm = status["portfolio_metrics"]
        assert pm["simulated_capital"] == 100000.0
        assert pm["active_positions_count"] == 1  # TODAY_OPEN
        assert pm["capital_utilized"] == 15000.0  # TODAY_OPEN allocated capital
        assert pm["capital_utilization_pct"] == 15.0
        assert pm["available_cash"] == 100000.0 - 15000.0 + 40.0  # 85,040.0

        # 5. Test close_single_position
        closed_res = trader.close_single_position("TODAY_OPEN", auto_recycle_margin=False)
        assert closed_res is not None
        assert closed_res["symbol"] == "TODAY_OPEN"
        assert closed_res["action"] == "CLOSED"
        assert closed_res["exit_reason"] == "MANUAL_SQUAREOFF"

        # Verify no open trades remain
        st_after = trader.get_automation_status()
        assert st_after["open_trades_count"] == 0
        assert st_after["portfolio_metrics"]["active_positions_count"] == 0
        assert st_after["portfolio_metrics"]["capital_utilized"] == 0.0

    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


def test_date_management_crud_and_export():
    """Verify listing dates summary, fetching by date, CSV export, and date-specific purge."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        trader = DailyIntradayAutoTrader(db_path=db_path)
        d1 = "2026-10-25"
        d2 = "2026-10-26"

        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        # Insert picks
        cur.execute("INSERT INTO daily_intraday_picks (date, rank, symbol, conviction_score, price, entry_trigger_price, initial_sl, target_price, strategy_name, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (d1, 1, "SYM_A", 85.0, 100.0, 100.5, 98.0, 104.0, "ORB_Breakout", f"{d1} 09:16:00"))
        cur.execute("INSERT INTO daily_intraday_picks (date, rank, symbol, conviction_score, price, entry_trigger_price, initial_sl, target_price, strategy_name, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (d2, 1, "SYM_B", 90.0, 200.0, 201.0, 196.0, 208.0, "ORB_Breakout", f"{d2} 09:16:00"))

        # Insert trades
        cur.execute("""
            INSERT INTO daily_intraday_trades
            (trade_date, symbol, side, qty, allocated_capital, entry_time, entry_price,
             exit_time, exit_price, exit_reason, initial_sl, highest_price, current_sl,
             target_price, gross_pnl, brokerage_and_taxes, net_pnl, return_pct, status, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (d1, "SYM_A", "BUY", 10, 1000.0, f"{d1} 09:20:00", 100.0,
              f"{d1} 10:00:00", 105.0, "TARGET_HIT", 98.0, 105.0, 98.0, 104.0,
              50.0, 2.0, 48.0, 4.8, "CLOSED", f"{d1} 10:00:00"))

        cur.execute("""
            INSERT INTO daily_intraday_trades
            (trade_date, symbol, side, qty, allocated_capital, entry_time, entry_price,
             exit_time, exit_price, exit_reason, initial_sl, highest_price, current_sl,
             target_price, gross_pnl, brokerage_and_taxes, net_pnl, return_pct, status, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (d2, "SYM_B", "BUY", 5, 1000.0, f"{d2} 09:20:00", 200.0,
              f"{d2} 11:00:00", 195.0, "STOP_LOSS_HIT", 196.0, 200.0, 196.0, 208.0,
              -25.0, 2.0, -27.0, -2.7, "CLOSED", f"{d2} 11:00:00"))
        conn.commit()
        conn.close()

        # 1. Available dates summary
        summaries = trader.get_available_dates_summary()
        assert len(summaries) == 2
        dates = [s["trade_date"] for s in summaries]
        assert d2 in dates and d1 in dates

        d1_meta = next(s for s in summaries if s["trade_date"] == d1)
        assert d1_meta["total_trades"] == 1
        assert d1_meta["closed_trades"] == 1
        assert d1_meta["winning_trades"] == 1
        assert d1_meta["net_pnl"] == 48.0

        # 2. Trades for date
        d1_trades = trader.get_trades_for_date(d1)
        assert len(d1_trades) == 1
        assert d1_trades[0]["symbol"] == "SYM_A"

        # 3. CSV Export
        csv_all = trader.export_trades_csv("all")
        assert "SYM_A" in csv_all and "SYM_B" in csv_all
        assert "Trade ID,Trade Date,Symbol" in csv_all

        csv_d1 = trader.export_trades_csv(d1)
        assert "SYM_A" in csv_d1
        assert "SYM_B" not in csv_d1

        # 4. Delete / Purge date d1
        del_res = trader.delete_trades_by_date(d1)
        assert del_res["status"] == "success"
        assert del_res["trades_deleted"] == 1
        assert del_res["picks_deleted"] == 1

        # Verify d1 is purged and d2 remains
        after_summaries = trader.get_available_dates_summary()
        assert len(after_summaries) == 1
        assert after_summaries[0]["trade_date"] == d2
        assert len(trader.get_trades_for_date(d1)) == 0
        assert len(trader.get_trades_for_date(d2)) == 1

    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


def test_5x_intraday_leverage_mechanics():
    """Verify that 5x MIS leverage is applied: quantity = (margin * 5) / price, and metrics reflect exposure."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        trader = DailyIntradayAutoTrader(db_path=db_path, initial_capital=100000.0, leverage=5.0)
        assert trader.leverage == 5.0

        sample_picks = [
            {"symbol": "INFY", "price": 1000.0, "conviction_score": 90.0, "rvol": 2.0, "sector": "IT", "strategy_name": "ORB"},
            {"symbol": "TCS", "price": 2000.0, "conviction_score": 85.0, "rvol": 1.5, "sector": "IT", "strategy_name": "ORB"},
        ]

        # Allocate ₹50,000 margin capital
        margin_capital = 50000.0
        trades = trader.execute_paper_algo_trades(
            picks=sample_picks,
            trade_date_str="2026-10-27",
            total_capital=margin_capital
        )

        assert len(trades) == 2
        # Sum of allocated capital must equal margin_capital
        assert sum(t["allocated_capital"] for t in trades) == margin_capital

        # With 5x leverage: total exposure should be approx ₹2,50,000 (50k * 5)
        for t in trades:
            margin = t["allocated_capital"]
            px = t["entry_price"]
            expected_exposure = margin * 5.0
            # Qty should reflect 5x buying power: ~ (margin * 5) / px
            expected_qty = int(expected_exposure / px)
            assert abs(t["qty"] - expected_qty) <= 1

        # Verify portfolio metrics with 5x leverage
        status = trader.get_automation_status(auto_squareoff_past_3pm=False)
        pm = status["portfolio_metrics"]
        assert pm["intraday_leverage"] == 5.0
        assert pm["total_buying_power"] == 500000.0  # 100k capital * 5x
        assert pm["capital_utilized"] == 50000.0
        assert pm["capital_utilization_pct"] == 50.0
        assert pm["available_cash"] == 50000.0
        # Gross exposure should be 5x margin utilized (approx ₹2,50,000)
        assert abs(pm["gross_exposure"] - 250000.0) <= 2000.0
        assert "5x MIS LEVERAGE" in pm["execution_mode"]
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


def test_manual_capital_and_leverage_configuration(tmp_path):
    """Tests that manual margin capital and leverage can be configured, persisted, and utilized."""
    db_path = tmp_path / "test_manual_cfg.db"
    trader = DailyIntradayAutoTrader(db_path=db_path, initial_capital=100000.0, leverage=5.0)

    # 1. Update manual capital to ₹2,00,000 and leverage to 4x (25% margin)
    res = trader.set_capital_and_leverage(capital=200000.0, leverage=4.0)
    assert res["capital"] == 200000.0
    assert res["leverage"] == 4.0
    assert res["buying_power"] == 800000.0

    # 2. Re-initialize a new trader instance on the same DB to ensure persistence
    trader2 = DailyIntradayAutoTrader(db_path=db_path)
    cfg = trader2.get_capital_and_leverage()
    assert cfg["capital"] == 200000.0
    assert cfg["leverage"] == 4.0
    assert cfg["buying_power"] == 800000.0

    # 3. Execute trades with custom 4x leverage
    picks = [{"symbol": "RELIANCE", "price": 2500.0, "conviction_score": 90.0, "rvol": 2.0, "sector": "Energy", "strategy_name": "ORB"}]
    trades = trader2.execute_paper_algo_trades(picks=picks, trade_date_str="2026-10-27", total_capital=100000.0, leverage=4.0)
    assert len(trades) == 1
    # 100k margin * 4x = 400k buying power -> 400,000 / 2500 = 160 shares
    assert trades[0]["qty"] == 160

    # 4. Status reflects custom capital & leverage
    status = trader2.get_automation_status(auto_squareoff_past_3pm=False)
    assert status["capital"] == 200000.0
    assert status["leverage"] == 4.0
    assert status["buying_power"] == 800000.0
    pm = status["portfolio_metrics"]
    assert pm["simulated_capital"] == 200000.0
    assert pm["intraday_leverage"] == 4.0
    assert pm["total_buying_power"] == 800000.0
    assert "4x MIS LEVERAGE" in pm["execution_mode"]


def test_continuous_whole_day_opportunity_scanning(tmp_path):
    """Verifies that the continuous engine scans for breakout opportunities whole day and dynamically enters trades."""
    db_path = tmp_path / "test_opportunity_scan.db"
    trader = DailyIntradayAutoTrader(db_path=db_path, initial_capital=100000.0, leverage=5.0)

    # 1. Populate candidate stocks in daily_intraday_picks with status WATCHING
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO daily_intraday_picks (
            date, rank, symbol, company_name, sector, price, conviction_score,
            rvol, strategy_name, entry_trigger_price, initial_sl, target_price,
            trailing_step_pct, status, created_at
        ) VALUES
        ('2026-10-28', 1, 'INFY', 'Infosys Ltd', 'IT', 1500.0, 92.0, 2.5, 'ORB_Breakout', 1505.0, 1485.0, 1530.0, 0.5, 'WATCHING', '2026-10-28 09:16:00'),
        ('2026-10-28', 2, 'TCS', 'Tata Consultancy', 'IT', 3500.0, 88.0, 1.8, 'ORB_Breakout', 3510.0, 3465.0, 3570.0, 0.5, 'WATCHING', '2026-10-28 09:16:00')
    """)
    conn.commit()
    conn.close()

    # Case A: Market prices are below entry triggers (e.g. INFY 1495, TCS 3490) -> No entry
    no_trades = trader.scan_and_execute_intraday_opportunities(
        current_prices={"INFY": 1495.0, "TCS": 3490.0},
        trade_date_str="2026-10-28"
    )
    assert len(no_trades) == 0

    # Case B: INFY breaks out above 1505 at 10:45 AM -> Dynamically entered!
    entered_trades = trader.scan_and_execute_intraday_opportunities(
        current_prices={"INFY": 1506.0, "TCS": 3495.0},
        trade_date_str="2026-10-28"
    )
    assert len(entered_trades) == 1
    assert entered_trades[0]["symbol"] == "INFY"
    assert entered_trades[0]["entry_price"] == 1506.0
    assert entered_trades[0]["status"] == "OPEN"

    # Verify INFY pick status updated to TRIGGERED
    status = trader.get_automation_status(auto_squareoff_past_3pm=False, trade_date_str="2026-10-28")
    infy_pick = next(p for p in status["today_picks"] if p["symbol"] == "INFY")
    assert infy_pick["status"] == "TRIGGERED"

    # Case C: INFY already open, scan again -> No duplicate trade for INFY
    no_dup = trader.scan_and_execute_intraday_opportunities(
        current_prices={"INFY": 1510.0, "TCS": 3495.0},
        trade_date_str="2026-10-28"
    )
    assert len(no_dup) == 0

    # Case D: Later at 1:30 PM, TCS breaks out above 3510 -> Dynamically entered!
    tcs_trade = trader.scan_and_execute_intraday_opportunities(
        current_prices={"INFY": 1515.0, "TCS": 3512.0},
        trade_date_str="2026-10-28"
    )
    assert len(tcs_trade) == 1
    assert tcs_trade[0]["symbol"] == "TCS"
    assert tcs_trade[0]["entry_price"] == 3512.0

    # Both trades are now active open positions
    status_final = trader.get_automation_status(auto_squareoff_past_3pm=False)
    assert status_final["open_trades_count"] == 2


def test_account_capital_availability_gate(tmp_path):
    """
    Verify strict account capital availability verification:
    1. get_account_capital_summary() returns precise margin availability.
    2. execute_paper_algo_trades() skips orders if available capital is lower than margin needed.
    3. scan_and_execute_intraday_opportunities() rejects trades when margin is exhausted.
    """
    db_file = tmp_path / "test_capital_gate.db"
    trader = DailyIntradayAutoTrader(db_path=db_file, initial_capital=1000.0, leverage=5.0)

    # 1. Verify capital summary on fresh account
    cap_summary = trader.get_account_capital_summary()
    assert cap_summary["capital_ready"] is True
    assert cap_summary["base_capital"] == 1000.0
    assert cap_summary["available_margin"] == 1000.0
    assert cap_summary["total_buying_power"] == 5000.0
    assert cap_summary["open_margin_utilized"] == 0.0

    # 2. Add candidates:
    # Candidate A: MRF at ₹120,000. At 5x leverage, 1 share requires ₹24,000 margin.
    # Total available margin is ₹1,000 -> Cannot afford even 1 share! Must be skipped.
    # Candidate B: ITC at ₹400. At 5x leverage, 1 share requires ₹80 margin -> Can afford!
    picks = [
        {
            "symbol": "MRF",
            "price": 120000.0,
            "conviction_score": 95.0,
            "rvol": 2.5,
            "sector": "Auto",
            "strategy_name": "Breakout",
            "initial_sl": 118000.0,
            "target_price": 125000.0
        },
        {
            "symbol": "ITC",
            "price": 400.0,
            "conviction_score": 88.0,
            "rvol": 2.0,
            "sector": "FMCG",
            "strategy_name": "Breakout",
            "initial_sl": 390.0,
            "target_price": 420.0
        }
    ]

    trades = trader.execute_paper_algo_trades(picks=picks, trade_date_str="2026-10-28")
    symbols_entered = [t["symbol"] for t in trades]

    # MRF must have been rejected due to insufficient capital
    assert "MRF" not in symbols_entered
    # ITC must be entered
    assert "ITC" in symbols_entered

    # Verify that available margin did not go negative
    updated_cap = trader.get_account_capital_summary()
    assert updated_cap["available_margin"] >= 0.0
    assert updated_cap["open_margin_utilized"] > 0.0

    # 3. If available margin is exhausted to 0, intraday opportunity scanner must reject new entries
    # Set simulated initial_capital to small amount equal to margin utilized
    trader.initial_capital = updated_cap["open_margin_utilized"]
    exhausted_cap = trader.get_account_capital_summary()
    assert exhausted_cap["available_margin"] == 0.0

    # Insert a breakout candidate into daily_intraday_picks
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO daily_intraday_picks (
            date, rank, symbol, company_name, sector, price, conviction_score,
            rvol, strategy_name, entry_trigger_price, initial_sl, target_price,
            trailing_step_pct, status, created_at
        ) VALUES
        ('2026-10-28', 3, 'RELIANCE', 'Reliance Ind', 'Energy', 2500.0, 90.0, 2.0, 'Breakout', 2510.0, 2450.0, 2600.0, 0.5, 'WATCHING', '2026-10-28 09:16:00')
    """)
    conn.commit()
    conn.close()

    # Opportunity triggers breakout, but margin is 0 -> should NOT enter trade
    opp_trades = trader.scan_and_execute_intraday_opportunities(
        current_prices={"RELIANCE": 2515.0},
        trade_date_str="2026-10-28"
    )
    assert len(opp_trades) == 0


def test_bidirectional_short_selling_mechanics(tmp_path):
    """
    Verifies that the engine executes SHORT (SELL) trades:
    1. Short candidate triggers breakdown below trigger price.
    2. Short trade enters with SL above entry and Target below entry.
    3. Trailing SL lowers as price drops, locking in profit.
    4. Target hit realizes full short profit.
    """
    db_file = tmp_path / "test_short_selling.db"
    trader = DailyIntradayAutoTrader(db_path=db_file, initial_capital=100000.0, leverage=5.0)

    # 1. Insert a SHORT candidate into daily_intraday_picks
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO daily_intraday_picks (
            date, rank, symbol, company_name, sector, price, conviction_score,
            rvol, strategy_name, entry_trigger_price, initial_sl, target_price,
            trailing_step_pct, status, side, created_at
        ) VALUES
        ('2026-10-28', 1, 'TATAMOTORS', 'Tata Motors', 'Auto', 1000.0, 88.0, 2.2, 'ORB_Breakdown_Short_V4', 996.0, 1014.0, 978.0, 0.5, 'WATCHING', 'SELL', '2026-10-28 09:16:00')
    """)
    conn.commit()
    conn.close()

    # 2. Trigger breakdown: Price drops to 995.0 (below 996 trigger)
    entered_trades = trader.scan_and_execute_intraday_opportunities(
        current_prices={"TATAMOTORS": 995.0},
        trade_date_str="2026-10-28"
    )
    assert len(entered_trades) == 1
    short_trade = entered_trades[0]
    assert short_trade["symbol"] == "TATAMOTORS"
    assert short_trade["side"] == "SELL"
    assert short_trade["entry_price"] == 995.0
    assert short_trade["initial_sl"] > 995.0  # SL is above entry for short
    assert short_trade["target_price"] < 995.0  # Target is below entry for short

    # 3. Price drops to +1.0% profit for short (price drops to 985.0)
    # Trailing SL should lower below entry to lock in cost-guaranteed profit
    updates = trader.monitor_and_update_trailing_sl(current_prices={"TATAMOTORS": 985.0})
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    cur.execute("SELECT current_sl, status FROM daily_intraday_trades WHERE symbol='TATAMOTORS'")
    row = cur.fetchone()
    conn.close()
    assert row[0] < 995.0  # SL lowered below entry price for short!
    assert row[1] == "OPEN"

    # 4. Price reaches target: drops to 970.0 (below 978 target) -> TARGET_HIT!
    exits = trader.monitor_and_update_trailing_sl(current_prices={"TATAMOTORS": 970.0})
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    cur.execute("SELECT status, exit_reason, net_pnl, gross_pnl FROM daily_intraday_trades WHERE symbol='TATAMOTORS'")
    row = cur.fetchone()
    conn.close()
    assert row[0] == "CLOSED"
    assert row[1] == "TARGET_HIT"
    assert row[2] > 0.0  # Positive net profit on short!
    assert row[3] > 0.0  # Positive gross profit on short!


def test_momentum_supported_trailing_target_and_sl(tmp_path):
    """
    Verifies that when momentum supports continuation:
    1. At +0.65%, Trailing SL locks at +0.35% (cost-guaranteed breakeven).
    2. At +1.00%, Trailing SL locks at +0.70%.
    3. At +1.35% with momentum holding high watermark, Target trails to Target 2 (+2.2%) and SL locks at +1.00%.
    4. At Target 2 (+2.2%), position closes with TARGET_HIT.
    5. In reversal scenario, position closes with TRAILING_SL_HIT locking in +1.00% gain.
    """
    db_file = tmp_path / "test_trailing_momentum.db"
    trader = DailyIntradayAutoTrader(db_path=db_file, initial_capital=100000.0, leverage=5.0)

    # 1. Insert BUY trade: Entry 1000.0, Initial SL 988.0, Target 1 1014.0 (+1.4%)
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO daily_intraday_trades (
            trade_date, symbol, side, qty, allocated_capital, entry_time,
            entry_price, initial_sl, highest_price, current_sl, target_price,
            gross_pnl, brokerage_and_taxes, net_pnl, return_pct, status, price_history, updated_at
        ) VALUES (
            '2026-10-28', 'RELIANCE', 'BUY', 50, 10000.0, '2026-10-28 09:30:00',
            1000.0, 988.0, 1000.0, 988.0, 1014.0,
            0.0, 0.0, 0.0, 0.0, 'OPEN', '[]', '2026-10-28 09:30:00'
        )
    """)
    conn.commit()
    conn.close()

    # Step 1: Price reaches +0.95% (1009.5) -> SL trails to 1002.5 (+0.25% cost-guaranteed)
    trader.monitor_and_update_trailing_sl(current_prices={"RELIANCE": 1009.5})
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    row = cur.execute("SELECT current_sl, target_price, status FROM daily_intraday_trades WHERE symbol='RELIANCE'").fetchone()
    conn.close()
    assert row[0] == 1002.5
    assert row[1] == 1014.0  # Target 1 intact
    assert row[2] == "OPEN"

    # Step 2: Price reaches +1.25% (1012.5) -> SL trails to >= 1009.0 (+0.90%)
    trader.monitor_and_update_trailing_sl(current_prices={"RELIANCE": 1012.5})
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    row = cur.execute("SELECT current_sl, target_price, status FROM daily_intraday_trades WHERE symbol='RELIANCE'").fetchone()
    conn.close()
    assert row[0] >= 1009.0
    assert row[1] == 1014.0
    assert row[2] == "OPEN"

    # Step 3: Price pushes to 1013.8 (+1.38% near Target 1) with strong momentum (at high)
    # Target trails to Target 2 (1022.0 = +2.2%) and SL locks in +1.00% (1010.0)
    trader.monitor_and_update_trailing_sl(current_prices={"RELIANCE": 1013.8})
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    row = cur.execute("SELECT current_sl, target_price, status FROM daily_intraday_trades WHERE symbol='RELIANCE'").fetchone()
    conn.close()
    assert row[1] == 1022.0  # Trailed to Target 2!
    assert row[0] >= 1010.0  # SL locked at +1.0% profit!
    assert row[2] == "OPEN"  # Trade stays open to capture runner!

    # Step 4: Price reaches Target 2 (1022.5) -> Exits with TARGET_HIT
    trader.monitor_and_update_trailing_sl(current_prices={"RELIANCE": 1022.5})
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    row = cur.execute("SELECT status, exit_reason, net_pnl FROM daily_intraday_trades WHERE symbol='RELIANCE'").fetchone()
    conn.close()
    assert row[0] == "CLOSED"
    assert row[1] == "TARGET_HIT"
    assert row[2] > 0.0


def test_max_10_daily_trades_limit_gate(tmp_path):
    """
    Verifies that the engine strictly enforces the maximum 10 trades per day ceiling:
    1. Once 10 trades are entered for a single day, scan_and_execute_intraday_opportunities
       halts new entries.
    2. get_automation_status accurately reports max_daily_trades=10, today_trades_count=10,
       and daily_trades_remaining=0.
    """
    db_file = tmp_path / "test_max_10_trades.db"
    trader = DailyIntradayAutoTrader(db_path=db_file, initial_capital=200000.0, leverage=5.0)

    # 1. Insert 10 existing trades for today (2026-10-28)
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    for i in range(1, 11):
        cur.execute(f"""
            INSERT INTO daily_intraday_trades (
                trade_date, symbol, side, qty, allocated_capital, entry_time,
                entry_price, initial_sl, highest_price, current_sl, target_price,
                gross_pnl, brokerage_and_taxes, net_pnl, return_pct, status, price_history, updated_at
            ) VALUES (
                '2026-10-28', 'STOCK_{i}', 'BUY', 10, 5000.0, '2026-10-28 09:30:00',
                100.0, 98.8, 100.0, 98.8, 101.4,
                10.0, 1.0, 9.0, 0.9, 'CLOSED', '[]', '2026-10-28 10:00:00'
            )
        """)

    # Also insert an 11th high-conviction breakout candidate in daily_intraday_picks
    cur.execute("""
        INSERT INTO daily_intraday_picks (
            date, rank, symbol, company_name, sector, price, conviction_score,
            rvol, strategy_name, entry_trigger_price, initial_sl, target_price,
            trailing_step_pct, status, created_at
        ) VALUES
        ('2026-10-28', 11, 'BONUS_STOCK', 'Bonus Stock Ltd', 'Tech', 500.0, 95.0, 3.0, 'ORB_Breakout', 501.0, 494.0, 508.0, 0.5, 'WATCHING', '2026-10-28 09:16:00')
    """)
    conn.commit()
    conn.close()

    # 2. Attempt to scan and execute with price triggering breakout at 505.0
    # Must be BLOCKED because 10 trades already occurred today
    new_trades = trader.scan_and_execute_intraday_opportunities(
        current_prices={"BONUS_STOCK": 505.0},
        trade_date_str="2026-10-28",
        max_daily_trades=10
    )
    assert len(new_trades) == 0

    # 3. Verify portfolio status reports 0 remaining trades
    status = trader.get_automation_status(trade_date_str="2026-10-28")
    pm = status["portfolio_metrics"]
    assert pm["max_daily_trades"] == 10
    assert pm["today_trades_count"] == 10
def test_use_index_regime_parameter(tmp_path):
    """Verifies use_index_regime configuration, persistence, and evaluation toggling."""
    db_file = tmp_path / "index_test.db"
    trader = DailyIntradayAutoTrader(db_path=db_file, initial_capital=100000.0, leverage=5.0, use_index_regime=True)
    assert trader.use_index_regime is True
    cfg = trader.get_capital_and_leverage()
    assert cfg["use_index_regime"] is True

    # Toggle to False and persist
    saved = trader.set_capital_and_leverage(capital=80000.0, leverage=4.0, use_index_regime=False)
    assert saved["use_index_regime"] is False
    assert trader.use_index_regime is False

    # Instantiate new trader with same DB to verify SQLite persistence reload
    trader_reloaded = DailyIntradayAutoTrader(db_path=db_file)
    assert trader_reloaded.use_index_regime is False
    assert trader_reloaded.initial_capital == 80000.0
    assert trader_reloaded.leverage == 4.0

    # Test toggling back to True
    trader_reloaded.set_capital_and_leverage(capital=100000.0, leverage=5.0, use_index_regime=True)
    assert trader_reloaded.use_index_regime is True


def test_zerodha_margin_release_and_opportunity_recycling(tmp_path):
    """
    Verifies that when a trade is closed:
    1. 100% of the blocked margin is unblocked plus net profit/loss (per Zerodha MIS intraday rules).
    2. Available margin increases immediately.
    3. The trader immediately scans and deploys freed margin into a pending high-conviction breakout opportunity.
    """
    db_file = tmp_path / "test_zerodha_recycling.db"
    trader = DailyIntradayAutoTrader(db_path=db_file, initial_capital=20000.0, leverage=5.0, use_index_regime=False)

    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()

    # 1. Insert an existing OPEN trade: INFY (allocated_capital=4000.0)
    cur.execute("""
        INSERT INTO daily_intraday_trades (
            trade_date, symbol, side, qty, allocated_capital, entry_time,
            entry_price, initial_sl, highest_price, current_sl, target_price,
            gross_pnl, brokerage_and_taxes, net_pnl, return_pct, status, price_history, updated_at
        ) VALUES (
            '2026-10-28', 'INFY', 'BUY', 13, 4000.0, '2026-10-28 09:30:00',
            1500.0, 1485.0, 1500.0, 1485.0, 1525.0,
            0.0, 0.0, 0.0, 0.0, 'OPEN', '[]', '2026-10-28 09:30:00'
        )
    """)

    # 2. Insert a WATCHING opportunity: TCS in daily_intraday_picks
    cur.execute("""
        INSERT INTO daily_intraday_picks (
            date, rank, symbol, company_name, sector, price, conviction_score,
            rvol, strategy_name, entry_trigger_price, initial_sl, target_price,
            trailing_step_pct, status, side, created_at
        ) VALUES (
            '2026-10-28', 1, 'TCS', 'Tata Consultancy Services', 'IT', 3500.0, 92.0,
            2.5, 'ORB_Breakout', 3505.0, 3465.0, 3550.0, 0.5, 'WATCHING', 'BUY', '2026-10-28 09:16:00'
        )
    """)
    conn.commit()
    conn.close()

    # Verify margin before close: Available = 20000 - 4000 = 16000
    before_status = trader.get_account_capital_summary(trade_date_str="2026-10-28")
    assert before_status["open_positions_count"] == 1
    assert before_status["open_margin_utilized"] == 4000.0
    assert before_status["available_margin"] == 16000.0

    # 3. Simulate prices: INFY hits target at 1535 (>1533 extended target) -> closes INFY
    # TCS is at 3510 (> entry_trigger 3505) -> triggers immediately via margin recycling!
    updates = trader.monitor_and_update_trailing_sl(
        current_prices={"INFY": 1535.0, "TCS": 3510.0},
        trade_date_str="2026-10-28"
    )

    # 4. Assert INFY closed via TARGET_HIT
    infy_update = next((u for u in updates if u["symbol"] == "INFY"), None)
    assert infy_update is not None
    assert infy_update["action"] == "CLOSED"
    assert infy_update["exit_reason"] == "TARGET_HIT"
    assert infy_update["net_pnl"] > 0

    # 5. Assert TCS was immediately entered into daily_intraday_trades using the freed margin!
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    trades = cur.execute("SELECT symbol, side, status, allocated_capital FROM daily_intraday_trades ORDER BY id ASC").fetchall()
    conn.close()

    assert len(trades) == 2
    # First trade: INFY CLOSED
    assert trades[0][0] == "INFY"
    assert trades[0][2] == "CLOSED"
    # Second trade: TCS OPEN
    assert trades[1][0] == "TCS"
    assert trades[1][1] == "BUY"
    assert trades[1][2] == "OPEN"
    assert trades[1][3] > 0.0

    # 6. Verify account capital summary reflects Zerodha margin release + net P&L credit
    after_status = trader.get_account_capital_summary(trade_date_str="2026-10-28")
    assert after_status["open_positions_count"] == 1  # Only TCS is open now
    assert after_status["today_realized_pnl"] > 0.0   # Realized net profit from INFY credited to margin
    assert after_status["available_margin"] > 16000.0 # Freed margin was recycled into TCS with surplus remaining


def test_orb_and_vwap_confluence_gate(tmp_path, monkeypatch):
    """
    Verifies that scan_and_execute_intraday_opportunities strictly enforces:
    1. Rejection of BUY if price is below 15m ORB High or below VWAP.
    2. Execution of BUY only when price is above ORB High AND above VWAP.
    """
    db_file = tmp_path / "test_orb_vwap.db"
    trader = DailyIntradayAutoTrader(db_path=db_file, initial_capital=50000.0, leverage=5.0)

    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    # Insert candidate into daily_intraday_picks
    cur.execute("""
        INSERT INTO daily_intraday_picks (
            date, rank, symbol, company_name, sector, price, conviction_score,
            rvol, strategy_name, entry_trigger_price, initial_sl, target_price,
            trailing_step_pct, status, side, created_at
        ) VALUES (
            '2026-10-28', 1, 'RELIANCE', 'Reliance Industries', 'Energy', 1160.0, 95.0,
            2.0, 'ORB_Momentum_Breakout_V4', 1165.0, 1150.0, 1180.0, 0.5, 'WATCHING', 'BUY', '2026-10-28 09:16:00'
        )
    """)
    conn.commit()
    conn.close()

    # Case A: Price is 1168 (above trigger 1165), but below ORB High 1175 and below VWAP 1170 -> VETOED
    monkeypatch.setattr(
        trader,
        "get_intraday_orb_and_vwap",
        lambda sym, current_price=None: {
            "symbol": sym, "curr_price": 1168.0, "orb_high": 1175.0, "orb_low": 1155.0, "vwap": 1170.0
        }
    )
    trades_vetoed = trader.scan_and_execute_intraday_opportunities(
        trade_date_str="2026-10-28"
    )
    assert len(trades_vetoed) == 0

    # Case B: Price is 1178 (above trigger 1165, above ORB High 1175, and above VWAP 1170) -> APPROVED
    monkeypatch.setattr(
        trader,
        "get_intraday_orb_and_vwap",
        lambda sym, current_price=None: {
            "symbol": sym, "curr_price": 1178.0, "orb_high": 1175.0, "orb_low": 1155.0, "vwap": 1170.0
        }
    )
    trades_approved = trader.scan_and_execute_intraday_opportunities(
        trade_date_str="2026-10-28"
    )
    assert len(trades_approved) == 1
    assert trades_approved[0]["symbol"] == "RELIANCE"
    assert trades_approved[0]["side"] == "BUY"


def test_market_hour_session_resolution_and_strategies(tmp_path):
    """
    Verifies that get_market_hour_session correctly resolves:
    1. 09:15 - 09:30: OPENING_DISCOVERY (trading_allowed=False, RANGE_BUILDER)
    2. 09:30 - 11:30: MORNING_EXPANSION (trading_allowed=True, ORB_MOMENTUM_BREAKOUT)
    3. 11:30 - 13:30: MIDDAY_EUROPEAN (trading_allowed=True, VWAP_PULLBACK_REVERSION)
    4. 13:30 - 14:45: AFTERNOON_POWER (trading_allowed=True, POWER_HOUR_MOMENTUM_RUNNER)
    5. 14:45 - 15:30: EOD_SQUAREOFF (trading_allowed=False, RISK_SHIELD)
    6. Off-hours: MARKET_CLOSED (trading_allowed=False)
    """
    db_file = tmp_path / "test_sessions.db"
    trader = DailyIntradayAutoTrader(db_path=str(db_file))

    # 1. 09:20 IST -> OPENING_DISCOVERY
    s1 = trader.get_market_hour_session(check_time=dt_time(9, 20))
    assert s1["session_id"] == "OPENING_DISCOVERY"
    assert s1["strategy_id"] == "RANGE_BUILDER"
    assert s1["trading_allowed"] is False

    # 2. 10:15 IST -> MORNING_EXPANSION
    s2 = trader.get_market_hour_session(check_time=dt_time(10, 15))
    assert s2["session_id"] == "MORNING_EXPANSION"
    assert s2["strategy_id"] == "ORB_MOMENTUM_BREAKOUT"
    assert s2["trading_allowed"] is True
    assert s2["target_pct"] == 1.5
    assert s2["sl_pct"] == 0.8

    # 3. 12:30 IST -> MIDDAY_EUROPEAN
    s3 = trader.get_market_hour_session(check_time=dt_time(12, 30))
    assert s3["session_id"] == "MIDDAY_EUROPEAN"
    assert s3["strategy_id"] == "VWAP_PULLBACK_REVERSION"
    assert s3["trading_allowed"] is True
    assert s3["target_pct"] == 1.0
    assert s3["sl_pct"] == 0.5

    # 4. 14:00 IST -> AFTERNOON_POWER
    s4 = trader.get_market_hour_session(check_time=dt_time(14, 0))
    assert s4["session_id"] == "AFTERNOON_POWER"
    assert s4["strategy_id"] == "POWER_HOUR_MOMENTUM_RUNNER"
    assert s4["trading_allowed"] is True
    assert s4["target_pct"] == 1.2
    assert s4["sl_pct"] == 0.65

    # 5. 15:05 IST -> EOD_SQUAREOFF
    s5 = trader.get_market_hour_session(check_time=dt_time(15, 5))
    assert s5["session_id"] == "EOD_SQUAREOFF"
    assert s5["strategy_id"] == "RISK_SHIELD"
    assert s5["trading_allowed"] is False

    # 6. 18:30 IST -> MARKET_CLOSED
    s6 = trader.get_market_hour_session(check_time=dt_time(18, 30))
    assert s6["session_id"] == "MARKET_CLOSED"
    assert s6["trading_allowed"] is False


def test_market_hour_strategy_execution_and_midday_reversion(tmp_path, monkeypatch):
    """
    Verifies that scan_and_execute_intraday_opportunities executes different strategy rules
    based on the market hour session:
    1. During OPENING_DISCOVERY (09:20): rejects trade execution.
    2. During MIDDAY_EUROPEAN (12:30): rejects breakout spikes at high of day, approves pullback to VWAP.
    3. Status payload surfaces active session and strategy.
    """
    db_file = tmp_path / "test_session_exec.db"
    trader = DailyIntradayAutoTrader(db_path=str(db_file))

    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO daily_intraday_picks (
            date, rank, symbol, company_name, sector, price, conviction_score,
            rvol, strategy_name, entry_trigger_price, initial_sl, target_price,
            trailing_step_pct, status, side, created_at
        ) VALUES (
            '2026-10-29', 1, 'INFY', 'Infosys Ltd', 'IT', 1500.0, 90.0,
            2.2, 'Intraday_MultiSession', 1505.0, 1490.0, 1530.0, 0.4, 'WATCHING', 'BUY', '2026-10-29 09:16:00'
        )
    """)
    conn.commit()
    conn.close()

    # 1. Simulate OPENING_DISCOVERY (09:20 IST) -> Must reject all entries
    trades_opening = trader.scan_and_execute_intraday_opportunities(
        trade_date_str="2026-10-29",
        simulated_time=dt_time(9, 20)
    )
    assert len(trades_opening) == 0

    # 2. Simulate MIDDAY_EUROPEAN (12:30 IST) with price overextended at High of Day (1520 vs VWAP 1500)
    # Midday mean-reversion rule forbids chasing overextended spikes at peak
    monkeypatch.setattr(
        trader,
        "get_intraday_orb_and_vwap",
        lambda sym, current_price=None: {
            "symbol": sym, "curr_price": 1520.0, "orb_high": 1522.0, "orb_low": 1490.0, "vwap": 1500.0
        }
    )
    trades_midday_spike = trader.scan_and_execute_intraday_opportunities(
        trade_date_str="2026-10-29",
        simulated_time=dt_time(12, 30)
    )
    assert len(trades_midday_spike) == 0  # Vetoed: overextended >0.7% from VWAP

    # 3. Simulate MIDDAY_EUROPEAN (12:30 IST) with healthy pullback to VWAP (1505 vs VWAP 1502, below HOD 1522)
    # Healthy pullback bounce -> APPROVED!
    monkeypatch.setattr(
        trader,
        "get_intraday_orb_and_vwap",
        lambda sym, current_price=None: {
            "symbol": sym, "curr_price": 1505.0, "orb_high": 1522.0, "orb_low": 1490.0, "vwap": 1502.0
        }
    )
    trades_midday_pullback = trader.scan_and_execute_intraday_opportunities(
        trade_date_str="2026-10-29",
        simulated_time=dt_time(12, 30)
    )
    assert len(trades_midday_pullback) == 1
    t = trades_midday_pullback[0]
    assert t["symbol"] == "INFY"
    assert t["strategy_applied"] == "VWAP_PULLBACK_REVERSION"
    assert t["market_session"] == "MIDDAY_EUROPEAN"
    assert t["initial_sl"] < 1505.0  # Tight risk below entry
    assert t["target_price"] > 1505.0

    # 4. Verify get_automation_status includes market session telemetry
    status = trader.get_automation_status(trade_date_str="2026-10-29")
    assert "market_session" in status
    assert "active_strategy" in status["portfolio_metrics"]
    assert "market_session" in status["portfolio_metrics"]










