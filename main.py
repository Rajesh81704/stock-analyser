"""
Main CLI Application
Step-by-step stock price and trend prediction pipeline runner.
Usage:
    python main.py --ticker AAPL --mode next_day
    python main.py --ticker NVDA --mode same_day --save-chart
"""

import argparse
import sys
from src.pipeline import StockPipeline
from src.predictor import LivePredictor
from src.visualizer import plot_pipeline_results


def print_banner():
    print("""
========================================================================
     QUANTITATIVE STOCK MARKET PREDICTOR & TREND FORECASTER
  5-Year Daily OHLCV | Multi-Indicator Feature Engine | ML Ensembles
========================================================================
""")


def print_table(title: str, headers: list, rows: list):
    print(f"\n>>> {title}")
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, val in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(val)))

    sep = "+-" + "-+-".join(["-" * w for w in col_widths]) + "-+"
    header_str = "| " + " | ".join([f"{h:<{col_widths[i]}}" for i, h in enumerate(headers)]) + " |"

    print(sep)
    print(header_str)
    print(sep)
    for row in rows:
        row_str = "| " + " | ".join([f"{str(v):<{col_widths[i]}}" for i, v in enumerate(row)]) + " |"
        print(row_str)
    print(sep)


def main():
    parser = argparse.ArgumentParser(description="Stock Market Price and Trend Prediction Engine")
    parser.add_argument("--ticker", type=str, default="AAPL", help="Stock ticker symbol (e.g. AAPL, MSFT, NVDA, TSLA)")
    parser.add_argument("--mode", type=str, choices=["next_day", "same_day"], default="next_day",
                        help="Prediction mode: 'next_day' (predicts tomorrow's close) or 'same_day' (predicts today's close from open)")
    parser.add_argument("--split", type=float, default=0.8, help="Train/Test chronological split ratio (default: 0.8)")
    parser.add_argument("--save-chart", action="store_true", default=True, help="Save evaluation plot as PNG")
    parser.add_argument("--chart-path", type=str, default="evaluation_plot.png", help="Path to save evaluation chart")

    args = parser.parse_args()
    print_banner()

    ticker = args.ticker.upper()
    mode = args.mode

    # 1. Run Pipeline
    pipeline = StockPipeline(ticker=ticker, mode=mode, train_split=args.split)
    summary = pipeline.run()

    # Detect currency
    actual_ticker = summary["ticker"]
    is_indian = (
        ticker.endswith(".NS")
        or ticker.endswith(".BO")
        or ticker in ["^NSEI", "^NSEBANK", "^BSESN", "NIFTY", "NIFTY50", "BANKNIFTY", "SENSEX"]
        or actual_ticker.endswith(".NS")
        or actual_ticker.endswith(".BO")
    )
    cur = "₹" if is_indian else "$"

    # 2. Print Regression Benchmarks
    reg_headers = ["Model", f"RMSE ({cur})", f"MAE ({cur})", "MAPE (%)", "R2 Score", "Directional Acc (%)"]
    reg_rows = []
    for model_name, metrics in summary["regression_metrics"].items():
        is_champ = " (Champion)" if model_name == summary["best_reg_model"] else ""
        reg_rows.append([
            f"{model_name}{is_champ}",
            f"{metrics['RMSE']:.2f}",
            f"{metrics['MAE']:.2f}",
            f"{metrics['MAPE_%']:.2f}%",
            f"{metrics['R2']:.4f}",
            f"{metrics['Directional_Accuracy_%']:.1f}%",
        ])
    print_table("REGRESSION BENCHMARKS (CLOSE PRICE)", reg_headers, reg_rows)

    # 3. Print Classification Benchmarks
    clf_headers = ["Model", "Accuracy (%)", "Precision (%)", "Recall (%)", "F1 Score (%)", "ROC-AUC (%)"]
    clf_rows = []
    for model_name, metrics in summary["classification_metrics"].items():
        is_champ = " (Champion)" if model_name == summary["best_clf_model"] else ""
        clf_rows.append([
            f"{model_name}{is_champ}",
            f"{metrics['Accuracy_%']:.1f}%",
            f"{metrics['Precision_%']:.1f}%",
            f"{metrics['Recall_%']:.1f}%",
            f"{metrics['F1_Score_%']:.1f}%",
            f"{metrics['ROC_AUC_%']:.1f}%",
        ])
    print_table("CLASSIFICATION BENCHMARKS (BULLISH / BEARISH TREND)", clf_headers, clf_rows)

    # 4. Top Features Table
    top_feats = summary["top_features"][:10]
    if top_feats:
        feat_headers = ["Rank", "Technical Feature", "Relative Importance (%)"]
        feat_rows = [[i + 1, item["feature"], f"{item['importance']:.2f}%"] for i, item in enumerate(top_feats)]
        print_table("TOP 10 INFLUENTIAL TECHNICAL INDICATORS", feat_headers, feat_rows)

    # 5. Live Forward Prediction
    predictor = LivePredictor(actual_ticker, pipeline.feature_engineer, pipeline.models_manager, pipeline.raw_df)
    live_pred = predictor.predict_forward()

    pred_info = live_pred["prediction"]
    ind_info = live_pred["key_indicators"]
    ohlcv = live_pred["last_ohlcv"]

    print("\n" + "=" * 72)
    print(f"  LIVE FORWARD FORECAST FOR {actual_ticker}")
    print(f"  Mode: {mode.replace('_', ' ').title()} | As-Of Date: {live_pred['as_of_date']}")
    print("=" * 72)
    print(f"  Reference Base Price:       {cur}{live_pred['reference_price']:.2f}")
    print(f"  PREDICTED CLOSE:            {cur}{pred_info['predicted_close']:.2f}")
    print(f"  Expected Price Delta:       {pred_info['expected_price_change']:+.2f} ({pred_info['expected_pct_change']:+.2f}%)")
    print(f"  Expected Trading Range:     {cur}{pred_info['expected_trading_range']['low']:.2f} to {cur}{pred_info['expected_trading_range']['high']:.2f}")
    print(f"  TREND SIGNAL:               {pred_info['trend']} (Confidence: {pred_info['confidence_%']}%)")
    print(f"  Trend Probability Split:    Bullish {pred_info['bullish_probability_%']}% | Bearish {pred_info['bearish_probability_%']}%")
    print("-" * 72)
    print("  KEY TECHNICAL INDICATOR SNAPSHOT:")
    print(f"  - RSI (14-day):             {ind_info['rsi_14']} {'[Overbought]' if ind_info['rsi_14']>=70 else '[Oversold]' if ind_info['rsi_14']<=30 else '[Neutral]'}")
    print(f"  - MACD / Signal:            {ind_info['macd']} / {ind_info['macd_signal']} (Hist: {ind_info['macd_hist']:+.3f})")
    print(f"  - Bollinger Bands:          Lower: {cur}{ind_info['bb_lower']:.2f} | Mid: {cur}{ind_info['bb_middle']:.2f} | Upper: {cur}{ind_info['bb_upper']:.2f}")
    print(f"  - Moving Averages:          SMA20: {cur}{ind_info['sma_20']:.2f} | SMA50: {cur}{ind_info['sma_50']:.2f} | SMA200: {cur}{ind_info['sma_200']:.2f}")
    print(f"  - Pivot & Levels:           Pivot: {cur}{ind_info['pivot']:.2f} | R1: {cur}{ind_info['resistance_r1']:.2f} | S1: {cur}{ind_info['support_s1']:.2f}")
    print(f"  - Volatility (ATR 14):      {cur}{ind_info['atr_14']:.2f} | ADX (Trend Strength): {ind_info['adx_14']}")
    print("=" * 72)

    # 6. Save chart
    if args.save_chart and pipeline.test_predictions is not None:
        plot_pipeline_results(ticker, pipeline.test_predictions, summary["top_features"], args.chart_path)


if __name__ == "__main__":
    main()
