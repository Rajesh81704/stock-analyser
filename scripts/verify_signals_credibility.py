"""
Signal Credibility Verification Script

Fetches today's (or historical) screener picks and runs all 8 strategy verifiers:
1. Support & Resistance (Pivot Points + Swing Highs/Lows)
2. VWAP Confluence
3. Volume/RVOL Confirmation
4. Bollinger Band Position
5. RSI Overbought/Oversold Guard
6. MACD Signal Alignment
7. Ichimoku Cloud Confluence
8. Candlestick Pattern Recognition

Usage:
  python scripts/verify_signals_credibility.py [--date 2026-10-29] [--symbols RELIANCE,TCS]
"""

import sys
import argparse
import logging
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s"
)
logger = logging.getLogger("VerifyScript")

import pandas as pd
from src.data_loader import fetch_stock_data, resolve_ticker
from src.algodesk.signal_verifier import (
    verify_signal_credibility,
    batch_verify_signals,
    format_verification_report,
    calc_pivot_points,
    find_swing_highs_lows,
)


# ──── NIFTY 100 Universe (liquid tradeable stocks)
DEFAULT_SYMBOLS = [
    "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "BHARTIARTL",
    "INFY", "ITC", "SBIN", "HINDUNILVR", "LT", "BAJFINANCE",
    "MARUTI", "SUNPHARMA", "AXISBANK", "KOTAKBANK", "TITAN",
    "TATAMOTORS", "NTPC", "TATASTEEL", "POWERGRID", "ADANIENT",
]


def load_historical_picks_from_db(date_str: str, db_path: str = "data/stock_screener.db"):
    """Load screener picks from the SQLite database for a given date."""
    import sqlite3
    picks = []
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT symbol, side, price, rvol, conviction_score, strategy_name
            FROM daily_intraday_picks
            WHERE date = ?
            ORDER BY rank ASC
        """, (date_str,))
        rows = cur.fetchall()
        conn.close()
        for r in rows:
            picks.append({
                "symbol": r["symbol"],
                "side": r["side"] or "BUY",
                "price": float(r["price"] or 0),
                "rvol": float(r["rvol"] or 1.0),
                "rsi": 55.0,  # default if not stored
                "conviction_score": float(r["conviction_score"] or 0),
                "strategy_name": r["strategy_name"],
            })
        logger.info(f"Loaded {len(picks)} picks from DB for {date_str}")
    except Exception as e:
        logger.warning(f"Could not load from DB ({e}), using default symbols")
    return picks


def compute_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(window=period).mean()
    loss = (-delta.clip(upper=0)).rolling(window=period).mean()
    rs = gain / (loss + 1e-8)
    return float((100 - (100 / (1 + rs))).iloc[-1])


def compute_rvol(series, window=20):
    latest_vol = float(series.iloc[-1])
    avg_vol = float(series.iloc[-window:].mean())
    return latest_vol / avg_vol if avg_vol > 0 else 1.0


def main():
    parser = argparse.ArgumentParser(description="Multi-Strategy Signal Credibility Verifier")
    parser.add_argument("--date", default=None, help="Date YYYY-MM-DD (default: today)")
    parser.add_argument("--symbols", default=None, help="Comma-separated symbols (e.g. RELIANCE,TCS)")
    parser.add_argument("--side", default=None, help="Force signal side: BUY or SELL")
    parser.add_argument("--min-credibility", type=float, default=55.0, help="Min credibility score (default 55)")
    parser.add_argument("--verbose", action="store_true", help="Show detailed sub-scores for each symbol")
    args = parser.parse_args()

    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")
    date_str = args.date or datetime.now(IST).date().isoformat()
    logger.info(f"Running Signal Credibility Verification for date: {date_str}")
    logger.info("=" * 80)

    # Load picks from DB if date is historical
    picks = load_historical_picks_from_db(date_str)

    # If no picks found in DB, build from manual list or args
    if not picks:
        symbols = [s.strip().upper() for s in args.symbols.split(",")] if args.symbols else DEFAULT_SYMBOLS
        default_side = (args.side or "BUY").upper()
        picks = [{"symbol": s, "side": default_side, "price": 0.0, "rvol": 1.0, "rsi": 55.0, "conviction_score": 0.0}
                 for s in symbols]
        logger.info(f"No DB picks found. Verifying {len(symbols)} symbols: {symbols}")

    # Force side if specified
    if args.side:
        for p in picks:
            p["side"] = args.side.upper()

    # Fetch OHLCV data for all symbols
    logger.info(f"\nFetching OHLCV data for {len(picks)} symbols...")
    df_map = {}
    vwap_map = {}

    for pick in picks:
        sym = pick["symbol"]
        try:
            resolved = resolve_ticker(sym)
            df = fetch_stock_data(resolved, period="3mo")
            if df is not None and len(df) >= 30:
                df.columns = [str(c).lower() for c in df.columns]

                # Compute RSI and RVOL from fetched data if not in pick
                if pick.get("rsi", 55.0) == 55.0:
                    try:
                        pick["rsi"] = compute_rsi(df["close"])
                    except Exception:
                        pass
                if pick.get("rvol", 1.0) == 1.0:
                    try:
                        pick["rvol"] = compute_rvol(df["volume"])
                    except Exception:
                        pass
                if pick.get("price", 0.0) == 0.0:
                    pick["price"] = float(df["close"].iloc[-1])

                df_map[sym] = df
                logger.info(f"  {sym}: {len(df)} bars | Close: {pick['price']:.2f} | RSI: {pick['rsi']:.1f} | RVOL: {pick['rvol']:.2f}x")
            else:
                logger.warning(f"  {sym}: insufficient data ({len(df) if df is not None else 0} bars)")
        except Exception as e:
            logger.error(f"  {sym}: fetch error - {e}")

    logger.info(f"\nFetched OHLCV for {len(df_map)}/{len(picks)} symbols")
    logger.info("=" * 80)

    # Run verification for each pick individually with detailed output
    all_results = []

    for pick in picks:
        sym = pick["symbol"]
        side = str(pick.get("side", "BUY")).upper()
        price = float(pick.get("price") or 0.0)
        rvol = float(pick.get("rvol") or 1.0)
        rsi = float(pick.get("rsi") or 50.0)

        df = df_map.get(sym)
        if df is None or price <= 0:
            logger.warning(f"\nSkipping {sym}: no data or zero price")
            continue

        print(f"\n{'─'*70}")
        print(f"VERIFYING: {sym} | Side: {side} | Price: Rs{price:.2f} | RVOL: {rvol:.2f}x | RSI: {rsi:.1f}")
        print(f"{'─'*70}")

        result = verify_signal_credibility(
            symbol=sym,
            side=side,
            curr_price=price,
            df=df,
            rvol=rvol,
            rsi=rsi,
            vwap=vwap_map.get(sym),
            verbose=args.verbose,
        )
        result["original_conviction"] = float(pick.get("conviction_score") or 0.0)
        all_results.append(result)

        # Print sub-scores
        grade = result["credibility_grade"]
        rec   = result["trade_recommendation"]
        score = result["credibility_score"]

        print(f"  CREDIBILITY: {score:.1f}/100 [{grade}] | RECOMMENDATION: {rec}")
        print(f"  Original Conviction: {result['original_conviction']:.1f}")
        print()
        print("  Strategy Sub-Scores:")
        for strat, data in result["sub_scores"].items():
            sc = data["score"]
            bar = "#" * int(sc) + "-" * (10 - int(sc))
            reason_short = data["reason"][:60]
            print(f"    {strat:<22} [{bar}] {sc:4.1f}/10  {reason_short}")

        pivot = result.get("pivot_data", {})
        if pivot:
            print(f"\n  Pivot Levels: P={pivot.get('pivot','?')} | R1={pivot.get('r1','?')} | "
                  f"R2={pivot.get('r2','?')} | S1={pivot.get('s1','?')} | S2={pivot.get('s2','?')}")

        sr = result.get("sr_levels", {})
        supp = sr.get("support_levels", [])
        resi = sr.get("resistance_levels", [])
        if supp: print(f"  Support Levels:    {[round(x,2) for x in supp[-3:]]}")
        if resi: print(f"  Resistance Levels: {[round(x,2) for x in resi[-3:]]}")

        print(f"\n  Key Factors:")
        for reason in result.get("key_reasons", [])[:3]:
            print(f"    - {reason[:75]}")

    # ── Summary Table ──
    print("\n" + "=" * 80)
    print("SIGNAL CREDIBILITY SUMMARY")
    print("=" * 80)
    print(f"{'Symbol':<12} {'Side':<5} {'Price':>8} {'Conv':>6} {'Cred':>6} {'Grade':<10} {'Recommendation'}")
    print("-" * 80)

    passed, rejected = 0, 0
    for r in sorted(all_results, key=lambda x: x["credibility_score"], reverse=True):
        grade = r["credibility_grade"]
        rec   = r["trade_recommendation"]
        sym   = r["symbol"]
        side  = r["side"]
        price = r["curr_price"]
        conv  = r.get("original_conviction", 0)
        cred  = r["credibility_score"]

        status = "PASS" if cred >= args.min_credibility else "FAIL"
        if status == "PASS":
            passed += 1
        else:
            rejected += 1

        print(f"{sym:<12} {side:<5} {price:>8.2f} {conv:>6.1f} {cred:>6.1f} {grade:<10} {rec}")

    print("-" * 80)
    print(f"Total: {len(all_results)} | Passed (>={args.min_credibility:.0f}): {passed} | Rejected: {rejected}")
    print("=" * 80)

    # Which signals would have been traded?
    tradeable = [r for r in all_results if r["trade_recommendation"] in ("PROCEED", "PROCEED_HALF_SIZE")]
    if tradeable:
        print(f"\nTRADEABLE SIGNALS ({len(tradeable)}):")
        for r in tradeable:
            sizing = "Full" if r["trade_recommendation"] == "PROCEED" else "Half-Size"
            print(f"  {r['symbol']} ({r['side']}) @ Rs{r['curr_price']:.2f} | {r['credibility_score']:.1f}/100 [{r['credibility_grade']}] -> {sizing} position")
    else:
        print("\nNo signals met credibility threshold for trading.")


if __name__ == "__main__":
    main()
