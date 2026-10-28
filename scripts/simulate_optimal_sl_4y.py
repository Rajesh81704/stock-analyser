#!/usr/bin/env python3
"""
4-Year Intraday Stop-Loss Optimization Simulation (2022 - 2026)
Simulates across Top 100 NSE liquid stocks to find the optimal Stop Loss
for MINIMUM LOSS and MAXIMUM PROFIT.
"""

import os
import glob
import time
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, List, Any

# Initial simulation settings
INITIAL_CAPITAL = 100000.0
RISK_PER_TRADE = 30000.0  # ₹30,000 allocated per position (3 positions = ₹90k capital)
BROKERAGE_TAX_RATE = 0.0003  # 0.03% round-trip Zerodha statutory costs
TARGET_PCT = 0.022  # 2.2% intraday target
TRAILING_PROGRESS = 0.40  # Move stop to breakeven after 40% progress toward target (+0.88%)
BREAKOUT_K = 0.25  # Breakout trigger = Open + 0.25 * ATR
MIN_RVOL = 1.10  # Minimum relative volume expansion
MAX_PICKS_PER_DAY = 3

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
        
        # Ensure clean standard columns
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

def run_single_simulation(
    stocks: Dict[str, pd.DataFrame],
    all_dates: List[str],
    sl_type: str,  # 'FIXED_PCT' or 'ATR_MULT'
    sl_value: float,
    target_pct: float = 0.022
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
        
        day_candidates.sort(key=lambda x: x["rvol"], reverse=True)
        active_picks = day_candidates[:MAX_PICKS_PER_DAY]
        
        for cand in active_picks:
            open_p = cand["open"]
            high_p = cand["high"]
            low_p = cand["low"]
            close_p = cand["close"]
            atr = cand["atr"]
            
            # Intraday breakout trigger
            breakout_buy = open_p + (BREAKOUT_K * atr)
            
            if high_p >= breakout_buy:
                entry_p = breakout_buy * 1.0003  # slippage
                target_p = entry_p * (1.0 + target_pct)
                
                # Determine initial stop loss
                if sl_type == "FIXED_PCT":
                    stop_distance = entry_p * (sl_value / 100.0)
                else:  # ATR_MULT
                    stop_distance = atr * sl_value
                    
                initial_stop = entry_p - stop_distance
                actual_sl_pct = (stop_distance / entry_p) * 100.0
                
                qty = int(RISK_PER_TRADE / entry_p)
                if qty <= 0:
                    continue
                
                # Trailing breakeven trigger
                be_threshold = entry_p + ((target_p - entry_p) * TRAILING_PROGRESS)
                trailing_activated = (high_p >= be_threshold)
                effective_stop = (entry_p * 1.001) if trailing_activated else initial_stop
                
                # Execution simulation
                # Conservative resolution when both boundaries touched:
                if low_p <= initial_stop and high_p >= target_p:
                    # If close was red, assume SL hit; if strong green, target hit
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
                net_pnls.append(net_pnl)
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

    # Metrics
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
    
    # Return on capital
    total_return_pct = (total_net_pnl / INITIAL_CAPITAL) * 100.0
    calmar_ratio = (total_return_pct / max_dd) if max_dd > 0 else 0.0
    
    return {
        "sl_label": f"{sl_value:.2f}%" if sl_type == "FIXED_PCT" else f"{sl_value:.2f}x ATR",
        "sl_type": sl_type,
        "sl_val": sl_value,
        "total_trades": total_trades,
        "win_rate": round(win_rate, 2),
        "total_net_pnl": round(total_net_pnl, 2),
        "total_return_pct": round(total_return_pct, 2),
        "profit_factor": round(profit_factor, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "calmar_ratio": round(calmar_ratio, 2),
        "expectancy_per_trade": round(expectancy, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "reward_risk": round(reward_risk_ratio, 2),
        "sl_hit_rate": round((sl_hits / total_trades * 100.0), 1) if total_trades else 0,
        "target_hit_rate": round((target_hits / total_trades * 100.0), 1) if total_trades else 0,
        "trailing_hit_rate": round((trailing_hits / total_trades * 100.0), 1) if total_trades else 0,
        "eod_rate": round((eod_exits / total_trades * 100.0), 1) if total_trades else 0,
    }

def main():
    print("=" * 80)
    print("🚀 4-YEAR INTRADAY STOP LOSS OPTIMIZATION SIMULATION (2022 - 2026)")
    print("=" * 80)
    
    t0 = time.time()
    stocks = load_all_stocks("data/top100_cache")
    
    # Collect all unique sorted dates
    all_dates_set = set()
    for s in stocks.values():
        all_dates_set.update(s.index)
    all_dates = sorted(list(all_dates_set))
    
    print(f"Loaded {len(stocks)} liquid NSE stocks over {len(all_dates)} trading sessions ({all_dates[0]} to {all_dates[-1]}).")
    print(f"Starting stop-loss parameter sweep...\n")
    
    # Fixed % Stop Loss range to test
    fixed_sl_values = [0.5, 0.75, 1.0, 1.2, 1.4, 1.5, 1.6, 1.8, 2.0, 2.2, 2.5, 3.0]
    # ATR Multiplier Stop Loss range to test
    atr_sl_values = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0]
    
    results = []
    
    print("--- [1/2] Testing Fixed Percentage Stop Losses ---")
    for sl in fixed_sl_values:
        res = run_single_simulation(stocks, all_dates, "FIXED_PCT", sl, TARGET_PCT)
        results.append(res)
        print(f"SL: {res['sl_label']:>6} | Net PnL: ₹{res['total_net_pnl']:>10,.2f} ({res['total_return_pct']:>6.1f}%) | WinRate: {res['win_rate']:>5.1f}% | PF: {res['profit_factor']:>4.2f} | MaxDD: {res['max_drawdown_pct']:>5.2f}% | Expectancy: ₹{res['expectancy_per_trade']:>6.2f} | SL Hit: {res['sl_hit_rate']:>4.1f}%")

    print("\n--- [2/2] Testing Dynamic ATR Multiplier Stop Losses ---")
    for sl in atr_sl_values:
        res = run_single_simulation(stocks, all_dates, "ATR_MULT", sl, TARGET_PCT)
        results.append(res)
        print(f"SL: {res['sl_label']:>8} | Net PnL: ₹{res['total_net_pnl']:>10,.2f} ({res['total_return_pct']:>6.1f}%) | WinRate: {res['win_rate']:>5.1f}% | PF: {res['profit_factor']:>4.2f} | MaxDD: {res['max_drawdown_pct']:>5.2f}% | Expectancy: ₹{res['expectancy_per_trade']:>6.2f} | SL Hit: {res['sl_hit_rate']:>4.1f}%")

    # Convert to DataFrame for ranking
    df_res = pd.DataFrame(results)
    
    # Rankings
    best_profit = df_res.sort_values(by="total_net_pnl", ascending=False).iloc[0]
    best_drawdown = df_res.sort_values(by="max_drawdown_pct", ascending=True).iloc[0]
    best_calmar = df_res.sort_values(by="calmar_ratio", ascending=False).iloc[0]
    best_pf = df_res.sort_values(by="profit_factor", ascending=False).iloc[0]
    best_expectancy = df_res.sort_values(by="expectancy_per_trade", ascending=False).iloc[0]
    
    print("\n" + "=" * 80)
    print("🏆 SIMULATION RESULTS & OPTIMAL STOP LOSS DISCOVERY")
    print("=" * 80)
    print(f"🥇 MAXIMUM PROFIT SL:            {best_profit['sl_label']} (Net PnL: ₹{best_profit['total_net_pnl']:,.2f}, Return: +{best_profit['total_return_pct']}%, PF: {best_profit['profit_factor']})")
    print(f"🛡️  MINIMUM DRAWDOWN (MIN LOSS):   {best_drawdown['sl_label']} (Max Drawdown: {best_drawdown['max_drawdown_pct']}%, Net PnL: ₹{best_drawdown['total_net_pnl']:,.2f})")
    print(f"⭐ BEST RISK-ADJUSTED (CALMAR):   {best_calmar['sl_label']} (Calmar: {best_calmar['calmar_ratio']}, Profit: ₹{best_calmar['total_net_pnl']:,.2f}, MaxDD: {best_calmar['max_drawdown_pct']}%)")
    print(f"🎯 HIGHEST PROFIT FACTOR:         {best_pf['sl_label']} (PF: {best_pf['profit_factor']}, Win Rate: {best_pf['win_rate']}%)")
    print("=" * 80)
    
    # Save results to CSV for record
    out_csv = "results/optimal_sl_4y_simulation.csv"
    os.makedirs("results", exist_ok=True)
    df_res.to_csv(out_csv, index=False)
    print(f"Full simulation summary saved to: {out_csv}")
    print(f"Elapsed time: {time.time() - t0:.2f} seconds.")

if __name__ == "__main__":
    main()
