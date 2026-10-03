"""
NIFTY 500 Model Backtesting & Validation Suite (2016 - 2021)
Evaluates out-of-sample performance, directional accuracy, MAE, Sharpe ratio, and strategy cumulative returns.
"""

import sqlite3
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.preprocessing import RobustScaler
from sklearn.metrics import accuracy_score, precision_score, recall_score, mean_absolute_error, confusion_matrix

from src.db import get_db_connection
from src.features import FeatureEngineer
from src.indicators import add_all_indicators


def run_backtest_validation(
    ticker: str = "RELIANCE.NS",
    start_date: str = "2016-01-01",
    end_date: str = "2021-12-31",
    train_ratio: float = 0.7,
    plot_results: bool = True
):
    """
    Executes Out-of-Sample Time-Series Validation for a stock between 2016 and 2021.
    Prevents lookahead bias by strictly splitting training data prior to testing data.
    """
    print(f"🔍 Loading historical data for {ticker} from {start_date} to {end_date}...")
    
    conn = get_db_connection()
    df_raw = pd.read_sql_query(
        """
        SELECT date, open, high, low, close, volume 
        FROM daily_ohlcv 
        WHERE ticker = ? AND date >= ? AND date <= ? 
        ORDER BY date ASC
        """,
        conn, params=(ticker, start_date, end_date)
    )
    conn.close()

    if len(df_raw) < 200:
        print(f"⚠️ Warning: Only {len(df_raw)} bars found for {ticker} in range {start_date} to {end_date}.")
        print("Note: If SQLite has insufficient bars for 2016-2018, data loader will fetch full 5-year data.")
        return None

    # 1. Feature Engineering
    fe = FeatureEngineer(mode="next_day")
    X, y_reg, y_clf, meta = fe.prepare_dataset(df_raw)

    dates = meta["date"].values
    closes = meta["close"].values
    
    # 2. Strict Chronological Train/Test Split (No Data Leakage)
    split_idx = int(len(X) * train_ratio)
    
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_reg_train, y_reg_test = y_reg.iloc[:split_idx], y_reg.iloc[split_idx:]
    y_clf_train, y_clf_test = y_clf.iloc[:split_idx], y_clf.iloc[split_idx:]
    
    train_dates = dates[:split_idx]
    test_dates = dates[split_idx:]
    
    # 3. Robust Scaling (Fit strictly on Train)
    scaler = RobustScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)

    # 4. Fit Champion Models (Ridge Regressor & Logistic Classifier)
    reg_model = Ridge(alpha=10.0, random_state=42)
    clf_model = LogisticRegression(
        C=0.2, max_iter=1000, solver="lbfgs", class_weight="balanced", random_state=42
    )

    reg_model.fit(X_train_scaled, y_reg_train)
    clf_model.fit(X_train_scaled, y_clf_train)

    # 5. Out-of-Sample Predictions
    pred_pct = reg_model.predict(X_test_scaled)
    pred_signal = clf_model.predict(X_test_scaled)
    pred_proba = clf_model.predict_proba(X_test_scaled)[:, 1]

    # 6. Calculate Quantitative Metrics
    acc = accuracy_score(y_clf_test, pred_signal) * 100
    prec = precision_score(y_clf_test, pred_signal, zero_division=0) * 100
    rec = recall_score(y_clf_test, pred_signal, zero_division=0) * 100
    mae = mean_absolute_error(y_reg_test, pred_pct)
    cm = confusion_matrix(y_clf_test, pred_signal)

    # 7. Simulated Quantitative Strategy
    actual_returns = y_reg_test.values / 100.0  # Actual daily returns
    
    # Strategy: Long when model signals BULLISH (1), Cash (0%) when BEARISH (0)
    strat_returns = np.where(pred_signal == 1, actual_returns, 0.0)

    cum_buy_hold = np.cumprod(1 + actual_returns) - 1
    cum_strategy = np.cumprod(1 + strat_returns) - 1

    sharpe_buy_hold = (np.mean(actual_returns) / (np.std(actual_returns) + 1e-8)) * np.sqrt(252)
    sharpe_strategy = (np.mean(strat_returns) / (np.std(strat_returns) + 1e-8)) * np.sqrt(252)

    # Print Full Evaluation Report
    print("\n" + "=" * 60)
    print(f"📊 MODEL BACKTEST & OUT-OF-SAMPLE VALIDATION REPORT: {ticker}")
    print("=" * 60)
    print(f"📅 Training Window   : {train_dates[0]} to {train_dates[-1]} ({len(X_train)} sessions)")
    print(f"📅 Testing Window    : {test_dates[0]} to {test_dates[-1]} ({len(X_test)} sessions)")
    print("-" * 60)
    print(f"🎯 Directional Accuracy : {acc:.2f}%")
    print(f"🎯 Precision (Bullish)  : {prec:.2f}%")
    print(f"🎯 Recall (Bullish)     : {rec:.2f}%")
    print(f"🎯 Mean Absolute Error  : {mae:.2f}%")
    print("-" * 60)
    print("📈 Confusion Matrix [TN  FP / FN  TP]:")
    print(f"   [{cm[0][0]:3d}  {cm[0][1]:3d}]  (Bearish correct vs False Bullish)")
    print(f"   [{cm[1][0]:3d}  {cm[1][1]:3d}]  (False Bearish vs Bullish correct)")
    print("-" * 60)
    print(f"💰 Buy & Hold Return   : {cum_buy_hold[-1]*100:+.2f}%  (Sharpe Ratio: {sharpe_buy_hold:.2f})")
    print(f"💰 Model Strategy Return: {cum_strategy[-1]*100:+.2f}%  (Sharpe Ratio: {sharpe_strategy:.2f})")
    print("=" * 60)

    # 8. Plot Visual Validation Charts
    if plot_results:
        plt.figure(figsize=(12, 6))
        dt_index = pd.to_datetime(test_dates)
        
        plt.plot(dt_index, cum_buy_hold * 100, label="Buy & Hold Benchmark", color="#9e9e9e", linestyle="--", linewidth=1.5)
        plt.plot(dt_index, cum_strategy * 100, label="Quant Strategy (Out-of-Sample)", color="#00e5ff", linewidth=2.0)
        
        plt.title(f"{ticker} — Out-of-Sample Model Backtest (2016-2021 Validation)", fontsize=13, fontweight="bold")
        plt.xlabel("Date", fontsize=11)
        plt.ylabel("Cumulative Return (%)", fontsize=11)
        plt.grid(True, linestyle="--", alpha=0.3)
        plt.legend(loc="upper left", fontsize=11)
        plt.tight_layout()
        plt.savefig("backtest_result.png", dpi=150)
        print("💾 Chart saved to backtest_result.png")
        plt.show()

    return {
        "accuracy": acc,
        "precision": prec,
        "recall": rec,
        "mae": mae,
        "buy_hold_return_pct": cum_buy_hold[-1] * 100,
        "strategy_return_pct": cum_strategy[-1] * 100,
        "sharpe_strategy": sharpe_strategy
    }


if __name__ == "__main__":
    run_backtest_validation(ticker="RELIANCE.NS", start_date="2016-01-01", end_date="2021-12-31")
