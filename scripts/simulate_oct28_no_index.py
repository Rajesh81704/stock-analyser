#!/usr/bin/env python3
"""
Simulation of October 28, 2026 across Nifty 100 Stocks
WITHOUT the Index-Level Momentum Parameter (Pure Stock-Level Selection).

Parameters:
- Index-level condition: DISABLED (No Nifty 50 regime alignment, pure individual stock technicals)
- Initial Stop Loss: -0.90%
- Trailing Stop: +0.25% cost cushion at +0.90% advance, +0.90% runner lock at +1.20% advance
- Target: +1.40%
- EOD Square-off: 15:10 IST
- Exact Zerodha Intraday Equity Costs + 5 bps Slippage
"""

import sys
from pathlib import Path
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.costs.calculator import CostCalculator, ZerodhaIntradayCostsConfig
from src.algodesk.automation.daily_screener_trader import NIFTY_100_LIQUID_UNIVERSE
from scripts.simulate_todays_data import fetch_5m_candles

def run_oct28_no_index():
    target_date = "2026-10-28"
    print(f"=========================================================================")
    print(f"   OCT 28 SIMULATION: WITHOUT INDEX-LEVEL MOMENTUM (PURE STOCK-LEVEL)   ")
    print(f"=========================================================================\n")

    candles = fetch_5m_candles(NIFTY_100_LIQUID_UNIVERSE)
    cost_calc = CostCalculator(ZerodhaIntradayCostsConfig())

    day_bars = {}
    for sym, df in candles.items():
        df_day = df[df.index.strftime("%Y-%m-%d") == target_date]
        if len(df_day) >= 50:
            day_bars[sym] = df_day

    print(f"[Data] Loaded {len(day_bars)} stocks on {target_date}.")
    print("[Index Filter] Index-Level Parameter: DISABLED (Pure Stock Momentum & Volatility)\n")

    # Pure individual stock screening (No index bias or bonus)
    scored_candidates = []
    for sym, df in day_bars.items():
        mb = df.between_time("09:15", "09:30")
        if len(mb) < 3:
            continue

        open_p = float(mb.iloc[0]["Open"])
        close_p = float(mb.iloc[-1]["Close"])
        vol = float(mb["Volume"].sum())
        day_ret_pct = ((close_p - open_p) / open_p) * 100.0

        hi_p = float(mb["High"].max())
        lo_p = float(mb["Low"].min())

        bull_score = max(0.0, day_ret_pct * 15.0) + (10.0 if close_p >= hi_p * 0.998 else 0.0)
        bear_score = max(0.0, -day_ret_pct * 15.0) + (10.0 if close_p <= lo_p * 1.002 else 0.0)

        # Pure Stock-Level Direction Decision (No index condition bonus)
        if (bear_score > bull_score and day_ret_pct <= 0.0) or (day_ret_pct <= -0.75):
            side = "SELL"
            score = bear_score
            trigger_p = round(close_p * 0.996, 2)
        else:
            side = "BUY"
            score = bull_score
            trigger_p = round(close_p * 1.004, 2)

        scored_candidates.append({
            "symbol": sym,
            "side": side,
            "score": round(score, 1),
            "morning_close": close_p,
            "trigger_p": trigger_p,
            "day_ret_pct": round(day_ret_pct, 2)
        })

    scored_candidates.sort(key=lambda x: x["score"], reverse=True)
    top_5_picks = scored_candidates[:5]

    print("[Screener Picks - Pure Stock Level (No Index Parameter)]:")
    for rank, p in enumerate(top_5_picks, 1):
        print(f"  #{rank}: {p['symbol']:<12} | Side: {p['side']:<4} | Conviction Score: {p['score']:>4.1f} | Morning Close: ₹{p['morning_close']:>7.2f} | Trigger: ₹{p['trigger_p']:>7.2f} | 09:15-09:30 Ret: {p['day_ret_pct']:+.2f}%")

    initial_capital = 100000.0
    leverage = 5.0
    slot_capital = (initial_capital * leverage) / 5.0
    slippage_pct = 0.0005

    executed_trades = []

    for pick in top_5_picks:
        sym = pick["symbol"]
        side = pick["side"]
        df_stock = day_bars[sym]
        trade_bars = df_stock.between_time("09:35", "15:10")
        trig = pick["trigger_p"]

        entry_bar = None
        for ts, b in trade_bars.iterrows():
            if ts.time() > pd.to_datetime("14:45").time():
                break
            if side == "BUY" and float(b["High"]) >= trig:
                entry_bar = (ts, max(float(b["Open"]), trig))
                break
            elif side == "SELL" and float(b["Low"]) <= trig:
                entry_bar = (ts, min(float(b["Open"]), trig))
                break

        if not entry_bar:
            print(f"  [-] {sym}: Did not hit trigger ₹{trig:.2f} (Safely Filtered).")
            continue

        entry_time, raw_entry = entry_bar
        eff_entry = raw_entry * (1.0 + slippage_pct if side == "BUY" else 1.0 - slippage_pct)
        qty = int(slot_capital / eff_entry)
        if qty <= 0:
            continue

        if side == "BUY":
            target_p = eff_entry * 1.0140
            initial_sl = eff_entry * (1.0 - 0.0090)
            current_sl = initial_sl
            t1_trig = eff_entry * 1.0090
            t1_lock = eff_entry * 1.0025
            t2_trig = eff_entry * 1.0120
            t2_lock = eff_entry * 1.0090
        else:
            target_p = eff_entry * (1.0 - 0.0140)
            initial_sl = eff_entry * 1.0090
            current_sl = initial_sl
            t1_trig = eff_entry * (1.0 - 0.0090)
            t1_lock = eff_entry * 0.9975
            t2_trig = eff_entry * (1.0 - 0.0120)
            t2_lock = eff_entry * 0.9910

        remaining_bars = trade_bars.loc[entry_time:]
        highest_favorable = eff_entry
        exit_price = None
        exit_time = None
        exit_reason = None

        for ts, b in remaining_bars.iterrows():
            if ts == entry_time:
                continue

            b_high = float(b["High"])
            b_low = float(b["Low"])
            b_close = float(b["Close"])

            if side == "BUY":
                highest_favorable = max(highest_favorable, b_high)
                if highest_favorable >= t2_trig:
                    current_sl = max(current_sl, t2_lock)
                elif highest_favorable >= t1_trig:
                    current_sl = max(current_sl, t1_lock)

                if b_high >= target_p:
                    exit_price = target_p * (1.0 - slippage_pct)
                    exit_time = ts
                    exit_reason = "TARGET_HIT (+1.4%)"
                    break
                elif b_low <= current_sl:
                    exit_price = current_sl * (1.0 - slippage_pct)
                    exit_time = ts
                    exit_reason = "TRAILING_SL_HIT" if current_sl > eff_entry else "STOP_LOSS_HIT (-0.9%)"
                    break
            else:
                highest_favorable = min(highest_favorable, b_low)
                if highest_favorable <= t2_trig:
                    current_sl = min(current_sl, t2_lock)
                elif highest_favorable <= t1_trig:
                    current_sl = min(current_sl, t1_lock)

                if b_low <= target_p:
                    exit_price = target_p * (1.0 + slippage_pct)
                    exit_time = ts
                    exit_reason = "TARGET_HIT (-1.4%)"
                    break
                elif b_high >= current_sl:
                    exit_price = current_sl * (1.0 + slippage_pct)
                    exit_time = ts
                    exit_reason = "TRAILING_SL_HIT" if current_sl < eff_entry else "STOP_LOSS_HIT (+0.9%)"
                    break

        if exit_price is None:
            last_b = remaining_bars.iloc[-1]
            exit_time = remaining_bars.index[-1]
            exit_price = float(last_b["Close"]) * (1.0 - slippage_pct if side == "BUY" else 1.0 + slippage_pct)
            exit_reason = "3PM_SQUAREOFF"

        breakdown = cost_calc.calculate_roundtrip(
            side="LONG" if side == "BUY" else "SHORT",
            qty=qty,
            raw_entry_price=eff_entry,
            raw_exit_price=exit_price,
            trailing_turnover_cr=150.0
        )
        gross_pnl = (exit_price - eff_entry) * qty if side == "BUY" else (eff_entry - exit_price) * qty
        costs = breakdown.total_costs
        net_pnl = gross_pnl - costs
        ret_pct = (net_pnl / (eff_entry * qty / leverage)) * 100.0

        executed_trades.append({
            "symbol": sym,
            "side": side,
            "entry_time": entry_time.strftime("%H:%M"),
            "entry_price": round(eff_entry, 2),
            "exit_time": exit_time.strftime("%H:%M"),
            "exit_price": round(exit_price, 2),
            "qty": qty,
            "gross_pnl": round(gross_pnl, 2),
            "brokerage_taxes": round(costs, 2),
            "net_pnl": round(net_pnl, 2),
            "return_pct": round(ret_pct, 2),
            "exit_reason": exit_reason
        })

    total_gross = sum(t["gross_pnl"] for t in executed_trades)
    total_costs = sum(t["brokerage_taxes"] for t in executed_trades)
    total_net = sum(t["net_pnl"] for t in executed_trades)
    winning_trades = [t for t in executed_trades if t["net_pnl"] > 0]
    losing_trades = [t for t in executed_trades if t["net_pnl"] < 0]
    win_rate = (len(winning_trades) / len(executed_trades) * 100.0) if executed_trades else 0.0

    print("\n" + "=" * 105)
    print(f"       INTRADAY TRADE LOGS: OCTOBER 28, 2026 (WITHOUT INDEX MOMENTUM PARAMETER)")
    print("=" * 105)
    print(f"{'Symbol':<12} | {'Side':<4} | {'Entry (IST)':<11} | {'Exit (IST)':<11} | {'Exit Reason':<23} | {'Gross P&L':>11} | {'Zerodha Fees':>12} | {'NET P&L':>11}")
    print("-" * 105)
    for t in executed_trades:
        print(f"{t['symbol']:<12} | {t['side']:<4} | ₹{t['entry_price']:<5.1f} ({t['entry_time']}) | ₹{t['exit_price']:<5.1f} ({t['exit_time']}) | {t['exit_reason']:<23} | ₹{t['gross_pnl']:>+10,.2f} | ₹{t['brokerage_taxes']:>11,.2f} | ₹{t['net_pnl']:>+10,.2f}")
    print("=" * 105)

    print(f"\nFINAL INTRADAY P&L SUMMARY (OCTOBER 28, 2026 - WITHOUT INDEX PARAMETER):")
    print(f"  Starting Capital:            ₹{initial_capital:,.2f}")
    print(f"  Total Trades Triggered:      {len(executed_trades)} of 5 candidate stocks")
    print(f"  Winning Trades:              {len(winning_trades)} ({win_rate:.1f}% Win Rate)")
    print(f"  Losing Trades:               {len(losing_trades)}")
    print(f"  Total Gross P&L:             ₹{total_gross:+,.2f}")
    print(f"  Brokerages & Statutory Taxes: ₹{total_costs:,.2f}")
    print(f"  ------------------------------------------------")
    print(f"  FINAL NET INTRADAY PROFIT:   ₹{total_net:+,.2f}  ({total_net/initial_capital*100:+.2f}% on Capital)")
    print(f"  ------------------------------------------------\n")

if __name__ == "__main__":
    run_oct28_no_index()
