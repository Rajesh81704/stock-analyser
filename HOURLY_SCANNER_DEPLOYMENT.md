# Hourly NIFTY 500 Scanner - Deployment Guide

## ✅ SYSTEM READY

Your hourly NIFTY 500 scanner with automatic entry system is **fully built and tested**.

**Test Results: 8/8 systems operational** ✅

```
✅ PASS - Imports (all strategies & engines)
✅ PASS - Paper Trading Engines (₹250K capital)
✅ PASS - Strategies (EMA Pullback + 52WH Breakout)
✅ PASS - Data Fetching (live market data)
✅ PASS - NIFTY 500 List (501 stocks loaded)
✅ PASS - Scanner Initialization
✅ PASS - Single Stock Scan (signal detection works)
✅ PASS - Scheduler (APScheduler configured)
```

---

## 🚀 QUICK START

### One Command to Start Everything

```bash
./START_HOURLY_SCANNER.sh
```

This will:
1. Check Python & dependencies
2. Run pre-flight tests
3. Start hourly scheduler
4. Begin scanning every hour during market hours

---

## 📋 WHAT HAPPENS EACH HOUR

**Every hour during market hours (9:30 AM - 3:15 PM IST), the scanner:**

1. **Fetches daily data** for 501 NIFTY stocks (parallel processing)
2. **Scans for EMA Pullback signals**
   - Pullback to 20 EMA + ADX > 20
   - Bullish rejection (hammer or engulfing)
   - Min R:R 1.5x
   - Max stop: 1.5 × ATR (TIGHT)

3. **Scans for 52WH Breakout signals**
   - Price near 52-week high (within 4%)
   - ADX > 20
   - Volume ≥ 1.5x average
   - Min R:R 1.5x

4. **Auto-enters trades**
   - EMA signals → EMA engine (₹125K)
   - 52WH signals → Breakout engine (₹125K)
   - Risk: 1% of engine equity per trade
   - Logs all entries

5. **Saves results**
   - Entry logs
   - Equity tracking
   - Signal history
   - Trade statistics

---

## 📊 SCAN SCHEDULE

```
Monday - Friday (Market Days Only)

09:30 AM  ← Scan 1 (after market open 9:15)
10:30 AM  ← Scan 2
11:30 AM  ← Scan 3
12:30 PM  ← Scan 4 (lunch hour)
01:30 PM  ← Scan 5 (afternoon)
02:30 PM  ← Scan 6 (pre-close hour)
03:15 PM  ← Scan 7 (final scan before 3:30 close)

Total: 7 scans/day × 250 trading days/year
     = 1,750 scans annually
     = 875,000+ stock scans/year
```

---

## 💰 CAPITAL ALLOCATION

```
Total Capital: ₹250,000
├─ EMA Pullback Engine: ₹125,000
│  ├─ Historical: 1,661 trades, 53% WR, +770% return
│  ├─ Hold period: 2-5 days typical
│  └─ Strategy: Pullback to 20 EMA + ADX
│
└─ 52WH Breakout Engine: ₹125,000
   ├─ Projected: 57.9% WR, +180% backtest return
   ├─ Hold period: 5-30 days typical
   └─ Strategy: Breakout near 52-week high
```

---

## 🎯 VALIDATION TARGET (4-8 Weeks)

**Validation Gate: +12% combined return**

- If achieved in 4-8 weeks → **GO-LIVE** ✅
- If +8-12% → Run 2 more weeks
- If <8% → Debug & recalibrate

**Expected monthly returns:** ~3% if target tracking

---

## 📁 FILE STRUCTURE

```
stock-analyser/
├─ START_HOURLY_SCANNER.sh          ← Run this to start
├─ scheduler_hourly_scan.py         ← Main scheduler (hourly jobs)
├─ scan_nifty500_hourly.py          ← Scanner logic
├─ test_hourly_scanner.py           ← Pre-flight tests
│
├─ algodesk/
│  ├─ data/
│  │  ├─ __init__.py
│  │  └─ fetch.py                   ← Data fetching (yfinance + local cache)
│  │
│  ├─ strategies/
│  │  ├─ ema_pullback_adx.py        ← EMA Pullback scanner
│  │  └─ breakout_52wh.py           ← 52WH Breakout scanner
│  │
│  ├─ execution/
│  │  └─ paper_trading.py           ← Trade execution engine
│  │
│  └─ paper_trading_logs/
│     ├─ nifty500_scan.log          ← All scans logged
│     ├─ scheduler.log              ← Scheduler activity
│     ├─ hourly_scan_results.json    ← Latest results summary
│     ├─ state.json                 ← Current equity & positions
│     └─ execution_log.json         ← All entries/exits
│
├─ data/
│  ├─ INFY.csv                      ← Local cache (faster)
│  ├─ TCS.csv
│  ├─ ... (500+ stocks)
│  └─ *.parquet                     ← Parquet format
│
└─ ind_nifty500list.csv             ← 501 NIFTY stocks to scan
```

---

## 🔍 MONITORING

### Check Scanner Status
```bash
# Real-time log tail
tail -f algodesk/paper_trading_logs/nifty500_scan.log

# Scheduler activity
tail -f algodesk/paper_trading_logs/scheduler.log
```

### View Latest Results
```bash
# Pretty-print results
cat algodesk/paper_trading_logs/hourly_scan_results.json | python3 -m json.tool

# Or in editor
code algodesk/paper_trading_logs/hourly_scan_results.json
```

### Check Current Equity
```bash
# View state
cat algodesk/paper_trading_logs/state.json | python3 -m json.tool
```

### View All Entries
```bash
# Execution log
cat algodesk/paper_trading_logs/execution_log.json | python3 -m json.tool | head -50
```

---

## 📈 EXPECTED OUTPUT

After first scan, you'll see:

```
Starting first scan...
Loaded 501 NIFTY 500 stocks
Scanned 50/501 stocks...
Scanned 100/501 stocks...
...
Scan complete: 8 signals found from 501 stocks

✅ ENTRY: INFY @ 2850.00 | SL: 2750.00 | TGT: 3050.00 | QTY: 25 | RR: 1.50
✅ ENTRY: TCS @ 3450.50 | SL: 3350.00 | TGT: 3750.00 | QTY: 20 | RR: 1.75
✅ ENTRY: WIPRO @ 450.25 | SL: 425.00 | TGT: 525.00 | QTY: 150 | RR: 2.00

Scanner Stats:
  - Total Scans: 1
  - Total Signals: 8
  - Total Entries: 3
  - EMA Equity: ₹124,200 (↓ due to open positions)
  - Breakout Equity: ₹125,000
  - Total Equity: ₹249,200
  - Open Positions: 3
```

---

## ⚙️ CONFIGURATION

All configs are in the scanner files:

### algodesk/strategies/ema_pullback_adx.py (Line 72)
```python
'max_stop_atr': 1.5,  # TIGHT stop loss (was 2.5)
```

### scheduler_hourly_scan.py
```python
# Jobs scheduled for these times:
scan_09_30   # 9:30 AM IST
scan_10_30   # 10:30 AM IST
scan_11_30   # 11:30 AM IST
scan_12_30   # 12:30 PM IST
scan_13_30   # 1:30 PM IST
scan_14_30   # 2:30 PM IST
scan_15_15   # 3:15 PM IST (final)
```

To change times, edit scheduler_hourly_scan.py and restart.

---

## 🛑 STOP/START

### Stop the Scanner
```bash
# Press Ctrl+C in the terminal running the scanner
# Or from another terminal:
pkill -f scheduler_hourly_scan.py
```

### Start Again
```bash
./START_HOURLY_SCANNER.sh
```

### Run in Background (Optional)
```bash
# With nohup (process runs even if terminal closes)
nohup python3 scheduler_hourly_scan.py > scheduler.log 2>&1 &

# Check it's running
ps aux | grep scheduler_hourly_scan

# View logs
tail -f scheduler.log
```

### Docker (Optional - for production/VPS)
```bash
docker build -f Dockerfile -t algodesk-scanner .
docker run -d \
  --name scanner \
  -v /path/to/data:/app/data \
  -v /path/to/logs:/app/algodesk/paper_trading_logs \
  algodesk-scanner
```

---

## 🔐 RISK MANAGEMENT

### Per Trade
- **Risk**: 1% of engine equity
- **Position sizing**: Automatic (calculated from stop loss)
- **Min R:R**: 1.5x required
- **Max stop**: 1.5 ATR (EMA), 2.0 ATR (52WH)

### Portfolio Level
- **Max positions**: 5 total (shared across both engines)
- **Max per sector**: 2 positions (simplified limit)
- **Total open risk**: ≤ 5% equity
- **Monthly halt**: Stops trading if monthly loss > -6%

### Automated Safeguards
- Position size will be limited if equity drops too low
- No entry if portfolio is at max 5 positions
- Exits triggered at stop loss (hardcoded in engine)
- Daily reconciliation checks equity consistency

---

## 🐛 TROUBLESHOOTING

### Scanner won't start
```bash
# Check Python version
python3 --version  # Should be 3.7+

# Check dependencies
python3 test_hourly_scanner.py

# If deps missing:
pip install -r requirements.txt
```

### No signals found
- Normal - signals are rare, depends on market conditions
- Scanner is working if no errors in logs
- Give it 2-3 scans minimum before judging

### Scans taking too long (>15 min)
- First scan is slower (data loading)
- Subsequent scans faster (caching)
- If consistently >20 min, reduce stock list or check internet

### Equity not updating
- Check `algodesk/paper_trading_logs/state.json`
- Verify entries are in execution_log.json
- Check for errors in nifty500_scan.log

### Memory usage high
- Normal for 501 stocks + indicators
- Each scan loads ~100 bars × 5 columns × 501 stocks
- ~25MB typical memory usage

---

## 📊 DAILY CHECKLIST

After starting scanner:

```
□ Scan 9:30 AM: Check for first signals
□ Scan 10:30 AM: Verify entries logged
□ Midday: Spot-check equity growth
□ Scan 3:15 PM: Final close check

Weekly:
□ Review hourly_scan_results.json
□ Check total signals found
□ Verify win rate tracking
□ Confirm equity growing toward +12% target
```

---

## 🎯 SUCCESS CRITERIA

**Week 1 Target**: +1.5% (₹3,750 profit)
**Week 2-4 Target**: +3% cumulative (₹7,500 profit)
**Week 4-8 Target**: +12% cumulative (₹30,000 profit)

If hitting these, you're on track for go-live.

---

## 🚀 NEXT STEPS

1. **Start scanner**: `./START_HOURLY_SCANNER.sh`
2. **Monitor first scan**: Watch for signal detection
3. **Daily reviews**: Check equity growth
4. **Weekly reports**: Export trades.csv + analyze
5. **Week 4**: Evaluate go-live decision

---

## 📞 SUPPORT

### Common Issues
- Check logs: `algodesk/paper_trading_logs/`
- Run tests: `python3 test_hourly_scanner.py`
- Review code: Strategy files have inline comments

### System Status
- Logs written to: `algodesk/paper_trading_logs/`
- Results saved to: `algodesk/paper_trading_logs/hourly_scan_results.json`
- State tracking: `algodesk/paper_trading_logs/state.json`
- All entries logged: `algodesk/paper_trading_logs/execution_log.json`

---

## 🎉 YOU'RE READY!

**The system is fully operational and ready to start scanning.**

Just run:
```bash
./START_HOURLY_SCANNER.sh
```

It will automatically scan every hour and enter trades when signals are found.

Good luck! 🚀
