"""
Unit tests for AlgoDesk Database Schemas & Models.
"""

from datetime import datetime
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.algodesk.db.base import Base, init_db
from src.algodesk.db.models import (
    Instrument,
    CandleBar,
    StrategyState,
    OrderRecord,
    TradeRecord,
    AITag,
    AuditLog,
)


@pytest.fixture
def memory_db():
    """In-memory SQLite database for isolated unit testing."""
    test_engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    init_db(test_engine)
    TestingSessionLocal = sessionmaker(bind=test_engine)
    session = TestingSessionLocal()
    yield session
    session.close()


def test_instrument_model(memory_db):
    """Tests creating and querying instruments."""
    inst = Instrument(
        instrument_token=256265,
        tradingsymbol="INFY",
        name="INFOSYS LTD",
        exchange="NSE",
        segment="NSE",
        tick_size=0.05,
        lot_size=1,
    )
    memory_db.add(inst)
    memory_db.commit()

    saved = memory_db.query(Instrument).filter_by(tradingsymbol="INFY").first()
    assert saved is not None
    assert saved.instrument_token == 256265
    assert saved.is_active is True


def test_order_and_trade_records(memory_db):
    """Tests order idempotency tag and trade record audit ledger."""
    order = OrderRecord(
        intent_id="intent-1234",
        tag="algo_orb_001",
        strategy_name="orb_stocks_in_play",
        symbol="RELIANCE",
        side="BUY",
        qty=50,
        order_type="MARKET",
        price=2800.0,
        status="COMPLETE",
        filled_qty=50,
        average_price=2800.25,
    )
    memory_db.add(order)
    memory_db.commit()

    saved_order = memory_db.query(OrderRecord).filter_by(tag="algo_orb_001").first()
    assert saved_order is not None
    assert saved_order.intent_id == "intent-1234"

    trade = TradeRecord(
        trade_id="trade-xyz-01",
        strategy_name="orb_stocks_in_play",
        symbol="RELIANCE",
        side="BUY",
        qty=50,
        entry_time=datetime(2026, 1, 15, 9, 20),
        entry_price=2800.25,
        exit_time=datetime(2026, 1, 15, 15, 10),
        exit_price=2820.00,
        gross_pnl=987.50,
        statutory_costs=42.10,
        slippage_cost=28.00,
        total_costs=70.10,
        net_pnl=917.40,
        exit_reason="TIME_EXIT",
    )
    memory_db.add(trade)
    memory_db.commit()

    saved_trade = memory_db.query(TradeRecord).filter_by(trade_id="trade-xyz-01").first()
    assert saved_trade is not None
    assert saved_trade.net_pnl == 917.40


def test_ai_tag_point_in_time_timestamp(memory_db):
    """
    CRITICAL: Validates that AITag contains a distinct created_at timestamp
    for point-in-time enforcement during historical simulations.
    """
    src_ts = datetime(2026, 1, 15, 9, 0)
    tag = AITag(
        symbol="TCS",
        headline="TCS reports strong Q3 results, margins expand",
        event_type="EARNINGS",
        sentiment="POSITIVE",
        confidence=0.92,
        source_timestamp=src_ts,
    )
    memory_db.add(tag)
    memory_db.commit()

    saved_tag = memory_db.query(AITag).filter_by(symbol="TCS").first()
    assert saved_tag is not None
    assert saved_tag.created_at is not None
    assert saved_tag.source_timestamp == src_ts
