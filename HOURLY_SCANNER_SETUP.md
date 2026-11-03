# Hourly NIFTY 500 Scanner with Auto-Entry

## Overview
Scans all NIFTY 500 stocks **every hour** during market hours (9:15 AM - 3:30 PM IST) for EMA Pullback and 52WH Breakout signals, then **automatically enters trades** in paper trading engine.

## What It Does

### Hourly Scans
- **9:30 AM** - First scan after market open
- **10:30 AM** - Mid-morning scan
- **11:30 AM** - Late morning scan
- **12:30 PM** - Lunch hour scan
- **1:30 PM** - Afternoon scan
- **2:30 PM** - Pre-close hour scan
- **3:15 PM** - Final scan before market close

Total: **7 scans per day × 250 trading days/year = 1,750 scans**

### Per Scan
1. **Fetch data** for all 500 NIFTY stocks (10-15 min)
2. **Scan EMA Pullback** - Detect pullback to 20 EMA + ADX > 20
3. **Scan 52WH Breakout** - Detect breakout near 52-week high
4. **Auto-enter** signals with 1% risk per trade
5. **Log all entries** and results

## Capital Allocation

```
Total Capital: ₹250,000
├─ EMA Pullback Engine:    ₹125,000 (53% WR, +770% backtest)
└─ 52WH Breakout Engine:   ₹125,000 (57.9% WR, +180% backtest)
```

## Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Run Single Scan Test
```bash
python scan_nifty500_hourly.py
```

Expected output:
```
NIFTY 500 HOURLY SCANNER - AUTO ENTRY SYSTEM
✅ EMA Engine: ₹125,000
✅ Breakout Engine: ₹125,000
✅ Total Capital: ₹250,000

Starting first scan...
Loaded 500 NIFTY 500 stocks
Scanned 50/500 stocks...
Scanned 100/500 stocks...
...
Scan complete: X signals found from 500 stocks

✅ ENTRY: INFY @ 2850.00 | SL: 2750.00 | TGT: 3050.00 | QTY: 25 | RR: 1.50
✅ ENTRY: TCS @ 3450.50 | SL: 3350.00 | TGT: 3750.00 | QTY: 20 | RR: 1.75
...
```

### 3. Start Hourly Scheduler
```bash
python scheduler_hourly_scan.py
```

This runs forever and automatically scans every hour during market hours.

Expected output:
```
NIFTY 500 HOURLY SCANNER - APScheduler
✅ Scheduler started!
Jobs scheduled:
   - Scan 09:30 AM
   - Scan 10:30 AM
   - Scan 11:30 AM
   - Scan 12:30 PM
   - Scan 1:30 PM
   - Scan 2:30 PM
   - Scan 3:15 PM (Final)

Scheduler running... Press Ctrl+C to stop
```

## Monitoring

### Real-Time Logs
```bash
tail -f algodesk/paper_trading_logs/nifty500_scan.log
tail -f algodesk/paper_trading_logs/scheduler.log
```

### Scan Results
```bash
cat algodesk/paper_trading_logs/hourly_scan_results.json
```

Shows:
- Total scans run
- Signals found
- Entries made
- Current equity in both engines
- Open positions

## Risk Management

### Per Trade
- **Risk**: 1% of engine equity
- **Position size**: Calculated based on stop loss distance
- **Min R:R**: 1.5x (EMA), 1.5x (52WH)
- **Max stop**: 1.5 ATR (EMA), 2.0 ATR (52WH)

### Portfolio Level
- **Max positions**: 5 total (shared across both engines)
- **Max per sector**: 2 positions
- **Total open risk**: ≤ 5% equity
- **Monthly halt**: If drawdown < -6%, stop trading

## Strategy Filters

### EMA Pullback (Setup A)
✅ Pullback to 20 EMA (low ≤ EMA20 × 1.005)
✅ Bullish rejection (hammer or engulfing)
✅ ADX ≥ 20 (trending market)
✅ Min traded value: ₹10 lac (liquid)
✅ Volume ≥ 1.5x average

### 52-Week High Breakout (Setup B)
✅ Price near 52-week high (within 4%)
✅ Close > 52W high pivot
✅ ADX ≥ 20
✅ Volume ≥ 1.5x average
✅ 55-78 RSI range

## Expected Results

### Historical Backtest
- **EMA Pullback**: 1,661 trades, 53% WR, +770% return
- **52WH Breakout**: 285 trades, 57.9% WR, +180% return

### Paper Trading Target (4-8 weeks)
- **Target**: +12% combined (₹30,000 profit)
- **If achieved**: Go-live with real capital on VPS
- **If +8-12%**: Run 2 more weeks
- **If <8%**: Debug and recalibrate

## Deployment

### Local Testing (Dev)
```bash
# Single scan
python scan_nifty500_hourly.py

# Hourly scheduler (foreground)
python scheduler_hourly_scan.py
```

### Production (VPS)
```bash
# Background scheduler with nohup
nohup python scheduler_hourly_scan.py > scheduler.log 2>&1 &

# Or with systemd service
sudo systemctl start algodesk-scanner
```

### Docker
```bash
docker build -f Dockerfile -t algodesk-scanner .
docker run -d --name scanner algodesk-scanner
```

## Troubleshooting

### Scan Times Out
- Check internet connection
- Increase scan timeout in scheduler
- Run fewer stocks first to test

### No Signals Found
- Check if stocks have adequate data (100+ daily bars)
- Verify data is being fetched correctly
- Check market regime (Nifty < 50 EMA = skip)

### Entries Not Made
- Check portfolio limits (max 5 positions)
- Verify risk calculation (1% rule)
- Check margin/equity requirements

## File Structure

```
stock-analyser/
├─ scan_nifty500_hourly.py          ← Main scanner logic
├─ scheduler_hourly_scan.py         ← APScheduler runner
├─ algodesk/
│  ├─ data/
│  │  └─ fetch.py                   ← Data fetching
│  ├─ strategies/
│  │  ├─ ema_pullback_adx.py        ← EMA scan logic
│  │  └─ breakout_52wh.py           ← 52WH scan logic
│  ├─ execution/
│  │  └─ paper_trading.py           ← Trade execution
│  └─ paper_trading_logs/
│     ├─ nifty500_scan.log          ← Scan logs
│     ├─ scheduler.log              ← Scheduler logs
│     └─ hourly_scan_results.json    ← Results summary
└─ ind_nifty500list.csv             ← 500 stock list
```

## Next Steps

1. **Run test scan**: `python scan_nifty500_hourly.py`
2. **Verify entry logic**: Check if trades are created
3. **Start scheduler**: `python scheduler_hourly_scan.py`
4. **Monitor daily**: Watch equity growth
5. **Target**: +12% in 4-8 weeks
6. **Go-live**: Deploy on VPS with real capital

## Questions?

Check logs:
- Scan issues: `algodesk/paper_trading_logs/nifty500_scan.log`
- Scheduler issues: `algodesk/paper_trading_logs/scheduler.log`
- Recent results: `algodesk/paper_trading_logs/hourly_scan_results.json`
