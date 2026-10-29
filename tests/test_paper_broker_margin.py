"""
Unit tests for PaperBroker Zerodha margin rules and opportunity recycling.
"""

import pytest
from src.algodesk.execution.paper_broker import PaperBroker, Position


def test_paper_broker_zerodha_margin_lifecycle_and_recycling():
    """
    Verifies:
    1. Margin blocked on order open per leverage (5x MIS).
    2. Available margin updates dynamically.
    3. Rejection when order exceeds available margin.
    4. On close, 100% of blocked margin is unblocked + net P&L credited.
    5. Opportunity recycling callback triggers immediately.
    """
    broker = PaperBroker(initial_capital=50000.0, leverage=5.0)

    # 1. Check initial capital and buying power
    assert broker.available_margin == 50000.0
    assert broker.total_blocked_margin == 0.0
    assert broker.buying_power == 250000.0

    # 2. Open BUY position for INFY: 20 shares @ Rs 1,500
    # Exposure ~ Rs 30,000. 5x MIS Margin required ~ Rs 6,000 (plus slight slippage)
    order1 = broker.execute_order(
        symbol="INFY",
        side="BUY",
        qty=20,
        price=1500.0,
        stop_loss=1485.0,
        target=1530.0
    )

    assert order1["status"] == "COMPLETE"
    assert "INFY" in broker.positions
    pos = broker.positions["INFY"]
    assert pos.qty == 20
    assert 6000 <= pos.blocked_margin <= 6005
    initial_blocked = pos.blocked_margin

    # Verify margin deduction
    assert broker.total_blocked_margin == initial_blocked
    assert broker.available_margin == round(50000.0 - initial_blocked, 2)
    assert broker.buying_power == round(broker.available_margin * 5.0, 2)

    # 3. Test Margin Gate: Attempt order requiring > Rs 44,000 margin
    # 200 shares @ Rs 1,500 = Rs 300,000 exposure -> Rs 60,000 margin required
    order_huge = broker.execute_order(
        symbol="RELIANCE",
        side="BUY",
        qty=200,
        price=1500.0
    )
    assert order_huge["status"] == "REJECTED"
    assert "Insufficient margin" in order_huge["reason"]

    # 4. Attach recycling callback
    callback_events = []
    broker.on_trade_closed_callbacks.append(
        lambda sym, credit: callback_events.append({"symbol": sym, "credit": credit})
    )

    # 5. Close INFY position at target: Rs 1,530 (+2% gain)
    # Gross P&L = 20 * (1530 - 1500) = Rs 600
    order_exit = broker.execute_order(
        symbol="INFY",
        side="SELL",
        qty=20,
        price=1530.0
    )
    assert order_exit["status"] == "COMPLETE"
    assert "INFY" not in broker.positions
    assert broker.total_blocked_margin == 0.0

    # Zerodha terms: Blocked margin is fully restored + net P&L credited
    assert len(broker.trades_history) == 1
    trade = broker.trades_history[0]
    assert trade["symbol"] == "INFY"
    assert trade["gross_pnl"] > 0.0
    assert trade["net_pnl"] > 0.0
    assert trade["unblocked_margin"] == initial_blocked
    assert trade["margin_credited"] == round(initial_blocked + trade["net_pnl"], 2)

    # Cash and available margin now reflect initial capital + net realized profit
    expected_available = round(50000.0 + trade["net_pnl"], 2)
    assert broker.available_margin == expected_available
    assert broker.cash == expected_available

    # 6. Verify recycling callback was immediately triggered
    assert len(callback_events) == 1
    assert callback_events[0]["symbol"] == "INFY"
    assert callback_events[0]["credit"] == trade["margin_credited"]

    # 7. Test that new opportunity can immediately utilize the freed capital
    order2 = broker.execute_order(
        symbol="TCS",
        side="BUY",
        qty=10,
        price=3500.0
    )
    assert order2["status"] == "COMPLETE"
    assert "TCS" in broker.positions
    assert 7000 <= broker.positions["TCS"].blocked_margin <= 7015
