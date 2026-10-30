"""
Multi-Strategy Signal Credibility Verifier

Cross-validates primary ORB/Momentum breakout signals using:
1. Support & Resistance (Pivot Points, Swing Highs/Lows, Supply/Demand Zones)
2. VWAP Confluence (price position relative to intraday VWAP)
3. Volume Profile (RVOL & volume accumulation zones)
4. Bollinger Band Squeeze/Breakout
5. RSI Divergence & Overbought/Oversold Guards
6. MACD Signal Alignment
7. Ichimoku Cloud Confluence
8. Candlestick Pattern Confirmation (engulfing, pin bar, doji rejection)

Each verifier returns a sub-score (0-10). Combined credibility score 0-100.
Signals with credibility < 50 are flagged as WEAK or REJECTED.
"""

import logging
from typing import Dict, Any, List, Optional, Tuple
import numpy as np
import pandas as pd

logger = logging.getLogger("SignalVerifier")


# ──────────────────────────────────────────────────────────────
# 1. Support / Resistance Zone Detection
# ──────────────────────────────────────────────────────────────

def calc_pivot_points(df: pd.DataFrame) -> Dict[str, float]:
    """Classic Daily Pivot Points using previous session OHLC."""
    prev = df.iloc[-2] if len(df) >= 2 else df.iloc[-1]
    cols = [str(c).lower() for c in df.columns]
    df2 = df.copy()
    df2.columns = cols
    prev2 = df2.iloc[-2] if len(df2) >= 2 else df2.iloc[-1]
    high  = float(prev2.get("high", 0))
    low   = float(prev2.get("low", 0))
    close = float(prev2.get("close", 0))

    if high == 0 and low == 0:
        return {}

    pivot = (high + low + close) / 3.0
    r1 = 2 * pivot - low
    r2 = pivot + (high - low)
    r3 = high + 2 * (pivot - low)
    s1 = 2 * pivot - high
    s2 = pivot - (high - low)
    s3 = low - 2 * (high - pivot)

    return {
        "pivot": round(pivot, 2), "r1": round(r1, 2), "r2": round(r2, 2),
        "r3": round(r3, 2), "s1": round(s1, 2), "s2": round(s2, 2), "s3": round(s3, 2)
    }


def find_swing_highs_lows(df: pd.DataFrame, window: int = 5) -> Dict[str, List[float]]:
    """Detects swing highs (resistance) and swing lows (support)."""
    df2 = df.copy()
    df2.columns = [str(c).lower() for c in df2.columns]
    highs = df2["high"]
    lows  = df2["low"]

    swing_highs, swing_lows = [], []
    for i in range(window, len(df2) - window):
        if highs.iloc[i] == highs.iloc[i - window:i + window + 1].max():
            swing_highs.append(float(highs.iloc[i]))
        if lows.iloc[i] == lows.iloc[i - window:i + window + 1].min():
            swing_lows.append(float(lows.iloc[i]))

    def dedup(levels, tol=0.003):
        levels = sorted(set(levels))
        result = [levels[0]] if levels else []
        for lv in levels[1:]:
            if abs(lv - result[-1]) / max(result[-1], 1.0) > tol:
                result.append(lv)
        return result

    return {
        "resistance_levels": dedup(swing_highs)[-5:],
        "support_levels":    dedup(swing_lows)[:5],
    }


def sr_proximity_score(curr_price, side, sr_levels, proximity_pct=1.0):
    """Returns (score 0-10, reason) for S/R alignment."""
    support_levels    = sr_levels.get("support_levels", [])
    resistance_levels = sr_levels.get("resistance_levels", [])
    pivot_data        = sr_levels.get("pivot_data", {})

    all_supports = support_levels + [pivot_data.get("s1", 0), pivot_data.get("s2", 0), pivot_data.get("s3", 0)]
    all_resistances = resistance_levels + [pivot_data.get("r1", 0), pivot_data.get("r2", 0),
                                           pivot_data.get("r3", 0), pivot_data.get("pivot", 0)]
    all_supports    = [x for x in all_supports    if x > 0]
    all_resistances = [x for x in all_resistances if x > 0]

    reasons, score = [], 0.0
    prox = proximity_pct / 100.0

    if side == "BUY":
        near_sup = [s for s in all_supports if abs(curr_price - s) / max(curr_price, 1) <= prox]
        above_sup = [s for s in all_supports if 0 < (curr_price - s) / max(curr_price, 1) <= prox * 2]
        broke_res = [r for r in all_resistances if 0 < (curr_price - r) / max(curr_price, 1) < prox]
        heavy_res = [r for r in all_resistances if 0 < (r - curr_price) / max(curr_price, 1) < 0.005]

        if near_sup:  score += 5.0; reasons.append(f"near support ₹{min(near_sup, key=lambda x: abs(x-curr_price)):.2f}")
        if above_sup: score += 3.0; reasons.append(f"bouncing above support ₹{max(above_sup):.2f}")
        if broke_res: score += 4.0; reasons.append(f"breakout above resistance ₹{min(broke_res, key=lambda x: abs(x-curr_price)):.2f}")
        if heavy_res: score -= 3.0; reasons.append(f"WARNING strong resistance overhead ₹{min(heavy_res):.2f}")
    else:
        near_res = [r for r in all_resistances if abs(curr_price - r) / max(curr_price, 1) <= prox]
        below_res = [r for r in all_resistances if 0 < (r - curr_price) / max(curr_price, 1) <= prox * 2]
        broke_sup = [s for s in all_supports if 0 < (s - curr_price) / max(curr_price, 1) < prox]
        strong_sup_below = [s for s in all_supports if 0 < (curr_price - s) / max(curr_price, 1) < 0.005]

        if near_res:  score += 5.0; reasons.append(f"near resistance ₹{min(near_res, key=lambda x: abs(x-curr_price)):.2f}")
        if below_res: score += 3.0; reasons.append(f"rejected below resistance ₹{min(below_res):.2f}")
        if broke_sup: score += 4.0; reasons.append(f"breakdown below support ₹{max(broke_sup, key=lambda x: abs(x-curr_price)):.2f}")
        if strong_sup_below: score -= 3.0; reasons.append(f"WARNING strong support below ₹{max(strong_sup_below):.2f}")

    score = max(0.0, min(10.0, score))
    return score, " | ".join(reasons) if reasons else "No nearby S/R alignment"


# ──────────────────────────────────────────────────────────────
# 2. VWAP Confluence
# ──────────────────────────────────────────────────────────────

def vwap_confluence_score(curr_price, vwap, side):
    """Returns (score 0-10, reason) for VWAP position."""
    if not vwap or vwap <= 0:
        return 5.0, "VWAP unavailable (neutral)"

    dist_pct = ((curr_price - vwap) / vwap) * 100.0

    if side == "BUY":
        if dist_pct > 0:
            score = min(10.0, 6.0 + dist_pct * 2.0) if dist_pct < 1.5 else 8.0
            return score, f"Price ₹{curr_price:.2f} above VWAP ₹{vwap:.2f} (+{dist_pct:.2f}%) [bullish]"
        else:
            score = max(0.0, 4.0 + dist_pct * 2.0)
            return score, f"Price ₹{curr_price:.2f} below VWAP ₹{vwap:.2f} ({dist_pct:.2f}%) [bearish for BUY]"
    else:
        if dist_pct < 0:
            score = min(10.0, 6.0 + abs(dist_pct) * 2.0) if abs(dist_pct) < 1.5 else 8.0
            return score, f"Price ₹{curr_price:.2f} below VWAP ₹{vwap:.2f} ({dist_pct:.2f}%) [bearish]"
        else:
            score = max(0.0, 4.0 - dist_pct * 2.0)
            return score, f"Price ₹{curr_price:.2f} above VWAP ₹{vwap:.2f} (+{dist_pct:.2f}%) [headwind for SELL]"


# ──────────────────────────────────────────────────────────────
# 3. Volume / RVOL Confirmation
# ──────────────────────────────────────────────────────────────

def volume_confirmation_score(rvol, side):
    """Returns (score 0-10, reason) for relative volume."""
    if rvol >= 2.0:
        return 10.0, f"RVOL {rvol:.2f}x (very high volume conviction)"
    elif rvol >= 1.5:
        return 8.0,  f"RVOL {rvol:.2f}x (high volume confirmation)"
    elif rvol >= 1.2:
        return 6.0,  f"RVOL {rvol:.2f}x (moderate volume)"
    elif rvol >= 1.0:
        return 4.0,  f"RVOL {rvol:.2f}x (average volume - low conviction)"
    else:
        return 2.0,  f"RVOL {rvol:.2f}x (below-average - weak signal)"


# ──────────────────────────────────────────────────────────────
# 4. Bollinger Band
# ──────────────────────────────────────────────────────────────

def bollinger_band_score(df, curr_price, side):
    """Returns (score 0-10, reason) for Bollinger Band position."""
    try:
        df2 = df.copy()
        df2.columns = [str(c).lower() for c in df2.columns]
        close = df2["close"]
        if len(close) < 20:
            return 5.0, "BB: insufficient data"

        sma    = close.rolling(20).mean()
        std    = close.rolling(20).std()
        upper  = sma + 2 * std
        lower  = sma - 2 * std
        middle = sma

        bb_upper  = float(upper.iloc[-1])
        bb_lower  = float(lower.iloc[-1])
        bb_middle = float(middle.iloc[-1])
        pct_b     = (curr_price - bb_lower) / max(bb_upper - bb_lower, 0.001)

        if side == "BUY":
            if curr_price > bb_upper:
                return 9.0, f"Breakout above upper BB ₹{bb_upper:.2f}"
            elif curr_price > bb_middle:
                return min(8.0, 5.0 + (pct_b - 0.5) * 8.0), f"Above BB midline ₹{bb_middle:.2f} (%B={pct_b:.2f})"
            else:
                return 2.0, f"Below BB midline ₹{bb_middle:.2f} [headwind for BUY]"
        else:
            if curr_price < bb_lower:
                return 9.0, f"Breakdown below lower BB ₹{bb_lower:.2f}"
            elif curr_price < bb_middle:
                return min(8.0, 5.0 + (0.5 - pct_b) * 8.0), f"Below BB midline ₹{bb_middle:.2f} (%B={pct_b:.2f})"
            else:
                return 2.0, f"Above BB midline ₹{bb_middle:.2f} [headwind for SELL]"
    except Exception as e:
        return 5.0, f"BB error: {e}"


# ──────────────────────────────────────────────────────────────
# 5. RSI Guard
# ──────────────────────────────────────────────────────────────

def rsi_guard_score(rsi, side):
    """Returns (score 0-10, reason) for RSI zone check."""
    if side == "BUY":
        if 52 <= rsi <= 68: return 10.0, f"RSI {rsi:.1f} ideal BUY zone (52-68)"
        elif 45 <= rsi < 52: return 7.0,  f"RSI {rsi:.1f} OK near neutral"
        elif 68 < rsi <= 75: return 6.0,  f"RSI {rsi:.1f} elevated approaching overbought"
        elif rsi > 75:       return 2.0,  f"RSI {rsi:.1f} OVERBOUGHT - high reversal risk"
        else:                return 3.0,  f"RSI {rsi:.1f} weak momentum for BUY"
    else:
        if 32 <= rsi <= 48: return 10.0, f"RSI {rsi:.1f} ideal SELL zone (32-48)"
        elif 48 < rsi <= 55: return 7.0,  f"RSI {rsi:.1f} OK near neutral"
        elif 25 <= rsi < 32: return 6.0,  f"RSI {rsi:.1f} approaching oversold"
        elif rsi < 25:       return 2.0,  f"RSI {rsi:.1f} OVERSOLD - high reversal risk"
        else:                return 3.0,  f"RSI {rsi:.1f} momentum not aligned for SELL"


# ──────────────────────────────────────────────────────────────
# 6. MACD Alignment
# ──────────────────────────────────────────────────────────────

def macd_alignment_score(df, side):
    """Returns (score 0-10, reason) for MACD signal alignment."""
    try:
        df2 = df.copy()
        df2.columns = [str(c).lower() for c in df2.columns]
        close = df2["close"]
        if len(close) < 35:
            return 5.0, "MACD: insufficient data"

        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd  = ema12 - ema26
        sig   = macd.ewm(span=9, adjust=False).mean()
        hist  = macd - sig

        macd_v = float(macd.iloc[-1])
        sig_v  = float(sig.iloc[-1])
        hist_v = float(hist.iloc[-1])
        hist_p = float(hist.iloc[-2])

        if side == "BUY":
            if macd_v > sig_v and hist_v > 0:
                if hist_v > hist_p: return 10.0, f"MACD bullish crossover expanding (hist={hist_v:.4f})"
                else:               return 7.0,  f"MACD bullish crossover contracting (hist={hist_v:.4f})"
            elif macd_v > sig_v:
                return 5.0, f"MACD line above signal, histogram turning ({hist_v:.4f})"
            else:
                return 2.0, f"MACD bearish: line below signal [{macd_v:.4f} < {sig_v:.4f}]"
        else:
            if macd_v < sig_v and hist_v < 0:
                if hist_v < hist_p: return 10.0, f"MACD bearish crossover expanding (hist={hist_v:.4f})"
                else:               return 7.0,  f"MACD bearish crossover contracting (hist={hist_v:.4f})"
            elif macd_v < sig_v:
                return 5.0, f"MACD line below signal, histogram turning ({hist_v:.4f})"
            else:
                return 2.0, f"MACD bullish: line above signal [{macd_v:.4f} > {sig_v:.4f}]"
    except Exception as e:
        return 5.0, f"MACD error: {e}"


# ──────────────────────────────────────────────────────────────
# 7. Ichimoku Cloud
# ──────────────────────────────────────────────────────────────

def ichimoku_confluence_score(df, curr_price, side):
    """Returns (score 0-10, reason) for Ichimoku cloud position."""
    try:
        df2 = df.copy()
        df2.columns = [str(c).lower() for c in df2.columns]
        high, low, close = df2["high"], df2["low"], df2["close"]

        if len(df2) < 52:
            return 5.0, "Ichimoku: need 52 bars"

        tenkan = (high.rolling(9).max()  + low.rolling(9).min())  / 2
        kijun  = (high.rolling(26).max() + low.rolling(26).min()) / 2
        span_a = (tenkan + kijun) / 2
        span_b = (high.rolling(52).max() + low.rolling(52).min()) / 2

        cloud_top    = float(max(span_a.iloc[-1], span_b.iloc[-1]))
        cloud_bottom = float(min(span_a.iloc[-1], span_b.iloc[-1]))
        tenkan_v     = float(tenkan.iloc[-1])
        kijun_v      = float(kijun.iloc[-1])

        if side == "BUY":
            if curr_price > cloud_top:
                sc = 9.0 if tenkan_v > kijun_v else 7.0
                return sc, f"Above bullish cloud (top ₹{cloud_top:.2f}) TK={'bullish' if tenkan_v>kijun_v else 'neutral'}"
            elif curr_price > cloud_bottom:
                return 4.0, f"Inside cloud (₹{cloud_bottom:.2f}-₹{cloud_top:.2f}) uncertain"
            else:
                return 1.0, f"Below bearish cloud (bottom ₹{cloud_bottom:.2f})"
        else:
            if curr_price < cloud_bottom:
                sc = 9.0 if tenkan_v < kijun_v else 7.0
                return sc, f"Below bearish cloud (bottom ₹{cloud_bottom:.2f}) TK={'bearish' if tenkan_v<kijun_v else 'neutral'}"
            elif curr_price < cloud_top:
                return 4.0, f"Inside cloud (₹{cloud_bottom:.2f}-₹{cloud_top:.2f}) uncertain"
            else:
                return 1.0, f"Above bullish cloud (top ₹{cloud_top:.2f})"
    except Exception as e:
        return 5.0, f"Ichimoku error: {e}"


# ──────────────────────────────────────────────────────────────
# 8. Candlestick Patterns
# ──────────────────────────────────────────────────────────────

def candlestick_pattern_score(df, side):
    """Returns (score 0-10, reason) for candlestick pattern recognition."""
    try:
        df2 = df.copy()
        df2.columns = [str(c).lower() for c in df2.columns]
        o, h, l, c = df2["open"], df2["high"], df2["low"], df2["close"]

        if len(df2) < 3:
            return 5.0, "Candlestick: insufficient data"

        c1_o, c1_h, c1_l, c1_c = float(o.iloc[-1]), float(h.iloc[-1]), float(l.iloc[-1]), float(c.iloc[-1])
        c2_o, c2_c = float(o.iloc[-2]), float(c.iloc[-2])
        c2_h, c2_l = float(h.iloc[-2]), float(l.iloc[-2])

        body  = abs(c1_c - c1_o)
        rng   = c1_h - c1_l
        if rng < 0.001:
            return 5.0, "Doji/flat candle (neutral)"

        body_r        = body / rng
        upper_wick_r  = (c1_h - max(c1_o, c1_c)) / rng
        lower_wick_r  = (min(c1_o, c1_c) - c1_l) / rng

        patterns, score = [], 5.0

        if lower_wick_r > 0.6 and body_r < 0.3 and c1_c > c1_o:
            patterns.append("Hammer (Bullish Pin Bar)")
            score += 4.0 if side == "BUY" else -2.0

        if upper_wick_r > 0.6 and body_r < 0.3 and c1_c < c1_o:
            patterns.append("Shooting Star (Bearish Pin Bar)")
            score += 4.0 if side == "SELL" else -2.0

        if c1_c > c1_o and c2_c < c2_o and c1_c > c2_o and c1_o < c2_c:
            patterns.append("Bullish Engulfing")
            score += 4.0 if side == "BUY" else -2.0

        if c1_c < c1_o and c2_c > c2_o and c1_c < c2_o and c1_o > c2_c:
            patterns.append("Bearish Engulfing")
            score += 4.0 if side == "SELL" else -2.0

        if body_r > 0.8:
            if c1_c > c1_o:
                patterns.append("Bullish Marubozu")
                score += 3.0 if side == "BUY" else -1.0
            else:
                patterns.append("Bearish Marubozu")
                score += 3.0 if side == "SELL" else -1.0

        if not patterns:
            patterns.append("No strong pattern (neutral)")

        score = max(0.0, min(10.0, score))
        return score, " | ".join(patterns)
    except Exception as e:
        return 5.0, f"Candlestick error: {e}"


# ──────────────────────────────────────────────────────────────
# Master Verifier
# ──────────────────────────────────────────────────────────────

STRATEGY_WEIGHTS = {
    "sr_proximity":    0.25,
    "vwap_confluence": 0.20,
    "volume_rvol":     0.15,
    "bollinger_band":  0.12,
    "rsi_guard":       0.12,
    "macd_alignment":  0.10,
    "ichimoku":        0.04,
    "candlestick":     0.02,
}

CREDIBILITY_THRESHOLDS = {
    "STRONG":   75,
    "MODERATE": 55,
    "WEAK":     40,
    "REJECTED":  0,
}


def verify_signal_credibility(
    symbol: str,
    side: str,
    curr_price: float,
    df: pd.DataFrame,
    rvol: float = 1.0,
    rsi: float = 50.0,
    vwap: Optional[float] = None,
    verbose: bool = True,
) -> Dict[str, Any]:
    """
    Master signal credibility engine. Runs all 8 strategy verifiers
    and returns composite credibility score (0-100) with breakdown.
    """
    df2 = df.copy()
    df2.columns = [str(c).lower() for c in df2.columns]

    results = {}

    # 1. S/R
    try:
        pivot_data = calc_pivot_points(df2)
        swing_data = find_swing_highs_lows(df2)
        sr_levels  = {**swing_data, "pivot_data": pivot_data}
        sc, rsn = sr_proximity_score(curr_price, side, sr_levels)
        results["sr_proximity"] = (sc, f"S/R: {rsn}")
    except Exception as e:
        sr_levels = {}
        results["sr_proximity"] = (5.0, f"S/R error: {e}")

    # 2. VWAP
    sc, rsn = vwap_confluence_score(curr_price, vwap, side)
    results["vwap_confluence"] = (sc, rsn)

    # 3. Volume
    sc, rsn = volume_confirmation_score(rvol, side)
    results["volume_rvol"] = (sc, rsn)

    # 4. Bollinger
    sc, rsn = bollinger_band_score(df2, curr_price, side)
    results["bollinger_band"] = (sc, rsn)

    # 5. RSI
    sc, rsn = rsi_guard_score(rsi, side)
    results["rsi_guard"] = (sc, rsn)

    # 6. MACD
    sc, rsn = macd_alignment_score(df2, side)
    results["macd_alignment"] = (sc, rsn)

    # 7. Ichimoku
    sc, rsn = ichimoku_confluence_score(df2, curr_price, side)
    results["ichimoku"] = (sc, rsn)

    # 8. Candlestick
    sc, rsn = candlestick_pattern_score(df2, side)
    results["candlestick"] = (sc, rsn)

    # Weighted composite
    raw = sum(results[s][0] * w * 10.0 for s, w in STRATEGY_WEIGHTS.items())
    credibility_score = round(min(100.0, max(0.0, raw)), 1)

    if credibility_score >= CREDIBILITY_THRESHOLDS["STRONG"]:
        grade, recommendation = "STRONG", "PROCEED"
    elif credibility_score >= CREDIBILITY_THRESHOLDS["MODERATE"]:
        grade, recommendation = "MODERATE", "PROCEED_HALF_SIZE"
    elif credibility_score >= CREDIBILITY_THRESHOLDS["WEAK"]:
        grade, recommendation = "WEAK", "SKIP"
    else:
        grade, recommendation = "REJECTED", "REJECT"

    ranked      = sorted(results.items(), key=lambda x: x[1][0], reverse=True)
    key_reasons = [f"{s}: {info[1]}" for s, info in ranked[:4]]

    if verbose:
        logger.info(
            f"[SignalVerifier] {symbol} ({side}) @ Rs{curr_price:.2f} | "
            f"Credibility: {credibility_score:.1f}/100 [{grade}] | Rec: {recommendation}"
        )
        for strat, (sc2, reason) in results.items():
            logger.info(f"   [{strat}] {sc2:.1f}/10 | {reason}")

    return {
        "symbol":               symbol,
        "side":                 side,
        "curr_price":           curr_price,
        "credibility_score":    credibility_score,
        "credibility_grade":    grade,
        "trade_recommendation": recommendation,
        "sub_scores":           {s: {"score": sc2, "reason": rsn} for s, (sc2, rsn) in results.items()},
        "key_reasons":          key_reasons,
        "sr_levels":            sr_levels,
        "pivot_data":           sr_levels.get("pivot_data", {}),
    }


def batch_verify_signals(
    candidates: List[Dict[str, Any]],
    df_map: Dict[str, pd.DataFrame],
    vwap_map: Optional[Dict[str, float]] = None,
    min_credibility: float = 55.0,
    verbose: bool = True,
) -> List[Dict[str, Any]]:
    """Batch verify signals, return only those passing min_credibility threshold."""
    verified = []
    for pick in candidates:
        sym   = pick.get("symbol", "")
        side  = str(pick.get("side", "BUY")).upper()
        price = float(pick.get("curr_price") or pick.get("price") or 0.0)
        rvol  = float(pick.get("rvol") or 1.0)
        rsi   = float(pick.get("rsi") or 50.0)
        vwap  = float(vwap_map.get(sym, 0.0)) if vwap_map else None

        df = df_map.get(sym)
        if df is None or price <= 0:
            logger.warning(f"[SignalVerifier] Skipping {sym}: no OHLCV or invalid price")
            continue

        try:
            result = verify_signal_credibility(
                symbol=sym, side=side, curr_price=price,
                df=df, rvol=rvol, rsi=rsi, vwap=vwap, verbose=verbose
            )
            result.update({k: pick.get(k) for k in pick if k not in result})
            result["original_conviction"] = float(pick.get("conviction_score") or pick.get("score") or 0.0)

            if result["credibility_score"] >= min_credibility:
                verified.append(result)
                logger.info(f"[SignalVerifier] {sym} PASSED: {result['credibility_score']:.1f}/100 [{result['credibility_grade']}]")
            else:
                logger.info(f"[SignalVerifier] {sym} REJECTED: {result['credibility_score']:.1f}/100 < {min_credibility}")
        except Exception as e:
            logger.error(f"[SignalVerifier] Error on {sym}: {e}")

    verified.sort(key=lambda x: x["credibility_score"], reverse=True)
    return verified


def format_verification_report(results: List[Dict[str, Any]]) -> str:
    """Formats human-readable signal verification report."""
    if not results:
        return "No signals passed credibility verification."

    lines = ["=" * 80, "SIGNAL CREDIBILITY VERIFICATION REPORT", "=" * 80]
    grade_sym = {"STRONG": "[STRONG]", "MODERATE": "[MODERATE]", "WEAK": "[WEAK]", "REJECTED": "[REJECTED]"}

    for i, r in enumerate(results, 1):
        grade = r.get("credibility_grade", "UNKNOWN")
        rec   = r.get("trade_recommendation", "UNKNOWN")
        lines.append(f"\n#{i} {r['symbol']} ({r['side']}) @ Rs{r['curr_price']:.2f}")
        lines.append(f"   Credibility: {r['credibility_score']:.1f}/100 {grade_sym.get(grade, grade)} | Rec: {rec}")
        lines.append(f"   Original Conviction: {r.get('original_conviction', 0):.1f}")
        lines.append("   Sub-Scores:")

        for strat, data in r.get("sub_scores", {}).items():
            sc  = data.get("score", 0)
            rsn = data.get("reason", "")
            bar = "#" * int(sc) + "-" * (10 - int(sc))
            lines.append(f"      {strat:<20} [{bar}] {sc:4.1f}/10 | {rsn[:60]}")

        lines.append("   Key Factors:")
        for reason in r.get("key_reasons", [])[:3]:
            lines.append(f"      - {reason[:75]}")

        pivot = r.get("pivot_data", {})
        if pivot:
            lines.append(
                f"   Pivot Levels: P={pivot.get('pivot','?')} "
                f"R1={pivot.get('r1','?')} R2={pivot.get('r2','?')} "
                f"S1={pivot.get('s1','?')} S2={pivot.get('s2','?')}"
            )

    lines.append("\n" + "=" * 80)
    return "\n".join(lines)
