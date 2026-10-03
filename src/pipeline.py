"""
Step 5: Training and Evaluation Pipeline
Orchestrates chronological train/test splitting, candidate model training,
multi-metric evaluation (RMSE, MAE, MAPE, R2, Accuracy, F1, ROC-AUC),
and champion model selection.
"""

from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    mean_absolute_error,
    mean_absolute_percentage_error,
    precision_score,
    r2_score,
    recall_score,
    roc_auc_score,
    root_mean_squared_error,
)
from src.data_loader import fetch_stock_data
from src.features import FeatureEngineer
from src.models import StockPredictorModels


class StockPipeline:
    def __init__(self, ticker: str, mode: str = "next_day", train_split: float = 0.8):
        """
        Parameters:
            ticker (str): Stock ticker symbol (e.g., 'AAPL', 'NVDA', 'MSFT').
            mode (str): 'next_day' or 'same_day'.
            train_split (float): Fraction of chronological data reserved for training (default 0.8).
        """
        self.ticker = ticker.upper()
        self.mode = mode
        self.train_split = train_split
        self.feature_engineer = FeatureEngineer(mode=mode)
        self.models_manager = StockPredictorModels()

        # Artifacts stored after run
        self.raw_df: Optional[pd.DataFrame] = None
        self.X: Optional[pd.DataFrame] = None
        self.y_reg: Optional[pd.Series] = None
        self.y_clf: Optional[pd.Series] = None
        self.meta_df: Optional[pd.DataFrame] = None

        self.reg_results: Dict[str, Dict[str, float]] = {}
        self.clf_results: Dict[str, Dict[str, float]] = {}
        self.test_predictions: Optional[pd.DataFrame] = None
        self.feature_importances: List[Dict[str, Any]] = []

    def run(self) -> Dict[str, Any]:
        """
        Runs the complete end-to-end training and evaluation pipeline.
        """
        print(f"\n=======================================================")
        print(f"Starting ML Pipeline for {self.ticker} [Mode: {self.mode}]")
        print(f"=======================================================")

        # 1. Fetch 5-year data
        self.raw_df = fetch_stock_data(self.ticker, period="5y")
        self.ticker = self.raw_df.attrs.get("ticker", self.ticker)

        # 2. Engineer features and targets
        self.X, self.y_reg, self.y_clf, self.meta_df = self.feature_engineer.prepare_dataset(self.raw_df)
        total_samples = len(self.X)
        print(f"[Pipeline] Cleaned sample size: {total_samples} trading days with {len(self.X.columns)} features.")

        # 3. Chronological Time-Series Split (No random shuffling to avoid lookahead bias!)
        split_idx = int(total_samples * self.train_split)

        X_train, X_test = self.X.iloc[:split_idx], self.X.iloc[split_idx:]
        y_reg_train, y_reg_test = self.y_reg.iloc[:split_idx], self.y_reg.iloc[split_idx:]
        y_clf_train, y_clf_test = self.y_clf.iloc[:split_idx], self.y_clf.iloc[split_idx:]
        meta_test = self.meta_df.iloc[split_idx:]

        train_start, train_end = X_train.index[0].strftime("%Y-%m-%d"), X_train.index[-1].strftime("%Y-%m-%d")
        test_start, test_end = X_test.index[0].strftime("%Y-%m-%d"), X_test.index[-1].strftime("%Y-%m-%d")
        print(f"[Pipeline] Train Period: {train_start} to {train_end} ({len(X_train)} bars)")
        print(f"[Pipeline] Test Period:  {test_start} to {test_end} ({len(X_test)} bars)")

        # 4. Feature Scaling (Fit on Train only, transform Test)
        X_train_scaled = self.models_manager.fit_scaler(X_train)
        X_test_scaled = self.models_manager.transform_features(X_test)

        # 5. Train Regression Models
        print("\n[Pipeline] Training candidate Regression models for Close Price...")
        self.models_manager.train_regression_models(X_train_scaled, y_reg_train)

        # Evaluate Regression Models
        best_reg_name = None
        lowest_rmse = float("inf")
        ref_test = meta_test["Ref_Price"].values

        for name, model in self.models_manager.reg_models.items():
            preds = model.predict(X_test_scaled)
            rmse = float(root_mean_squared_error(y_reg_test, preds))
            mae = float(mean_absolute_error(y_reg_test, preds))
            mape = float(mean_absolute_percentage_error(y_reg_test, preds) * 100.0)
            r2 = float(r2_score(y_reg_test, preds))

            # Directional accuracy: did predicted change have the same sign as actual change?
            pred_delta = preds - ref_test
            actual_delta = y_reg_test.values - ref_test
            dir_acc = float(np.mean(np.sign(pred_delta) == np.sign(actual_delta)) * 100.0)

            self.reg_results[name] = {
                "RMSE": round(rmse, 3),
                "MAE": round(mae, 3),
                "MAPE_%": round(mape, 2),
                "R2": round(r2, 4),
                "Directional_Accuracy_%": round(dir_acc, 2),
            }

            if rmse < lowest_rmse:
                lowest_rmse = rmse
                best_reg_name = name

        # 6. Train Classification Models
        print("[Pipeline] Training candidate Classification models for Trend (Bullish / Bearish)...")
        self.models_manager.train_classification_models(X_train_scaled, y_clf_train)

        # Evaluate Classification Models
        best_clf_name = None
        highest_f1 = -1.0

        for name, model in self.models_manager.clf_models.items():
            preds = model.predict(X_test_scaled)
            proba = model.predict_proba(X_test_scaled)[:, 1] if hasattr(model, "predict_proba") else preds

            acc = float(accuracy_score(y_clf_test, preds) * 100.0)
            prec = float(precision_score(y_clf_test, preds, zero_division=0) * 100.0)
            rec = float(recall_score(y_clf_test, preds, zero_division=0) * 100.0)
            f1 = float(f1_score(y_clf_test, preds, zero_division=0) * 100.0)
            try:
                auc = float(roc_auc_score(y_clf_test, proba) * 100.0)
            except Exception:
                auc = 50.0

            cm = confusion_matrix(y_clf_test, preds).tolist()

            self.clf_results[name] = {
                "Accuracy_%": round(acc, 2),
                "Precision_%": round(prec, 2),
                "Recall_%": round(rec, 2),
                "F1_Score_%": round(f1, 2),
                "ROC_AUC_%": round(auc, 2),
                "Confusion_Matrix": cm,
            }

            if f1 > highest_f1:
                highest_f1 = f1
                best_clf_name = name

        # Select champions
        self.models_manager.set_best_models(best_reg_name, best_clf_name)
        self.feature_importances = self.models_manager.get_feature_importances(top_n=15)

        # Generate Test Predictions DataFrame with champion models
        champion_reg = self.models_manager.best_reg_model
        champion_clf = self.models_manager.best_clf_model

        best_reg_preds = champion_reg.predict(X_test_scaled)
        best_clf_preds = champion_clf.predict(X_test_scaled)
        best_clf_probs = (
            champion_clf.predict_proba(X_test_scaled)[:, 1]
            if hasattr(champion_clf, "predict_proba")
            else best_clf_preds
        )

        self.test_predictions = pd.DataFrame(
            {
                "Date": [d.strftime("%Y-%m-%d") for d in X_test.index],
                "Actual_Close": np.round(y_reg_test.values, 2),
                "Predicted_Close": np.round(best_reg_preds, 2),
                "Actual_Trend": y_clf_test.values.astype(int),
                "Predicted_Trend": best_clf_preds.astype(int),
                "Bullish_Confidence_%": np.round(best_clf_probs * 100.0, 1),
            },
            index=X_test.index,
        )

        print(f"\n[Pipeline] Champion Regression Model:     {best_reg_name} (RMSE: {self.reg_results[best_reg_name]['RMSE']})")
        print(f"[Pipeline] Champion Classification Model: {best_clf_name} (Accuracy: {self.clf_results[best_clf_name]['Accuracy_%']}%, F1: {self.clf_results[best_clf_name]['F1_Score_%']}%)")

        return {
            "ticker": self.ticker,
            "mode": self.mode,
            "train_samples": len(X_train),
            "test_samples": len(X_test),
            "train_period": f"{train_start} to {train_end}",
            "test_period": f"{test_start} to {test_end}",
            "best_reg_model": best_reg_name,
            "best_clf_model": best_clf_name,
            "regression_metrics": self.reg_results,
            "classification_metrics": self.clf_results,
            "top_features": self.feature_importances,
        }
