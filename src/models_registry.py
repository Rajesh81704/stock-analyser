"""
Model Registry & Incremental Retraining Engine
Manages persistent ML models per NIFTY 500 stock in models_registry/{ticker}.joblib.
Provides fast training, Gradient Boosted tree model updates, and multi-timeframe (next-day & next-hour) predictions.
"""

import os
from typing import Any, Dict, Optional, Tuple
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import RobustScaler

from src.features import FeatureEngineer
from src.indicators import add_all_indicators

REGISTRY_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "models_registry"))


class StockModelArtifact:
    def __init__(self, ticker: str):
        self.ticker = ticker
        self.reg_model = HistGradientBoostingRegressor(
            max_iter=150, max_depth=5, min_samples_leaf=10, l2_regularization=2.0, random_state=42
        )
        self.clf_model = HistGradientBoostingClassifier(
            max_iter=150, max_depth=5, min_samples_leaf=10, l2_regularization=2.0, random_state=42
        )
        self.rf_clf = RandomForestClassifier(
            n_estimators=60, max_depth=5, min_samples_leaf=5, random_state=42
        )
        self.lr_clf = LogisticRegression(
            max_iter=200, C=1.0, random_state=42
        )
        self.scaler = RobustScaler()
        self.feature_columns: list = []
        self.last_trained_date: Optional[str] = None


def get_model_path(ticker: str) -> str:
    """Returns local filesystem path for a stock's serialized model."""
    safe_ticker = ticker.replace("^", "").replace(".", "_")
    os.makedirs(REGISTRY_DIR, exist_ok=True)
    return os.path.join(REGISTRY_DIR, f"{safe_ticker}.joblib")


def load_or_init_model(ticker: str) -> StockModelArtifact:
    """Loads existing model from disk or initializes a new instance."""
    path = get_model_path(ticker)
    if os.path.exists(path):
        try:
            return joblib.load(path)
        except Exception:
            pass
    return StockModelArtifact(ticker)


def save_model(artifact: StockModelArtifact):
    """Saves model artifact to disk."""
    path = get_model_path(artifact.ticker)
    joblib.dump(artifact, path)


def compute_optimized_confidence(
    raw_probs: np.ndarray,
    pred_trend: int,
    latest_row: pd.DataFrame,
    ref_price: float,
    mode: str = "next_day",
    ensemble_votes: Optional[list] = None
) -> Tuple[float, str, list]:
    """
    Multi-Factor False Positive Elimination & Calibrated Confidence Engine.

    Elimination & Damping Factors:
    1. Multi-Model Stacking Consensus (Gradient Boosting + Random Forest + Logistic Regression)
    2. Trend Confluence Filter (Price vs SMA20, SMA50)
    3. Overbought/Oversold Reversion Damping (RSI > 70 or < 30)
    4. Momentum Histogram Confluence (MACD Hist sign)
    5. Volatility & Sideways Choppiness Damping (ADX < 16)
    6. Support & Resistance Proximity & Breakout Filter (Pivots R1/S1)
    """
    raw_confidence = float(max(raw_probs[0], raw_probs[1])) * 100.0
    trend_signal = "BULLISH" if pred_trend == 1 else "BEARISH"
    elimination_factors = []

    score = raw_confidence

    # 1. Multi-Model Stacking Ensemble Consensus Filter
    if ensemble_votes and len(ensemble_votes) == 3:
        bull_votes = sum(1 for v in ensemble_votes if v == 1)
        if (pred_trend == 1 and bull_votes == 3) or (pred_trend == 0 and bull_votes == 0):
            score += 6.0
            elimination_factors.append("3-Model Unanimous Consensus (HistGB + Random Forest + LogReg, +6.0% Conf)")
        else:
            score -= 4.0
            elimination_factors.append("Damped: Model Architecture Divergence (2/3 Majority Vote, -4.0% Conf)")

    rsi = float(latest_row.get("RSI_14", pd.Series([50.0])).iloc[0])
    adx = float(latest_row.get("ADX_14", pd.Series([20.0])).iloc[0])
    macd_hist = float(latest_row.get("MACD_Hist", pd.Series([0.0])).iloc[0])
    sma_20 = float(latest_row.get("SMA_20", pd.Series([ref_price])).iloc[0])
    sma_50 = float(latest_row.get("SMA_50", pd.Series([ref_price])).iloc[0])

    # 2. Moving Average Trend Alignment Filter
    if trend_signal == "BULLISH":
        if ref_price > sma_20 and ref_price > sma_50:
            score += 4.5
            elimination_factors.append("Uptrend Confluence (+4.5% Conf)")
        elif ref_price < sma_20 and ref_price < sma_50:
            score -= 10.0
            elimination_factors.append("Damped: Counter-trend against 20/50 SMA (-10.0%)")
    else:  # BEARISH
        if ref_price < sma_20 and ref_price < sma_50:
            score += 4.5
            elimination_factors.append("Downtrend Confluence (+4.5% Conf)")
        elif ref_price > sma_20 and ref_price > sma_50:
            score -= 10.0
            elimination_factors.append("Damped: Counter-trend against 20/50 SMA (-10.0%)")

    # 3. RSI Overbought / Oversold Exhaustion Damping
    if trend_signal == "BULLISH" and rsi > 70.0:
        penalty = min(15.0, (rsi - 70.0) * 1.5)
        score -= penalty
        elimination_factors.append(f"Eliminated Overbought Risk (RSI {rsi:.1f}, -{penalty:.1f}%)")
    elif trend_signal == "BEARISH" and rsi < 30.0:
        penalty = min(15.0, (30.0 - rsi) * 1.5)
        score -= penalty
        elimination_factors.append(f"Eliminated Oversold Risk (RSI {rsi:.1f}, -{penalty:.1f}%)")

    # 4. MACD Momentum Confluence
    if (trend_signal == "BULLISH" and macd_hist > 0) or (trend_signal == "BEARISH" and macd_hist < 0):
        score += 3.0
        elimination_factors.append("MACD Momentum Confluence (+3.0%)")
    elif (trend_signal == "BULLISH" and macd_hist < 0) or (trend_signal == "BEARISH" and macd_hist > 0):
        score -= 5.0
        elimination_factors.append("Damped: MACD Momentum Divergence (-5.0%)")

    # 5. ADX Low Trend Strength Filter
    if adx < 16.0:
        score -= 8.0
        elimination_factors.append(f"Damped: Rangebound Noise (ADX {adx:.1f} < 16, -8.0%)")
    elif adx > 30.0:
        score += 3.5
        elimination_factors.append(f"Strong Trend Regime (ADX {adx:.1f}, +3.5%)")

    # 6. Support & Resistance Proximity & Breakout Filter (Floor Trader Pivots R1, S1, P)
    pivot_p = float(latest_row.get("Pivot", pd.Series([ref_price])).iloc[0])
    pivot_r1 = float(latest_row.get("Pivot_R1", pd.Series([ref_price * 1.01])).iloc[0])
    pivot_s1 = float(latest_row.get("Pivot_S1", pd.Series([ref_price * 0.99])).iloc[0])

    dist_to_r1_pct = ((pivot_r1 - ref_price) / (ref_price + 1e-8)) * 100.0
    dist_to_s1_pct = ((ref_price - pivot_s1) / (ref_price + 1e-8)) * 100.0

    if trend_signal == "BULLISH":
        if ref_price >= pivot_r1:
            # Confirmed Breakout above Resistance R1!
            score += 5.0
            elimination_factors.append("Confirmed R1 Resistance Breakout (+5.0% Conf)")
        elif 0.0 <= dist_to_r1_pct <= 0.6:
            # Buying directly into Resistance R1 ceiling (Rejection Risk!)
            score -= 10.0
            elimination_factors.append(f"Damped: Buying into Resistance Ceiling (R1 at ₹{pivot_r1:.2f}, -10.0%)")
    else:  # BEARISH
        if ref_price <= pivot_s1:
            # Confirmed Breakdown below Support S1!
            score += 5.0
            elimination_factors.append("Confirmed S1 Support Breakdown (+5.0% Conf)")
        elif 0.0 <= dist_to_s1_pct <= 0.6:
            # Shorting directly into Support S1 floor (Bounce Risk!)
            score -= 10.0
            elimination_factors.append(f"Damped: Shorting into Support Floor (S1 at ₹{pivot_s1:.2f}, -10.0%)")

    calibrated_confidence = max(50.0, min(95.0, score))
    return round(calibrated_confidence, 1), trend_signal, elimination_factors


def train_and_predict_stock(
    ticker: str,
    df_history: pd.DataFrame,
    df_hourly: Optional[pd.DataFrame] = None,
    mode: str = "next_day"
) -> Optional[Dict[str, Any]]:
    """
    Trains/refits the model on historical bars and generates forward forecasts.
    """
    if df_history is None or len(df_history) < 30:
        return None

    try:
        fe = FeatureEngineer(mode=mode)
        X, y_reg, y_clf, meta = fe.prepare_dataset(df_history, df_hourly=df_hourly)

        if len(X) < 20:
            return None

        # Load or initialize model artifact
        artifact = load_or_init_model(ticker)
        artifact.feature_columns = fe.feature_columns

        # Ensure multi-model classifiers exist on loaded artifacts
        if not hasattr(artifact, "rf_clf"):
            artifact.rf_clf = RandomForestClassifier(n_estimators=60, max_depth=5, min_samples_leaf=5, random_state=42)
        if not hasattr(artifact, "lr_clf"):
            artifact.lr_clf = LogisticRegression(max_iter=200, C=1.0, random_state=42)

        # Fit Scaler & Ensembles
        X_scaled = artifact.scaler.fit_transform(X)
        artifact.reg_model.fit(X_scaled, y_reg)
        artifact.clf_model.fit(X_scaled, y_clf)
        artifact.rf_clf.fit(X_scaled, y_clf)
        artifact.lr_clf.fit(X_scaled, y_clf)

        artifact.last_trained_date = df_history.index[-1].strftime("%Y-%m-%d")
        save_model(artifact)

        # Generate Forward Prediction
        latest_row, ref_price = fe.prepare_inference_row(df_history, df_hourly=df_hourly)
        latest_scaled = artifact.scaler.transform(latest_row)

        pred_close = float(artifact.reg_model.predict(latest_scaled)[0])
        
        # 3-Model Ensemble Voting (HistGB, RandomForest, LogisticRegression)
        pred_hgb = int(artifact.clf_model.predict(latest_scaled)[0])
        pred_rf = int(artifact.rf_clf.predict(latest_scaled)[0])
        pred_lr = int(artifact.lr_clf.predict(latest_scaled)[0])

        ensemble_votes = [pred_hgb, pred_rf, pred_lr]
        pred_trend_int = 1 if sum(ensemble_votes) >= 2 else 0

        raw_probs = artifact.clf_model.predict_proba(latest_scaled)[0]

        # Multi-factor confidence calibration & false positive elimination
        confidence, trend_signal, elim_factors = compute_optimized_confidence(
            raw_probs, pred_trend_int, latest_row, ref_price, mode=mode, ensemble_votes=ensemble_votes
        )

        delta = pred_close - ref_price
        pct_change = (delta / (ref_price + 1e-8)) * 100.0

        latest_atr = float(latest_row.get("ATR_14", pd.Series([ref_price * 0.02])).iloc[0])
        range_low = pred_close - (0.5 * latest_atr)
        range_high = pred_close + (0.5 * latest_atr)

        as_of_date = df_history.index[-1].strftime("%Y-%m-%d")
        if mode == "next_day":
            target_date = (df_history.index[-1] + pd.Timedelta(days=1 if df_history.index[-1].weekday() < 4 else 3)).strftime("%Y-%m-%d")
        else:
            target_date = "Next Trading Hour"

        return {
            "ticker": ticker,
            "mode": mode,
            "date": as_of_date,
            "target_date": target_date,
            "reference_close": round(ref_price, 2),
            "predicted_close": round(pred_close, 2),
            "expected_pct_change": round(pct_change, 2),
            "range_low": round(range_low, 2),
            "range_high": round(range_high, 2),
            "trend_signal": trend_signal,
            "confidence_pct": confidence,
            "champion_model": "HistGradientBoosting",
            "elimination_factors": elim_factors,
        }

    except Exception as e:
        print(f"[ModelRegistry] Error training {ticker}: {e}")
        return None

