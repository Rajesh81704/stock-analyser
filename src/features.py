"""
Step 3: Feature Engineering and Dataset Preparation Module
Aligns technical indicators, handles feature lagging to prevent lookahead bias,
combines 1-hour intraday signals with daily candles, and generates multi-timeframe targets.
Supports:
1. 'next_day' mode: Predicts Close[t+1] and Next-Day Trend (Close[t+1] > Close[t]) using daily + 1-hour intraday data up to day t.
2. 'next_hour' mode: Predicts Close[h+1] and Next-Hour Trend (Close[h+1] > Close[h]) using 1-hour candles up to hour h.
"""

from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
from src.indicators import add_all_indicators


def extract_hourly_intraday_features(df_hourly: pd.DataFrame) -> pd.DataFrame:
    """
    Extracts 1-hour intraday smart-money signatures aggregated per daily trading session.
    Computes:
    - H_Last_Hour_Return: Final 60-min session return (2:30 PM to 3:30 PM IST)
    - H_Last_Hour_Vol_Ratio: Final 1-hour volume / average intraday hourly volume
    - H_Dist_VWAP: % distance of session Close to Intraday VWAP
    - H_Intraday_Range: Intraday High-Low spread normalized by Close
    """
    if df_hourly is None or len(df_hourly) == 0:
        return pd.DataFrame()

    df_h = df_hourly.copy()
    if isinstance(df_h.columns, pd.MultiIndex):
        df_h.columns = df_h.columns.get_level_values(0)

    df_h["date"] = pd.to_datetime(df_h.index.date)
    hourly_feats = []

    for d_date, group in df_h.groupby("date"):
        if len(group) < 2:
            continue
        last_bar = group.iloc[-1]

        # Intraday VWAP
        vol_sum = group["Volume"].sum() + 1e-8
        vwap = (group["Close"] * group["Volume"]).sum() / vol_sum

        last_hour_ret = (last_bar["Close"] - last_bar["Open"]) / (last_bar["Open"] + 1e-8)
        last_hour_vol_ratio = last_bar["Volume"] / (group["Volume"].mean() + 1e-8)
        dist_vwap = (last_bar["Close"] - vwap) / (vwap + 1e-8)
        intraday_range = (group["High"].max() - group["Low"].min()) / (last_bar["Close"] + 1e-8)

        hourly_feats.append({
            "date": d_date,
            "H_Last_Hour_Return": float(last_hour_ret),
            "H_Last_Hour_Vol_Ratio": float(last_hour_vol_ratio),
            "H_Dist_VWAP": float(dist_vwap),
            "H_Intraday_Range": float(intraday_range),
        })

    if not hourly_feats:
        return pd.DataFrame()

    return pd.DataFrame(hourly_feats).set_index("date")


class FeatureEngineer:
    def __init__(self, mode: str = "next_day"):
        """
        Parameters:
            mode (str): 'next_day' (predict next day) or 'next_hour' (predict next hour).
        """
        if mode not in ["next_day", "next_hour", "same_day"]:
            raise ValueError("Mode must be 'next_day', 'next_hour', or 'same_day'")
        self.mode = mode
        self.feature_columns: List[str] = []

    def prepare_dataset(
        self, raw_df: pd.DataFrame, df_hourly: Optional[pd.DataFrame] = None
    ) -> Tuple[pd.DataFrame, pd.Series, pd.Series, pd.DataFrame]:
        """
        Enriches raw OHLCV DataFrame with technical indicators & intraday 1-hour features.
        Generates regression and trend classification targets.
        """
        df = add_all_indicators(raw_df)

        # Multi-period momentum returns
        for lag in [1, 2, 3, 5, 10]:
            df[f"Return_{lag}d"] = df["Close"].pct_change(lag)

        # Merge 1-hour intraday aggregated features if provided
        if df_hourly is not None and len(df_hourly) > 0:
            df_h_agg = extract_hourly_intraday_features(df_hourly)
            if not df_h_agg.empty:
                df.index = pd.to_datetime(df.index)
                df = df.join(df_h_agg, how="left")

        # Target definitions based on mode
        if self.mode == "next_day":
            # Features at day t predict Close at day t+1 (Next Day Movement)
            df["Target_Close"] = df["Close"].shift(-1)
            df["Target_Trend"] = (df["Target_Close"] > df["Close"]).astype(int)
            df["Ref_Price"] = df["Close"]

            feature_cols = [
                # Intraday 1-Hour Signals (If present)
                "H_Last_Hour_Return", "H_Last_Hour_Vol_Ratio", "H_Dist_VWAP", "H_Intraday_Range",
                # Price & Gap
                "Open", "High", "Low", "Close", "Overnight_Gap", "Open_In_Prior_Range", "Open_To_Pivot",
                # Moving Averages
                "SMA_10", "SMA_20", "SMA_50", "SMA_200", "EMA_9", "EMA_21", "EMA_50",
                "Dist_SMA_20", "Dist_SMA_50", "Dist_SMA_200", "Dist_EMA_9", "Golden_Cross", "EMA_Fast_Cross",
                # RSI
                "RSI_14", "RSI_7", "RSI_Overbought", "RSI_Oversold", "RSI_Centered",
                # MACD
                "MACD", "MACD_Signal", "MACD_Hist", "MACD_Norm", "MACD_Hist_Norm", "MACD_Bullish",
                # Bollinger Bands
                "BB_Middle", "BB_Upper", "BB_Lower", "BB_Bandwidth", "BB_Percent_B", "BB_Squeeze",
                # Volatility
                "ATR_14", "NATR_14", "High_Low_Spread", "Historical_Vol_20",
                # Volume
                "Vol_Ratio_20", "Vol_ROC_5", "OBV_Signal", "VPT",
                # Trend
                "ADX_14", "Plus_DI_14", "Minus_DI_14", "Trend_Strength", "EMA_20_Slope", "Bullish_Candle_Trend",
                # Support & Resistance
                "Resistance_20", "Support_20", "Dist_To_Resistance", "Dist_To_Support",
                "Pivot", "Pivot_R1", "Pivot_S1", "Dist_To_Pivot", "Above_Pivot",
                # Momentum returns
                "Return_1d", "Return_2d", "Return_3d", "Return_5d"
            ]

        elif self.mode == "next_hour":
            # Features at hour h predict Close at hour h+1 (Next Hour Movement)
            df["Target_Close"] = df["Close"].shift(-1)
            df["Target_Trend"] = (df["Target_Close"] > df["Close"]).astype(int)
            df["Ref_Price"] = df["Close"]

            feature_cols = [
                "Open", "High", "Low", "Close", "Volume",
                "SMA_10", "SMA_20", "SMA_50", "EMA_9", "EMA_21",
                "Dist_SMA_20", "Dist_EMA_9",
                "RSI_14", "RSI_7", "RSI_Centered",
                "MACD", "MACD_Signal", "MACD_Hist",
                "BB_Middle", "BB_Upper", "BB_Lower", "BB_Percent_B",
                "ATR_14", "NATR_14", "High_Low_Spread",
                "Return_1d", "Return_2d", "Return_3d"
            ]

        else:  # mode == "same_day"
            df["Target_Close"] = df["Close"]
            df["Target_Trend"] = (df["Close"] > df["Open"]).astype(int)
            df["Ref_Price"] = df["Open"]
            feature_cols = ["Open", "Overnight_Gap", "Open_In_Prior_Range", "Open_To_Pivot", "RSI_14", "MACD"]

        valid_features = [col for col in feature_cols if col in df.columns]
        self.feature_columns = valid_features

        clean_df = df.dropna(subset=["Target_Close", "Target_Trend"]).copy()

        X = clean_df[valid_features].replace([np.inf, -np.inf], np.nan).ffill().bfill().fillna(0.0)
        valid_indices = X.dropna().index
        X = X.loc[valid_indices]
        y_reg = clean_df.loc[valid_indices, "Target_Close"]
        y_clf = clean_df.loc[valid_indices, "Target_Trend"]
        meta_df = clean_df.loc[valid_indices, ["Open", "High", "Low", "Close", "Volume", "Ref_Price"]]

        return X, y_reg, y_clf, meta_df

    def prepare_inference_row(self, raw_df: pd.DataFrame, df_hourly: Optional[pd.DataFrame] = None) -> Tuple[pd.DataFrame, float]:
        """
        Prepares single most recent row of features for live forward prediction.
        """
        df = add_all_indicators(raw_df)
        for lag in [1, 2, 3, 5, 10]:
            df[f"Return_{lag}d"] = df["Close"].pct_change(lag)

        if df_hourly is not None and len(df_hourly) > 0:
            df_h_agg = extract_hourly_intraday_features(df_hourly)
            if not df_h_agg.empty:
                df.index = pd.to_datetime(df.index)
                df = df.join(df_h_agg, how="left")

        latest_row = df.iloc[[-1]][self.feature_columns].copy()
        latest_row = latest_row.replace([np.inf, -np.inf], np.nan).ffill().bfill().fillna(0.0)
        ref_price = float(df["Close"].iloc[-1])
        return latest_row, ref_price

