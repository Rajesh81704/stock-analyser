#!/usr/bin/env python3
"""
Multi-Day Paper Trading Simulator: 28th & 29th Oct 2026
=========================================================
Downloads real 5-minute intraday candles across all NIFTY 100 stocks
and simulates the refined multi-session algorithmic trading strategy across
both consecutive market sessions:
  - Day 1: 2026-10-28 (09:15 to 15:00 IST)
  - Day 2: 2026-10-29 (09:15 to 15:00 IST)

Features:
- Realistic Zerodha MIS margin model (5x intraday leverage, dynamic margin recycling)
- Multi-tier trailing stop loss & profit lock
- 09:15-09:20 opening bell filter & overextended move veto (>2.0%)
- 14:15 afternoon entry cutoff & mandatory 15:00 EOD square-off
- Accurate Zerodha brokerage + STT + turnover + GST statutory calculation
- Day-by-day and cumulative multi-day P&L report
"""

import sys
import os
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import time as dt_time
import concurrent.futures
import pandas as pd
import yfinance as yf

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.costs.calculator import CostCalculator, ZerodhaIntradayCostsConfig
from src.algodesk.automation.daily_screener_trader import NIFTY_100_LIQUID_UNIVERSE

STARTING_CAPITAL = 100000.0
LEVERAGE = 5.0
MAX_CONCURRENT_POSITIONS = 5
MAX_DAILY_TRADES = 5
SLIPPAGE_PCT = 0.0005  # 5 bps slippage


def download_5m_candles_for_nifty100(symbols: List[str]) -> Dict[str, pd.DataFrame]:
    """Downloads 5-minute candles for the last 5 market days in parallel."""
    print(f"\n==========================================================================")
    print(f"📥 Downloading 5-minute candles for {len(symbols)} NIFTY 100 stocks (Last 5 Days)...")
    print(f"==========================================================================")

    candles_by_symbol = {}

    def fetch_single(sym: str):
        ticker_str = f"{sym}.NS"
        try:
            df = yf.download(ticker_str, period="5d", interval="5m", progress=False)
            if df is not None and not df.empty:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                df.columns = [str(c).title() for c in df.columns]

                # Compute VWAP for each calendar date independently
                df["DateOnly"] = df.index.date
                df_list = []
                for _, group in df.groupby("DateOnly"):
                    g = group.copy()
                    typical_price = (g["High"] + g["Low"] + g["Close"]) / 3.0
                    cum_vol = g["Volume"].cumsum()
                    cum_vol_val = (typical_price * g["Volume"]).cumsum()
                    g["VWAP"] = (cum_vol_val / cum_vol).fillna(g["Close"])
                    df_list.append(g)
                clean_df = pd.concat(df_list).drop(columns=["DateOnly"])
                return sym, clean_df
        except Exception:
            pass
        return sym, None

    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as executor:
        futures = {executor.submit(fetch_single, sym): sym for sym in symbols}
        for future in concurrent.futures.as_completed(futures):
            sym, df = future.result()
            if df is not None and len(df) >= 30:
                candles_by_symbol[sym] = df

    print(f"✅ Successfully downloaded multi-day 5m candles for {len(candles_by_symbol)}/{len(symbols)} stocks.")
    return candles_by_symbol


def rank_opening_candidates(
    candles_by_symbol: Dict[str, pd.DataFrame],
    target_date_str: str
) -> List[Dict[str, Any]]:
    """
    Ranks stocks based on the opening 5-minute candle (09:15 - 09:20 IST):
    Filters out runaway gaps (> 2.0%) and selects high relative-volume thrusts.
    """
    candidates = []
    for sym, df in candles_by_symbol.items():
        try:
            day_df = df.loc[target_date_str]
        except KeyError:
            continue

        if day_df is None or len(day_df) < 5:
            continue

        # First 5-minute bar (09:15 to 09:20)
        b0 = day_df.iloc[0]
        open_p = float(b0["Open"])
        close_p = float(b0["Close"])
        high_p = float(b0["High"])
        low_p = float(b0["Low"])
        vol_0 = float(b0["Volume"])

        if open_p <= 0:
            continue

        ret_pct = ((close_p - open_p) / open_p) * 100.0
        range_pct = ((high_p - low_p) / open_p) * 100.0

        # Overextended Gap Filter: Skip moves > 2.0% to avoid exhaustion short squeezes/tops
        if abs(ret_pct) > 2.0:
            continue

        side = "BUY" if ret_pct >= 0 else "SELL"
        conviction = min(99.0, 65.0 + abs(ret_pct) * 10.0 + range_pct * 4.0)

        candidates.append({
            "symbol": sym,
            "base_price": open_p,
            "opening_high": high_p,
            "opening_low": low_p,
            "side": side,
            "ret_pct": ret_pct,
            "range_pct": range_pct,
            "volume": vol_0,
            "conviction": round(conviction, 1)
        })

    candidates.sort(key=lambda x: x["conviction"] * (x["volume"] ** 0.3), reverse=True)
    return candidates


def simulate_single_day(
    day_str: str,
    candles_by_symbol: Dict[str, pd.DataFrame],
    starting_capital: float
) -> Dict[str, Any]:
    """Simulates one complete intraday market session (09:15 - 15:00 IST)."""
    cost_calc = CostCalculator(ZerodhaIntradayCostsConfig())

    candidates = rank_opening_candidates(candles_by_symbol, day_str)

    # Filter candles for this specific day
    day_candles = {}
    all_timestamps = set()
    for sym, df in candles_by_symbol.items():
        try:
            sub = df.loc[day_str]
            if len(sub) >= 20:
                day_candles[sym] = sub
                all_timestamps.update(sub.index)
        except KeyError:
            pass

    sorted_timestamps = sorted(list(all_timestamps))

    open_positions: List[Dict[str, Any]] = []
    closed_trades: List[Dict[str, Any]] = []
    traded_symbols = set()

    total_account_equity = starting_capital
    available_margin = starting_capital
    realized_pnl = 0.0
    total_costs = 0.0
    trades_taken_today = 0

    midday_highs = {}
    midday_lows = {}

    for ts in sorted_timestamps:
        current_time = ts.time()
        time_str = ts.strftime("%H:%M")

        # -------------------------------------------------------------
        # 1. Update Trailing SL and Targets for Open Positions
        # -------------------------------------------------------------
        positions_to_close = []
        for pos in open_positions:
            sym = pos["symbol"]
            if sym not in day_candles or ts not in day_candles[sym].index:
                continue

            bar = day_candles[sym].loc[ts]
            b_high = float(bar["High"])
            b_low = float(bar["Low"])
            b_close = float(bar["Close"])
            vwap = float(bar["VWAP"])

            entry_p = pos["entry_price"]
            side = pos["side"]
            current_sl = pos["current_sl"]
            target_p = pos["target_price"]
            highest_seen = max(pos["highest_price"], b_high)
            lowest_seen = min(pos["lowest_price"], b_low)
            pos["highest_price"] = highest_seen
            pos["lowest_price"] = lowest_seen

            exit_price = None
            exit_reason = None

            if side == "BUY":
                gain_pct = ((highest_seen - entry_p) / entry_p) * 100.0
                if gain_pct >= 0.8:
                    pos["current_sl"] = max(pos["current_sl"], entry_p * 1.0025)  # Breakeven lock +0.25%
                if gain_pct >= 1.2:
                    pos["current_sl"] = max(pos["current_sl"], entry_p * 1.0080)  # Profit lock +0.80%

                if b_high >= target_p:
                    exit_price = target_p * (1.0 - SLIPPAGE_PCT)
                    exit_reason = f"TARGET (+{pos['target_pct']:.1f}%)"
                elif b_low <= pos["current_sl"]:
                    exit_price = pos["current_sl"] * (1.0 - SLIPPAGE_PCT)
                    if pos["current_sl"] > entry_p:
                        exit_reason = "TRAILING_STOP (PROFIT_LOCK)"
                    else:
                        exit_reason = f"STOP_LOSS (-{pos['sl_pct']:.1f}%)"
            else:  # SELL
                drop_pct = ((entry_p - lowest_seen) / entry_p) * 100.0
                if drop_pct >= 0.8:
                    pos["current_sl"] = min(pos["current_sl"], entry_p * 0.9975)  # Breakeven lock +0.25%
                if drop_pct >= 1.2:
                    pos["current_sl"] = min(pos["current_sl"], entry_p * 0.9920)  # Profit lock +0.80%

                if b_low <= target_p:
                    exit_price = target_p * (1.0 + SLIPPAGE_PCT)
                    exit_reason = f"TARGET (+{pos['target_pct']:.1f}%)"
                elif b_high >= pos["current_sl"]:
                    exit_price = pos["current_sl"] * (1.0 + SLIPPAGE_PCT)
                    if pos["current_sl"] < entry_p:
                        exit_reason = "TRAILING_STOP (PROFIT_LOCK)"
                    else:
                        exit_reason = f"STOP_LOSS (-{pos['sl_pct']:.1f}%)"

            # Mandatory 15:00 IST EOD Square-Off
            if current_time >= dt_time(15, 0):
                exit_price = b_close * (1.0 - SLIPPAGE_PCT if side == "BUY" else 1.0 + SLIPPAGE_PCT)
                exit_reason = "EOD_SQUAREOFF (15:00 IST)"

            if exit_price is not None:
                positions_to_close.append((pos, exit_price, exit_reason, time_str))

        # Close positions and recycle margin immediately
        for pos, exit_p, exit_r, exit_t in positions_to_close:
            open_positions.remove(pos)
            sym = pos["symbol"]
            qty = pos["qty"]
            side = pos["side"]
            entry_p = pos["entry_price"]
            alloc_m = pos["allocated_margin"]

            calc_side = "LONG" if side == "BUY" else "SHORT"
            gross_pnl = (exit_p - entry_p) * qty if side == "BUY" else (entry_p - exit_p) * qty
            trade_costs = cost_calc.calculate_roundtrip(
                side=calc_side, qty=qty, raw_entry_price=entry_p, raw_exit_price=exit_p
            ).total_costs

            net_pnl = gross_pnl - trade_costs
            realized_pnl += net_pnl
            total_costs += trade_costs

            # Margin recycled: original allocated margin + net PnL returned
            available_margin += (alloc_m + net_pnl)
            total_account_equity += net_pnl

            closed_trades.append({
                "date": day_str,
                "symbol": sym,
                "session": pos["session_id"],
                "side": side,
                "entry_time": pos["entry_time"],
                "entry_price": round(entry_p, 2),
                "exit_time": exit_t,
                "exit_price": round(exit_p, 2),
                "qty": qty,
                "margin": round(alloc_m, 2),
                "gross_pnl": round(gross_pnl, 2),
                "costs": round(trade_costs, 2),
                "net_pnl": round(net_pnl, 2),
                "reason": exit_r
            })

        # Track midday range (11:30 - 13:30)
        if dt_time(11, 30) <= current_time <= dt_time(13, 30):
            for sym, df_day in day_candles.items():
                if ts in df_day.index:
                    b = df_day.loc[ts]
                    midday_highs[sym] = max(midday_highs.get(sym, float(b["High"])), float(b["High"]))
                    midday_lows[sym] = min(midday_lows.get(sym, float(b["Low"])), float(b["Low"]))

        # -------------------------------------------------------------
        # 2. Market Hour Regime & Scan for New Opportunities
        # -------------------------------------------------------------
        # Strict Locks: No entries before 09:20 or after 14:15
        if current_time < dt_time(9, 20) or current_time >= dt_time(14, 15):
            continue

        if trades_taken_today >= MAX_DAILY_TRADES:
            continue

        slots_left = min(MAX_CONCURRENT_POSITIONS - len(open_positions), MAX_DAILY_TRADES - trades_taken_today)
        if slots_left <= 0 or available_margin < 2000.0:
            continue

        # Strategy Dispatch
        if dt_time(9, 20) <= current_time < dt_time(11, 30):
            session_id = "MORNING_EXPANSION"
            strategy_id = "ORB_MOMENTUM_BREAKOUT"
        elif dt_time(11, 30) <= current_time < dt_time(13, 30):
            # Midday preservation: 0 new chase breakout entries
            continue
        elif dt_time(13, 30) <= current_time < dt_time(14, 15):
            session_id = "AFTERNOON_POWER"
            strategy_id = "POWER_HOUR_MOMENTUM_RUNNER"
        else:
            continue

        for cand in candidates:
            if slots_left <= 0 or available_margin < 2000.0 or trades_taken_today >= MAX_DAILY_TRADES:
                break

            sym = cand["symbol"]
            if sym in traded_symbols or sym in [p["symbol"] for p in open_positions]:
                continue
            if sym not in day_candles or ts not in day_candles[sym].index:
                continue

            bar = day_candles[sym].loc[ts]
            cmp_p = float(bar["Close"])
            b_high = float(bar["High"])
            b_low = float(bar["Low"])
            vwap = float(bar["VWAP"])
            op_h = cand["opening_high"]
            op_l = cand["opening_low"]
            base_p = cand["base_price"]
            side = cand["side"]

            is_entry = False
            target_pct = 0.0
            sl_pct = 0.0

            if strategy_id == "ORB_MOMENTUM_BREAKOUT":
                if side == "BUY":
                    if b_high >= op_h * 1.001 and cmp_p > vwap and cmp_p > base_p:
                        is_entry = True
                        target_pct = 1.2
                        sl_pct = 0.8
                else:  # SELL
                    if b_low <= op_l * 0.999 and cmp_p < vwap and cmp_p < base_p:
                        is_entry = True
                        target_pct = 1.2
                        sl_pct = 0.8
            elif strategy_id == "POWER_HOUR_MOMENTUM_RUNNER":
                m_high = midday_highs.get(sym, op_h)
                m_low = midday_lows.get(sym, op_l)
                if side == "BUY":
                    if cmp_p > vwap and b_high >= m_high * 1.0005:
                        is_entry = True
                        target_pct = 1.2
                        sl_pct = 0.65
                else:
                    if cmp_p < vwap and b_low <= m_low * 0.9995:
                        is_entry = True
                        target_pct = 1.2
                        sl_pct = 0.65

            if is_entry:
                eff_entry = cmp_p * (1.0 + SLIPPAGE_PCT if side == "BUY" else 1.0 - SLIPPAGE_PCT)
                alloc_m = min(available_margin, available_margin / max(1, slots_left))
                qty = max(1, int((alloc_m * LEVERAGE) / eff_entry))
                actual_margin = (qty * eff_entry) / LEVERAGE

                if side == "BUY":
                    target_price = eff_entry * (1.0 + target_pct / 100.0)
                    initial_sl = eff_entry * (1.0 - sl_pct / 100.0)
                else:
                    target_price = eff_entry * (1.0 - target_pct / 100.0)
                    initial_sl = eff_entry * (1.0 + sl_pct / 100.0)

                open_positions.append({
                    "symbol": sym,
                    "session_id": session_id,
                    "strategy_id": strategy_id,
                    "side": side,
                    "entry_time": time_str,
                    "entry_price": eff_entry,
                    "qty": qty,
                    "allocated_margin": actual_margin,
                    "current_sl": initial_sl,
                    "target_price": target_price,
                    "highest_price": eff_entry,
                    "lowest_price": eff_entry,
                    "target_pct": target_pct,
                    "sl_pct": sl_pct
                })

                available_margin -= actual_margin
                slots_left -= 1
                trades_taken_today += 1
                traded_symbols.add(sym)

    # Any remaining open position squared off at 15:00
    for pos in list(open_positions):
        sym = pos["symbol"]
        df_sym = day_candles[sym]
        last_close = float(df_sym.iloc[-1]["Close"])
        side = pos["side"]
        qty = pos["qty"]
        entry_p = pos["entry_price"]
        alloc_m = pos["allocated_margin"]
        exit_p = last_close * (1.0 - SLIPPAGE_PCT if side == "BUY" else 1.0 + SLIPPAGE_PCT)

        calc_side = "LONG" if side == "BUY" else "SHORT"
        gross_pnl = (exit_p - entry_p) * qty if side == "BUY" else (entry_p - exit_p) * qty
        trade_costs = cost_calc.calculate_roundtrip(
            side=calc_side, qty=qty, raw_entry_price=entry_p, raw_exit_price=exit_p
        ).total_costs
        net_pnl = gross_pnl - trade_costs
        realized_pnl += net_pnl
        total_costs += trade_costs
        total_account_equity += net_pnl

        closed_trades.append({
            "date": day_str,
            "symbol": sym,
            "session": pos["session_id"],
            "side": side,
            "entry_time": pos["entry_time"],
            "entry_price": round(entry_p, 2),
            "exit_time": "15:00",
            "exit_price": round(exit_p, 2),
            "qty": qty,
            "margin": round(alloc_m, 2),
            "gross_pnl": round(gross_pnl, 2),
            "costs": round(trade_costs, 2),
            "net_pnl": round(net_pnl, 2),
            "reason": "EOD_SQUAREOFF (15:00 IST)"
        })

    winning = [t for t in closed_trades if t["net_pnl"] > 0]
    losing = [t for t in closed_trades if t["net_pnl"] <= 0]
    win_rate = (len(winning) / max(1, len(closed_trades))) * 100.0
    gross_total = sum(t["gross_pnl"] for t in closed_trades)

    return {
        "date": day_str,
        "starting_equity": starting_capital,
        "ending_equity": total_account_equity,
        "trades": closed_trades,
        "total_trades": len(closed_trades),
        "wins": len(winning),
        "losses": len(losing),
        "win_rate": win_rate,
        "gross_pnl": gross_total,
        "costs": total_costs,
        "net_pnl": realized_pnl,
        "return_pct": ((total_account_equity - starting_capital) / starting_capital) * 100.0
    }


def main():
    candles = download_5m_candles_for_nifty100(NIFTY_100_LIQUID_UNIVERSE)

    days_to_simulate = ["2026-10-28", "2026-10-29"]
    current_equity = STARTING_CAPITAL
    day_results = []

    print("\n" + "=" * 90)
    print("🚀 STARTING 2-DAY CONSECUTIVE PAPER TRADING SIMULATION (28th & 29th Oct 2026)")
    print(f"💰 Initial Starting Capital: ₹{STARTING_CAPITAL:,.2f} | Leverage: {LEVERAGE:.0f}x MIS Intraday")
    print("=" * 90)

    for d in days_to_simulate:
        res = simulate_single_day(d, candles, current_equity)
        day_results.append(res)
        current_equity = res["ending_equity"]

    # Print Day 1 and Day 2 detailed audit logs
    for res in day_results:
        d = res["date"]
        print(f"\n==========================================================================================")
        print(f"📅 SESSION REPORT: {d} (09:15 - 15:00 IST)")
        print(f"==========================================================================================")
        print(f"• Starting Margin: ₹{res['starting_equity']:,.2f} | Ending Margin: ₹{res['ending_equity']:,.2f}")
        print(f"• Trades: {res['total_trades']} | Wins: {res['wins']} | Losses: {res['losses']} | Win Rate: {res['win_rate']:.1f}%")
        print(f"• Gross P&L: ₹{res['gross_pnl']:+,.2f} | Brokerage & Taxes: ₹{res['costs']:,.2f} | Net P&L: ₹{res['net_pnl']:+,.2f} ({res['return_pct']:+.2f}%)")
        print("\n--- Detailed Trade Log ---")
        print(f"{'Symbol':<12} {'Side':<5} {'Entry':<6} {'Entry Price':<11} {'Exit':<6} {'Exit Price':<11} {'Margin':<10} {'Net P&L':<11} {'Reason'}")
        print("-" * 90)
        for t in res["trades"]:
            print(f"{t['symbol']:<12} {t['side']:<5} {t['entry_time']:<6} ₹{t['entry_price']:<10.2f} {t['exit_time']:<6} ₹{t['exit_price']:<10.2f} ₹{t['margin']:<9.2f} ₹{t['net_pnl']:<10.2f} {t['reason']}")

    # Print Cumulative Multi-Day Summary
    all_trades = []
    for r in day_results:
        all_trades.extend(r["trades"])

    cum_gross = sum(r["gross_pnl"] for r in day_results)
    cum_costs = sum(r["costs"] for r in day_results)
    cum_net = sum(r["net_pnl"] for r in day_results)
    total_wins = sum(r["wins"] for r in day_results)
    total_losses = sum(r["losses"] for r in day_results)
    overall_win_rate = (total_wins / max(1, len(all_trades))) * 100.0
    total_roi = ((current_equity - STARTING_CAPITAL) / STARTING_CAPITAL) * 100.0

    print("\n" + "=" * 90)
    print("🏆 CUMULATIVE 2-DAY CONSECUTIVE PAPER TRADING SUMMARY")
    print("=" * 90)
    print(f"• Initial Starting Capital : ₹{STARTING_CAPITAL:,.2f}")
    print(f"• Final Account Equity     : ₹{current_equity:,.2f}")
    print(f"• Total Trades Taken       : {len(all_trades)} across 2 days")
    print(f"• Overall Win Rate         : {overall_win_rate:.1f}% ({total_wins} Wins / {total_losses} Losses)")
    print(f"• Cumulative Gross Profit  : ₹{cum_gross:+,.2f}")
    print(f"• Total Brokerage & Taxes  : ₹{cum_costs:,.2f} (Zerodha Cost Model)")
    print(f"• Net Realized Profit      : ₹{cum_net:+,.2f}")
    print(f"• Net Return on Capital    : {total_roi:+.2f}%")
    print("=" * 90 + "\n")


if __name__ == "__main__":
    main()
