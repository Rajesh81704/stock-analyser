"""
Quantitative Technical Screener Node Registry Architecture
Defines Screener Filter Nodes. Node #1: "Bullish Trending Stocks" (26 Rules).
"""

from typing import Any, Dict, List, Optional
import pandas as pd
from src.indicators import add_screener_indicators


FILTER_RULES_SPEC_NODE_1 = [
    {"id": 1, "name": "Daily EMA(close,20) > 20", "desc": "EMA 20 value is greater than 20"},
    {"id": 2, "name": "Daily SMA(volume,20) >= 100000", "desc": "20-day Volume SMA is at least 100,000"},
    {"id": 3, "name": "Daily Ichimoku Conversion Line(3,7,14) >= Base Line(3,7,14)", "desc": "Tenkan-sen >= Kijun-sen for fast Ichimoku"},
    {"id": 4, "name": "Daily Ichimoku Span A(3,7,14) >= Span B(3,7,14)", "desc": "Leading Span A >= Span B for fast Ichimoku"},
    {"id": 5, "name": "Daily Close >= Ichimoku Cloud Bottom(3,7,14)", "desc": "Price above or inside Cloud for fast Ichimoku"},
    {"id": 6, "name": "Daily Close >= Parabolic SAR(0.02, 0.02, 0.2)", "desc": "Price above Parabolic SAR (Bullish trend)"},
    {"id": 7, "name": "Daily RSI(10) >= 20", "desc": "10-day RSI >= 20 (Not extremely oversold)"},
    {"id": 8, "name": "Daily StochRSI(10) >= 20", "desc": "10-day Stochastic RSI >= 20"},
    {"id": 9, "name": "Daily CCI(10) >= 0", "desc": "10-day Commodity Channel Index >= 0 (Bullish regime)"},
    {"id": 10, "name": "Daily MFI(10) >= 20", "desc": "10-day Money Flow Index >= 20"},
    {"id": 11, "name": "Daily Williams %R(10) >= -80", "desc": "10-day Williams %R >= -80"},
    {"id": 12, "name": "Daily Close >= EMA(close,14)", "desc": "Price above 14-day EMA"},
    {"id": 13, "name": "Daily ADX +DI(10) >= -DI(10)", "desc": "Positive Directional Indicator >= Negative DI"},
    {"id": 14, "name": "Daily Aroon Up(10) >= Aroon Down(10)", "desc": "Aroon Up >= Aroon Down"},
    {"id": 15, "name": "Daily Slow Stochastic %K(5,3) >= %D(5,3)", "desc": "Slow %K >= Slow %D"},
    {"id": 16, "name": "Daily Fast Stochastic %K(5,3) >= %D(5,3)", "desc": "Fast %K >= Fast %D"},
    {"id": 17, "name": "Daily Close >= SMA(close,10)", "desc": "Price above 10-day SMA"},
    {"id": 18, "name": "Daily MACD Line(14,5,3) >= Signal Line(14,5,3)", "desc": "MACD Line >= Signal Line"},
    {"id": 19, "name": "Daily MACD Histogram(14,5,3) >= 0", "desc": "MACD Histogram is non-negative"},
    {"id": 20, "name": "Daily RSI(14) > 50", "desc": "14-day RSI > 50 (Bullish momentum)"},
    {"id": 21, "name": "Daily StochRSI(14) > 50", "desc": "14-day StochRSI > 50"},
    {"id": 22, "name": "Daily RSI(10) < 80", "desc": "10-day RSI < 80 (Avoid extreme overbought risk)"},
    {"id": 23, "name": "Daily Close >= Upper Bollinger Band(20,2)", "desc": "Price riding or breaking above Upper Bollinger Band"},
    {"id": 24, "name": "Daily Close >= Ichimoku Cloud Bottom(9,26,52)", "desc": "Price above Standard Ichimoku Cloud Bottom"},
    {"id": 25, "name": "Daily Close > Open", "desc": "Green candle body (Bullish day)"},
    {"id": 26, "name": "Daily Volume > 100000", "desc": "Daily trading volume > 100,000"},
]


class BullishTrendingScreenerNode:
    """
    Screener Node #1: 'Bullish Trending Stocks' Filter Node.
    Evaluates 26 strict quantitative rules on Cash Segment Equities.
    """

    node_id: str = "NODE_01_BULLISH_TRENDING"
    node_name: str = "Bullish Trending Stocks"
    description: str = "26-Rule Algorithmic Technical Filter Engine for Cash Segment Stocks"

    def __init__(self, df: pd.DataFrame):
        self.raw_df = df.copy()
        self.df_ind = add_screener_indicators(self.raw_df)

    def evaluate_latest(self) -> Dict[str, Any]:
        """
        Evaluates all 26 filter rules on the latest daily bar.
        """
        if self.df_ind.empty or len(self.df_ind) < 10:
            return {
                "node_id": self.node_id,
                "node_name": self.node_name,
                "passed_all": False,
                "passed_count": 0,
                "total_rules": 26,
                "pass_percentage": 0.0,
                "filter_results": [],
                "latest_bar": {},
            }

        latest = self.df_ind.iloc[-1]

        close = float(latest["Close"])
        open_p = float(latest["Open"])
        high = float(latest["High"])
        low = float(latest["Low"])
        volume = float(latest["Volume"])

        ema_20 = float(latest.get("ema_20", 0.0))
        vol_sma_20 = float(latest.get("vol_sma_20", 0.0))
        ichi_conv_3_7_14 = float(latest.get("ichi_conv_3_7_14", 0.0))
        ichi_base_3_7_14 = float(latest.get("ichi_base_3_7_14", 0.0))
        ichi_span_a_3_7_14 = float(latest.get("ichi_span_a_3_7_14", 0.0))
        ichi_span_b_3_7_14 = float(latest.get("ichi_span_b_3_7_14", 0.0))
        ichi_cloud_bottom_3_7_14 = float(latest.get("ichi_cloud_bottom_3_7_14", 0.0))

        psar = float(latest.get("psar", 0.0))
        rsi_10 = float(latest.get("rsi_10", 0.0))
        stoch_rsi_10 = float(latest.get("stoch_rsi_10", 0.0))
        cci_10 = float(latest.get("cci_10", 0.0))
        mfi_10 = float(latest.get("mfi_10", 0.0))
        williams_r_10 = float(latest.get("williams_r_10", 0.0))
        ema_14 = float(latest.get("ema_14", 0.0))
        plus_di_10 = float(latest.get("plus_di_10", 0.0))
        minus_di_10 = float(latest.get("minus_di_10", 0.0))
        aroon_up_10 = float(latest.get("aroon_up_10", 0.0))
        aroon_down_10 = float(latest.get("aroon_down_10", 0.0))
        slow_stoch_k_5_3 = float(latest.get("slow_stoch_k_5_3", 0.0))
        slow_stoch_d_5_3 = float(latest.get("slow_stoch_d_5_3", 0.0))
        fast_stoch_k_5_3 = float(latest.get("fast_stoch_k_5_3", 0.0))
        fast_stoch_d_5_3 = float(latest.get("fast_stoch_d_5_3", 0.0))
        sma_10 = float(latest.get("sma_10", 0.0))

        macd_line_14_5_3 = float(latest.get("macd_line_14_5_3", 0.0))
        macd_signal_14_5_3 = float(latest.get("macd_signal_14_5_3", 0.0))
        macd_hist_14_5_3 = float(latest.get("macd_hist_14_5_3", 0.0))

        rsi_14 = float(latest.get("rsi_14", 0.0))
        stoch_rsi_14 = float(latest.get("stoch_rsi_14", 0.0))
        bb_upper_20_2 = float(latest.get("bb_upper_20_2", 0.0))
        ichi_cloud_bottom_9_26_52 = float(latest.get("ichi_cloud_bottom_9_26_52", 0.0))

        rule_evals = [
            {"id": 1, "passed": bool(ema_20 > 20.0), "actual": f"EMA(20) = {ema_20:.2f}", "target": "> 20.0"},
            {"id": 2, "passed": bool(vol_sma_20 >= 100000.0), "actual": f"Vol SMA(20) = {vol_sma_20:,.0f}", "target": ">= 100,000"},
            {"id": 3, "passed": bool(ichi_conv_3_7_14 >= ichi_base_3_7_14), "actual": f"Conv = {ichi_conv_3_7_14:.2f}, Base = {ichi_base_3_7_14:.2f}", "target": "Conv >= Base"},
            {"id": 4, "passed": bool(ichi_span_a_3_7_14 >= ichi_span_b_3_7_14), "actual": f"Span A = {ichi_span_a_3_7_14:.2f}, Span B = {ichi_span_b_3_7_14:.2f}", "target": "Span A >= Span B"},
            {"id": 5, "passed": bool(close >= ichi_cloud_bottom_3_7_14), "actual": f"Close = {close:.2f}, Bottom = {ichi_cloud_bottom_3_7_14:.2f}", "target": "Close >= Cloud Bottom"},
            {"id": 6, "passed": bool(close >= psar), "actual": f"Close = {close:.2f}, PSAR = {psar:.2f}", "target": "Close >= PSAR"},
            {"id": 7, "passed": bool(rsi_10 >= 20.0), "actual": f"RSI(10) = {rsi_10:.1f}", "target": ">= 20.0"},
            {"id": 8, "passed": bool(stoch_rsi_10 >= 20.0), "actual": f"StochRSI(10) = {stoch_rsi_10:.1f}", "target": ">= 20.0"},
            {"id": 9, "passed": bool(cci_10 >= 0.0), "actual": f"CCI(10) = {cci_10:.1f}", "target": ">= 0.0"},
            {"id": 10, "passed": bool(mfi_10 >= 20.0), "actual": f"MFI(10) = {mfi_10:.1f}", "target": ">= 20.0"},
            {"id": 11, "passed": bool(williams_r_10 >= -80.0), "actual": f"Williams %R(10) = {williams_r_10:.1f}", "target": ">= -80.0"},
            {"id": 12, "passed": bool(close >= ema_14), "actual": f"Close = {close:.2f}, EMA(14) = {ema_14:.2f}", "target": "Close >= EMA(14)"},
            {"id": 13, "passed": bool(plus_di_10 >= minus_di_10), "actual": f"+DI(10) = {plus_di_10:.1f}, -DI(10) = {minus_di_10:.1f}", "target": "+DI >= -DI"},
            {"id": 14, "passed": bool(aroon_up_10 >= aroon_down_10), "actual": f"Aroon Up = {aroon_up_10:.0f}, Down = {aroon_down_10:.0f}", "target": "Up >= Down"},
            {"id": 15, "passed": bool(slow_stoch_k_5_3 >= slow_stoch_d_5_3), "actual": f"Slow %K = {slow_stoch_k_5_3:.1f}, %D = {slow_stoch_d_5_3:.1f}", "target": "%K >= %D"},
            {"id": 16, "passed": bool(fast_stoch_k_5_3 >= fast_stoch_d_5_3), "actual": f"Fast %K = {fast_stoch_k_5_3:.1f}, %D = {fast_stoch_d_5_3:.1f}", "target": "%K >= %D"},
            {"id": 17, "passed": bool(close >= sma_10), "actual": f"Close = {close:.2f}, SMA(10) = {sma_10:.2f}", "target": "Close >= SMA(10)"},
            {"id": 18, "passed": bool(macd_line_14_5_3 >= macd_signal_14_5_3), "actual": f"MACD = {macd_line_14_5_3:.3f}, Signal = {macd_signal_14_5_3:.3f}", "target": "MACD >= Signal"},
            {"id": 19, "passed": bool(macd_hist_14_5_3 >= 0.0), "actual": f"Hist = {macd_hist_14_5_3:.3f}", "target": ">= 0.0"},
            {"id": 20, "passed": bool(rsi_14 > 50.0), "actual": f"RSI(14) = {rsi_14:.1f}", "target": "> 50.0"},
            {"id": 21, "passed": bool(stoch_rsi_14 > 50.0), "actual": f"StochRSI(14) = {stoch_rsi_14:.1f}", "target": "> 50.0"},
            {"id": 22, "passed": bool(rsi_10 < 80.0), "actual": f"RSI(10) = {rsi_10:.1f}", "target": "< 80.0"},
            {"id": 23, "passed": bool(close >= (bb_upper_20_2 * 0.995)), "actual": f"Close = {close:.2f}, Upper BB = {bb_upper_20_2:.2f}", "target": "Close >= Upper BB"},
            {"id": 24, "passed": bool(close >= ichi_cloud_bottom_9_26_52), "actual": f"Close = {close:.2f}, Bottom = {ichi_cloud_bottom_9_26_52:.2f}", "target": "Close >= Cloud Bottom"},
            {"id": 25, "passed": bool(close > open_p), "actual": f"Close = {close:.2f}, Open = {open_p:.2f}", "target": "Close > Open (Green Candle)"},
            {"id": 26, "passed": bool(volume > 100000.0), "actual": f"Volume = {volume:,.0f}", "target": "> 100,000"},
        ]

        filter_results = []
        passed_count = 0
        for spec, res in zip(FILTER_RULES_SPEC_NODE_1, rule_evals):
            is_pass = res["passed"]
            if is_pass:
                passed_count += 1
            filter_results.append({
                "rule_id": spec["id"],
                "rule_name": spec["name"],
                "description": spec["desc"],
                "passed": is_pass,
                "actual_value": res["actual"],
                "target_threshold": res["target"],
            })

        total_rules = len(FILTER_RULES_SPEC_NODE_1)
        pass_pct = round((passed_count / total_rules) * 100.0, 1)
        passed_all = (passed_count == total_rules)

        last_date = self.df_ind.index[-1].strftime("%Y-%m-%d")

        prev_close = float(self.df_ind["Close"].iloc[-2]) if len(self.df_ind) >= 2 else open_p
        change_pct = round(((close - prev_close) / prev_close) * 100.0, 2) if prev_close > 0 else 0.0

        return {
            "node_id": self.node_id,
            "node_name": self.node_name,
            "date": last_date,
            "passed_all": passed_all,
            "passed_count": passed_count,
            "total_rules": total_rules,
            "pass_percentage": pass_pct,
            "filter_results": filter_results,
            "latest_bar": {
                "date": last_date,
                "open": round(open_p, 2),
                "high": round(high, 2),
                "low": round(low, 2),
                "close": round(close, 2),
                "volume": int(volume),
                "change_pct": change_pct,
                "rsi_14": round(rsi_14, 1),
                "rsi_10": round(rsi_10, 1),
                "stoch_rsi_14": round(stoch_rsi_14, 1),
                "macd": round(macd_line_14_5_3, 3),
                "macd_signal": round(macd_signal_14_5_3, 3),
                "ema_20": round(ema_20, 2),
                "ema_14": round(ema_14, 2),
                "bb_upper": round(bb_upper_20_2, 2),
            },
        }


FILTER_RULES_SPEC_NODE_2 = [
    {"id": 1, "name": "Daily EMA(close,20) > 20", "desc": "EMA 20 value is greater than 20"},
    {"id": 2, "name": "Daily SMA(volume,20) >= 100000", "desc": "20-day Volume SMA is at least 100,000"},
    {"id": 3, "name": "Daily Ichimoku Conversion Line(3,7,14) >= Base Line(3,7,14)", "desc": "Tenkan-sen >= Kijun-sen for fast Ichimoku"},
    {"id": 4, "name": "Daily Ichimoku Span A(3,7,14) >= Span B(3,7,14)", "desc": "Leading Span A >= Span B for fast Ichimoku"},
    {"id": 5, "name": "Daily Close >= Ichimoku Cloud Bottom(3,7,14)", "desc": "Price above or inside Cloud for fast Ichimoku"},
    {"id": 6, "name": "Daily Close >= Parabolic SAR(0.02, 0.02, 0.2)", "desc": "Price above Parabolic SAR (Bullish trend)"},
    {"id": 7, "name": "Daily RSI(10) >= 20", "desc": "10-day RSI >= 20 (Not extremely oversold)"},
    {"id": 8, "name": "Daily StochRSI(10) >= 20", "desc": "10-day Stochastic RSI >= 20"},
    {"id": 9, "name": "Daily CCI(10) >= 0", "desc": "10-day Commodity Channel Index >= 0 (Bullish regime)"},
    {"id": 10, "name": "Daily MFI(10) >= 20", "desc": "10-day Money Flow Index >= 20"},
    {"id": 11, "name": "Daily Williams %R(10) >= -80", "desc": "10-day Williams %R >= -80"},
    {"id": 12, "name": "Daily Close >= EMA(close,14)", "desc": "Price above 14-day EMA"},
    {"id": 13, "name": "Daily ADX +DI(10) >= -DI(10)", "desc": "Positive Directional Indicator >= Negative DI"},
    {"id": 14, "name": "Daily Aroon Up(10) >= Aroon Down(10)", "desc": "Aroon Up >= Aroon Down"},
    {"id": 15, "name": "Daily Slow Stochastic %K(5,3) >= %D(5,3)", "desc": "Slow %K >= Slow %D"},
    {"id": 16, "name": "Daily Fast Stochastic %K(5,3) >= %D(5,3)", "desc": "Fast %K >= Fast %D"},
    {"id": 17, "name": "Daily Close >= SMA(close,10)", "desc": "Price above 10-day SMA"},
    {"id": 18, "name": "Daily MACD Line(14,5,3) >= Signal Line(14,5,3)", "desc": "MACD Line >= Signal Line"},
    {"id": 19, "name": "Daily MACD Histogram(14,5,3) >= 0", "desc": "MACD Histogram is non-negative"},
    {"id": 20, "name": "Daily RSI(14) > 50", "desc": "14-day RSI > 50 (Bullish momentum)"},
    {"id": 21, "name": "Daily StochRSI(14) > 50", "desc": "14-day StochRSI > 50"},
    {"id": 22, "name": "Daily RSI(10) < 80", "desc": "10-day RSI < 80 (Avoid extreme overbought risk)"},
    {"id": 23, "name": "Daily Close >= Upper Bollinger Band(20,2)", "desc": "Price riding or breaking above Upper Bollinger Band"},
    {"id": 24, "name": "Daily Close >= Ichimoku Cloud Bottom(9,26,52)", "desc": "Price above Standard Ichimoku Cloud Bottom"},
    {"id": 25, "name": "Daily Close > Open", "desc": "Green candle body (Bullish day)"},
    {"id": 26, "name": "Daily Volume > 100000", "desc": "Daily trading volume > 100,000"},
]


class BullishMomentumScreenerNode:
    """
    Screener Node #2: 'Pure Bullish Momentum Scan' Filter Node.
    Evaluates 26 strict quantitative rules on Cash Segment Equities.
    """

    node_id: str = "NODE_02_BULLISH_MOMENTUM"
    node_name: str = "Pure Bullish Momentum Scan"
    description: str = "26-Rule Algorithmic Technical Filter Engine for Cash Segment Stocks (Ichimoku, Parabolic SAR, RSI, StochRSI, CCI, MFI, Aroon, MACD, Bollinger Bands)"

    def __init__(self, df: pd.DataFrame):
        self.raw_df = df.copy()
        self.df_ind = add_screener_indicators(self.raw_df)

    def evaluate_latest(self) -> Dict[str, Any]:
        if self.df_ind.empty or len(self.df_ind) < 10:
            return {
                "node_id": self.node_id,
                "node_name": self.node_name,
                "passed_all": False,
                "passed_count": 0,
                "total_rules": 26,
                "pass_percentage": 0.0,
                "filter_results": [],
                "latest_bar": {},
            }

        latest = self.df_ind.iloc[-1]

        close = float(latest["Close"])
        open_p = float(latest["Open"])
        high = float(latest["High"])
        low = float(latest["Low"])
        volume = float(latest["Volume"])

        ema_20 = float(latest.get("ema_20", 0.0))
        vol_sma_20 = float(latest.get("vol_sma_20", 0.0))
        ichi_conv_3_7_14 = float(latest.get("ichi_conv_3_7_14", 0.0))
        ichi_base_3_7_14 = float(latest.get("ichi_base_3_7_14", 0.0))
        ichi_span_a_3_7_14 = float(latest.get("ichi_span_a_3_7_14", 0.0))
        ichi_span_b_3_7_14 = float(latest.get("ichi_span_b_3_7_14", 0.0))
        ichi_cloud_bottom_3_7_14 = float(latest.get("ichi_cloud_bottom_3_7_14", 0.0))

        psar = float(latest.get("psar", 0.0))
        rsi_10 = float(latest.get("rsi_10", 0.0))
        stoch_rsi_10 = float(latest.get("stoch_rsi_10", 0.0))
        cci_10 = float(latest.get("cci_10", 0.0))
        mfi_10 = float(latest.get("mfi_10", 0.0))
        williams_r_10 = float(latest.get("williams_r_10", 0.0))
        ema_14 = float(latest.get("ema_14", 0.0))
        plus_di_10 = float(latest.get("plus_di_10", 0.0))
        minus_di_10 = float(latest.get("minus_di_10", 0.0))
        aroon_up_10 = float(latest.get("aroon_up_10", 0.0))
        aroon_down_10 = float(latest.get("aroon_down_10", 0.0))
        slow_stoch_k_5_3 = float(latest.get("slow_stoch_k_5_3", 0.0))
        slow_stoch_d_5_3 = float(latest.get("slow_stoch_d_5_3", 0.0))
        fast_stoch_k_5_3 = float(latest.get("fast_stoch_k_5_3", 0.0))
        fast_stoch_d_5_3 = float(latest.get("fast_stoch_d_5_3", 0.0))
        sma_10 = float(latest.get("sma_10", 0.0))

        macd_line_14_5_3 = float(latest.get("macd_line_14_5_3", 0.0))
        macd_signal_14_5_3 = float(latest.get("macd_signal_14_5_3", 0.0))
        macd_hist_14_5_3 = float(latest.get("macd_hist_14_5_3", 0.0))

        rsi_14 = float(latest.get("rsi_14", 0.0))
        stoch_rsi_14 = float(latest.get("stoch_rsi_14", 0.0))
        bb_upper_20_2 = float(latest.get("bb_upper_20_2", 0.0))
        ichi_cloud_bottom_9_26_52 = float(latest.get("ichi_cloud_bottom_9_26_52", 0.0))

        rule_evals = [
            {"id": 1, "passed": bool(ema_20 > 20.0), "actual": f"EMA(20) = {ema_20:.2f}", "target": "> 20.0"},
            {"id": 2, "passed": bool(vol_sma_20 >= 100000.0), "actual": f"Vol SMA(20) = {vol_sma_20:,.0f}", "target": ">= 100,000"},
            {"id": 3, "passed": bool(ichi_conv_3_7_14 >= ichi_base_3_7_14), "actual": f"Conv = {ichi_conv_3_7_14:.2f}, Base = {ichi_base_3_7_14:.2f}", "target": "Conv >= Base"},
            {"id": 4, "passed": bool(ichi_span_a_3_7_14 >= ichi_span_b_3_7_14), "actual": f"Span A = {ichi_span_a_3_7_14:.2f}, Span B = {ichi_span_b_3_7_14:.2f}", "target": "Span A >= Span B"},
            {"id": 5, "passed": bool(close >= ichi_cloud_bottom_3_7_14), "actual": f"Close = {close:.2f}, Bottom = {ichi_cloud_bottom_3_7_14:.2f}", "target": "Close >= Cloud Bottom"},
            {"id": 6, "passed": bool(close >= psar), "actual": f"Close = {close:.2f}, PSAR = {psar:.2f}", "target": "Close >= PSAR"},
            {"id": 7, "passed": bool(rsi_10 >= 20.0), "actual": f"RSI(10) = {rsi_10:.1f}", "target": ">= 20.0"},
            {"id": 8, "passed": bool(stoch_rsi_10 >= 20.0), "actual": f"StochRSI(10) = {stoch_rsi_10:.1f}", "target": ">= 20.0"},
            {"id": 9, "passed": bool(cci_10 >= 0.0), "actual": f"CCI(10) = {cci_10:.1f}", "target": ">= 0.0"},
            {"id": 10, "passed": bool(mfi_10 >= 20.0), "actual": f"MFI(10) = {mfi_10:.1f}", "target": ">= 20.0"},
            {"id": 11, "passed": bool(williams_r_10 >= -80.0), "actual": f"Williams %R(10) = {williams_r_10:.1f}", "target": ">= -80.0"},
            {"id": 12, "passed": bool(close >= ema_14), "actual": f"Close = {close:.2f}, EMA(14) = {ema_14:.2f}", "target": "Close >= EMA(14)"},
            {"id": 13, "passed": bool(plus_di_10 >= minus_di_10), "actual": f"+DI(10) = {plus_di_10:.1f}, -DI(10) = {minus_di_10:.1f}", "target": "+DI >= -DI"},
            {"id": 14, "passed": bool(aroon_up_10 >= aroon_down_10), "actual": f"Aroon Up = {aroon_up_10:.0f}, Down = {aroon_down_10:.0f}", "target": "Up >= Down"},
            {"id": 15, "passed": bool(slow_stoch_k_5_3 >= slow_stoch_d_5_3), "actual": f"Slow %K = {slow_stoch_k_5_3:.1f}, %D = {slow_stoch_d_5_3:.1f}", "target": "%K >= %D"},
            {"id": 16, "passed": bool(fast_stoch_k_5_3 >= fast_stoch_d_5_3), "actual": f"Fast %K = {fast_stoch_k_5_3:.1f}, %D = {fast_stoch_d_5_3:.1f}", "target": "%K >= %D"},
            {"id": 17, "passed": bool(close >= sma_10), "actual": f"Close = {close:.2f}, SMA(10) = {sma_10:.2f}", "target": "Close >= SMA(10)"},
            {"id": 18, "passed": bool(macd_line_14_5_3 >= macd_signal_14_5_3), "actual": f"MACD = {macd_line_14_5_3:.3f}, Signal = {macd_signal_14_5_3:.3f}", "target": "MACD >= Signal"},
            {"id": 19, "passed": bool(macd_hist_14_5_3 >= 0.0), "actual": f"Hist = {macd_hist_14_5_3:.3f}", "target": ">= 0.0"},
            {"id": 20, "passed": bool(rsi_14 > 50.0), "actual": f"RSI(14) = {rsi_14:.1f}", "target": "> 50.0"},
            {"id": 21, "passed": bool(stoch_rsi_14 > 50.0), "actual": f"StochRSI(14) = {stoch_rsi_14:.1f}", "target": "> 50.0"},
            {"id": 22, "passed": bool(rsi_10 < 80.0), "actual": f"RSI(10) = {rsi_10:.1f}", "target": "< 80.0"},
            {"id": 23, "passed": bool(close >= (bb_upper_20_2 * 0.995)), "actual": f"Close = {close:.2f}, Upper BB = {bb_upper_20_2:.2f}", "target": "Close >= Upper BB"},
            {"id": 24, "passed": bool(close >= ichi_cloud_bottom_9_26_52), "actual": f"Close = {close:.2f}, Bottom = {ichi_cloud_bottom_9_26_52:.2f}", "target": "Close >= Cloud Bottom"},
            {"id": 25, "passed": bool(close > open_p), "actual": f"Close = {close:.2f}, Open = {open_p:.2f}", "target": "Close > Open (Green Candle)"},
            {"id": 26, "passed": bool(volume > 100000.0), "actual": f"Volume = {volume:,.0f}", "target": "> 100,000"},
        ]

        filter_results = []
        passed_count = 0
        for spec, res in zip(FILTER_RULES_SPEC_NODE_2, rule_evals):
            is_pass = res["passed"]
            if is_pass:
                passed_count += 1
            filter_results.append({
                "rule_id": spec["id"],
                "rule_name": spec["name"],
                "description": spec["desc"],
                "passed": is_pass,
                "actual_value": res["actual"],
                "target_threshold": res["target"],
            })

        total_rules = len(FILTER_RULES_SPEC_NODE_2)
        pass_pct = round((passed_count / total_rules) * 100.0, 1)
        passed_all = (passed_count == total_rules)

        last_date = self.df_ind.index[-1].strftime("%Y-%m-%d")

        prev_close = float(self.df_ind["Close"].iloc[-2]) if len(self.df_ind) >= 2 else open_p
        change_pct = round(((close - prev_close) / prev_close) * 100.0, 2) if prev_close > 0 else 0.0

        return {
            "node_id": self.node_id,
            "node_name": self.node_name,
            "date": last_date,
            "passed_all": passed_all,
            "passed_count": passed_count,
            "total_rules": total_rules,
            "pass_percentage": pass_pct,
            "filter_results": filter_results,
            "latest_bar": {
                "date": last_date,
                "open": round(open_p, 2),
                "high": round(high, 2),
                "low": round(low, 2),
                "close": round(close, 2),
                "volume": int(volume),
                "change_pct": change_pct,
                "rsi_14": round(rsi_14, 1),
                "rsi_10": round(rsi_10, 1),
                "stoch_rsi_14": round(stoch_rsi_14, 1),
                "macd": round(macd_line_14_5_3, 3),
                "macd_signal": round(macd_signal_14_5_3, 3),
                "ema_20": round(ema_20, 2),
                "ema_14": round(ema_14, 2),
                "bb_upper": round(bb_upper_20_2, 2),
            },
        }


# Alias for backwards compatibility
BullishTrendingScreener = BullishTrendingScreenerNode
FILTER_RULES_SPEC = FILTER_RULES_SPEC_NODE_1


def list_available_screener_nodes() -> List[Dict[str, Any]]:
    """Returns a list of all registered quantitative screener filter nodes."""
    return [
        {
            "node_id": "NODE_01_BULLISH_TRENDING",
            "node_name": "Bullish Trending Stocks",
            "category": "Bullish Scan",
            "rule_count": 26,
            "description": "26-Rule Algorithmic Technical Filter Node for Cash Segment Equities (Ichimoku, Parabolic SAR, RSI, MACD, Stoch, Aroon, Bollinger)",
            "rules_spec": FILTER_RULES_SPEC_NODE_1,
        },
        {
            "node_id": "NODE_02_BULLISH_MOMENTUM",
            "node_name": "Pure Bullish Momentum Scan",
            "category": "Momentum Scan",
            "rule_count": 26,
            "description": "26-Rule Algorithmic Momentum Filter Node for Cash Segment Equities",
            "rules_spec": FILTER_RULES_SPEC_NODE_2,
        },
    ]
