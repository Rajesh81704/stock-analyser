#!/usr/bin/env python3
"""
Intraday Strategy Simulation on 29th Oct 2026 across NIFTY 100 Universe with 5-Minute Candles.
============================================================================================
Downloads real-time 5-minute candle data for all 100 stocks on 2026-10-29 and simulates:
1. Updated Multi-Session Strategy:
   - 09:15-09:30: Opening Range Discovery (Establishes 15m ORB & VWAP, No Entries)
   - 09:30-11:30: Morning Expansion (15m ORB High/Low + VWAP Confluence)
   - 11:30-13:30: Midday European Session (VWAP Pullback Support Reversion, Vetoes Breakout Traps)
   - 13:30-14:45: Afternoon Power-Hour (Consolidation Box Breakout)
   - Zerodha 5x MIS margin recycling & dynamic trailing stop-loss
2. Baseline Comparison (Old Naive Strategy without ORB wait or VWAP gates)
"""

import sys
import os
import time
from pathlib import Path
from datetime import datetime, time as dt_time
from typing import Dict, List, Optional, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import yfinance as yf

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.costs.calculator import CostCalculator, ZerodhaIntradayCostsConfig
from src.algodesk.automation.daily_screener_trader import NIFTY_100_LIQUID_UNIVERSE

TARGET_DATE = "2026-10-29"
INITIAL_CAPITAL = 100000.0
LEVERAGE = 5.0
MAX_CONCURRENT_POSITIONS = 5
MAX_DAILY_TRADES = 10
SLIPPAGE_PCT = 0.0005  # 5 bps slippage

def download_5m_candles_for_nifty100(symbols: List[str]) -> Dict[str, pd.DataFrame]:
    """Downloads today's 5-minute candles for all Nifty 100 stocks in parallel."""
    print(f"\n==========================================================================")
    print(f"📥 Downloading today's ({TARGET_DATE}) 5-minute candles for {len(symbols)} NIFTY 100 stocks...")
    print(f"==========================================================================")

    tickers = [f"{s}.NS" for s in symbols]
    candles_by_symbol = {}

    def fetch_single(sym: str):
        ticker_str = f"{sym}.NS"
        try:
            df = yf.download(ticker_str, period="1d", interval="5m", progress=False)
            if df is not None and not df.empty:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                df.columns = [str(c).title() for c in df.columns]
                # Filter for today only
                df = df[df.index.strftime("%Y-%m-%d") == TARGET_DATE]
                if len(df) >= 3:
                    # Calculate cumulative VWAP
                    typical_price = (df["High"] + df["Low"] + df["Close"]) / 3.0
                    cum_vol = df["Volume"].cumsum()
                    cum_tp_vol = (typical_price * df["Volume"]).cumsum()
                    df["VWAP"] = (cum_tp_vol / cum_vol.replace(0, np.nan)).ffill().bfill()
                    return sym, df
        except Exception as e:
            pass
        return sym, None

    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = {executor.submit(fetch_single, sym): sym for sym in symbols}
        for fut in as_completed(futures):
            sym, df = fut.result()
            if df is not None:
                candles_by_symbol[sym] = df

    print(f"✅ Successfully downloaded 5-minute candles for {len(candles_by_symbol)}/{len(symbols)} NIFTY 100 stocks.")
    if candles_by_symbol:
        sample_sym = next(iter(candles_by_symbol.keys()))
        sample_df = candles_by_symbol[sample_sym]
        print(f"   Sample ({sample_sym}): {len(sample_df)} bars from {sample_df.index[0].strftime('%H:%M')} to {sample_df.index[-1].strftime('%H:%M')} IST")
    return candles_by_symbol


def compute_premarket_scores(candles_by_symbol: Dict[str, pd.DataFrame]) -> List[Dict[str, Any]]:
    """Ranks stocks based on initial 15m opening volatility, volume and momentum."""
    candidates = []
    for sym, df in candles_by_symbol.items():
        m_bars = df.between_time("09:15", "09:30")
        if len(m_bars) >= 3:
            open_p = float(m_bars.iloc[0]["Open"])
            close_p = float(m_bars.iloc[-1]["Close"])
            orb_h = float(m_bars["High"].max())
            orb_l = float(m_bars["Low"].min())
            vol_sum = float(m_bars["Volume"].sum())
            ret_pct = ((close_p - open_p) / open_p) * 100.0
            range_pct = ((orb_h - orb_l) / open_p) * 100.0

            # Side determination based on opening thrust
            side = "BUY" if ret_pct >= 0 else "SELL"
            conviction = min(99.0, 65.0 + abs(ret_pct) * 8.0 + range_pct * 4.0)

            # Overextended Gap Filter: Skip runaway gaps (> 2.0%) to eliminate sharp mean-reversion counter-trend traps
            if abs(ret_pct) > 2.0:
                continue

            candidates.append({
                "symbol": sym,
                "base_price": open_p,
                "orb_high": orb_h,
                "orb_low": orb_l,
                "side": side,
                "ret_pct": ret_pct,
                "range_pct": range_pct,
                "volume": vol_sum,
                "conviction": round(conviction, 1)
            })

    candidates.sort(key=lambda x: x["conviction"], reverse=True)
    return candidates


def simulate_multisession_engine(
    candles_by_symbol: Dict[str, pd.DataFrame],
    candidates: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Executes the updated multi-session strategy bar-by-bar across 2026-10-29:
    1. 09:15 - 09:30: Discovery (no trades)
    2. 09:30 - 11:30: Morning Expansion (15m ORB + VWAP)
    3. 11:30 - 13:30: Midday European (VWAP Pullback Reversion)
    4. 13:30 - 14:45: Afternoon Power-Hour (Consolidation Breakout)
    5. Margin recycling: freed capital immediately reused.
    """
    cost_calc = CostCalculator(ZerodhaIntradayCostsConfig())

    # Build union of bar timestamps in chronological order
    all_timestamps = set()
    for df in candles_by_symbol.values():
        all_timestamps.update(df.index)
    sorted_timestamps = sorted(list(all_timestamps))

    open_positions: List[Dict[str, Any]] = []
    closed_trades: List[Dict[str, Any]] = []
    traded_symbols = set()

    total_capital = INITIAL_CAPITAL
    available_margin = INITIAL_CAPITAL
    realized_pnl = 0.0

    trades_taken_today = 0

    cand_dict = {c["symbol"]: c for c in candidates}

    # Track midday range (11:30 - 13:30) for afternoon power hour
    midday_highs = {}
    midday_lows = {}

    for ts in sorted_timestamps:
        current_time = ts.time()
        time_str = ts.strftime("%H:%M")

        # -----------------------------------------------------------------
        # Step A: Update Trailing Stop Losses & Check Exits for Open Positions
        # -----------------------------------------------------------------
        positions_to_close = []
        for pos in open_positions:
            sym = pos["symbol"]
            if sym not in candles_by_symbol or ts not in candles_by_symbol[sym].index:
                continue

            bar = candles_by_symbol[sym].loc[ts]
            b_open = float(bar["Open"])
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
                # Trailing step adjustment
                gain_pct = ((highest_seen - entry_p) / entry_p) * 100.0
                if gain_pct >= 0.8:
                    pos["current_sl"] = max(pos["current_sl"], entry_p * 1.0025)  # Breakeven lock +0.25%
                if gain_pct >= 1.2:
                    pos["current_sl"] = max(pos["current_sl"], entry_p * 1.0080)  # Profit lock +0.80%

                # Check Target Hit
                if b_high >= target_p:
                    exit_price = target_p * (1.0 - SLIPPAGE_PCT)
                    exit_reason = f"TARGET (+{pos['target_pct']:.1f}%)"
                # Check Stop Loss Hit
                elif b_low <= pos["current_sl"]:
                    exit_price = pos["current_sl"] * (1.0 - SLIPPAGE_PCT)
                    if pos["current_sl"] > entry_p:
                        exit_reason = "TRAILING_STOP (PROFIT_LOCK)"
                    else:
                        exit_reason = f"STOP_LOSS (-{pos['sl_pct']:.1f}%)"
                # Check VWAP Invalidation Exit (After 11:30, if price drops below VWAP by >0.2%, exit early)
                elif current_time >= dt_time(11, 30) and b_close < vwap * 0.998:
                    exit_price = b_close * (1.0 - SLIPPAGE_PCT)
                    exit_reason = "VWAP_INVALIDATION (CUT_EARLY)"
            else:  # SELL (Short)
                drop_pct = ((entry_p - lowest_seen) / entry_p) * 100.0
                if drop_pct >= 0.8:
                    pos["current_sl"] = min(pos["current_sl"], entry_p * 0.9975)  # Breakeven lock +0.25%
                if drop_pct >= 1.2:
                    pos["current_sl"] = min(pos["current_sl"], entry_p * 0.9920)  # Profit lock +0.80%

                # Check Target Hit
                if b_low <= target_p:
                    exit_price = target_p * (1.0 + SLIPPAGE_PCT)
                    exit_reason = f"TARGET (+{pos['target_pct']:.1f}%)"
                # Check Stop Loss Hit
                elif b_high >= pos["current_sl"]:
                    exit_price = pos["current_sl"] * (1.0 + SLIPPAGE_PCT)
                    if pos["current_sl"] < entry_p:
                        exit_reason = "TRAILING_STOP (PROFIT_LOCK)"
                    else:
                        exit_reason = f"STOP_LOSS (-{pos['sl_pct']:.1f}%)"
                # Check VWAP Invalidation Exit (After 11:30, if price rallies above VWAP by >0.2%, exit early)
                elif current_time >= dt_time(11, 30) and b_close > vwap * 1.002:
                    exit_price = b_close * (1.0 + SLIPPAGE_PCT)
                    exit_reason = "VWAP_INVALIDATION (CUT_EARLY)"

            # Check EOD 15:00 Square-Off
            if current_time >= dt_time(15, 0):
                exit_price = b_close * (1.0 - SLIPPAGE_PCT if side == "BUY" else 1.0 + SLIPPAGE_PCT)
                exit_reason = "EOD_SQUAREOFF (15:00 IST)"
            elif exit_price is None:
                pass

            if exit_price is not None:
                positions_to_close.append((pos, exit_price, exit_reason, time_str))

        # Process closed positions & recycle Zerodha margin immediately
        for pos, exit_p, exit_r, exit_t in positions_to_close:
            open_positions.remove(pos)
            sym = pos["symbol"]
            qty = pos["qty"]
            side = pos["side"]
            entry_p = pos["entry_price"]
            alloc_m = pos["allocated_margin"]

            calc_side = "LONG" if side == "BUY" else "SHORT"
            if side == "BUY":
                gross_pnl = (exit_p - entry_p) * qty
            else:
                gross_pnl = (entry_p - exit_p) * qty

            costs = cost_calc.calculate_roundtrip(
                side=calc_side,
                qty=qty,
                raw_entry_price=entry_p,
                raw_exit_price=exit_p
            ).total_costs

            net_pnl = gross_pnl - costs
            realized_pnl += net_pnl

            # Zerodha margin recycling: margin released + net P&L restored to account
            margin_restored = max(0.0, alloc_m + net_pnl)
            available_margin += margin_restored

            closed_trades.append({
                "symbol": sym,
                "strategy": pos["strategy_id"],
                "session": pos["session_id"],
                "side": side,
                "entry_time": pos["entry_time"],
                "entry_price": round(entry_p, 2),
                "exit_time": exit_t,
                "exit_price": round(exit_p, 2),
                "qty": qty,
                "allocated_margin": round(alloc_m, 2),
                "gross_pnl": round(gross_pnl, 2),
                "costs": round(costs, 2),
                "net_pnl": round(net_pnl, 2),
                "return_on_margin": round((net_pnl / alloc_m) * 100.0, 2),
                "exit_reason": exit_r
            })

        # Track midday highs and lows (11:30 - 13:30)
        if dt_time(11, 30) <= current_time <= dt_time(13, 30):
            for sym, df in candles_by_symbol.items():
                if ts in df.index:
                    b = df.loc[ts]
                    midday_highs[sym] = max(midday_highs.get(sym, float(b["High"])), float(b["High"]))
                    midday_lows[sym] = min(midday_lows.get(sym, float(b["Low"])), float(b["Low"]))

        # -----------------------------------------------------------------
        # Step B: Determine Market Hour Session & Scan for Entries
        # -----------------------------------------------------------------
        # Hard lock: No trading before 09:30 or after 14:15
        if current_time < dt_time(9, 30) or current_time >= dt_time(14, 15):
            continue

        # Daily limits check
        if trades_taken_today >= MAX_DAILY_TRADES:
            continue
        slots_left = min(MAX_CONCURRENT_POSITIONS - len(open_positions), MAX_DAILY_TRADES - trades_taken_today)
        if slots_left <= 0 or available_margin < 2000.0:
            continue

        # Identify Session
        if dt_time(9, 30) <= current_time < dt_time(11, 30):
            session_id = "MORNING_EXPANSION"
            strategy_id = "ORB_MOMENTUM_BREAKOUT"
        elif dt_time(11, 30) <= current_time < dt_time(13, 30):
            session_id = "MIDDAY_EUROPEAN"
            strategy_id = "VWAP_PULLBACK_REVERSION"
        elif dt_time(13, 30) <= current_time < dt_time(14, 15):
            session_id = "AFTERNOON_POWER"
            strategy_id = "POWER_HOUR_MOMENTUM_RUNNER"
        else:
            continue

        # Scan candidate pool for confirmed triggers
        for cand in candidates:
            if slots_left <= 0 or available_margin < 2000.0 or trades_taken_today >= MAX_DAILY_TRADES:
                break

            sym = cand["symbol"]
            if sym in traded_symbols or sym in [p["symbol"] for p in open_positions]:
                continue
            if sym not in candles_by_symbol or ts not in candles_by_symbol[sym].index:
                continue

            bar = candles_by_symbol[sym].loc[ts]
            cmp_p = float(bar["Close"])
            b_high = float(bar["High"])
            b_low = float(bar["Low"])
            vwap = float(bar["VWAP"])
            orb_h = cand["orb_high"]
            orb_l = cand["orb_low"]
            base_p = cand["base_price"]
            side = cand["side"]

            is_entry = False
            target_pct = 0.0
            sl_pct = 0.0

            # -------------------------------------------------------------
            # Strategy 1: MORNING_EXPANSION (09:30 - 11:30)
            # -------------------------------------------------------------
            if strategy_id == "ORB_MOMENTUM_BREAKOUT":
                if side == "BUY":
                    if b_high >= orb_h * 1.001 and cmp_p > vwap and cmp_p > base_p:
                        is_entry = True
                        target_pct = 1.5
                        sl_pct = 0.8
                else:  # SELL
                    if b_low <= orb_l * 0.999 and cmp_p < vwap and cmp_p < base_p:
                        is_entry = True
                        target_pct = 1.5
                        sl_pct = 0.8

            # -------------------------------------------------------------
            # Strategy 2: MIDDAY_EUROPEAN (11:30 - 13:30) - Anti Breakout Trap
            # -------------------------------------------------------------
            elif strategy_id == "VWAP_PULLBACK_REVERSION":
                if side == "BUY":
                    if (vwap <= cmp_p <= vwap * 1.007) and (cmp_p < orb_h * 0.998):
                        is_entry = True
                        target_pct = 1.0
                        sl_pct = 0.5
                else:  # SELL
                    if (vwap * 0.993 <= cmp_p <= vwap) and (cmp_p > orb_l * 1.002):
                        is_entry = True
                        target_pct = 1.0
                        sl_pct = 0.5

            # -------------------------------------------------------------
            # Strategy 3: AFTERNOON_POWER (13:30 - 14:45)
            # -------------------------------------------------------------
            elif strategy_id == "POWER_HOUR_MOMENTUM_RUNNER":
                m_high = midday_highs.get(sym, orb_h)
                m_low = midday_lows.get(sym, orb_l)
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
                    init_sl = eff_entry * (1.0 - (sl_pct / 100.0))
                    target_p = eff_entry * (1.0 + (target_pct / 100.0))
                else:
                    init_sl = eff_entry * (1.0 + (sl_pct / 100.0))
                    target_p = eff_entry * (1.0 - (target_pct / 100.0))

                open_positions.append({
                    "symbol": sym,
                    "side": side,
                    "strategy_id": strategy_id,
                    "session_id": session_id,
                    "entry_time": time_str,
                    "entry_price": eff_entry,
                    "qty": qty,
                    "allocated_margin": actual_margin,
                    "current_sl": init_sl,
                    "target_price": target_p,
                    "initial_sl": init_sl,
                    "highest_price": eff_entry,
                    "lowest_price": eff_entry,
                    "target_pct": target_pct,
                    "sl_pct": sl_pct
                })

                available_margin -= actual_margin
                slots_left -= 1
                trades_taken_today += 1
                traded_symbols.add(sym)

    # Any remaining open positions at end of session get squared off at 15:00
    for pos in list(open_positions):
        sym = pos["symbol"]
        df = candles_by_symbol[sym]
        last_close = float(df.iloc[-1]["Close"])
        side = pos["side"]
        qty = pos["qty"]
        entry_p = pos["entry_price"]
        alloc_m = pos["allocated_margin"]
        exit_p = last_close * (1.0 - SLIPPAGE_PCT if side == "BUY" else 1.0 + SLIPPAGE_PCT)

        calc_side = "LONG" if side == "BUY" else "SHORT"
        gross_pnl = (exit_p - entry_p) * qty if side == "BUY" else (entry_p - exit_p) * qty
        costs = cost_calc.calculate_roundtrip(side=calc_side, qty=qty, raw_entry_price=entry_p, raw_exit_price=exit_p).total_costs
        net_pnl = gross_pnl - costs
        realized_pnl += net_pnl

        closed_trades.append({
            "symbol": sym,
            "strategy": pos["strategy_id"],
            "session": pos["session_id"],
            "side": side,
            "entry_time": pos["entry_time"],
            "entry_price": round(entry_p, 2),
            "exit_time": "15:00",
            "exit_price": round(exit_p, 2),
            "qty": qty,
            "allocated_margin": round(alloc_m, 2),
            "gross_pnl": round(gross_pnl, 2),
            "costs": round(costs, 2),
            "net_pnl": round(net_pnl, 2),
            "return_on_margin": round((net_pnl / alloc_m) * 100.0, 2),
            "exit_reason": "EOD_SQUAREOFF (15:00 IST)"
        })
    open_positions.clear()

    return {
        "closed_trades": closed_trades,
        "total_trades_entered": len(closed_trades),
        "total_closed": len(closed_trades),
        "total_realized_pnl": round(realized_pnl, 2),
        "total_net_pnl": round(realized_pnl, 2)
    }


def simulate_old_naive_strategy(
    candles_by_symbol: Dict[str, pd.DataFrame],
    candidates: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Simulates the OLD naive strategy (enters at 09:16 immediately without waiting
    for 15m ORB or VWAP confluence, fixed +1.4% target and -1.0% stop-loss).
    """
    cost_calc = CostCalculator(ZerodhaIntradayCostsConfig())
    top_5 = candidates[:5]

    trades = []
    for cand in top_5:
        sym = cand["symbol"]
        if sym not in candles_by_symbol:
            continue
        df = candles_by_symbol[sym]
        if len(df) < 5:
            continue

        entry_bar = df.iloc[0] # 09:15-09:20 open tick
        entry_p = float(entry_bar["Open"]) * (1.0 + SLIPPAGE_PCT)
        qty = int((20000.0 * LEVERAGE) / entry_p)
        if qty <= 0:
            continue

        target_p = entry_p * 1.014
        sl_p = entry_p * 0.990

        exit_p = None
        exit_r = None
        exit_t = None

        for ts, bar in df.iloc[1:].iterrows():
            b_high = float(bar["High"])
            b_low = float(bar["Low"])
            if b_high >= target_p:
                exit_p = target_p * (1.0 - SLIPPAGE_PCT)
                exit_r = "TARGET (+1.4%)"
                exit_t = ts.strftime("%H:%M")
                break
            elif b_low <= sl_p:
                exit_p = sl_p * (1.0 - SLIPPAGE_PCT)
                exit_r = "STOP_LOSS (-1.0%)"
                exit_t = ts.strftime("%H:%M")
                break

        if exit_p is None:
            last_b = df.iloc[-1]
            exit_p = float(last_b["Close"]) * (1.0 - SLIPPAGE_PCT)
            exit_r = "RUNNING_MTM"
            exit_t = df.index[-1].strftime("%H:%M")

        gross = (exit_p - entry_p) * qty
        costs = cost_calc.calculate_roundtrip("LONG", qty, entry_p, exit_p).total_costs
        net = gross - costs

        trades.append({
            "symbol": sym,
            "side": "BUY",
            "entry_time": "09:15",
            "entry_price": round(entry_p, 2),
            "exit_time": exit_t,
            "exit_price": round(exit_p, 2),
            "qty": qty,
            "gross_pnl": round(gross, 2),
            "costs": round(costs, 2),
            "net_pnl": round(net, 2),
            "exit_reason": exit_r
        })

    return {
        "trades": trades,
        "total_net_pnl": round(sum(t["net_pnl"] for t in trades), 2),
        "win_rate": round(len([t for t in trades if t["net_pnl"] > 0]) / max(1, len(trades)) * 100.0, 1)
    }


def main():
    candles = download_5m_candles_for_nifty100(NIFTY_100_LIQUID_UNIVERSE)
    if not candles:
        print("❌ Could not download candle data.")
        return

    candidates = compute_premarket_scores(candles)
    print(f"\n==========================================================================")
    print(f"📊 Top 10 Screened Stocks on 2026-10-29 (Ranked by Conviction & Momentum):")
    print(f"==========================================================================")
    for i, c in enumerate(candidates[:10], 1):
        print(f" {i:2d}. {c['symbol']:<12} | Side: {c['side']:<4} | Base: ₹{c['base_price']:<8.2f} | 15m Range: ₹{c['orb_low']:.2f} - ₹{c['orb_high']:.2f} | Move: {c['ret_pct']:+5.2f}% | Conviction: {c['conviction']}")

    # 1. Run New Multi-Session Strategy
    print(f"\n🚀 Running Simulation with UPDATED Multi-Session Strategy...")
    new_res = simulate_multisession_engine(candles, candidates)

    # 2. Run Old Naive Strategy
    print(f"⏳ Running Baseline Comparison with OLD Naive Strategy...")
    old_res = simulate_old_naive_strategy(candles, candidates)

    print(f"\n" + "=" * 90)
    print(f"📈 COMPREHENSIVE PNL REPORT: 29th Oct 2026 (09:15 - 15:00 IST FULL DAY SESSION)")
    print(f"=" * 90)

    print(f"\n🔹 [UPDATED MULTI-SESSION STRATEGY]")
    all_new_trades = new_res["closed_trades"]
    total_gross = sum(t["gross_pnl"] for t in all_new_trades)
    total_costs = sum(t["costs"] for t in all_new_trades)
    total_net = sum(t["net_pnl"] for t in all_new_trades)
    win_cnt = len([t for t in all_new_trades if t["net_pnl"] > 0])
    loss_cnt = len([t for t in all_new_trades if t["net_pnl"] <= 0])
    win_rate = (win_cnt / len(all_new_trades) * 100.0) if all_new_trades else 0.0

    print(f"   Total Trades Taken: {len(all_new_trades)} (Closed: {len(all_new_trades)} | All Squared Off by 15:00 IST)")
    print(f"   Win Rate:           {win_rate:.1f}% ({win_cnt} Wins / {loss_cnt} Losses)")
    print(f"   Total Gross P&L:    ₹{total_gross:+,.2f}")
    print(f"   Brokerage & Taxes:  ₹{total_costs:,.2f}")
    print(f"   Final Realized P&L: ₹{total_net:+,.2f}")
    print(f"   Final Account Equity: ₹{INITIAL_CAPITAL + total_net:,.2f} (from ₹{INITIAL_CAPITAL:,.2f})")

    # Session Breakdown
    sessions = {}
    for t in all_new_trades:
        s = t["session"]
        if s not in sessions:
            sessions[s] = {"trades": 0, "wins": 0, "net_pnl": 0.0}
        sessions[s]["trades"] += 1
        if t["net_pnl"] > 0:
            sessions[s]["wins"] += 1
        sessions[s]["net_pnl"] += t["net_pnl"]

    print(f"\n--- Performance Breakdown by Market Session ---")
    for s_name, s_data in sessions.items():
        s_wr = (s_data["wins"] / s_data["trades"] * 100.0) if s_data["trades"] > 0 else 0.0
        print(f" • {s_name:<20}: {s_data['trades']} trades | Win Rate: {s_wr:5.1f}% | Net PnL: ₹{s_data['net_pnl']:+,.2f}")

    print(f"\n--- Detailed Trade-by-Trade Log (09:15 - 15:00 IST) ---")
    headers = f"{'Symbol':<12} {'Session':<18} {'Side':<5} {'Entry':<6} {'Price':<9} {'Exit':<6} {'Exit Price':<10} {'Margin':<10} {'Net PnL':<11} {'Reason':<25}"
    print(headers)
    print("-" * len(headers))
    for t in all_new_trades:
        exit_t = t.get("exit_time", "15:00")
        exit_p = t.get("exit_price", 0.0)
        reason = t.get("exit_reason", "")
        pnl_str = f"₹{t['net_pnl']:+,.2f}"
        print(f"{t['symbol']:<12} {t['session']:<18} {t['side']:<5} {t['entry_time']:<6} ₹{t['entry_price']:<8.2f} {exit_t:<6} ₹{exit_p:<9.2f} ₹{t['allocated_margin']:<9.2f} {pnl_str:<11} {reason:<25}")

    print(f"\n" + "-" * 90)
    print(f"🔸 [OLD NAIVE STRATEGY (Baseline Comparison)]")
    print(f"   Total Trades Taken: {len(old_res['trades'])}")
    print(f"   Combined Total P&L: ₹{old_res['total_net_pnl']:+,.2f}")
    print(f"   Win Rate:           {old_res['win_rate']:.1f}%")

    print(f"\n--- Trade Breakdown (Old Naive Strategy) ---")
    for t in old_res["trades"]:
        pnl_str = f"₹{t['net_pnl']:+,.2f}"
        print(f"• {t['symbol']:<12} Entry: ₹{t['entry_price']:<8.2f} (09:15) | Exit: ₹{t['exit_price']:<8.2f} ({t['exit_time']}) | Net PnL: {pnl_str:<10} | {t['exit_reason']}")

    print(f"\n" + "=" * 90)
    alpha = new_res["total_net_pnl"] - old_res["total_net_pnl"]
    print(f"🏆 Strategy Alpha Improvement: ₹{alpha:+,.2f}")
    print(f"=" * 90 + "\n")

if __name__ == "__main__":
    main()
