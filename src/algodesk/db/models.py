"""
SQLAlchemy ORM Models for AlgoDesk.

Defines database schemas for:
- Instruments master
- Candles & Historical Bars
- Data quality audits
- Strategy states & daily live confirmation gates
- Orders & Trades audit ledger
- Point-in-time AI tags & reviews
- System audit log
"""

from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    Integer,
    BigInteger,
    String,
    Float,
    Boolean,
    DateTime,
    Text,
    JSON,
    Index,
)
from src.algodesk.db.base import Base

# Universal primary key type: BigInteger on PostgreSQL, Integer on SQLite for rowid autoincrement
PK_TYPE = BigInteger().with_variant(Integer, "sqlite")


def utc_now():
    return datetime.now(timezone.utc)


class Instrument(Base):
    """NSE Cash Equities Instrument Master Cache."""
    __tablename__ = "instruments"

    id = Column(PK_TYPE, primary_key=True, autoincrement=True)
    instrument_token = Column(BigInteger, unique=True, nullable=False, index=True)
    tradingsymbol = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(256), nullable=True)
    exchange = Column(String(16), default="NSE", nullable=False)
    segment = Column(String(16), default="NSE", nullable=False)
    tick_size = Column(Float, default=0.05, nullable=False)
    lot_size = Column(Integer, default=1, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)


class CandleBar(Base):
    """Intraday OHLCV Candle Bars."""
    __tablename__ = "candle_bars"

    id = Column(PK_TYPE, primary_key=True, autoincrement=True)
    symbol = Column(String(64), nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    timeframe = Column(String(8), default="5m", nullable=False)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(BigInteger, nullable=False)
    oi = Column(BigInteger, default=0, nullable=False)

    __table_args__ = (
        Index("idx_candle_sym_ts_tf", "symbol", "timeframe", "timestamp", unique=True),
    )


class DataQualityLog(Base):
    """Audit log of data hygiene anomalies, gaps, and suspected corporate actions."""
    __tablename__ = "data_quality_logs"

    id = Column(PK_TYPE, primary_key=True, autoincrement=True)
    symbol = Column(String(64), nullable=False, index=True)
    date = Column(DateTime, nullable=True)
    check_type = Column(String(64), nullable=False) # "LARGE_RETURN_SPLIT", "GAP", "DUPLICATE"
    severity = Column(String(16), default="WARNING") # "INFO", "WARNING", "CRITICAL"
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utc_now)


class StrategyState(Base):
    """Persistent state, active execution mode, and daily live confirmation status."""
    __tablename__ = "strategy_states"

    id = Column(PK_TYPE, primary_key=True, autoincrement=True)
    name = Column(String(64), unique=True, nullable=False, index=True)
    mode = Column(String(16), default="PAPER", nullable=False) # "BACKTEST", "PAPER", "LIVE"
    is_enabled = Column(Boolean, default=True, nullable=False)
    live_enabled = Column(Boolean, default=False, nullable=False) # From YAML
    daily_confirmed_at = Column(DateTime, nullable=True)         # Must match today's date for LIVE
    parameters = Column(JSON, default=dict)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)


class OrderRecord(Base):
    """Idempotent order ledger for Paper and Live execution."""
    __tablename__ = "orders"

    id = Column(PK_TYPE, primary_key=True, autoincrement=True)
    intent_id = Column(String(64), unique=True, nullable=False, index=True) # UUID from Strategy
    tag = Column(String(32), unique=True, nullable=False, index=True)       # Broker order tag
    strategy_name = Column(String(64), nullable=False, index=True)
    symbol = Column(String(64), nullable=False, index=True)
    side = Column(String(8), nullable=False)                                # "BUY", "SELL"
    qty = Column(Integer, nullable=False)
    order_type = Column(String(16), nullable=False)                        # "MARKET", "LIMIT", "SL"
    price = Column(Float, nullable=True)
    trigger_price = Column(Float, nullable=True)
    status = Column(String(32), default="PENDING", nullable=False)          # "SUBMITTED", "COMPLETE", "REJECTED"
    kite_order_id = Column(String(64), nullable=True, index=True)
    filled_qty = Column(Integer, default=0, nullable=False)
    average_price = Column(Float, default=0.0, nullable=False)
    rejection_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)


class TradeRecord(Base):
    """Executed roundtrip trade ledger."""
    __tablename__ = "trades"

    id = Column(PK_TYPE, primary_key=True, autoincrement=True)
    trade_id = Column(String(64), unique=True, nullable=False, index=True)
    strategy_name = Column(String(64), nullable=False, index=True)
    symbol = Column(String(64), nullable=False, index=True)
    side = Column(String(8), nullable=False)
    qty = Column(Integer, nullable=False)
    entry_time = Column(DateTime, nullable=False)
    entry_price = Column(Float, nullable=False)
    exit_time = Column(DateTime, nullable=True)
    exit_price = Column(Float, nullable=True)
    gross_pnl = Column(Float, default=0.0)
    statutory_costs = Column(Float, default=0.0)
    slippage_cost = Column(Float, default=0.0)
    total_costs = Column(Float, default=0.0)
    net_pnl = Column(Float, default=0.0)
    exit_reason = Column(String(64), nullable=True) # "STOP_LOSS", "TIME_EXIT", "KILL_SWITCH"
    created_at = Column(DateTime, default=utc_now)


class AITag(Base):
    """
    Point-in-Time AI News & Announcement Sentiment Tags.
    CRITICAL: created_at represents the exact timestamp this tag entered the database.
    Backtests can ONLY access tags where created_at <= current_bar_time.
    """
    __tablename__ = "ai_tags"

    id = Column(PK_TYPE, primary_key=True, autoincrement=True)
    symbol = Column(String(64), nullable=False, index=True)
    headline = Column(Text, nullable=False)
    event_type = Column(String(64), nullable=True)
    sentiment = Column(String(16), nullable=False) # "POSITIVE", "NEGATIVE", "NEUTRAL"
    relevance = Column(Float, default=1.0)
    confidence = Column(Float, default=1.0)
    source_timestamp = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False, index=True)


class AIReview(Base):
    """Daily End-of-Day Quant Performance and Trade Analysis by Gemini."""
    __tablename__ = "ai_reviews"

    id = Column(PK_TYPE, primary_key=True, autoincrement=True)
    review_date = Column(DateTime, unique=True, nullable=False, index=True)
    summary = Column(Text, nullable=False)
    recurring_patterns = Column(JSON, default=list)
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    created_at = Column(DateTime, default=utc_now)


class AuditLog(Base):
    """Immutable audit trail for parameter changes, manual overrides, and kill-switch activations."""
    __tablename__ = "audit_logs"

    id = Column(PK_TYPE, primary_key=True, autoincrement=True)
    action = Column(String(64), nullable=False)
    actor = Column(String(64), default="system", nullable=False)
    details = Column(JSON, default=dict)
    created_at = Column(DateTime, default=utc_now, index=True)
