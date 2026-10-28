#!/usr/bin/env python3
"""
Full Simulation Trade across October 28, 2026 on Nifty 100 Stocks to Final Intraday PnL.

Incorporating:
1. Overall Index Condition (NIFTY 50 regime & direction alignment)
2. Bidirectional Signals (Long Breakout & Short Breakdown)
3. Initial Stop Loss: -0.90%
4. Multi-tier Dynamic Trailing:
   - At +0.90% advance: SL trails to Cost + 0.25% (guaranteeing net positive after friction)
   - At +1.20% advance: SL trails to +0.90% runner lock
5. Target: +1.40%
6. EOD Square-off: 15:10 IST
7. Exact Zerodha Intraday Equity Costs + 5 bps Slippage
8. Persists into SQLite table `daily_intraday_trades` in data/stock_screener.db
"""

import sys
import sqlite3
import json
from pathlib import Path
from datetime import datetime
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.costs.calculator import CostCalculator, ZerodhaIntradayCostsConfig
from src.algodesk.automation.daily_screener_trader import NIFTY_100_LIQUID_UNIVERSE, DB_PATH
from scripts.simulate_todays_data import fetch_5m_candles

def run_oct28_simulation():
    target_date = "2026-10-28"
    print(f"=========================================================================")
    print(f"   STARTING OCT 28 SIMULATION ACROSS NIFTY 100 WITH LATEST CALIBRATION  ")
    print(f"=========================================================================\n")

    candles = fetch_5m_candles(NIFTY_100_LIQUID_UNIVERSE)
    cost_calc = CostCalculator(ZerodhaIntradayCostsConfig())

    # Filter Day's 5-minute bars
    day_bars = {}
    for sym, df in candles.items():
        df_day = df[df.index.strftime("%Y-%m-%d") == target_date]
        if len(df_day) >= 50:
            day_bars[sym] = df_day

    print(f"\n[Data] Loaded complete 5-minute intraday bars for {len(day_bars)} stocks on {target_date}.")

    # 1. Determine Overall Index Condition on Oct 28
    # Calculate universe average morning return from 09:15 to 09:30
    morning_returns = []
    for sym, df in day_bars.items():
        mb = df.between_time("09:15", "09:30")
        if len(mb) >= 3:
            ret = ((float(mb.iloc[-1]["Close"]) - float(mb.iloc[0]["Open"])) / float(mb.iloc[0]["Open"])) * 100.0
            morning_returns.append(ret)

    mkt_avg_chg = float(np.mean(morning_returns)) if morning_returns else 0.0
    if mkt_avg_chg >= 0.15:
        mkt_regime = "BULLISH"
    elif mkt_avg_chg <= -0.15:
        mkt_regime = "BEARISH"
    else:
        mkt_regime = "NEUTRAL"

    print(f"[Market Condition] Broad Market / Index Regime: {mkt_regime} (Avg Morning Change: {mkt_avg_chg:+.2f}%)")

    # 2. Multi-factor Screening & Signal Generation with Index Alignment
    scored_candidates = []
    for sym, df in day_bars.items():
        mb = df.between_time("09:15", "09:30")
        if len(mb) < 3:
            continue

        open_p = float(mb.iloc[0]["Open"])
        close_p = float(mb.iloc[-1]["Close"])
        vol = float(mb["Volume"].sum())
        day_ret_pct = ((close_p - open_p) / open_p) * 100.0

        # High/Low ranges for breakout/breakdown proximity
        hi_p = float(mb["High"].max())
        lo_p = float(mb["Low"].min())

        bull_score = max(0.0, day_ret_pct * 15.0) + (10.0 if close_p >= hi_p * 0.998 else 0.0)
        bear_score = max(0.0, -day_ret_pct * 15.0) + (10.0 if close_p <= lo_p * 1.002 else 0.0)

        # Factor in Index Condition
        if mkt_regime == "BULLISH":
            bull_score += 15.0
            bear_score = max(0.0, bear_score - 15.0)
        elif mkt_regime == "BEARISH":
            bear_score += 15.0
            bull_score = max(0.0, bull_score - 15.0)

        if mkt_regime == "BEARISH":
            is_short = (bear_score > bull_score - 5.0) or (day_ret_pct <= -0.3)
        elif mkt_regime == "BULLISH":
            is_short = (bear_score > bull_score + 15.0) and (day_ret_pct <= -0.8)
        else:
            is_short = (bear_score > bull_score and day_ret_pct <= 0.0)

        if is_short:
            side = "SELL"
            score = bear_score
            trigger_p = round(close_p * 0.996, 2) # -0.4% breakdown trigger
        else:
            side = "BUY"
            score = bull_score
            trigger_p = round(close_p * 1.004, 2) # +0.4% breakout trigger

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

    print(f"\n[Screener Picks] Selected Top 5 Signals Aligned with Index Condition:")
    for rank, p in enumerate(top_5_picks, 1):
        print(f"  #{rank}: {p['symbol']:<12} | Side: {p['side']:<4} | Conviction Score: {p['score']:>4.1f} | Base: ₹{p['morning_close']:>7.2f} | Trigger: ₹{p['trigger_p']:>7.2f}")

    # 3. Simulate Intraday Execution Bar-by-Bar (09:35 - 15:10 IST)
    initial_capital = 100000.0
    leverage = 5.0
    slot_capital = (initial_capital * leverage) / 5.0  # ₹100,000 exposure per position
    slippage_pct = 0.0005 # 5 bps

    executed_trades = []

    for pick in top_5_picks:
        sym = pick["symbol"]
        side = pick["side"]
        df_stock = day_bars[sym]
        trade_bars = df_stock.between_time("09:35", "15:10")
        trig = pick["trigger_p"]

        # Check entry trigger
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
            print(f"  [-] {sym}: Did not trigger breakout/breakdown (Safely Filtered).")
            continue

        entry_time, raw_entry = entry_bar
        eff_entry = raw_entry * (1.0 + slippage_pct if side == "BUY" else 1.0 - slippage_pct)
        qty = int(slot_capital / eff_entry)
        if qty <= 0:
            continue

        # Strategy Calibrated Rules
        if side == "BUY":
            target_p = eff_entry * 1.0140             # +1.40%
            initial_sl = eff_entry * (1.0 - 0.0090)   # -0.90%
            current_sl = initial_sl
            t1_trig = eff_entry * 1.0090             # +0.90% move
            t1_lock = eff_entry * 1.0025             # Lock Cost + 0.25%
            t2_trig = eff_entry * 1.0120             # +1.20% move
            t2_lock = eff_entry * 1.0090             # Lock +0.90% runner gain
        else: # SELL (SHORT)
            target_p = eff_entry * (1.0 - 0.0140)     # -1.40%
            initial_sl = eff_entry * 1.0090           # +0.90%
            current_sl = initial_sl
            t1_trig = eff_entry * (1.0 - 0.0090)     # -0.90% move
            t1_lock = eff_entry * 0.9975             # Lock Cost + 0.25%
            t2_trig = eff_entry * (1.0 - 0.0120)     # -1.20% move
            t2_lock = eff_entry * 0.9910             # Lock +0.90% runner gain

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
            else: # SELL
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

        # Exact Zerodha Cost Breakdown
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

        trade_item = {
            "date": target_date,
            "symbol": sym,
            "side": side,
            "entry_time": entry_time.strftime("%H:%M"),
            "entry_price": round(eff_entry, 2),
            "exit_time": exit_time.strftime("%H:%M"),
            "exit_price": round(exit_price, 2),
            "qty": qty,
            "allocated_capital": round((qty * eff_entry) / leverage, 2),
            "gross_pnl": round(gross_pnl, 2),
            "brokerage_taxes": round(costs, 2),
            "net_pnl": round(net_pnl, 2),
            "return_pct": round(ret_pct, 2),
            "exit_reason": exit_reason,
            "status": "CLOSED"
        }
        executed_trades.append(trade_item)

    # 4. Save into SQLite Database
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    # Clear previous trades for 2026-10-28 to avoid duplicates
    cur.execute("DELETE FROM daily_intraday_trades WHERE trade_date = ?", (target_date,))
    cur.execute("DELETE FROM daily_intraday_picks WHERE date = ?", (target_date,))

    for rank, p in enumerate(top_5_picks, 1):
        cur.execute("""
            INSERT INTO daily_intraday_picks (
                date, rank, symbol, company_name, sector, price, conviction_score,
                rvol, strategy_name, entry_trigger_price, initial_sl, target_price,
                trailing_step_pct, status, side, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            target_date, rank, p["symbol"], f"{p['symbol']} Ltd", "Nifty 100",
            p["morning_close"], p["score"], 1.5, "ORB_Calibrated_V5", p["trigger_p"],
            round(p["morning_close"] * (0.991 if p["side"] == "BUY" else 1.009), 2),
            round(p["morning_close"] * (1.014 if p["side"] == "BUY" else 0.986), 2),
            0.5, "TRIGGERED", p["side"], f"{target_date} 09:30:00"
        ))

    for t in executed_trades:
        cur.execute("""
            INSERT INTO daily_intraday_trades (
                trade_date, symbol, side, qty, allocated_capital, entry_time,
                entry_price, initial_sl, highest_price, current_sl, target_price,
                exit_time, exit_price, exit_reason, gross_pnl, brokerage_and_taxes,
                net_pnl, return_pct, status, price_history, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            t["date"], t["symbol"], t["side"], t["qty"], t["allocated_capital"],
            f"{target_date} {t['entry_time']}:00", t["entry_price"],
            round(t["entry_price"] * (0.991 if t["side"] == "BUY" else 1.009), 2),
            t["exit_price"], t["exit_price"],
            round(t["entry_price"] * (1.014 if t["side"] == "BUY" else 0.986), 2),
            f"{target_date} {t['exit_time']}:00", t["exit_price"], t["exit_reason"],
            t["gross_pnl"], t["brokerage_taxes"], t["net_pnl"], t["return_pct"],
            t["status"], "[]", f"{target_date} {t['exit_time']}:00"
        ))

    conn.commit()
    conn.close()

    # 5. Output Final Results
    total_gross = sum(t["gross_pnl"] for t in executed_trades)
    total_costs = sum(t["brokerage_taxes"] for t in executed_trades)
    total_net = sum(t["net_pnl"] for t in executed_trades)
    winning_trades = [t for t in executed_trades if t["net_pnl"] > 0]
    losing_trades = [t for t in executed_trades if t["net_pnl"] < 0]
    win_rate = (len(winning_trades) / len(executed_trades) * 100.0) if executed_trades else 0.0

    print("\n" + "=" * 105)
    print(f"             FINAL INTRADAY SIMULATION TRADE RESULTS: OCTOBER 28, 2026")
    print("=" * 105)
    print(f"{'Symbol':<12} | {'Side':<4} | {'Entry (IST)':<11} | {'Exit (IST)':<11} | {'Exit Reason':<23} | {'Gross P&L':>11} | {'Zerodha Fees':>12} | {'NET P&L':>11}")
    print("-" * 105)
    for t in executed_trades:
        print(f"{t['symbol']:<12} | {t['side']:<4} | ₹{t['entry_price']:<5.1f} ({t['entry_time']}) | ₹{t['exit_price']:<5.1f} ({t['exit_time']}) | {t['exit_reason']:<23} | ₹{t['gross_pnl']:>+10,.2f} | ₹{t['brokerage_taxes']:>11,.2f} | ₹{t['net_pnl']:>+10,.2f}")
    print("=" * 105)

    print(f"\nFINAL INTRADAY P&L SUMMARY (OCTOBER 28, 2026):")
    print(f"  Starting Capital:            ₹{initial_capital:,.2f}")
    print(f"  Total Trades Triggered:      {len(executed_trades)} of 5 candidate stocks")
    print(f"  Winning Trades:              {len(winning_trades)} ({win_rate:.1f}% Win Rate)")
    print(f"  Losing Trades:               {len(losing_trades)}")
    print(f"  Total Gross P&L:             ₹{total_gross:+,.2f}")
    print(f"  Brokerages & Statutory Taxes: ₹{total_costs:,.2f}")
    print(f"  ------------------------------------------------")
    print(f"  FINAL NET INTRADAY PROFIT:   ₹{total_net:+,.2f}  (+{total_net/initial_capital*100:+.2f}% on Capital)")
    print(f"  ------------------------------------------------\n")
    print(f"All trade logs successfully saved into database: {DB_PATH}")

if __name__ == "__main__":
    run_oct28_simulation()
