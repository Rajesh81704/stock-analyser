"""
Visualization Module
Generates plots for:
1. Actual vs Predicted Close Price on Test Set
2. Technical Indicators Dashboard (Price + BB + MA, RSI, MACD, Volume)
3. Top Feature Importances
"""

import os
from typing import Any, Dict, List, Optional
try:
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
except ImportError:
    plt = None
    mdates = None
import numpy as np
import pandas as pd


def plot_pipeline_results(
    ticker: str,
    test_preds: pd.DataFrame,
    feature_importances: List[Dict[str, Any]],
    output_path: str = "evaluation_plot.png",
):
    """
    Creates a publication-quality 3-panel figure:
    1. Actual vs Predicted Close Price on the out-of-sample Test Period
    2. Prediction Residuals / Percentage Error
    3. Top 10 Most Important Technical Indicators
    """
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)

    plt.style.use("seaborn-v0_8-darkgrid" if "seaborn-v0_8-darkgrid" in plt.style.available else "default")
    fig = plt.figure(figsize=(14, 10), dpi=150)
    gs = fig.add_gridspec(3, 1, height_ratios=[2.2, 1.0, 1.4], hspace=0.3)

    dates = pd.to_datetime(test_preds["Date"])
    actual = test_preds["Actual_Close"]
    predicted = test_preds["Predicted_Close"]
    pct_err = ((predicted - actual) / actual) * 100.0

    # Panel 1: Price Forecast vs Actual
    ax1 = fig.add_subplot(gs[0])
    ax1.plot(dates, actual, label="Actual Close Price", color="#00e5ff", linewidth=1.8)
    ax1.plot(dates, predicted, label="ML Predicted Close", color="#ff007f", linestyle="--", linewidth=1.8, alpha=0.9)
    ax1.set_title(f"{ticker} Out-of-Sample Price Prediction Benchmark (Test Set)", fontsize=13, fontweight="bold", pad=10)
    ax1.set_ylabel("Price ($)", fontsize=11)
    ax1.legend(loc="upper left", frameon=True, facecolor="#1e222d", edgecolor="#363c4e", labelcolor="white")
    ax1.grid(True, linestyle=":", alpha=0.5)

    # Format x-axis dates
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))

    # Panel 2: Residual Errors
    ax2 = fig.add_subplot(gs[1], sharex=ax1)
    ax2.plot(dates, pct_err, color="#ffa726", linewidth=1.2, label="Prediction Error %")
    ax2.axhline(0, color="gray", linestyle="--", linewidth=0.8)
    ax2.fill_between(dates, pct_err, 0, where=(pct_err >= 0), color="#26a69a", alpha=0.3)
    ax2.fill_between(dates, pct_err, 0, where=(pct_err < 0), color="#ef5350", alpha=0.3)
    ax2.set_ylabel("Error %", fontsize=11)
    ax2.set_title("Percentage Prediction Error", fontsize=11, fontweight="bold", pad=6)
    ax2.grid(True, linestyle=":", alpha=0.5)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))

    # Panel 3: Feature Importances
    ax3 = fig.add_subplot(gs[2])
    if feature_importances:
        top_10 = feature_importances[:10][::-1]  # reverse for horizontal bar chart
        feats = [item["feature"] for item in top_10]
        imps = [item["importance"] for item in top_10]
        colors = plt.cm.viridis(np.linspace(0.4, 0.9, len(feats)))
        bars = ax3.barh(feats, imps, color=colors, edgecolor="#1e222d", height=0.6)
        ax3.set_xlabel("Relative Importance (%)", fontsize=11)
        ax3.set_title("Top 10 Feature Drivers (Technical Indicators)", fontsize=11, fontweight="bold", pad=6)
        for bar in bars:
            width = bar.get_width()
            ax3.text(width + 0.3, bar.get_y() + bar.get_height() / 2, f"{width:.1f}%",
                     va="center", ha="left", fontsize=9, color="#333333")
    else:
        ax3.text(0.5, 0.5, "Feature importance not available for current model", ha="center", va="center")

    # Layout adjustments
    fig.subplots_adjust(top=0.95, bottom=0.08, left=0.08, right=0.96, hspace=0.35)
    fig.savefig(output_path, bbox_inches="tight")
    plt.close(fig)
    print(f"[Visualizer] Evaluation chart saved to: {output_path}")
    return output_path
