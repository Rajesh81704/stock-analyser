"""
Comprehensive Individual Stock Evaluation Engine
Evaluates:
1. Fundamentals (Market Cap Cr, P/E, P/B, EPS, Dividend Yield, ROE, 52W High/Low)
2. Technical Parameters (RSI, MACD, Ichimoku, Parabolic SAR, Bollinger Bands, Moving Averages)
3. Percentage Returns: Last Day Return (%) & Last Week Return (%)
4. Historical Daily Candles array for graph visualization
5. Screener Node evaluation (Node #1: Bullish Trending Stocks 26 Rules)
"""

from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd

from src.data_loader import fetch_stock_data, fetch_stock_fundamentals, resolve_ticker
from src.indicators import add_screener_indicators
from src.screener import BullishTrendingScreenerNode, list_available_screener_nodes


def evaluate_individual_stock(ticker: str, period: str = "6mo") -> Dict[str, Any]:
    """
    Executes a comprehensive evaluation for an individual stock.
    Returns fundamentals, technicals, returns (1-day & 1-week %), daily candle history for charting,
    and Screener Filter Node evaluations.
    """
    clean_ticker = ticker.strip().upper()
    resolved = resolve_ticker(clean_ticker)

    # 1. Fetch OHLCV price series
    df = fetch_stock_data(resolved, period=period)
    df_ind = add_screener_indicators(df)

    if len(df_ind) < 5:
        raise ValueError(f"Insufficient historical data for {clean_ticker}")

    latest = df_ind.iloc[-1]
    prev_day = df_ind.iloc[-2] if len(df_ind) >= 2 else latest
    prev_week = df_ind.iloc[-6] if len(df_ind) >= 6 else df_ind.iloc[0]

    close_curr = float(latest["Close"])
    close_prev_day = float(prev_day["Close"])
    close_prev_week = float(prev_week["Close"])

    # 2. Percentage Returns
    last_day_change = close_curr - close_prev_day
    last_day_return_pct = round((last_day_change / (close_prev_day + 1e-10)) * 100.0, 2)

    last_week_change = close_curr - close_prev_week
    last_week_return_pct = round((last_week_change / (close_prev_week + 1e-10)) * 100.0, 2)

    # 3. Fundamentals
    fundamentals = fetch_stock_fundamentals(resolved)

    # 4. Dynamic Candle Payload for Graph based on timeframe period
    p_lower = period.lower().strip()
    if p_lower == "1d":
        history_slice = df_ind.tail(5)
    elif p_lower == "1w":
        history_slice = df_ind.tail(10)
    elif p_lower == "1m":
        history_slice = df_ind.tail(22)
    elif p_lower == "3m":
        history_slice = df_ind.tail(65)
    elif p_lower == "1y":
        history_slice = df_ind.tail(252)
    elif p_lower == "5y":
        history_slice = df_ind
    else:
        history_slice = df_ind.tail(65)

    chart_candles = []
    for d, row in history_slice.iterrows():
        chart_candles.append({
            "date": d.strftime("%Y-%m-%d"),
            "open": round(float(row["Open"]), 2),
            "high": round(float(row["High"]), 2),
            "low": round(float(row["Low"]), 2),
            "close": round(float(row["Close"]), 2),
            "volume": int(row["Volume"]),
            "sma_20": round(float(row["ema_20"]), 2) if "ema_20" in row else round(float(row["Close"]), 2),
        })

    # 5. Screener Filter Node Evaluation (Node #1)
    node1_screener = BullishTrendingScreenerNode(df)
    node1_result = node1_screener.evaluate_latest()

    available_nodes = list_available_screener_nodes()

    # 6. Comprehensive Technical Snapshot
    technicals = {
        "rsi_14": round(float(latest.get("rsi_14", 50.0)), 1),
        "rsi_10": round(float(latest.get("rsi_10", 50.0)), 1),
        "stoch_rsi_14": round(float(latest.get("stoch_rsi_14", 50.0)), 1),
        "macd_line": round(float(latest.get("macd_line_14_5_3", 0.0)), 3),
        "macd_signal": round(float(latest.get("macd_signal_14_5_3", 0.0)), 3),
        "macd_hist": round(float(latest.get("macd_hist_14_5_3", 0.0)), 3),
        "ema_20": round(float(latest.get("ema_20", close_curr)), 2),
        "ema_14": round(float(latest.get("ema_14", close_curr)), 2),
        "sma_10": round(float(latest.get("sma_10", close_curr)), 2),
        "vol_sma_20": int(latest.get("vol_sma_20", float(latest["Volume"]))),
        "psar": round(float(latest.get("psar", close_curr)), 2),
        "bb_upper": round(float(latest.get("bb_upper_20_2", close_curr)), 2),
        "bb_middle": round(float(latest.get("bb_middle_20_2", close_curr)), 2),
        "bb_lower": round(float(latest.get("bb_lower_20_2", close_curr)), 2),
        "cci_10": round(float(latest.get("cci_10", 0.0)), 1),
        "mfi_10": round(float(latest.get("mfi_10", 50.0)), 1),
        "williams_r_10": round(float(latest.get("williams_r_10", -50.0)), 1),
        "adx_10": round(float(latest.get("adx_10", 20.0)), 1),
        "plus_di_10": round(float(latest.get("plus_di_10", 20.0)), 1),
        "minus_di_10": round(float(latest.get("minus_di_10", 20.0)), 1),
        "aroon_up_10": round(float(latest.get("aroon_up_10", 50.0)), 0),
        "aroon_down_10": round(float(latest.get("aroon_down_10", 50.0)), 0),
    }

    return {
        "status": "success",
        "ticker": clean_ticker,
        "resolved_ticker": resolved,
        "as_of_date": df_ind.index[-1].strftime("%Y-%m-%d"),
        "latest_close": round(close_curr, 2),
        "currency_symbol": "₹",
        "returns": {
            "last_day_change": round(last_day_change, 2),
            "last_day_return_pct": last_day_return_pct,
            "last_week_change": round(last_week_change, 2),
            "last_week_return_pct": last_week_return_pct,
        },
        "fundamentals": fundamentals,
        "technicals": technicals,
        "screener_nodes": [node1_result],
        "available_filter_nodes": available_nodes,
        "chart_candles": chart_candles,
    }
