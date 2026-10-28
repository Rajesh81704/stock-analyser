#!/usr/bin/env python3
"""
4-Year Intraday Target Optimization Simulation (2022 - 2026)
Simulates across Top 100 NSE liquid stocks over 4 years to discover
the optimal Target Percentage for:
1. Highest Win Rate / Hit Rate
2. Multiple small profitable trades per day
3. Maximum Total Net Gain after accounting for all statutory taxes and brokerages
"""

import os
import glob
import time
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, List, Any

# Simulation settings
INITIAL_CAPITAL = 100000.0
CAPITAL_PER_TRADE = 30000.0  # ₹30,000 allocated per trade (allows 3 concurrent slots)
BROKERAGE_TAX_RATE = 0.0003  # 0.03% round-trip Zerodha statutory costs
SL_FIXED_PCT = 1.20          # 1.20% empirical optimal stop loss established from 4-year study
BREAKOUT_K = 0.25            # Breakout confirmation = Open + 0.25 * ATR
MIN_RVOL = 1.10              # Volume expansion filter
MAX_PICKS_PER_DAY = 5        # Allows multiple trades throughout the day

def load_all_stocks(cache_dir: str = "data/top100_cache") -> Dict[str, pd.DataFrame]:
    files = sorted(glob.glob(os.path.join(cache_dir, "*.parquet")))
    if not files:
        raise FileNotFoundError(f"No parquet files found in {cache_dir}")
    
    stocks = {}
    for f in files:
        sym = Path(f).stem.replace(".parquet", "")
        df = pd.read_parquet(f)
        if len(df) < 50:
            continue
        
        # Standardize columns
        df.columns = [c.capitalize() for c in df.columns]
        df.index = pd.to_datetime(df.index).strftime("%Y-%m-%d")
        
        # Calculate 14-day ATR & 20-day Mean Volume
        high = df["High"].values
        low = df["Low"].values
        close = df["Close"].values
        prev_close = np.roll(close, 1)
        prev_close[0] = close[0]
        
        tr = np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
        df["ATR"] = pd.Series(tr, index=df.index).rolling(14, min_periods=5).mean().bfill()
        df["MeanVol"] = df["Volume"].rolling(20, min_periods=5).mean().bfill()
        df["ATR_pct"] = (df["ATR"] / df["Close"]) * 100.0
        
        stocks[sym] = df
        
    return stocks

def run_target_simulation(
    stocks: Dict[str, pd.DataFrame],
    all_dates: List[str],
    target_type: str,   # 'FIXED_PCT' or 'ATR_MULT'
    target_value: float,
    sl_pct: float = 1.20,
    trail_to_be_ratio: float = 0.40  # Move SL to breakeven (+0.1% cost cover) after 40% progress toward target
) -> Dict[str, Any]:
    
    total_trades = 0
    wins = 0
    losses = 0
    sl_hits = 0
    target_hits = 0
    trailing_hits = 0
    eod_exits = 0
    
    gross_profits = []
    gross_losses = []
    net_pnls = []
    equity = INITIAL_CAPITAL
    equity_curve = [equity]
    
    days_with_trades = 0
    daily_trade_counts = []
    daily_pnls = []
    
    for d in all_dates:
        day_candidates = []
        for sym, df in stocks.items():
            if d not in df.index:
                continue
            idx = df.index.get_loc(d)
            if idx < 15:
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
                day_candidates.append({
                    "sym": sym,
                    "open": open_p,
                    "high": high_p,
                    "low": low_p,
                    "close": close_p,
                    "atr": atr,
                    "rvol": rvol
                })
        
        # Rank by relative volume momentum
        day_candidates.sort(key=lambda x: x["rvol"], reverse=True)
        active_picks = day_candidates[:MAX_PICKS_PER_DAY]
        
        day_trades_count = 0
        day_pnl = 0.0
        
        for cand in active_picks:
            open_p = cand["open"]
            high_p = cand["high"]
            low_p = cand["low"]
            close_p = cand["close"]
            atr = cand["atr"]
            
            # Intraday breakout trigger
            breakout_buy = open_p + (BREAKOUT_K * atr)
            
            if high_p >= breakout_buy:
                entry_p = breakout_buy * 1.0003  # slippage factor
                
                # Target price calculation
                if target_type == "FIXED_PCT":
                    target_dist = entry_p * (target_value / 100.0)
                else:  # ATR_MULT
                    target_dist = atr * target_value
                    
                target_p = entry_p + target_dist
                actual_target_pct = (target_dist / entry_p) * 100.0
                
                # Stop loss calculation (1.20%)
                initial_stop = entry_p * (1.0 - (sl_pct / 100.0))
                
                qty = int(CAPITAL_PER_TRADE / entry_p)
                if qty <= 0:
                    continue
                
                # Dynamic breakeven / lock-in threshold (e.g. 40% progress to target)
                be_threshold = entry_p + (target_dist * trail_to_be_ratio)
                trailing_activated = (high_p >= be_threshold)
                # If trailing activated, lock in small gain (+0.25% cost guarantee)
                effective_stop = (entry_p * 1.0025) if trailing_activated else initial_stop
                
                # Execution simulation
                if low_p <= initial_stop and high_p >= target_p:
                    # Ambiguous bar: resolve conservatively based on day candle direction
                    if close_p < open_p:
                        exit_p = initial_stop
                        exit_reason = "STOP_LOSS"
                    else:
                        exit_p = target_p
                        exit_reason = "TARGET"
                elif high_p >= target_p:
                    exit_p = target_p
                    exit_reason = "TARGET"
                elif low_p <= effective_stop:
                    exit_p = effective_stop
                    exit_reason = "TRAILING_STOP" if trailing_activated else "STOP_LOSS"
                else:
                    exit_p = close_p
                    exit_reason = "EOD"
                
                gross_pnl = (exit_p - entry_p) * qty
                cost = (entry_p + exit_p) * qty * BROKERAGE_TAX_RATE
                net_pnl = round(gross_pnl - cost, 2)
                
                total_trades += 1
                day_trades_count += 1
                net_pnls.append(net_pnl)
                day_pnl += net_pnl
                equity += net_pnl
                equity_curve.append(equity)
                
                if net_pnl > 0:
                    wins += 1
                    gross_profits.append(net_pnl)
                else:
                    losses += 1
                    gross_losses.append(abs(net_pnl))
                
                if exit_reason == "TARGET":
                    target_hits += 1
                elif exit_reason == "STOP_LOSS":
                    sl_hits += 1
                elif exit_reason == "TRAILING_STOP":
                    trailing_hits += 1
                else:
                    eod_exits += 1
                    
        if day_trades_count > 0:
            days_with_trades += 1
            daily_trade_counts.append(day_trades_count)
            daily_pnls.append(day_pnl)

    win_rate = (wins / total_trades * 100.0) if total_trades > 0 else 0.0
    total_net_pnl = sum(net_pnls)
    sum_gross_profit = sum(gross_profits)
    sum_gross_loss = sum(gross_losses)
    profit_factor = (sum_gross_profit / sum_gross_loss) if sum_gross_loss > 0 else 999.0
    avg_win = (sum_gross_profit / wins) if wins > 0 else 0.0
    avg_loss = (sum_gross_loss / losses) if losses > 0 else 0.0
    expectancy = (total_net_pnl / total_trades) if total_trades > 0 else 0.0
    reward_risk_ratio = (avg_win / avg_loss) if avg_loss > 0 else 0.0
    
    # Max Drawdown
    eq_arr = np.array(equity_curve)
    peaks = np.maximum.accumulate(eq_arr)
    dds = (peaks - eq_arr) / peaks * 100.0
    max_dd = float(np.max(dds)) if len(dds) > 0 else 0.0
    
    total_return_pct = (total_net_pnl / INITIAL_CAPITAL) * 100.0
    calmar_ratio = (total_return_pct / max_dd) if max_dd > 0 else 0.0
    
    # Daily metrics
    avg_daily_trades = np.mean(daily_trade_counts) if daily_trade_counts else 0.0
    daily_win_days = sum(1 for p in daily_pnls if p > 0)
    day_win_rate = (daily_win_days / len(daily_pnls) * 100.0) if daily_pnls else 0.0
    
    label = f"{target_value:.2f}%" if target_type == "FIXED_PCT" else f"{target_value:.2f}x ATR"
    
    return {
        "target_label": label,
        "target_type": target_type,
        "target_val": target_value,
        "total_trades": total_trades,
        "win_rate": round(win_rate, 2),
        "target_hit_rate": round((target_hits / total_trades * 100.0), 1) if total_trades else 0,
        "sl_hit_rate": round((sl_hits / total_trades * 100.0), 1) if total_trades else 0,
        "trailing_hit_rate": round((trailing_hits / total_trades * 100.0), 1) if total_trades else 0,
        "total_net_pnl": round(total_net_pnl, 2),
        "total_return_pct": round(total_return_pct, 2),
        "profit_factor": round(profit_factor, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "calmar_ratio": round(calmar_ratio, 2),
        "expectancy_per_trade": round(expectancy, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "day_win_rate": round(day_win_rate, 1),
        "avg_daily_trades": round(avg_daily_trades, 1)
    }

def main():
    print("=" * 90)
    print("🎯 4-YEAR INTRADAY TARGET OPTIMIZATION SIMULATION (2022 - 2026)")
    print("Goal: High Hit-Rate & Multiple Small Wins for Consistent Daily Gains")
    print("Stop Loss Fixed at: 1.20% | Capital: ₹1,00,000 | Trade Size: ₹30,000")
    print("=" * 90)
    
    t0 = time.time()
    stocks = load_all_stocks("data/top100_cache")
    
    all_dates_set = set()
    for s in stocks.values():
        all_dates_set.update(s.index)
    all_dates = sorted(list(all_dates_set))
    
    print(f"Loaded {len(stocks)} liquid NSE stocks over {len(all_dates)} trading sessions ({all_dates[0]} to {all_dates[-1]}).\n")
    
    # Target values to test: from small scalping targets to wide runner targets
    fixed_targets = [0.5, 0.6, 0.75, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.8, 2.0, 2.2, 2.5, 3.0]
    atr_targets = [0.3, 0.4, 0.5, 0.6, 0.75, 1.0, 1.2, 1.5]
    
    results = []
    
    print("--- [1/2] Testing Fixed Target Percentages ---")
    header = f"{'Target':>8} | {'WinRate':>7} | {'TargetHit':>9} | {'Net PnL (₹)':>12} | {'Return':>7} | {'PF':>5} | {'MaxDD':>6} | {'DayWin%':>7} | {'Expectancy':>10}"
    print(header)
    print("-" * len(header))
    
    for t_val in fixed_targets:
        res = run_target_simulation(stocks, all_dates, "FIXED_PCT", t_val, sl_pct=SL_FIXED_PCT)
        results.append(res)
        print(f"{res['target_label']:>8} | {res['win_rate']:>6.1f}% | {res['target_hit_rate']:>8.1f}% | ₹{res['total_net_pnl']:>11,.2f} | {res['total_return_pct']:>6.1f}% | {res['profit_factor']:>5.2f} | {res['max_drawdown_pct']:>5.2f}% | {res['day_win_rate']:>6.1f}% | ₹{res['expectancy_per_trade']:>9.2f}")
    
    print("\n--- [2/2] Testing Dynamic ATR Multiplier Targets ---")
    print(header)
    print("-" * len(header))
    for t_val in atr_targets:
        res = run_target_simulation(stocks, all_dates, "ATR_MULT", t_val, sl_pct=SL_FIXED_PCT)
        results.append(res)
        print(f"{res['target_label']:>8} | {res['win_rate']:>6.1f}% | {res['target_hit_rate']:>8.1f}% | ₹{res['total_net_pnl']:>11,.2f} | {res['total_return_pct']:>6.1f}% | {res['profit_factor']:>5.2f} | {res['max_drawdown_pct']:>5.2f}% | {res['day_win_rate']:>6.1f}% | ₹{res['expectancy_per_trade']:>9.2f}")
        
    df_res = pd.DataFrame(results)
    
    # Rankings
    best_hitrate = df_res.sort_values(by="win_rate", ascending=False).iloc[0]
    best_profit = df_res.sort_values(by="total_net_pnl", ascending=False).iloc[0]
    best_pf = df_res.sort_values(by="profit_factor", ascending=False).iloc[0]
    best_calmar = df_res.sort_values(by="calmar_ratio", ascending=False).iloc[0]
    best_daywin = df_res.sort_values(by="day_win_rate", ascending=False).iloc[0]
    
    print("\n" + "=" * 90)
    print("🏆 SIMULATION RESULTS & OPTIMAL TARGET DISCOVERY")
    print("=" * 90)
    print(f"🎯 HIGHEST WIN RATE (HIT RATE): {best_hitrate['target_label']} (Win Rate: {best_hitrate['win_rate']}%, Target Hit: {best_hitrate['target_hit_rate']}%, Day Win%: {best_hitrate['day_win_rate']}%, Net PnL: ₹{best_hitrate['total_net_pnl']:,.2f})")
    print(f"🥇 MAXIMUM TOTAL NET PROFIT:   {best_profit['target_label']} (Net PnL: ₹{best_profit['total_net_pnl']:,.2f}, Return: +{best_profit['total_return_pct']}%, PF: {best_profit['profit_factor']}, Win Rate: {best_profit['win_rate']}%)")
    print(f"⭐ BEST PROFIT FACTOR:         {best_pf['target_label']} (PF: {best_pf['profit_factor']}, Net PnL: ₹{best_pf['total_net_pnl']:,.2f}, MaxDD: {best_pf['max_drawdown_pct']}%)")
    print(f"🛡️  BEST RISK-ADJUSTED (CALMAR): {best_calmar['target_label']} (Calmar: {best_calmar['calmar_ratio']}, Net PnL: ₹{best_calmar['total_net_pnl']:,.2f}, MaxDD: {best_calmar['max_drawdown_pct']}%)")
    print(f"📅 HIGHEST GREEN DAYS %:       {best_daywin['target_label']} (Day Win%: {best_daywin['day_win_rate']}%, Net PnL: ₹{best_daywin['total_net_pnl']:,.2f})")
    print("=" * 90)
    
    out_csv = "results/optimal_target_4y_simulation.csv"
    os.makedirs("results", exist_ok=True)
    df_res.to_csv(out_csv, index=False)
    print(f"Saved full simulation summary to: {out_csv}")
    print(f"Simulation execution time: {time.time() - t0:.2f} seconds.")

if __name__ == "__main__":
    main()
