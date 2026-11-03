# 🚀 Hourly NIFTY 500 Scanner - README

**Status:** ✅ READY FOR DEPLOYMENT  
**Build Date:** November 3, 2026  
**Tests Passing:** 8/8 ✅

---

## START NOW

```bash
./START_HOURLY_SCANNER.sh
```

That's it. Scanner will run every hour and auto-enter trades when signals found.

---

## WHAT IT DOES

- **Scans 501 NIFTY stocks** every hour (9:30 AM - 3:15 PM IST)
- **Finds EMA Pullback signals** (20 EMA + ADX > 20)
- **Finds 52WH Breakout signals** (near 52-week high)
- **Automatically enters trades** with 1% risk per position
- **Tracks equity** in real-time
- **Logs everything** for monitoring

---

## ARCHITECTURE

```
scan_nifty500_hourly.py
    ├─ NIFTY500Scanner class
    ├─ scan_all()          → Scan 501 stocks
    ├─ scan_symbol()       → Scan one stock
    └─ process_signal()    → Auto-enter trade

scheduler_hourly_scan.py
    ├─ HourlyScannnerScheduler
    ├─ 7 hourly jobs
    └─ Result persistence

START_HOURLY_SCANNER.sh
    ├─ Dependency check
    ├─ Pre-flight tests
    └─ Launch scheduler
```

---

## STRATEGIES

### EMA Pullback Strategy
- **Engine Capital:** ₹125,000
- **Historical WR:** 53% (1,661 trades, +770% return)
- **Setup:** Pullback to 20 EMA + ADX > 20 + bullish rejection
- **Stop Loss:** 1.5 × ATR (TIGHT)
- **Hold:** 2-5 days typical

### 52WH Breakout Strategy  
- **Engine Capital:** ₹125,000
- **Projected WR:** 57.9% (+180% backtest)
- **Setup:** Price near 52-week high + volume confirmation
- **Stop Loss:** 2.0 × ATR
- **Hold:** 5-30 days typical

**Total Capital:** ₹250,000

---

## SCAN SCHEDULE

```
Mon-Fri Only (Market Days):

09:30 AM ← Scan 1
10:30 AM ← Scan 2
11:30 AM ← Scan 3
12:30 PM ← Scan 4
01:30 PM ← Scan 5
02:30 PM ← Scan 6
03:15 PM ← Scan 7

7 scans/day × 250 days = 1,750 scans/year
```

---

## VALIDATION TARGET

**4-8 weeks:** Achieve +12% return (₹30,000 profit)

| Outcome | Action |
|---------|--------|
| +12% | ✅ GO-LIVE |
| +8-12% | Run 2 more weeks |
| <8% | Debug & recalibrate |

---

## FILES CREATED

### Core
- `scan_nifty500_hourly.py` - Main scanner (12 KB)
- `scheduler_hourly_scan.py` - APScheduler (7.1 KB)
- `START_HOURLY_SCANNER.sh` - Startup script (3.5 KB)

### Testing
- `test_hourly_scanner.py` - Pre-flight tests (10 KB, 8/8 passing)

### Data
- `algodesk/data/fetch.py` - Data fetching (3.1 KB)

### Documentation
- `HOURLY_SCANNER_SETUP.md` - Setup guide
- `HOURLY_SCANNER_DEPLOYMENT.md` - Deployment details
- `SCANNER_DEPLOYMENT_COMPLETE.txt` - Deployment summary

---

## MONITORING

### Live Logs
```bash
tail -f algodesk/paper_trading_logs/nifty500_scan.log
```

### Latest Results
```bash
cat algodesk/paper_trading_logs/hourly_scan_results.json | python3 -m json.tool
```

### Current Positions
```bash
cat algodesk/paper_trading_logs/state.json | python3 -m json.tool
```

### All Entries
```bash
cat algodesk/paper_trading_logs/execution_log.json | python3 -m json.tool
```

---

## RISK MANAGEMENT

- **Risk per trade:** 1% of engine equity
- **Max positions:** 5 total (shared across both engines)
- **Max per sector:** 2 positions
- **Min R:R:** 1.5x required
- **Monthly loss halt:** -6% threshold

---

## HOW TO USE

### Start
```bash
./START_HOURLY_SCANNER.sh
```

### Monitor (other terminal)
```bash
tail -f algodesk/paper_trading_logs/nifty500_scan.log
```

### Stop
```bash
# Press Ctrl+C or:
pkill -f scheduler_hourly_scan.py
```

### Restart
```bash
./START_HOURLY_SCANNER.sh
```

---

## EXPECTED OUTPUT

```
Starting scan of 501 stocks...
Scanned 50/501 stocks...
...
Scan complete: 8 signals found from 501 stocks

✅ ENTRY: INFY @ 2850.00 | SL: 2750.00 | TGT: 3050.00 | QTY: 25 | RR: 1.50
✅ ENTRY: TCS @ 3450.50 | SL: 3350.00 | TGT: 3750.00 | QTY: 20 | RR: 1.75
✅ ENTRY: WIPRO @ 450.25 | SL: 425.00 | TGT: 525.00 | QTY: 150 | RR: 2.00

Scan Stats:
  Signals Found: 8
  Entries Made: 3
  EMA Equity: ₹124,200
  Breakout Equity: ₹125,000
  Total Equity: ₹249,200
  Open Positions: 3
```

---

## DAILY ROUTINE

```
Morning:
  ✓ Start scanner: ./START_HOURLY_SCANNER.sh
  ✓ Monitor first scan at 9:30 AM

Throughout Day:
  ✓ Check logs: tail -f algodesk/paper_trading_logs/nifty500_scan.log
  ✓ Spot-check equity

Evening:
  ✓ Review daily results
  ✓ Note any issues
  ✓ Let scanner run (doesn't need input)
```

---

## TROUBLESHOOTING

**Q: Scanner won't start**
- Run: `python3 test_hourly_scanner.py`
- Check: `pip install -r requirements.txt`

**Q: No signals found**
- This is normal - signals are rare
- Give it 2-3 scans before worrying

**Q: Equity not updating**
- Check logs: `tail -f algodesk/paper_trading_logs/nifty500_scan.log`
- Verify state: `cat algodesk/paper_trading_logs/state.json`

**Q: Memory/CPU usage high**
- Normal - scanning 500+ stocks takes resources
- Typical: 25-50 MB memory, 30-60% CPU during scan

---

## DEPLOYMENT FLOW

```
1. START
   ./START_HOURLY_SCANNER.sh
   ↓
2. CHECK DEPENDENCY
   Runs test suite (8/8 passing)
   ↓
3. INITIALIZE
   Loads 501 NIFTY stocks
   Creates engines (₹250K)
   ↓
4. SCHEDULE JOBS
   7 hourly jobs configured
   ↓
5. SCAN & TRADE
   Every hour:
   ├─ Fetch data
   ├─ Scan for signals
   ├─ Auto-enter positions
   └─ Log results
   ↓
6. MONITOR
   Watch: tail -f logs/
   Check: results.json
```

---

## NEXT MILESTONES

| Time | Target | Status |
|------|--------|--------|
| Week 1 | +₹3,750 (1.5%) | Track |
| Week 2 | +₹7,500 (3%) | Track |
| Week 4 | +₹15,000 (6%) | Track |
| Week 8 | +₹30,000 (12%) | 🎯 GO-LIVE |

---

## GO-LIVE PLAN

When you hit +12% target:

1. ✅ Validate results
2. ✅ Deploy to VPS (202.142.101.115)
3. ✅ Switch to live capital
4. ✅ Start with 0.25% risk
5. ✅ Scale to 0.5%, then 1.0%

---

## QUESTIONS?

- **Setup:** See `HOURLY_SCANNER_SETUP.md`
- **Deployment:** See `HOURLY_SCANNER_DEPLOYMENT.md`
- **Details:** See `SCANNER_DEPLOYMENT_COMPLETE.txt`
- **Code:** Check comments in `scan_nifty500_hourly.py`

---

## READY?

```bash
./START_HOURLY_SCANNER.sh
```

🚀 **System is fully operational and ready to trade!**
