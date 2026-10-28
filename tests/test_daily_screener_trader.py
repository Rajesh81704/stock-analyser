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
        assert row[0] == 100.35  # Cost-guaranteed profit cushion (+0.35%)
        assert row[1] == 100.8
        assert row[2] == "OPEN"

        # Step 3: Price moves to +1.5% (101.5) -> Trailing SL raised to 0.6% below high watermark (101.5 * 0.994 = 100.89)
        updates = trader.monitor_and_update_trailing_sl(current_prices={"TESTSTOCK": 101.5})
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        row = cur.execute("SELECT current_sl, highest_price, status FROM daily_intraday_trades WHERE symbol='TESTSTOCK'").fetchone()
        conn.close()
        assert row[0] == 100.89
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
        closed_res = trader.close_single_position("TODAY_OPEN")
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
    status = trader.get_automation_status(auto_squareoff_past_3pm=False)
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

    # 3. Price drops to +0.8% profit for short (price drops to 987.0)
    # Trailing SL should lower below entry to lock in cost-guaranteed profit
    updates = trader.monitor_and_update_trailing_sl(current_prices={"TATAMOTORS": 987.0})
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





