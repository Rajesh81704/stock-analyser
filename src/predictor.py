"""
Step 6: Live Inference and Forward Prediction Engine
Generates live predictions for the next trading day (or same day close),
including predicted Close price, Bullish/Bearish signal, probability confidence,
support/resistance boundaries, and indicator summaries.
"""

from typing import Any, Dict
import numpy as np
import pandas as pd
from src.features import FeatureEngineer
from src.models import StockPredictorModels


class LivePredictor:
    def __init__(
        self,
        ticker: str,
        feature_engineer: FeatureEngineer,
        models_manager: StockPredictorModels,
        raw_df: pd.DataFrame,
    ):
        self.ticker = ticker.upper()
        self.feature_engineer = feature_engineer
        self.models_manager = models_manager
        self.raw_df = raw_df

    def predict_forward(self) -> Dict[str, Any]:
        """
        Generates the forecast for the upcoming trading session.
        """
        # 1. Prepare latest features
        inference_row, ref_price = self.feature_engineer.prepare_inference_row(self.raw_df)
        inference_scaled = self.models_manager.transform_features(inference_row)

        # 2. Regression prediction (Predicted Close Price)
        champion_reg = self.models_manager.best_reg_model
        pred_close = float(champion_reg.predict(inference_scaled)[0])
        price_change = pred_close - ref_price
        pct_change = (price_change / ref_price) * 100.0

        # 3. Classification prediction (Bullish / Bearish Trend)
        champion_clf = self.models_manager.best_clf_model
        pred_trend_int = int(champion_clf.predict(inference_scaled)[0])

        if hasattr(champion_clf, "predict_proba"):
            probs = champion_clf.predict_proba(inference_scaled)[0]
            bullish_prob = float(probs[1]) * 100.0
            bearish_prob = float(probs[0]) * 100.0
            confidence = max(bullish_prob, bearish_prob)
        else:
            bullish_prob = 100.0 if pred_trend_int == 1 else 0.0
            bearish_prob = 100.0 - bullish_prob
            confidence = 100.0

        trend_label = "BULLISH" if pred_trend_int == 1 else "BEARISH"

        # 4. Extract latest key technical indicators
        last_date = self.raw_df.index[-1].strftime("%Y-%m-%d")
        last_open = float(self.raw_df["Open"].iloc[-1])
        last_high = float(self.raw_df["High"].iloc[-1])
        last_low = float(self.raw_df["Low"].iloc[-1])
        last_close = float(self.raw_df["Close"].iloc[-1])
        last_volume = float(self.raw_df["Volume"].iloc[-1])

        # Key indicators from latest row
        latest_row_dict = inference_row.iloc[0].to_dict()

        atr = float(latest_row_dict.get("ATR_14", 0.0))
        expected_high = pred_close + (0.5 * atr) if atr > 0 else pred_close * 1.01
        expected_low = pred_close - (0.5 * atr) if atr > 0 else pred_close * 0.99

        return {
            "ticker": self.ticker,
            "mode": self.feature_engineer.mode,
            "as_of_date": last_date,
            "last_ohlcv": {
                "open": round(last_open, 2),
                "high": round(last_high, 2),
                "low": round(last_low, 2),
                "close": round(last_close, 2),
                "volume": int(last_volume),
            },
            "reference_price": round(ref_price, 2),
            "prediction": {
                "predicted_close": round(pred_close, 2),
                "expected_price_change": round(price_change, 2),
                "expected_pct_change": round(pct_change, 2),
                "expected_trading_range": {
                    "low": round(expected_low, 2),
                    "high": round(expected_high, 2),
                },
                "trend": trend_label,
                "confidence_%": round(confidence, 1),
                "bullish_probability_%": round(bullish_prob, 1),
                "bearish_probability_%": round(bearish_prob, 1),
                "reg_model_used": self.models_manager.best_reg_name,
                "clf_model_used": self.models_manager.best_clf_name,
            },
            "key_indicators": {
                "rsi_14": round(float(latest_row_dict.get("RSI_14", 50.0)), 2),
                "macd": round(float(latest_row_dict.get("MACD", 0.0)), 3),
                "macd_signal": round(float(latest_row_dict.get("MACD_Signal", 0.0)), 3),
                "macd_hist": round(float(latest_row_dict.get("MACD_Hist", 0.0)), 3),
                "sma_20": round(float(latest_row_dict.get("SMA_20", 0.0)), 2),
                "sma_50": round(float(latest_row_dict.get("SMA_50", 0.0)), 2),
                "sma_200": round(float(latest_row_dict.get("SMA_200", 0.0)), 2),
                "bb_upper": round(float(latest_row_dict.get("BB_Upper", 0.0)), 2),
                "bb_middle": round(float(latest_row_dict.get("BB_Middle", 0.0)), 2),
                "bb_lower": round(float(latest_row_dict.get("BB_Lower", 0.0)), 2),
                "atr_14": round(atr, 2),
                "adx_14": round(float(latest_row_dict.get("ADX_14", 0.0)), 2),
                "pivot": round(float(latest_row_dict.get("Pivot", 0.0)), 2),
                "resistance_r1": round(float(latest_row_dict.get("Pivot_R1", 0.0)), 2),
                "support_s1": round(float(latest_row_dict.get("Pivot_S1", 0.0)), 2),
                "resistance_20d": round(float(latest_row_dict.get("Resistance_20", 0.0)), 2),
                "support_20d": round(float(latest_row_dict.get("Support_20", 0.0)), 2),
            },
        }
