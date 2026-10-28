#!/usr/bin/env python3
"""
10-Year Intraday Backtesting & Simulation Engine (2016 - 2026)
Universe: NIFTY 100 Liquid Stocks
Evaluates the Modified Strategy:
- Optimal Target 1: 1.40%
- Initial Stop Loss: 1.20%
- Multi-tier Trailing Stop Loss:
    * +0.65% gain -> SL trails to +0.35% (Zero-risk breakeven lock)
    * +1.00% gain -> SL trails to +0.70% (Locked profit)
- Momentum-Supported Trailing Target:
    * At +1.30% gain: If momentum supports continuation, Target trails to Target 2 (+2.20%) and SL tightens to +1.00%
    * Exits at Target 2 (+2.20%) with TARGET_HIT, or exits with TRAILING_SL_HIT (+1.00% locked) on pullback
- Compares Baseline (Fixed 1.40%) vs Modified (Trailing SL + Momentum Trailing Target)
- Generates 10-Year Year-by-Year Breakdown (2016 - 2026)
"""

import os
import sys
import glob
import time
import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Tuple

import numpy as np
import pandas as pd
import yfinance as yf

# Configure logging
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
logger = logging.getLogger("10YBacktester")

# Simulation Hyperparameters
INITIAL_CAPITAL = 100000.0
CAPITAL_PER_TRADE = 30000.0      # ₹30,000 margin allocation (allows up to 3 concurrent slots)
LEVERAGE = 5.0                   # 5x MIS Intraday Leverage
BROKERAGE_TAX_RATE = 0.0003      # 0.03% round-trip Zerodha statutory costs (brokerage + STT + stamp + exchange + GST)
SL_FIXED_PCT = 1.20              # 1.20% initial stop loss
BREAKOUT_K = 0.25                # Breakout confirmation = Open + 0.25 * ATR
MIN_RVOL = 1.10                  # Relative volume expansion filter
MAX_PICKS_PER_DAY = 3            # Top 3 highest conviction setups per session

CACHE_DIR = Path("data/top100_10y_cache")

# NIFTY 100 Universe
NIFTY_100_TICKERS = [
    "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "BHARTIARTL", "INFY", "ITC", "SBIN",
    "LTIM", "HINDUNILVR", "LT", "BAJFINANCE", "MARUTI", "SUNPHARMA", "AXISBANK",
    "KOTAKBANK", "TITAN", "ONGC", "TATAMOTORS", "NTPC", "TATASTEEL", "POWERGRID",
    "ADANIENT", "JSWSTEEL", "COALINDIA", "M&M", "ADANIPORTS", "ULTRACEMCO", "BPCL",
    "GRASIM", "HCLTECH", "BAJAJFINSV", "WIPRO", "NESTLEIND", "CIPLA", "TECHM",
    "EICHERMOT", "TATACONSUM", "DRREDDY", "DIVISLAB", "APOLLOHOSP", "HEROMOTOCO",
    "BRITANNIA", "ASIANPAINT", "SHREECEM", "INDUSINDBK", "BEL", "HAL", "VEDL",
    "DLF", "CHOLAFIN", "TRENT", "ZOMATO", "SIEMENS", "ABB", "BANKBARODA", "CANBK",
    "PNB", "TVSMOTOR", "HINDALCO", "AMBUJACEM", "GODREJCP", "PIDILITIND", "DABUR",
    "IOC", "GAIL", "BHEL", "RECLTD", "PFC", "HINDPETRO", "BERGEPAINT", "AUROPHARMA",
    "LUPIN", "VOLTAS", "CUMMINSIND", "PERSISTENT", "POLYCAB", "COLPAL", "ASHOKLEY",
    "MUTHOOTFIN", "PIIND", "SRF", "TATACHEM", "TATAPOWER", "TATACOMM", "JINDALSTEL",
    "SAIL", "NMDC", "NATIONALUM", "PETRONET", "CONCOR", "IDFCFIRSTB", "BANDHANBNK",
    "SBICARD", "SBILIFE", "HDFCLIFE", "ICICIPRULI", "ICICIGI", "JUBLFOOD", "IRCTC"
]

TICKER_MAP = {
    "TATAMOTORS": "TMCV.NS",
}


def resolve_yf_ticker(sym: str) -> str:
    if sym in TICKER_MAP:
        return TICKER_MAP[sym]
    if not sym.endswith(".NS") and not sym.startswith("^"):
        return f"{sym}.NS"
    return sym


def fetch_and_cache_10y_data(force_refresh: bool = False) -> Dict[str, pd.DataFrame]:
    """Downloads or loads from cache 10 years of daily data for NIFTY 100 stocks."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    loaded_stocks = {}
    missing_symbols = []

    for sym in NIFTY_100_TICKERS:
        cache_file = CACHE_DIR / f"{sym}.parquet"
        if not force_refresh and cache_file.exists():
            try:
                df = pd.read_parquet(cache_file)
                if len(df) > 500:
                    loaded_stocks[sym] = df
                    continue
            except Exception:
                pass
        missing_symbols.append(sym)

    if missing_symbols:
        logger.info(f"Downloading 10-year data for {len(missing_symbols)} missing stocks via Yahoo Finance...")
        chunk_size = 20
        chunks = [missing_symbols[i:i + chunk_size] for i in range(0, len(missing_symbols), chunk_size)]

        for idx, chunk in enumerate(chunks, 1):
            yf_symbols = [resolve_yf_ticker(s) for s in chunk]
            sym_to_yf = {resolve_yf_ticker(s): s for s in chunk}
            try:
                logger.info(f"Downloading batch {idx}/{len(chunks)} ({len(chunk)} stocks)...")
                raw = yf.download(yf_symbols, period="10y", group_by="ticker", progress=False)

                for yf_sym in yf_symbols:
                    orig_sym = sym_to_yf[yf_sym]
                    try:
                        if len(yf_symbols) > 1:
                            df = raw[yf_sym].copy() if yf_sym in raw.columns.levels[0] else None
                        else:
                            df = raw.copy()

                        if df is not None and not df.empty:
                            df.dropna(subset=["Open", "High", "Low", "Close"], inplace=True)
                            if len(df) > 200:
                                cache_file = CACHE_DIR / f"{orig_sym}.parquet"
                                df.to_parquet(cache_file)
                                loaded_stocks[orig_sym] = df
                    except Exception as e:
                        logger.warning(f"Error parsing {orig_sym} ({yf_sym}): {e}")
            except Exception as e:
                logger.error(f"Batch {idx} download failed: {e}")

    logger.info(f"Total 10-year stocks successfully prepared: {len(loaded_stocks)} / {len(NIFTY_100_TICKERS)}")
    return loaded_stocks


def prepare_stock_features(raw_stocks: Dict[str, pd.DataFrame]) -> Tuple[Dict[str, pd.DataFrame], List[str]]:
    """Calculates ATR, relative volume, and standardizes date index."""
    stocks = {}
    all_dates_set = set()

    for sym, df in raw_stocks.items():
        if len(df) < 50:
            continue

        df = df.copy()
        # Flatten MultiIndex if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df.columns = [str(c).capitalize() for c in df.columns]
        df.index = pd.to_datetime(df.index).strftime("%Y-%m-%d")

        high = df["High"].values
        low = df["Low"].values
        close = df["Close"].values
        prev_close = np.roll(close, 1)
        prev_close[0] = close[0]

        tr = np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
        df["ATR"] = pd.Series(tr, index=df.index).rolling(14, min_periods=5).mean().bfill()
        df["MeanVol"] = df["Volume"].rolling(20, min_periods=5).mean().bfill()

        stocks[sym] = df
        all_dates_set.update(df.index)

    sorted_dates = sorted(list(all_dates_set))
    return stocks, sorted_dates


def run_strategy_backtest(
    stocks: Dict[str, pd.DataFrame],
    all_dates: List[str],
    use_trailing_target: bool = True,
    use_trailing_sl: bool = True,
    use_short_selling: bool = True,
    target_1_pct: float = 1.40,
    target_2_pct: float = 2.20,
    sl_pct: float = 1.20,
    trail_sl_tier1_pct: float = 0.65,
    trail_sl_tier1_lock: float = 0.35,
    trail_sl_tier2_pct: float = 1.00,
    trail_sl_tier2_lock: float = 0.70
) -> Dict[str, Any]:
    """
    Simulates intraday execution over 10 years across NIFTY 100 stocks.
    Models:
    - Long Breakout & Short Breakdown
    - Multi-tier Trailing Stop Loss (+0.35% cost cover at +0.65%, +0.70% lock at +1.00%)
    - Dynamic Trailing Target: Extends Target 1 (1.40%) to Target 2 (2.20%) when momentum supports
    - 5x MIS leverage
    """
    total_trades = 0
    wins = 0
    losses = 0

    target_1_hits = 0
    target_2_hits = 0
    sl_hits = 0
    trailing_sl_hits = 0
    eod_exits = 0

    gross_pnls = []
    net_pnls = []
    equity = INITIAL_CAPITAL
    equity_curve = [equity]

    daily_trade_counts = []
    daily_pnls = []
    daily_records = []
    trades_by_year = {}

    for d in all_dates:
        year = d[:4]
        if year not in trades_by_year:
            trades_by_year[year] = {
                "trades": 0, "wins": 0, "losses": 0, "net_pnl": 0.0,
                "gross_pnl": 0.0, "target_hits": 0, "sl_hits": 0, "trailing_hits": 0
            }

        candidates = []
        for sym, df in stocks.items():
            if d not in df.index:
                continue
            idx = df.index.get_loc(d)
            if idx < 20:
                continue

            row = df.loc[d]
            open_p = float(row["Open"])
            high_p = float(row["High"])
            low_p = float(row["Low"])
            close_p = float(row["Close"])
            vol = float(row["Volume"])
            atr = float(row["ATR"])
            mean_vol = float(row["MeanVol"])

            if open_p <= 0 or atr <= 0 or vol <= 0:
                continue

            rvol = vol / max(1.0, mean_vol)
            if rvol >= MIN_RVOL:
                candidates.append({
                    "sym": sym,
                    "open": open_p,
                    "high": high_p,
                    "low": low_p,
                    "close": close_p,
                    "atr": atr,
                    "rvol": rvol
                })

        candidates.sort(key=lambda x: x["rvol"], reverse=True)
        picks = candidates[:MAX_PICKS_PER_DAY]

        day_trades = 0
        day_net = 0.0

        for cand in picks:
            open_p = cand["open"]
            high_p = cand["high"]
            low_p = cand["low"]
            close_p = cand["close"]
            atr = cand["atr"]

            # 1. Check Long Breakout Setup
            long_trigger = open_p + (BREAKOUT_K * atr)
            short_trigger = open_p - (BREAKOUT_K * atr) if use_short_selling else -1.0

            # Determine side based on which trigger was reached first / day trend
            side = None
            if high_p >= long_trigger and (low_p > short_trigger or close_p >= open_p):
                side = "BUY"
            elif use_short_selling and low_p <= short_trigger:
                side = "SELL"

            if side is None:
                continue

            entry_p = (long_trigger * 1.0003) if side == "BUY" else (short_trigger * 0.9997)
            # Position sizing with 5x leverage
            margin_allocated = CAPITAL_PER_TRADE
            exposure = margin_allocated * LEVERAGE
            qty = max(1, int(exposure / entry_p))

            # Initial parameters
            if side == "BUY":
                initial_sl = entry_p * (1.0 - (sl_pct / 100.0))
                curr_target = entry_p * (1.0 + (target_1_pct / 100.0))
                extended_target = entry_p * (1.0 + (target_2_pct / 100.0))
                target_1_level = curr_target
            else:
                initial_sl = entry_p * (1.0 + (sl_pct / 100.0))
                curr_target = entry_p * (1.0 - (target_1_pct / 100.0))
                extended_target = entry_p * (1.0 - (target_2_pct / 100.0))
                target_1_level = curr_target

            effective_sl = initial_sl
            target_trailed = False

            # Trade Simulation
            if side == "BUY":
                max_favorable_gain_pct = ((high_p - entry_p) / entry_p) * 100.0

                # Multi-tier Trailing Stop Loss
                if use_trailing_sl:
                    if max_favorable_gain_pct >= trail_sl_tier2_pct:
                        # Tier 2: +1.00% gain -> SL trails to +0.70%
                        effective_sl = max(effective_sl, entry_p * (1.0 + (trail_sl_tier2_lock / 100.0)))
                    elif max_favorable_gain_pct >= trail_sl_tier1_pct:
                        # Tier 1: +0.65% gain -> SL trails to +0.35% (cost-guaranteed breakeven)
                        effective_sl = max(effective_sl, entry_p * (1.0 + (trail_sl_tier1_lock / 100.0)))

                # Momentum-Supported Trailing Target
                # If price pushes toward Target 1 (gain >= 1.30%) and close is near high (momentum supports continuation)
                if use_trailing_target and max_favorable_gain_pct >= 1.30:
                    is_momentum_strong = (close_p >= high_p * 0.996)
                    if is_momentum_strong and high_p < extended_target:
                        # Target trails to Target 2 (+2.20%) and SL locks in +1.00%
                        curr_target = extended_target
                        effective_sl = max(effective_sl, entry_p * 1.010)
                        target_trailed = True

                # Determine exit
                if high_p >= curr_target:
                    exit_p = curr_target
                    exit_reason = "TARGET_2" if target_trailed else "TARGET_1"
                elif low_p <= effective_sl:
                    exit_p = effective_sl
                    exit_reason = "TRAILING_SL" if effective_sl > initial_sl else "STOP_LOSS"
                else:
                    exit_p = close_p
                    exit_reason = "EOD"

                gross_pnl = (exit_p - entry_p) * qty

            else:  # SELL (SHORT)
                max_favorable_gain_pct = ((entry_p - low_p) / entry_p) * 100.0

                # Multi-tier Trailing Stop Loss
                if use_trailing_sl:
                    if max_favorable_gain_pct >= trail_sl_tier2_pct:
                        effective_sl = min(effective_sl, entry_p * (1.0 - (trail_sl_tier2_lock / 100.0)))
                    elif max_favorable_gain_pct >= trail_sl_tier1_pct:
                        effective_sl = min(effective_sl, entry_p * (1.0 - (trail_sl_tier1_lock / 100.0)))

                # Momentum-Supported Trailing Target
                if use_trailing_target and max_favorable_gain_pct >= 1.30:
                    is_momentum_strong = (close_p <= low_p * 1.004)
                    if is_momentum_strong and low_p > extended_target:
                        curr_target = extended_target
                        effective_sl = min(effective_sl, entry_p * 0.990)
                        target_trailed = True

                if low_p <= curr_target:
                    exit_p = curr_target
                    exit_reason = "TARGET_2" if target_trailed else "TARGET_1"
                elif high_p >= effective_sl:
                    exit_p = effective_sl
                    exit_reason = "TRAILING_SL" if effective_sl < initial_sl else "STOP_LOSS"
                else:
                    exit_p = close_p
                    exit_reason = "EOD"

                gross_pnl = (entry_p - exit_p) * qty

            cost = (entry_p + exit_p) * qty * BROKERAGE_TAX_RATE
            net_pnl = round(gross_pnl - cost, 2)

            total_trades += 1
            day_trades += 1
            net_pnls.append(net_pnl)
            gross_pnls.append(gross_pnl)
            day_net += net_pnl
            equity += net_pnl
            equity_curve.append(equity)

            trades_by_year[year]["trades"] += 1
            trades_by_year[year]["net_pnl"] += net_pnl
            trades_by_year[year]["gross_pnl"] += gross_pnl

            if net_pnl > 0:
                wins += 1
                trades_by_year[year]["wins"] += 1
            else:
                losses += 1
                trades_by_year[year]["losses"] += 1

            if exit_reason == "TARGET_1":
                target_1_hits += 1
                trades_by_year[year]["target_hits"] += 1
            elif exit_reason == "TARGET_2":
                target_2_hits += 1
                trades_by_year[year]["target_hits"] += 1
            elif exit_reason == "TRAILING_SL":
                trailing_sl_hits += 1
                trades_by_year[year]["trailing_hits"] += 1
            elif exit_reason == "STOP_LOSS":
                sl_hits += 1
                trades_by_year[year]["sl_hits"] += 1
            else:
                eod_exits += 1

        if day_trades > 0:
            daily_trade_counts.append(day_trades)
            daily_pnls.append(day_net)
            daily_records.append({"date": d, "trades": day_trades, "net_pnl": day_net})

    # Summary Statistics
    win_rate = (wins / total_trades * 100.0) if total_trades > 0 else 0.0
    total_net_pnl = sum(net_pnls)
    total_gross_pnl = sum(gross_pnls)
    gross_profits = [p for p in net_pnls if p > 0]
    gross_losses = [abs(p) for p in net_pnls if p < 0]
    sum_gross_profit = sum(gross_profits)
    sum_gross_loss = sum(gross_losses)
    profit_factor = (sum_gross_profit / sum_gross_loss) if sum_gross_loss > 0 else 999.0

    eq_arr = np.array(equity_curve)
    peaks = np.maximum.accumulate(eq_arr)
    dds = (peaks - eq_arr) / peaks * 100.0
    max_dd = float(np.max(dds)) if len(dds) > 0 else 0.0

    total_return_pct = (total_net_pnl / INITIAL_CAPITAL) * 100.0
    calmar_ratio = (total_return_pct / max_dd) if max_dd > 0 else 0.0

    winning_days = sum(1 for p in daily_pnls if p > 0)
    day_win_rate = (winning_days / len(daily_pnls) * 100.0) if daily_pnls else 0.0

    # Year-by-year metrics
    yearly_summary = {}
    for y, stats in sorted(trades_by_year.items()):
        y_trades = stats["trades"]
        if y_trades == 0:
            continue
        y_wr = (stats["wins"] / y_trades * 100.0)
        yearly_summary[y] = {
            "year": y,
            "trades": y_trades,
            "wins": stats["wins"],
            "losses": stats["losses"],
            "win_rate": round(y_wr, 1),
            "net_pnl": round(stats["net_pnl"], 2),
            "target_hits": stats["target_hits"],
            "trailing_hits": stats["trailing_hits"],
            "sl_hits": stats["sl_hits"]
        }

    return {
        "strategy_name": "Modified Strategy (Trailing SL + Momentum Trailing Target)" if use_trailing_target else "Baseline Strategy (Fixed 1.40% Target)",
        "total_trades": total_trades,
        "total_days_traded": len(daily_pnls),
        "wins": wins,
        "losses": losses,
        "win_rate": round(win_rate, 2),
        "day_win_rate": round(day_win_rate, 1),
        "target_1_hits": target_1_hits,
        "target_2_hits": target_2_hits,
        "total_target_hits": target_1_hits + target_2_hits,
        "target_hit_rate": round(((target_1_hits + target_2_hits) / total_trades * 100.0), 1) if total_trades else 0,
        "trailing_sl_hits": trailing_sl_hits,
        "trailing_sl_rate": round((trailing_sl_hits / total_trades * 100.0), 1) if total_trades else 0,
        "sl_hits": sl_hits,
        "sl_hit_rate": round((sl_hits / total_trades * 100.0), 1) if total_trades else 0,
        "eod_exits": eod_exits,
        "total_net_pnl": round(total_net_pnl, 2),
        "total_gross_pnl": round(total_gross_pnl, 2),
        "total_return_pct": round(total_return_pct, 2),
        "profit_factor": round(profit_factor, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "calmar_ratio": round(calmar_ratio, 2),
        "avg_trade_pnl": round((total_net_pnl / total_trades), 2) if total_trades else 0,
        "avg_daily_trades": round(np.mean(daily_trade_counts), 1) if daily_trade_counts else 0,
        "yearly_summary": yearly_summary
    }


def main():
    print("=" * 80)
    print("🚀 10-YEAR HISTORICAL BACKTEST: NIFTY 100 STOCKS (2016 - 2026)")
    print("   Testing Trailing SL & Momentum-Supported Trailing Target Engine")
    print("=" * 80)

    # 1. Fetch & Prepare Data
    t0 = time.time()
    raw_stocks = fetch_and_cache_10y_data(force_refresh=False)
    stocks, all_dates = prepare_stock_features(raw_stocks)
    print(f"✅ Data Preparation complete in {time.time() - t0:.2f}s:")
    print(f"   Stocks analyzed: {len(stocks)}")
    print(f"   Trading days: {len(all_dates)} ({all_dates[0]} to {all_dates[-1]})")
    print("-" * 80)

    # 2. Run Comparative Simulations
    print("⏳ Running Simulation 1: Baseline Strategy (Fixed 1.40% Target, Fixed 1.20% SL)...")
    res_baseline = run_strategy_backtest(
        stocks, all_dates,
        use_trailing_target=False,
        use_trailing_sl=False,
        target_1_pct=1.40
    )

    print("⏳ Running Simulation 2: Intermediate (Fixed 1.40% Target + Multi-Tier Trailing SL)...")
    res_trail_sl_only = run_strategy_backtest(
        stocks, all_dates,
        use_trailing_target=False,
        use_trailing_sl=True,
        target_1_pct=1.40
    )

    print("⏳ Running Simulation 3: Modified Strategy (Multi-Tier Trailing SL + Momentum Trailing Target)...")
    res_modified = run_strategy_backtest(
        stocks, all_dates,
        use_trailing_target=True,
        use_trailing_sl=True,
        target_1_pct=1.40,
        target_2_pct=2.20
    )

    # 3. Print Comprehensive Comparison Table
    print("\n" + "=" * 95)
    print(f"{'10-YEAR METRIC (2016-2026)':<35} | {'BASELINE (FIXED 1.4%)':<18} | {'TRAILING SL ONLY':<18} | {'MODIFIED (SL+TARGET)':<18}")
    print("=" * 95)

    def row(label, k, fmt="{:.2f}", suffix=""):
        v1 = fmt.format(res_baseline[k]) + suffix
        v2 = fmt.format(res_trail_sl_only[k]) + suffix
        v3 = fmt.format(res_modified[k]) + suffix
        print(f"{label:<35} | {v1:<18} | {v2:<18} | {v3:<18}")

    row("Total Trades Executed", "total_trades", "{:d}")
    row("Overall Win Rate", "win_rate", "{:.1f}", "%")
    row("Daily Win Rate (% Days Profitable)", "day_win_rate", "{:.1f}", "%")
    row("Clean Target Hit Rate", "target_hit_rate", "{:.1f}", "%")
    row("Trailing SL Hit Rate", "trailing_sl_rate", "{:.1f}", "%")
    row("Full Stop-Loss Hit Rate", "sl_hit_rate", "{:.1f}", "%")
    row("Profit Factor", "profit_factor", "{:.2f}")
    row("Total Net PnL (₹)", "total_net_pnl", "₹{:,.2f}")
    row("Total Return on Capital", "total_return_pct", "{:,.1f}", "%")
    row("Maximum Drawdown", "max_drawdown_pct", "{:.2f}", "%")
    row("Calmar Ratio (Return/MDD)", "calmar_ratio", "{:.1f}")
    row("Average PnL per Trade", "avg_trade_pnl", "₹{:.2f}")
    row("Average Daily Trades", "avg_daily_trades", "{:.1f}")
    print("=" * 95)

    # 4. Print 10-Year Year-by-Year Performance Breakdown
    print("\n" + "=" * 90)
    print("📅 10-YEAR ANNUAL BREAKDOWN: MODIFIED STRATEGY (2016 - 2026)")
    print("=" * 90)
    print(f"{'Year':<6} | {'Trades':<8} | {'Wins':<6} | {'Losses':<6} | {'Win Rate':<10} | {'Target Hits':<12} | {'Trail Hits':<10} | {'Net PnL (₹)':<14}")
    print("-" * 90)

    for y, ystat in sorted(res_modified["yearly_summary"].items()):
        print(f"{ystat['year']:<6} | {ystat['trades']:<8} | {ystat['wins']:<6} | {ystat['losses']:<6} | {ystat['win_rate']:>7.1f}%   | {ystat['target_hits']:<12} | {ystat['trailing_hits']:<10} | ₹{ystat['net_pnl']:>12,.2f}")

    print("=" * 90)

    # 5. Save results to JSON artifact
    artifact_path = Path("data/backtest_10y_results.json")
    with open(artifact_path, "w") as f:
        json.dump({
            "baseline": res_baseline,
            "trailing_sl_only": res_trail_sl_only,
            "modified_strategy": res_modified
        }, f, indent=2)
    print(f"\n📁 Saved complete 10-year simulation results to: {artifact_path}")


if __name__ == "__main__":
    main()
