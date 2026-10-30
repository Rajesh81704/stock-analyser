# Quantitative Research Report: Opening Range Breakout (ORB)
**Generated:** 2026-10-30 11:12:44 IST

> ⚠️ **CRITICAL NOTICE: SYNTHETIC DATA MODE ACTIVE**
> This backtest was executed on synthetically generated random-walk data for pipeline smoke-testing.
> **These results only prove code mechanics and data flow. They have ZERO predictive alpha value.**

## Executive Summary

### Verdict: ❌ **STRATEGY IS UNPROFITABLE OUT-OF-SAMPLE AFTER COSTS**

> ⚠️ **Methodological Mandate**: Only **Out-of-Sample (OOS)** results reflect realistic forward expectations. In-Sample (IS) results suffer from selection bias and curve-fitting risk.

> ⚠️ **STATISTICAL SIGNIFICANCE WARNING**: The Out-of-Sample evaluation recorded only **29 trades** (< 100 trades threshold). Conclusions are subject to high sampling variance and small-sample noise.

### Key Quant Performance Breakdown

| Metric | Full Horizon | In-Sample (70%) | Out-of-Sample (30%) |
| :--- | :---: | :---: | :---: |
| **Evaluation Period** | Full | First 70% | Last 30% (from 2026-09-11) |
| **Trading Days** | 42 | 29 | 13 |
| **Total Trades** | 50 | 21 | 29 |
| **Net Return %** | **-61.26%** | **-29.66%** | **-44.93%** |
| **Annualized CAGR %** | -99.65% | -95.18% | -100.00% |
| **Annualized Sharpe (250d)** | **-13.330** | **-9.395** | **-28.924** |
| **Max Drawdown %** | 61.26% | 29.66% | 39.51% |
| **Win Rate %** | 0.00% | 0.00% | 0.00% |
| **Profit Factor** | 0.00 | 0.00 | 0.00 |
| **Avg Win / Avg Loss** | Rs 0.0 / Rs 1225.2 (0.00x) | Rs 0.0 / Rs 1412.2 (0.00x) | Rs 0.0 / Rs 1089.9 (0.00x) |
| **Stopped Out %** | 100.0% | 100.0% | 100.0% |
| **Gross P&L (Rs)** | Rs -49,650.73 | Rs -23,430.19 | Rs -26,220.54 |
| **Total Costs & Slippage (Rs)** | -Rs 11,611.06 | -Rs 6,225.12 | -Rs 5,385.94 |
| **Net P&L (Rs)** | **Rs -61,261.81** | **Rs -29,655.30** | **Rs -31,606.51** |

### Directional Segregation (Long vs Short)

| Period | Direction | Trades | Win Rate % | Net P&L (Rs) |
| :--- | :---: | :---: | :---: | :---: |
| **Full Horizon** | Long | 28 | 0.0% | Rs -35,227.83 |
| **Full Horizon** | Short | 22 | 0.0% | Rs -26,033.98 |
| **In-Sample** | Long | 14 | 0.0% | Rs -18,823.50 |
| **In-Sample** | Short | 7 | 0.0% | Rs -10,831.80 |
| **Out-of-Sample** | Long | 14 | 0.0% | Rs -16,404.33 |
| **Out-of-Sample** | Short | 15 | 0.0% | Rs -15,202.18 |

## Cost Drag & Friction Analysis

- **Total Gross P&L**: Rs -49,650.73
- **Total Friction (Statutory Fees + Slippage)**: Rs 11,611.06
- **Friction as % of Gross P&L**: **23.4%**
- **Net Edge Extracted**: Rs -61,261.81

> In high-frequency intraday momentum, statutory taxes (STT on sells, stamp duty on buys, exchange fees, SEBI charges, GST) and execution slippage represent an enormous hurdle. Many apparent gross edges are entirely consumed by realistic market friction.

## Monthly Returns Matrix (%)

| year | Aug | Sep | Year |
| :---: | :---: | :---: | :---: |
| 2026.00 | -4.51 | -59.43 | -61.26 |


## Day-of-Week Performance

| Day | Trades | Win Rate % | Gross P&L (Rs) | Costs (Rs) | Net P&L (Rs) |
| :---: | :---: | :---: | :---: | :---: | :---: |
| Monday | 12 | 0.00 | -11076.47 | 2916.60 | -13993.10 |
| Tuesday | 12 | 0.00 | -11613.72 | 2842.03 | -14455.74 |
| Wednesday | 9 | 0.00 | -8953.02 | 2030.92 | -10983.93 |
| Thursday | 6 | 0.00 | -4350.80 | 1378.43 | -5729.23 |
| Friday | 11 | 0.00 | -13656.72 | 2443.08 | -16099.81 |


## Top 10 Traded Symbols

| Symbol | Trades | Win Rate % | Gross P&L (Rs) | Total Costs (Rs) | Net P&L (Rs) |
| :---: | :---: | :---: | :---: | :---: | :---: |
| HDFCBANK.NS | 11 | 0.00 | -12598.75 | 2643.34 | -15242.10 |
| INFY.NS | 11 | 0.00 | -9915.23 | 2680.30 | -12595.55 |
| TCS.NS | 11 | 0.00 | -10439.71 | 2204.81 | -12644.50 |
| ICICIBANK.NS | 9 | 0.00 | -9485.26 | 2148.51 | -11633.78 |
| RELIANCE.NS | 8 | 0.00 | -7211.78 | 1934.10 | -9145.88 |


## Core Strategy Parameters

- **Opening Range Duration**: 5 minutes
- **RVOL Baseline**: 14 trading days (strictly shifted)
- **Minimum RVOL**: 1.0x
- **ATR Filter Window**: 14 days (shifted 1 day)
- **Stop Distance**: 0.1 x ATR14
- **Liquidity Filter**: 20-day average turnover >= Rs 20.0 Cr, Price >= Rs 50.0
- **Universe Candidates Selected per Day**: Top 3
- **Risk per Trade**: 1.0% of start-of-day equity
- **Max Gross Leverage**: 5.0x
- **Intrabar Conservative Rule**: True
- **Square-Off Time Exit**: 15:10:00 IST

## Known Limitations & Structural Caveats

1. **Survivorship Bias**: Testing on current Nifty 500 constituents misses stocks that went bankrupt, merged, or were removed due to deteriorating liquidity.
2. **Stop Order Fill Assumptions**: Assumes stop orders are immediately filled at stop or open gap. In volatile breakouts, stop orders can suffer severe slippage.
3. **Zero Market Impact Assumption**: Assumes our orders do not move the order book or consume depth.
4. **Price Circuits**: Does not filter for 5%/10%/20% circuit freezes where trading halts or execution becomes impossible.
5. **Broker MIS Shorting Bans**: Assumes all constituents can be shorted intraday via MIS without broker surveillance or scrip-level short restrictions.
6. **Past Performance Disclaimer**: Past backtested performance is NOT indicative of future live market returns.
