"""
Step 4: Machine Learning Models Module
Defines regression and classification model pipelines for stock price and trend prediction:
- Regression: Ridge, Random Forest Regressor, LightGBM Regressor, XGBoost Regressor
- Classification: Logistic Regression, Random Forest Classifier, LightGBM Classifier, XGBoost Classifier
- Handles feature scaling, regularized training, and feature importance extraction.
"""

from typing import Any, Dict, List, Optional, Tuple
import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
try:
    import lightgbm as lgb
except ImportError:
    lgb = None

try:
    import xgboost as xgb
except ImportError:
    xgb = None


class StockPredictorModels:
    def __init__(self):
        self.scaler = RobustScaler()
        self.reg_models: Dict[str, Any] = {}
        self.clf_models: Dict[str, Any] = {}
        self.best_reg_name: str = ""
        self.best_clf_name: str = ""
        self.best_reg_model: Any = None
        self.best_clf_model: Any = None
        self.feature_names: List[str] = []

    def get_regression_models(self) -> Dict[str, Any]:
        """Returns initialized candidate regression models."""
        return {
            "Ridge": Ridge(alpha=10.0, random_state=42),
            "RandomForest": RandomForestRegressor(
                n_estimators=150,
                max_depth=7,
                min_samples_leaf=4,
                random_state=42,
                n_jobs=-1
            ),
            "LightGBM": lgb.LGBMRegressor(
                n_estimators=150,
                max_depth=5,
                learning_rate=0.03,
                num_leaves=20,
                subsample=0.8,
                colsample_bytree=0.8,
                random_state=42,
                verbose=-1
            ),
            "XGBoost": xgb.XGBRegressor(
                n_estimators=150,
                max_depth=4,
                learning_rate=0.03,
                subsample=0.8,
                colsample_bytree=0.8,
                random_state=42,
                verbosity=0
            ),
        }

    def get_classification_models(self) -> Dict[str, Any]:
        """Returns initialized candidate classification models."""
        return {
            "LogisticRegression": LogisticRegression(
                C=0.1,
                max_iter=1000,
                class_weight="balanced",
                random_state=42
            ),
            "RandomForest": RandomForestClassifier(
                n_estimators=150,
                max_depth=5,
                min_samples_leaf=5,
                class_weight="balanced",
                random_state=42,
                n_jobs=-1
            ),
            "LightGBM": lgb.LGBMClassifier(
                n_estimators=120,
                max_depth=4,
                learning_rate=0.03,
                num_leaves=15,
                subsample=0.8,
                colsample_bytree=0.8,
                class_weight="balanced",
                random_state=42,
                verbose=-1
            ),
            "XGBoost": xgb.XGBClassifier(
                n_estimators=120,
                max_depth=4,
                learning_rate=0.03,
                subsample=0.8,
                colsample_bytree=0.8,
                scale_pos_weight=1.0,
                random_state=42,
                verbosity=0
            ),
        }

    def fit_scaler(self, X_train: pd.DataFrame) -> np.ndarray:
        """Fits the RobustScaler on training features only (preventing leakage)."""
        self.feature_names = list(X_train.columns)
        return self.scaler.fit_transform(X_train)

    def transform_features(self, X: pd.DataFrame) -> np.ndarray:
        """Transforms feature set using the pre-fitted scaler."""
        return self.scaler.transform(X)

    def train_regression_models(
        self, X_train_scaled: np.ndarray, y_train: pd.Series
    ) -> Dict[str, Any]:
        """Trains all candidate regression models."""
        models = self.get_regression_models()
        trained = {}
        for name, model in models.items():
            model.fit(X_train_scaled, y_train)
            trained[name] = model
        self.reg_models = trained
        return trained

    def train_classification_models(
        self, X_train_scaled: np.ndarray, y_train: pd.Series
    ) -> Dict[str, Any]:
        """Trains all candidate classification models."""
        models = self.get_classification_models()
        trained = {}
        for name, model in models.items():
            model.fit(X_train_scaled, y_train)
            trained[name] = model
        self.clf_models = trained
        return trained

    def set_best_models(self, best_reg_name: str, best_clf_name: str):
        """Sets the selected champion models."""
        self.best_reg_name = best_reg_name
        self.best_reg_model = self.reg_models[best_reg_name]
        self.best_clf_name = best_clf_name
        self.best_clf_model = self.clf_models[best_clf_name]

    def get_feature_importances(self, top_n: int = 15) -> List[Dict[str, Any]]:
        """Extracts top feature importances from the champion model."""
        importances = None
        model = self.best_reg_model

        if hasattr(model, "feature_importances_"):
            importances = model.feature_importances_
        elif hasattr(model, "coef_"):
            importances = np.abs(model.coef_)
        elif hasattr(self.best_clf_model, "feature_importances_"):
            importances = self.best_clf_model.feature_importances_

        if importances is None or len(importances) != len(self.feature_names):
            return []

        # Normalize to percentage
        total = np.sum(importances)
        if total > 0:
            norm_imp = (importances / total) * 100.0
        else:
            norm_imp = importances

        feat_imp = [
            {"feature": name, "importance": round(float(imp), 2)}
            for name, imp in zip(self.feature_names, norm_imp)
        ]
        feat_imp.sort(key=lambda x: x["importance"], reverse=True)
        return feat_imp[:top_n]

    def save(self, filepath: str):
        """Saves models, scaler, and metadata to disk."""
        payload = {
            "scaler": self.scaler,
            "reg_models": self.reg_models,
            "clf_models": self.clf_models,
            "best_reg_name": self.best_reg_name,
            "best_clf_name": self.best_clf_name,
            "best_reg_model": self.best_reg_model,
            "best_clf_model": self.best_clf_model,
            "feature_names": self.feature_names,
        }
        joblib.dump(payload, filepath)

    @classmethod
    def load(cls, filepath: str) -> "StockPredictorModels":
        """Loads models, scaler, and metadata from disk."""
        payload = joblib.load(filepath)
        obj = cls()
        obj.scaler = payload["scaler"]
        obj.reg_models = payload["reg_models"]
        obj.clf_models = payload["clf_models"]
        obj.best_reg_name = payload["best_reg_name"]
        obj.best_clf_name = payload["best_clf_name"]
        obj.best_reg_model = payload["best_reg_model"]
        obj.best_clf_model = payload["best_clf_model"]
        obj.feature_names = payload["feature_names"]
        return obj
