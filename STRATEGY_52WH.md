# 52-Week High Breakout Algorithm - Complete Implementation

**Strategy Kind:** `52wh`  
**Timeframe:** Daily (EOD)  
**Position Type:** Long-only, CNC Delivery  
**Universe:** NIFTY 100 (NSE)  
**Capital Model:** 1% risk per trade, max 15% position size, max 5 concurrent

---

## Overview

This strategy captures stocks breaking above their 52-week high with proper trend confirmation, momentum filters, and volume validation. It's designed to catch institutional breakout moves while filtering out false breakouts.

**Key Insight:** Stocks near 52-week highs have positive drift, but false breakouts are common. Volume and trend confirmation are critical.

---

## Parameters

| Parameter | Value | Purpose |
|-----------|-------|---------|
| NEAR_HIGH_PCT | 4% | Filter: stock within 4% of 52W high |
| LOOKBACK | 252 | 52-week lookback period |
| EMA_FAST | 20 | Fast trend EMA |
| EMA_MID | 50 | Mid trend EMA |
| EMA_LONG | 200 | Long trend EMA |
| RSI_LEN | 14 | RSI period |
| RSI_MIN / RSI_MAX | 55 / 78 | Momentum range (avoiding oversold/overbought) |
| ADX_MIN | 20 | Min ADX for trend strength |
| ATR_LEN | 14 | ATR period for volatility |
| VOL_MULT | 1.5x | Volume must be 1.5x 20-day average |
| MIN_AVG_VOLUME | 200k | Minimum daily volume (liquidity) |
| MIN_TRADED_VALUE | ₹10 Cr | Minimum daily traded value |
| MAX_EXTENSION_ATR | 1.0 | Max entry extension from pivot |
| GAP_MAX_ATR | 0.5 | Max gap-up tolerance |
| MAX_STOP_PCT | 7% | Stop loss never wider than 7% |
| FOLLOW_THROUGH_DAYS | 5 | Days to wait for follow-through |
| TIME_STOP_DAYS | 30 | Max hold period |

---

## Strategy Stages

### Stage 1: End-of-Day Watchlist Scan

**Purpose:** Identify stocks ready to break.

**Filters:**
```
Market Regime:  Nifty.close > Nifty.EMA50        # Weak market = skip all
Liquidity:      avg_volume >= 200k AND traded_value >= ₹10Cr
52W High:       pivot = highest high (last 252 days)
Near High:      close >= pivot * (1 - 4%) AND close < pivot
Trend:          close > EMA50 > EMA200           # Uptrend confirmed
Momentum:       55 <= RSI14 <= 78 AND ADX14 >= 20
Relative Str:   3-month return > Nifty 3-month return
Base Coiling:   (high - low, last 10d) <= 3 * ATR  # Tight range
Volume Dry-up:  avg_vol(5d) < avg_vol(50d)      # Bullish squeeze
```

**Output:**
- Add to watchlist if ALL filters pass
- **Trigger Level:** pivot * 1.001 (0.1% above 52W high)
- **Base Low:** lowest low (last 10 days) → Stop structure

---

### Stage 2: Entry Trigger (Breakout Confirmation)

**Daily Mode (Backtest):**
```
Signal Day T:   close > pivot
                volume >= 1.5 * avg_vol20
                close in top 30% of day's range
                (close - pivot) <= 1.0 * ATR

Entry Day T+1:  place buy-stop at high(T) * 1.001
                skip if: open gaps > 0.5*ATR above it
```

**Entry Price:** High of previous day * 1.001

**Validation:**
- Don't chase: entry extension <= 1.0 * ATR from pivot
- Gap-up rejection: ignore if open gaps > 0.5 * ATR above trigger
- Volume confirmation: cumulative volume pace must support 1.5x average

---

### Stage 3: Stop Loss Calculation

**Two Methods (Take Tighter):**

```python
structural_stop = base_low * 0.999      # Support from recent swing low
atr_stop        = entry - 2 * ATR       # Risk management

stop_loss       = max(structural_stop, atr_stop)      # Tighter of two
stop_loss       = min(stop_loss, entry - 1 * ATR)    # Never closer than 1 ATR

# Validate
if (entry - stop_loss) / entry > 7%:
    skip_this_trade()  # Stop too wide
```

**Position Size:**
```python
risk_amount = equity * 1%
qty = floor(risk_amount / (entry - stop_loss))
qty = min(qty, equity * 15% / entry)  # Max position cap
```

---

## Position Management (Daily)

### Exit Triggers (In Priority Order)

1. **Stop Loss Hit**
   - Exit at min(open, stop_loss)
   - Reason: `stop_hit`

2. **Failed Breakout**
   - Exit if 2 consecutive closes below pivot
   - Reason: `failed_breakout`
   - Logic: "Breakout didn't hold support"

3. **Profit Taking at 1R**
   - Move stop to entry (breakeven)
   - Trail remainder using EMA20

4. **Partial Profit Taking at 2R**
   - Exit 1/3 of position at +2R
   - Let remainder run with trailing stop
   - Reason: `profit_taking_2r`

5. **No Follow-Through**
   - After FOLLOW_THROUGH_DAYS (5 days)
   - If price < entry + 0.5R, exit all
   - Reason: `no_follow_through`

6. **Trailing Stop**
   - After stop moved to entry (breakeven)
   - Exit on close < EMA20
   - Reason: `trail_ema20`

7. **Time Stop**
   - Exit after TIME_STOP_DAYS (30 days)
   - Reason: `time_stop`

---

## Portfolio Guards (Shared)

```
✅ Max Risk Management
   - Single position max: equity * 15%
   - Total open risk: <= equity * 5%
   - Max concurrent positions: 5

✅ Sector Limits
   - Max 2 positions per sector
   - Never hold same symbol in multiple strategies

✅ Market Regime
   - Daily loss halt: if month_drawdown <= -6%, stop new entries
   - Nifty filter: if Nifty.close <= Nifty.EMA50, skip entire scan

✅ Reconciliation
   - Halt trading if margin check fails
   - Reconcile every 1 hour during live trading
```

---

## File Locations

**Implementation:**
- Core Strategy: `src/algodesk/strategies/breakout_52wh.py`
- Class: `BreakoutHighStrategy`
- Methods: `scan()`, `calculate_entry_stop()`, `manage()`

**Backtest:**
- Dual Comparison: `backtest_swing_dual_strategy.py`
  - Compares 52WH vs EMA Pullback
  - Side-by-side metrics, drawdown analysis

**Configuration:**
- Auto-loaded via: `src/algodesk/strategies/registry.py`
- No manual registration needed

---

## Running the Strategy

### 1. Single Strategy Backtest
```bash
python backtest_swing_dual_strategy.py
```
Output: Win rate, return %, max drawdown, trade-by-trade log

### 2. Register in Live Trading
```python
from src.algodesk.strategies.breakout_52wh import BreakoutHighStrategy

strat = BreakoutHighStrategy(config={
    'near_high_pct': 0.04,
    'rsi_min': 55,
    'rsi_max': 78,
})

# Scan
signal = strat.scan(df, context)

# Manage
exit_action = strat.manage(position, df, context)
```

### 3. Paper Trading
```bash
python algodesk/jobs/launch_paper_trading.py
# Then feed signals to: panel.process_signal(signal_dict)
```

---

## Risk Analysis

### False Breakout Mitigation
- **2-Day Hold Rule:** Exit on 2 consecutive closes below pivot
- **No Follow-Through:** Exit if no upside after 5 days
- **Volume Filter:** 1.5x average volume on entry day

### Market Regime Protection
- **Nifty Filter:** Skip entire scan if Nifty.close <= Nifty.EMA50
- **Drawdown Halt:** Stop new entries if monthly loss > -6%

### Position Sizing
- Never risk > 1% per trade
- Never position > 15% of equity
- Max 5 concurrent = safety buffer

---

## Comparison with EMA Pullback Strategy

| Aspect | 52-Week High | EMA Pullback |
|--------|-------------|--------------|
| **Setup Type** | Breakout | Pullback |
| **Entry Signal** | Above 52W pivot | EMA20 bounce |
| **Volume Filter** | 1.5x average | Optional |
| **Stop Loss** | 2 * ATR (structural) | 1 * ATR (ATR-based) |
| **Exit Logic** | Failed breakout (2-day) | Close < EMA20 |
| **Hold Period** | 5-30 days (typical) | 2-5 days (typical) |
| **Win Rate** | TBD (backtest) | ~53% historical |
| **Best For** | Trending markets | Mean-reversion + trend |

---

## Expected Performance (Estimates)

**Based on Educational Materials:**
- **Win Rate:** 55-65% (volume-confirmed breakouts higher)
- **Average Win:** 2-3x risk
- **Average Loss:** -1.0x risk
- **Profit Factor:** 2.0-2.5x
- **Monthly Return:** +2% to +5%
- **Max Drawdown:** -8% to -15%

**Notes:**
- Survivorship bias: historical Nifty 100 better than live data
- False breakouts spike in choppy markets (apply Nifty filter!)
- Best in trending markets (Jan-May, Sep-Nov typical)

---

## Known Issues & Solutions

| Issue | Cause | Solution |
|-------|-------|----------|
| False breakouts | Weak market regime | Use Nifty.EMA50 filter |
| Stops hit too often | Too tight 1-ATR rule | Loosen to 1.5 * ATR |
| No follow-through | Weak relative strength | Require 6-month outperformance |
| Gap-down losses | No gap protection | Set GAP_MAX_ATR = 0.3 (strict) |
| Too few trades | Filters too tight | Lower RSI_MIN to 50 |

---

## Next Steps

1. **Backtest both strategies** (run `backtest_swing_dual_strategy.py`)
2. **Compare metrics:** Which has higher Sharpe ratio?
3. **Choose primary strategy** or run both in parallel
4. **Paper trade for 4-8 weeks** with ₹250K capital
5. **Monitor daily:** Win rate, drawdown, risk metrics
6. **Go-live decision:** Only after +12% backtest validation

---

## References

- Upstox Educational Material: 52-week high breakout setup
- TradingView Ideas: Volume confirmation, trailing stops
- NSE Guidelines: Delivery percentage, institutional participation
- Risk Management: Custom stop structure, position sizing

---

**Implementation Date:** November 2, 2026  
**Status:** ✅ Ready for Backtest & Paper Trading
