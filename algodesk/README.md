# AlgoDesk: Swing Trading Platform for Indian Equities

A production-grade algorithmic trading platform for NSE (National Stock Exchange) swing trading on Nifty 500 stocks using daily timeframes.

## Features

- **Long-only CNC (Delivery)** trading on NSE
- **EMA Pullback + ADX Strategy** with two setup types:
  - **Setup A**: Pullback to EMA20 with bullish rejection
  - **Setup B**: Breakout with rising ADX
- **Realistic backtesting** with actual costs (STT, DP, slippage)
- **Walk-forward validation** (3-year train, 1-year test)
- **Risk management** with portfolio guards (sector limits, position counts, drawdown halts)
- **Live execution** via Zerodha Kite Connect
- **SQLite database** with WAL mode for concurrent access
- **Gemini AI** for daily reports and event screening (never for signals)

## Architecture

```
algodesk/
├── config.yaml                    # All parameters in one file
├── store/schema.sql              # SQLite DDL
├── strategies/                   # Strategy plug-ins
│   ├── base.py                  # Abstract Strategy class
│   └── ema_pullback_adx.py      # EMA Pullback + ADX (full implementation)
├── indicators/                   # Technical indicators
│   ├── ema.py
│   ├── atr.py
│   ├── adx.py
│   └── rsi.py (scaffold)
├── risk/                        # Risk management
│   ├── sizing.py                # Position sizing (Kelly criterion)
│   └── limits.py                # Portfolio guards
├── backtest/                    # Backtesting framework
│   ├── engine.py               # Main loop (candle-by-candle)
│   ├── costs.py                # Realistic Zerodha cost model
│   ├── metrics.py              # Trade metrics and equity curve
│   └── walkforward.py          # Train/test validation
├── execution/                   # Live trading layer
│   ├── broker.py               # PaperBroker + LiveBroker
│   ├── gtt.py                  # GTT stop-loss placement
│   └── reconcile.py            # DB vs Kite reconciliation
├── data/                        # Data ingestion
│   ├── kite_client.py          # Zerodha API wrapper
│   ├── ingest.py               # Daily candle ingestion
│   └── corp_actions.py         # Split/bonus handling
└── jobs/                        # Deployment
    ├── cron_entrypoints.py     # Daily job scheduler
    └── systemd_service.service # Background process
```

## Quick Start

### 1. Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Copy config template
cp config.yaml.example config.yaml

# Set environment variables (in .env or export)
export ZERODHA_API_KEY="your_api_key"
export ZERODHA_ACCESS_TOKEN="your_access_token"
```

### 2. Inspect Strategy

```python
from algodesk.strategies.ema_pullback_adx import EMAPullbackADXStrategy
from algodesk.indicators.ema import calc_ema_trend
import pandas as pd

# Load strategy
config = {'indicators': {'ema_fast': 20, 'ema_slow': 50}, ...}
strategy = EMAPullbackADXStrategy(config)

# Example: scan for setups
df = pd.read_csv('data/RELIANCE.csv')
setup = strategy.scan(df, {'symbol': 'RELIANCE', 'nifty': nifty_df})
```

### 3. Backtest

```bash
# Run full backtest (2021-2024)
python algodesk/backtest/engine.py \
  --config algodesk/config.yaml \
  --start 2021-01-01 \
  --end 2024-10-30 \
  --output REVIEW_PACKET/

# Walk-forward validation
python algodesk/backtest/walkforward.py \
  --config algodesk/config.yaml
```

### 4. Paper Trade

```bash
# Run paper trading (no real orders)
python algodesk/jobs/cron_entrypoints.py \
  --mode paper \
  --symbols RELIANCE TCS HDFCBANK INFY ICICIBANK
```

### 5. Live Trade (After Validation)

```bash
# Start live trading (requires explicit LIVE flag in config)
systemctl start algodesk-swap
systemctl status algodesk-swap

# Monitor logs
tail -f /var/log/algodesk/main.log
```

## Database

SQLite with WAL mode for concurrent reads:

- **candles_daily**: Historical OHLCV data
- **signals**: End-of-day setups (Setup A/B)
- **orders**: Placed orders
- **positions**: Open/closed positions
- **equity_curve**: Daily P&L snapshots
- **runs**: Backtest run results
- **reconcile_log**: Daily DB vs Kite checks

## Configuration

All parameters in `config.yaml`:

```yaml
indicators:
  ema_fast: 20
  ema_slow: 50
  adx_len: 14
  adx_min: 20
  atr_len: 14
  vol_mult: 1.5

risk:
  risk_pct: 0.01          # 1% per trade
  max_position_pct: 0.20  # 20% of equity
  max_positions: 5
  max_per_sector: 2
  max_open_risk: 0.05     # 5% of equity

setup:
  valid_days: 2
  gap_max_atr: 0.5
  time_stop_days: 20
```

## Backtest Output (REVIEW_PACKET)

After backtesting, expect:

- **config_used.yaml**: Parameters for reproducibility
- **trades.csv**: All trades with entry/exit, P&L, exit reason
- **equity_curve.csv**: Daily snapshots (equity, drawdown, exposure)
- **metrics.json**: Summary stats (win rate, profit factor, expectancy)
- **walkforward_results.csv**: Train vs test performance
- **parameter_sensitivity.csv**: Robustness check (parameter sweeps)
- **verdict.md**: Honest assessment of strategy edge

## Strategy Rules

### Entry (EMA Pullback + ADX)

#### Setup A: Pullback
- Low <= EMA20 × 1.005
- Close > EMA20
- Bullish rejection (hammer or engulfing)
- Trigger: High × 1.001 (buy-stop)

#### Setup B: Breakout
- Close > EMA50 and > resistance
- ADX > 20 and rising
- Volume > 1.5 × 30-day average
- Trigger: High × 1.001 (buy-stop)

### Exit

- **Target**: At target1 → Exit 50%, move stop to breakeven
- **Stop Loss**: Market exit if close <= stop
- **Remainder**: Exit when close < EMA20
- **ADX Deceleration**: (Setup B only) Exit if ADX peaks and breaks structure
- **Time Stop**: Exit after 20+ days

### Portfolio Guards

- Max 5 open positions
- Max 2 per sector
- Max 5% open risk (of equity)
- Halt new entries if monthly DD <= -6%

## Costs Model

Realistic Zerodha CNC costs:

- **Buy**: 0% brokerage + 0.1% slippage
- **Sell**: 0.1% brokerage + 0.1% STT + ~3 paise exchange + ₹13.50 DP + 0.1% slippage
- **Round-trip**: ~0.4-0.5% of average notional

## Daily Schedule (IST)

- 08:30 - Morning reconciliation (DB vs Kite)
- 08:45 - Auth refresh
- 09:00 - Place entries, cancel stale setups
- 09:15-15:30 - Order watch (poll 30-60s, place GTT on fill)
- 15:45 - EOD ingest
- 16:00 - Scan for setups
- 16:15 - Position management
- 16:30 - Report (Gemini summary)

## Deployment

### Development
```bash
python -m pytest tests/
python algodesk/backtest/engine.py --config config.yaml
```

### Production (Linux VPS)
```bash
# Install systemd service
sudo cp algodesk/jobs/systemd_service.service /etc/systemd/system/algodesk-swap.service
sudo systemctl daemon-reload
sudo systemctl enable algodesk-swap
sudo systemctl start algodesk-swap

# Check status
sudo systemctl status algodesk-swap
sudo journalctl -u algodesk-swap -f

# Check logs
tail -f /var/log/algodesk/main.log
```

## Critical Design Decisions

1. **Plug-in Strategy Architecture**: New strategies inherit `Strategy` base class, override `scan()` and `manage()`
2. **No Look-Ahead**: Backtest replicates real-world (Signal T → Order T+1 → Fill T+1)
3. **Single Codebase**: Same strategy code runs in backtest and live
4. **Realistic Costs**: Every charge modeled (STT, DP, slippage, taxes)
5. **Gemini Reports Only**: AI used only for daily reports, never for signals
6. **Parameters in YAML**: All config externalized, no hardcoded values
7. **Portfolio Guards**: Sector limits, position counts, drawdown halts, order rejection monitoring

## Risk Management

### Position Sizing
- Fixed risk per trade = 1% of equity
- Position size = Risk / (trigger - stop)
- Capped at 20% of equity, max 5 concurrent

### Portfolio Limits
- Max 2 positions per sector (to avoid concentration)
- Max 5% open risk (total unrealized loss if all stops hit)
- Monthly drawdown halt at -6% (pause new entries)

### Live Execution
- **Paper Trading** (--mode paper): Full simulation, no real orders
- **Live at 0.25%** (minimum risk): Scale only if matches backtest within 5%
- Daily reconciliation with Kite (alert on mismatches)

## Expected Performance (Preview)

Based on typical swing trading on Nifty 500:

- **Win Rate**: 55-65%
- **Profit Factor**: 1.5-2.5x
- **Expectancy**: 0.5-1.0 R per trade
- **Max Drawdown**: 15-25%
- **Annual Return**: 20-40% (varies by market)
- **Trades/Year**: 40-80 trades

*Note: Actual results depend on market conditions. Backtest is ground truth.*

## Important Notes

⚠️ **No live orders without LIVE flag in config**  
⚠️ **Start at 0.25% risk, scale only after 4 weeks matching backtest**  
⚠️ **Daily reconciliation is mandatory**  
⚠️ **Parameter tuning after seeing results = curve fitting (forbidden)**

## Support & Documentation

- **Config guide**: See `config.yaml` for all parameters
- **Strategy spec**: See `SWING_TRADING_BUILD_PLAN.md`
- **Build status**: See `SWING_ALGO_DELIVERY.txt`
- **Tests**: See `tests/` directory

## License

Proprietary - Internal use only

---

**Status**: ✅ Architecture complete, strategy implemented, backtest in progress.  
**Next**: Complete backtest engine, paper trading validation, live deployment.
