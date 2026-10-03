"""
Market-Wide Analysis Module
Executes daily analytics across all NIFTY 500 stocks:
- Market Breadth (Advances vs Declines, % above 50 & 200 SMA)
- Sector Performance aggregation
- Top 10 Bullish Breakouts & Top 10 Bearish Breakdowns
"""

import json
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd

from src.db import get_db_connection, upsert_market_analysis


def compute_daily_market_analysis(target_date: str = None) -> Dict[str, Any]:
    """
    Computes market-wide breadth and opportunity rankings across NIFTY 500.
    Saves and returns the daily market analysis report.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # Find target date if not provided (latest OHLCV date in DB)
        if not target_date:
            cursor.execute("SELECT MAX(date) as max_date FROM daily_ohlcv;")
            row = cursor.fetchone()
            if not row or not row["max_date"]:
                return {}
            target_date = row["max_date"]

        # 1. Query latest OHLCV and previous close
        query = """
        SELECT o.ticker, o.date, o.close, o.open,
               t.sma_50, t.sma_200, t.rsi_14,
               m.sector, m.company_name,
               p.predicted_close, p.expected_pct_change, p.trend_signal, p.confidence_pct
        FROM daily_ohlcv o
        LEFT JOIN technical_indicators t ON o.ticker = t.ticker AND o.date = t.date
        LEFT JOIN stocks_meta m ON o.ticker = m.ticker
        LEFT JOIN predictions p ON o.ticker = p.ticker AND o.date = p.date
        WHERE o.date = ?;
        """
        cursor.execute(query, (target_date,))
        rows = [dict(r) for r in cursor.fetchall()]

    if not rows:
        return {}

    total_stocks = len(rows)
    advances = 0
    declines = 0
    above_sma50 = 0
    above_sma200 = 0
    sector_deltas: Dict[str, List[float]] = {}
    bullish_candidates = []
    bearish_candidates = []

    for r in rows:
        close = r.get("close") or 0.0
        open_p = r.get("open") or 0.0
        sma_50 = r.get("sma_50")
        sma_200 = r.get("sma_200")
        sector = r.get("sector") or "Diversified"
        exp_pct = r.get("expected_pct_change") or 0.0
        trend = r.get("trend_signal") or "NEUTRAL"
        conf = r.get("confidence_pct") or 50.0

        # Day movement
        if close > open_p:
            advances += 1
        elif close < open_p:
            declines += 1

        # Breadth
        if sma_50 and close > sma_50:
            above_sma50 += 1
        if sma_200 and close > sma_200:
            above_sma200 += 1

        # Sector tracking
        day_ret = ((close - open_p) / (open_p + 1e-8)) * 100.0
        sector_deltas.setdefault(sector, []).append(day_ret)

        # Candidates for breakouts / breakdowns
        item = {
            "ticker": r["ticker"],
            "company_name": r.get("company_name", r["ticker"]),
            "sector": sector,
            "close": round(close, 2),
            "expected_pct_change": round(exp_pct, 2),
            "trend_signal": trend,
            "confidence_pct": round(conf, 1),
            "rsi_14": round(r["rsi_14"], 1) if r.get("rsi_14") else None,
        }

        if trend == "BULLISH" and exp_pct > 0:
            bullish_candidates.append(item)
        elif trend == "BEARISH" and exp_pct < 0:
            bearish_candidates.append(item)

    pct_above_50 = round((above_sma50 / total_stocks) * 100.0, 1) if total_stocks else 0.0
    pct_above_200 = round((above_sma200 / total_stocks) * 100.0, 1) if total_stocks else 0.0

    # Sort top 10 bullish by expected upside
    bullish_candidates.sort(key=lambda x: (x["expected_pct_change"], x["confidence_pct"]), reverse=True)
    top_bullish = bullish_candidates[:10]

    # Sort top 10 bearish by expected downside
    bearish_candidates.sort(key=lambda x: (x["expected_pct_change"], -x["confidence_pct"]))
    top_bearish = bearish_candidates[:10]

    # Sector average returns
    sector_summary = {
        sec: round(sum(rets) / len(rets), 2)
        for sec, rets in sector_deltas.items()
        if len(rets) > 0
    }

    record = {
        "date": target_date,
        "advances": advances,
        "declines": declines,
        "pct_above_sma50": pct_above_50,
        "pct_above_sma200": pct_above_200,
        "top_bullish_tickers": json.dumps(top_bullish),
        "top_bearish_tickers": json.dumps(top_bearish),
        "sector_performance": json.dumps(sector_summary),
    }

    upsert_market_analysis(record)
    print(f"[MarketAnalyzer] Analysis recorded for {target_date}: {advances} Advances, {declines} Declines, "
          f"{pct_above_50}% > SMA50, {pct_above_200}% > SMA200.")
    return record


def classify_stock_conviction(trend_signal: str, expected_pct_change: float, confidence_pct: float) -> Tuple[str, str]:
    """
    Classifies a stock into one of 6 sentiment conviction bands:
    Returns (segment_key, display_label)
    """
    trend = (trend_signal or "").upper()
    pct = float(expected_pct_change or 0.0)
    conf = float(confidence_pct or 50.0)

    if trend == "BULLISH":
        if pct >= 1.5 or (pct >= 0.8 and conf >= 68.0):
            return "extreme_bullish", "Extreme Bullish"
        elif pct >= 0.4:
            return "medium_bullish", "Medium Bullish"
        else:
            return "mild_bullish", "Mild Bullish"
    else:  # BEARISH or other
        if pct <= -1.5 or (pct <= -0.8 and conf >= 68.0):
            return "extreme_bearish", "Extreme Bearish"
        elif pct <= -0.4:
            return "medium_bearish", "Medium Bearish"
        else:
            return "mild_bearish", "Mild Bearish"


def compute_market_segmentation(target_sector: str = None, target_segment: str = None) -> Dict[str, Any]:
    """
    Analyzes all stocks and models, segmenting them by industry sector
    and sentiment conviction: Extreme Bullish, Medium Bullish, Mild Bullish,
    Mild Bearish, Medium Bearish, and Extreme Bearish.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        query = """
        SELECT p.ticker, p.date, p.target_date, p.reference_close, p.predicted_close,
               p.expected_pct_change, p.confidence_pct, p.trend_signal,
               m.company_name, m.sector, m.industry, m.market_cap,
               t.rsi_14, t.macd_hist
        FROM predictions p
        JOIN (SELECT ticker, MAX(date) as max_date FROM predictions GROUP BY ticker) p_max
          ON p.ticker = p_max.ticker AND p.date = p_max.max_date
        LEFT JOIN stocks_meta m ON p.ticker = m.ticker
        LEFT JOIN technical_indicators t ON p.ticker = t.ticker AND p.date = t.date;
        """
        cursor.execute(query)
        rows = [dict(r) for r in cursor.fetchall()]

    if not rows:
        return {
            "status": "empty",
            "message": "No model predictions found in database. Run cron or model initialization first.",
            "total_stocks": 0,
            "sentiment_counts": {},
            "sectors": [],
            "stocks": [],
        }

    total_stocks = len(rows)
    segment_counts = {
        "extreme_bullish": 0,
        "medium_bullish": 0,
        "mild_bullish": 0,
        "mild_bearish": 0,
        "medium_bearish": 0,
        "extreme_bearish": 0,
    }

    sector_map: Dict[str, Dict[str, Any]] = {}
    classified_stocks: List[Dict[str, Any]] = []

    for r in rows:
        ticker = r["ticker"]
        company = r.get("company_name") or ticker
        sector = r.get("sector") or "Diversified"
        industry = r.get("industry") or sector
        ref_close = float(r.get("reference_close") or 0.0)
        pred_close = float(r.get("predicted_close") or ref_close)
        exp_pct = round(float(r.get("expected_pct_change") or 0.0), 2)
        conf = round(float(r.get("confidence_pct") or 50.0), 1)
        trend = (r.get("trend_signal") or "BULLISH").upper()
        rsi = round(float(r.get("rsi_14")), 1) if r.get("rsi_14") is not None else None

        seg_key, seg_label = classify_stock_conviction(trend, exp_pct, conf)
        segment_counts[seg_key] += 1

        stock_item = {
            "ticker": ticker,
            "company_name": company,
            "sector": sector,
            "industry": industry,
            "close": ref_close,
            "predicted_close": pred_close,
            "expected_pct_change": exp_pct,
            "confidence_pct": conf,
            "trend_signal": trend,
            "rsi_14": rsi,
            "segment_key": seg_key,
            "segment_label": seg_label,
        }
        classified_stocks.append(stock_item)

        # Sector breakdown accumulation
        if sector not in sector_map:
            sector_map[sector] = {
                "sector": sector,
                "total_stocks": 0,
                "bullish_count": 0,
                "bearish_count": 0,
                "counts": {
                    "extreme_bullish": 0,
                    "medium_bullish": 0,
                    "mild_bullish": 0,
                    "mild_bearish": 0,
                    "medium_bearish": 0,
                    "extreme_bearish": 0,
                },
                "stocks": [],
            }

        sec_entry = sector_map[sector]
        sec_entry["total_stocks"] += 1
        sec_entry["counts"][seg_key] += 1
        if trend == "BULLISH":
            sec_entry["bullish_count"] += 1
        else:
            sec_entry["bearish_count"] += 1
        sec_entry["stocks"].append(stock_item)

    # Process sector summaries & bias
    sector_list = []
    for sec_name, data in sector_map.items():
        total_sec = data["total_stocks"]
        bull_pct = round((data["bullish_count"] / total_sec) * 100.0, 1) if total_sec else 0.0
        bear_pct = round((data["bearish_count"] / total_sec) * 100.0, 1) if total_sec else 0.0

        if bull_pct >= 58.0:
            bias = "BULLISH_DOMINANT"
        elif bear_pct >= 58.0:
            bias = "BEARISH_DOMINANT"
        elif bull_pct > bear_pct:
            bias = "BULLISH_LEAN"
        elif bear_pct > bull_pct:
            bias = "BEARISH_LEAN"
        else:
            bias = "BALANCED"

        sector_list.append({
            "sector": sec_name,
            "total_stocks": total_sec,
            "bullish_count": data["bullish_count"],
            "bearish_count": data["bearish_count"],
            "bullish_pct": bull_pct,
            "bearish_pct": bear_pct,
            "bias": bias,
            "counts": data["counts"],
        })

    # Sort sectors by total stocks descending
    sector_list.sort(key=lambda s: s["total_stocks"], reverse=True)

    # Filter stocks if requested
    filtered_stocks = classified_stocks
    if target_sector:
        sec_clean = target_sector.strip().lower()
        filtered_stocks = [s for s in filtered_stocks if sec_clean in (s["sector"] or "").lower()]

    if target_segment:
        seg_clean = target_segment.strip().lower().replace(" ", "_")
        filtered_stocks = [s for s in filtered_stocks if s["segment_key"] == seg_clean]

    # Sort filtered stocks by conviction / expected pct change descending
    filtered_stocks.sort(key=lambda s: (s["expected_pct_change"], s["confidence_pct"]), reverse=True)

    total_bullish = segment_counts["extreme_bullish"] + segment_counts["medium_bullish"] + segment_counts["mild_bullish"]
    total_bearish = segment_counts["mild_bearish"] + segment_counts["medium_bearish"] + segment_counts["extreme_bearish"]

    return {
        "status": "success",
        "total_stocks": total_stocks,
        "total_bullish": total_bullish,
        "total_bearish": total_bearish,
        "sentiment_counts": {
            "extreme_bullish": {
                "count": segment_counts["extreme_bullish"],
                "pct": round((segment_counts["extreme_bullish"] / total_stocks) * 100.0, 1) if total_stocks else 0.0,
                "label": "Extreme Bullish",
                "color": "#00e5ff",
                "description": "High predicted upside (>= +1.5%) with strong ML model conviction",
            },
            "medium_bullish": {
                "count": segment_counts["medium_bullish"],
                "pct": round((segment_counts["medium_bullish"] / total_stocks) * 100.0, 1) if total_stocks else 0.0,
                "label": "Medium Bullish",
                "color": "#00e676",
                "description": "Solid predicted upside (+0.4% to +1.5%)",
            },
            "mild_bullish": {
                "count": segment_counts["mild_bullish"],
                "pct": round((segment_counts["mild_bullish"] / total_stocks) * 100.0, 1) if total_stocks else 0.0,
                "label": "Mild Bullish",
                "color": "#69f0ae",
                "description": "Slight upward bias (0% to +0.4%)",
            },
            "mild_bearish": {
                "count": segment_counts["mild_bearish"],
                "pct": round((segment_counts["mild_bearish"] / total_stocks) * 100.0, 1) if total_stocks else 0.0,
                "label": "Mild Bearish",
                "color": "#ffb74d",
                "description": "Slight downward bias (0% to -0.4%)",
            },
            "medium_bearish": {
                "count": segment_counts["medium_bearish"],
                "pct": round((segment_counts["medium_bearish"] / total_stocks) * 100.0, 1) if total_stocks else 0.0,
                "label": "Medium Bearish",
                "color": "#ff7043",
                "description": "Moderate downside risk (-0.4% to -1.5%)",
            },
            "extreme_bearish": {
                "count": segment_counts["extreme_bearish"],
                "pct": round((segment_counts["extreme_bearish"] / total_stocks) * 100.0, 1) if total_stocks else 0.0,
                "label": "Extreme Bearish",
                "color": "#ff1744",
                "description": "Sharp predicted drop (<= -1.5%) with high model confidence",
            },
        },
        "sectors": sector_list,
        "stocks_count": len(filtered_stocks),
        "stocks": filtered_stocks,
    }

