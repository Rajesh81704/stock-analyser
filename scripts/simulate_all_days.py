#!/usr/bin/env python3
"""
Simulate Intraday Trading with the Latest Calibrated Rules
across all available trading dates on 5-Minute Nifty 100 Candles.

Latest Calibrated Architecture:
1. Initial Stop Loss: -0.90% (tight risk guard to guarantee >1.0 payoff ratio against target)
2. Breakeven Cushion Tier: Trails SL to Cost + 0.25% once gain reaches +0.90%
3. Runner Lock Tier: Trails SL to +0.90% once gain reaches +1.20%
4. Target: +1.40%
5. Compounded daily equity tracking with Zerodha intraday fees and 5 bps slippage.
"""

import sys
from pathlib import Path
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.costs.calculator import CostCalculator, ZerodhaIntradayCostsConfig
from src.algodesk.automation.daily_screener_trader import NIFTY_100_LIQUID_UNIVERSE
from scripts.simulate_todays_data import fetch_5m_candles, check_dates_available

def run_multi_day_simulation():
    candles = fetch_5m_candles(NIFTY_100_LIQUID_UNIVERSE)
    available_dates = check_dates_available(candles)
    print(f"\nLoaded {len(candles)} symbols across {len(available_dates)} trading sessions: {available_dates}\n")

    cost_calc = CostCalculator(ZerodhaIntradayCostsConfig())
    initial_capital = 100000.0
    current_equity = initial_capital
    leverage = 5.0
    slippage_pct = 0.0005 # 5 bps

    daily_results = []
    all_trades = []

    for trade_date in available_dates:
        # Filter symbols with valid session on this date
        day_bars = {}
        for sym, df in candles.items():
            df_day = df[df.index.strftime("%Y-%m-%d") == trade_date]
            if len(df_day) >= 50:
                day_bars[sym] = df_day

        if len(day_bars) < 30:
            continue

        # Morning screener (09:15 - 09:30)
        morning_scores = []
        for sym, df in day_bars.items():
            mb = df.between_time("09:15", "09:30")
            if len(mb) >= 3:
                open_p = float(mb.iloc[0]["Open"])
                close_p = float(mb.iloc[-1]["Close"])
                vol = float(mb["Volume"].sum())
                ret_pct = ((close_p - open_p) / open_p) * 100.0
                morning_scores.append({
                    "symbol": sym,
                    "ret_pct": ret_pct,
                    "vol": vol,
                    "entry_time": mb.index[-1],
                    "entry_p": close_p
                })

        morning_scores.sort(key=lambda x: x["ret_pct"], reverse=True)
        top_picks = morning_scores[:5] # Top 5 stocks to trade

        slot_capital = (current_equity * leverage) / 5.0
        day_trades = []

        for pick in top_picks:
            sym = pick["symbol"]
            df_stock = day_bars[sym]
            trade_bars = df_stock.between_time("09:35", "15:10")
            if trade_bars.empty:
                continue

            raw_entry = float(pick["entry_p"])
            eff_entry = raw_entry * (1.0 + slippage_pct)
            qty = int(slot_capital / eff_entry)
            if qty <= 0:
                continue

            # Latest Calibrated Strategy Parameters
            target_price = eff_entry * 1.0140             # +1.40%
            initial_sl = eff_entry * (1.0 - 0.0090)       # -0.90%
            current_sl = initial_sl

            trail_tier1_trigger = eff_entry * 1.0090     # +0.90% advance
            trail_tier1_lock = eff_entry * 1.0025        # lock +0.25% (cost cushion)

            trail_tier2_trigger = eff_entry * 1.0120     # +1.20% advance
            trail_tier2_lock = eff_entry * 1.0090        # lock +0.90% runner gain

            highest_p = eff_entry
            exit_price = None
            exit_time = None
            exit_reason = None

            for ts, b in trade_bars.iterrows():
                b_high = float(b["High"])
                b_low = float(b["Low"])
                b_close = float(b["Close"])
                highest_p = max(highest_p, b_high)

                # Dynamic Trailing Adjustment
                if highest_p >= trail_tier2_trigger:
                    current_sl = max(current_sl, trail_tier2_lock)
                elif highest_p >= trail_tier1_trigger:
                    current_sl = max(current_sl, trail_tier1_lock)

                # Check Target Hit
                if b_high >= target_price:
                    exit_price = target_price * (1.0 - slippage_pct)
                    exit_time = ts
                    exit_reason = "TARGET (+1.4%)"
                    break
                # Check Stop Loss Hit
                elif b_low <= current_sl:
                    exit_price = current_sl * (1.0 - slippage_pct)
                    exit_time = ts
                    if current_sl > eff_entry:
                        exit_reason = "TRAILING_STOP"
                    else:
                        exit_reason = "STOP_LOSS (-0.9%)"
                    break

            if exit_price is None:
                last_b = trade_bars.iloc[-1]
                exit_price = float(last_b["Close"]) * (1.0 - slippage_pct)
                exit_time = trade_bars.index[-1]
                exit_reason = "TIME_EXIT (15:10)"

            breakdown = cost_calc.calculate_roundtrip(
                side="LONG",
                qty=qty,
                raw_entry_price=eff_entry,
                raw_exit_price=exit_price,
                trailing_turnover_cr=150.0
            )
            gross_pnl = (exit_price - eff_entry) * qty
            costs = breakdown.total_costs
            net_pnl = gross_pnl - costs

            trade_rec = {
                "date": trade_date,
                "symbol": sym,
                "entry_time": pick["entry_time"].strftime("%H:%M"),
                "entry_price": round(eff_entry, 2),
                "exit_time": exit_time.strftime("%H:%M"),
                "exit_price": round(exit_price, 2),
                "qty": qty,
                "gross_pnl": round(gross_pnl, 2),
                "costs": round(costs, 2),
                "net_pnl": round(net_pnl, 2),
                "exit_reason": exit_reason
            }
            day_trades.append(trade_rec)
            all_trades.append(trade_rec)

        day_gross = sum(t["gross_pnl"] for t in day_trades)
        day_costs = sum(t["costs"] for t in day_trades)
        day_net = sum(t["net_pnl"] for t in day_trades)
        wins = len([t for t in day_trades if t["net_pnl"] > 0])
        win_rate = (wins / len(day_trades) * 100.0) if day_trades else 0.0

        current_equity += day_net
        daily_ret_pct = (day_net / (current_equity - day_net)) * 100.0

        daily_results.append({
            "date": trade_date,
            "trades": len(day_trades),
            "wins": wins,
            "win_rate": round(win_rate, 1),
            "gross_pnl": round(day_gross, 2),
            "costs": round(day_costs, 2),
            "net_pnl": round(day_net, 2),
            "daily_return_pct": round(daily_ret_pct, 2),
            "ending_equity": round(current_equity, 2),
            "stocks": [t["symbol"] for t in day_trades]
        })

    # Summary
    total_trades_count = len(all_trades)
    total_wins_count = len([t for t in all_trades if t["net_pnl"] > 0])
    overall_win_rate = (total_wins_count / total_trades_count * 100.0) if total_trades_count else 0.0
    total_gross = sum(d["gross_pnl"] for d in daily_results)
    total_costs = sum(d["costs"] for d in daily_results)
    total_net = sum(d["net_pnl"] for d in daily_results)
    total_return_pct = ((current_equity - initial_capital) / initial_capital) * 100.0

    print("=========================================================================================")
    print("         MULTI-DAY INTRADAY SIMULATION RESULTS (LATEST CALIBRATION)                      ")
    print("=========================================================================================")
    print(f"{'Date':<12} | {'Trades':<6} | {'Win Rate':<8} | {'Gross P&L':<12} | {'Taxes/Fees':<10} | {'Net P&L':<12} | {'Return %':<8} | {'Equity (₹)':<10}")
    print("-" * 90)
    for d in daily_results:
        print(f"{d['date']:<12} | {d['trades']:<6} | {d['win_rate']:>6.1f}%  | {d['gross_pnl']:>+12,.2f} | {d['costs']:>10,.2f} | {d['net_pnl']:>+12,.2f} | {d['daily_return_pct']:>+7.2f}% | ₹{d['ending_equity']:>10,.2f}")
    print("=========================================================================================")
    print(f"Overall Period Summary:")
    print(f"  Starting Equity:     ₹{initial_capital:,.2f}")
    print(f"  Ending Equity:       ₹{current_equity:,.2f}")
    print(f"  Total Net Return:    {total_return_pct:+.2f}%")
    print(f"  Total Trades Taken:  {total_trades_count}")
    print(f"  Overall Win Rate:    {overall_win_rate:.1f}% ({total_wins_count}/{total_trades_count})")
    print(f"  Total Gross P&L:     ₹{total_gross:+,.2f}")
    print(f"  Total Taxes/Fees:    ₹{total_costs:,.2f}")
    print(f"  TOTAL NET PROFIT:    ₹{total_net:+,.2f}")
    print("=========================================================================================")

if __name__ == "__main__":
    run_multi_day_simulation()
