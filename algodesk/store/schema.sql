-- Swing Trading Algo Platform - Schema
-- SQLite with WAL mode for concurrent access

PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;

-- Daily candles (cached from Kite)
CREATE TABLE IF NOT EXISTS candles_daily (
    symbol TEXT NOT NULL,
    date TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume INTEGER NOT NULL,
    oi INTEGER DEFAULT 0,
    adjusted_close REAL,  -- post-split/bonus
    split_factor REAL DEFAULT 1.0,
    bonus_factor REAL DEFAULT 1.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, date)
);

CREATE INDEX idx_candles_symbol_date ON candles_daily(symbol, date DESC);
CREATE INDEX idx_candles_date ON candles_daily(date);

-- Dividend/split/bonus events
CREATE TABLE IF NOT EXISTS corporate_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    ex_date TEXT NOT NULL,
    action_type TEXT NOT NULL,  -- split, dividend, bonus, rights
    factor REAL NOT NULL,  -- split ratio, dividend amount, etc.
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(symbol, ex_date, action_type)
);

-- Setup signals (end-of-day scans)
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    kind TEXT NOT NULL,  -- 'A_pullback', 'B_breakout'
    trigger REAL NOT NULL,
    stop REAL NOT NULL,
    target1 REAL NOT NULL,
    risk REAL GENERATED ALWAYS AS (trigger - stop) STORED,
    rr REAL GENERATED ALWAYS AS ((target1 - trigger) / (trigger - stop)) STORED,
    ema20 REAL NOT NULL,
    ema50 REAL NOT NULL,
    adx REAL,
    atr REAL NOT NULL,
    volume_ratio REAL,
    meta_json TEXT,  -- candle pattern, support/resistance details
    valid_until TEXT NOT NULL,  -- SETUP_VALID_DAYS
    status TEXT DEFAULT 'open',  -- open, filled, cancelled, expired
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(date, symbol, kind)
);

CREATE INDEX idx_signals_status_date ON signals(status, valid_until);
CREATE INDEX idx_signals_symbol ON signals(symbol);

-- Orders placed
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id INTEGER NOT NULL,
    kite_order_id TEXT,
    symbol TEXT NOT NULL,
    type TEXT NOT NULL,  -- buy_stop, sell, sell_limit
    qty INTEGER NOT NULL,
    price REAL NOT NULL,
    trigger_price REAL,  -- for buy-stop / sell-stop
    status TEXT DEFAULT 'pending',  -- pending, complete, rejected, cancelled
    filled_qty INTEGER DEFAULT 0,
    avg_price REAL,
    reason TEXT,
    placed_at TIMESTAMP,
    filled_at TIMESTAMP,
    cancelled_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (signal_id) REFERENCES signals(id)
);

CREATE INDEX idx_orders_status ON orders(status);
CREATE INDEX idx_orders_symbol_date ON orders(symbol, created_at);

-- Live positions
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    qty INTEGER NOT NULL,
    entry_price REAL NOT NULL,
    entry_date TEXT NOT NULL,
    stop REAL NOT NULL,
    target1 REAL NOT NULL,
    has_partial_exit INTEGER DEFAULT 0,
    partial_qty INTEGER DEFAULT 0,
    partial_price REAL,
    partial_date TEXT,
    exit_price REAL,
    exit_date TEXT,
    exit_reason TEXT,  -- target_hit, stop_hit, time_stop, manual, adx_decel
    pnl_rs REAL,
    pnl_pct REAL,
    opened_at TIMESTAMP,
    closed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (signal_id) REFERENCES signals(id)
);

CREATE INDEX idx_positions_status ON positions(closed_at);
CREATE INDEX idx_positions_symbol ON positions(symbol);

-- Equity curve (daily snapshot)
CREATE TABLE IF NOT EXISTS equity_curve (
    date TEXT PRIMARY KEY,
    equity_rs REAL NOT NULL,
    open_risk_rs REAL,
    exposure_pct REAL,
    num_positions INTEGER DEFAULT 0,
    trades_today INTEGER DEFAULT 0,
    drawdown_pct REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Backtest runs
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy TEXT NOT NULL,  -- 'ema_pullback_adx'
    params_json TEXT NOT NULL,  -- serialized config
    universe TEXT,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    initial_capital REAL NOT NULL,
    final_equity REAL,
    total_return_pct REAL,
    max_drawdown_pct REAL,
    win_rate REAL,
    profit_factor REAL,
    expectancy_r REAL,
    trades_total INTEGER,
    trades_winning INTEGER,
    trades_losing INTEGER,
    avg_win_r REAL,
    avg_loss_r REAL,
    worst_streak INTEGER,
    trades_per_year REAL,
    setup_a_trades INTEGER,
    setup_b_trades INTEGER,
    metrics_json TEXT,  -- full metric dump
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Reconciliation log
CREATE TABLE IF NOT EXISTS reconcile_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    symbol TEXT,
    db_qty INTEGER,
    kite_qty INTEGER,
    status TEXT,  -- 'match', 'mismatch', 'alert'
    message TEXT
);

-- Alerts & events
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    level TEXT NOT NULL,  -- INFO, WARNING, ERROR, CRITICAL
    event TEXT NOT NULL,
    message TEXT,
    action_taken TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_alerts_level_ts ON alerts(level, timestamp DESC);
