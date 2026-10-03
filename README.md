# Quantitative Stock Market Predictor & Trend Forecaster

An end-to-end machine learning system that ingests **5-year historical daily OHLCV data** via Yahoo Finance (`yfinance`), computes **64+ quantitative technical indicators**, and trains regularized machine learning ensembles (Ridge, Random Forest, LightGBM, XGBoost) to predict:
1. **Target 1 (Regression):** The **Close Price** (Next-Day Close or Same-Day Close from Open).
2. **Target 2 (Classification):** The **Trend Direction** (**Bullish** vs **Bearish** with probabilistic confidence).

---

## Key Features

- **5-Year Historical Daily Data:** Fetched cleanly via `yfinance`, with automated split/dividend adjustment, null handling, and trading calendar alignment.
- **Engineered Technical Indicators:**
  - **Volatility:** Average True Range (ATR-14), Normalized ATR (`NATR`), Historical Volatility (20-day annualized std of log returns), High-Low intraday spread.
  - **Volume:** 20-day Volume SMA ratio, 5-day Volume Rate of Change (ROC), On-Balance Volume (OBV), 20-day OBV EMA, Volume Price Trend (VPT).
  - **Trend:** Average Directional Index (ADX-14), +DI, -DI, Trend Strength filter, 20-day EMA slope, Consecutive candle trends.
  - **Moving Averages (MA):** Simple Moving Averages (`SMA 10`, `SMA 20`, `SMA 50`, `SMA 200`), Exponential Moving Averages (`EMA 9`, `EMA 21`, `EMA 50`), price-to-MA percentage distance ratios, Golden Cross and Fast EMA Cross indicators.
  - **RSI:** 14-day Wilder's smoothed RSI, 7-day Fast RSI, Overbought (>70) and Oversold (<30) flags, Zero-centered RSI.
  - **Support & Resistance:** 20-day rolling local High (Resistance) and Low (Support), Classical Floor Trader Pivot Points ($P, R_1, S_1, R_2, S_2$), normalized distance to Support/Resistance/Pivot.
  - **MACD:** Fast (12) / Slow (26) EMA spread, 9-day Signal line, MACD Histogram, normalized MACD as % of price, Bullish crossover flag.
  - **Bollinger Bands:** 20-day Middle Band, Upper Band ($+2\sigma$), Lower Band ($-2\sigma$), Bandwidth, %B oscillator, Volatility Squeeze detector.
  - **Opening Price Features:** Today's Open price, Overnight Gap % (`(Open - Prev_Close)/Prev_Close`), Open position within yesterday's range, Open relative to pivot.
- **Strict Leakage Prevention:**
  - Zero random shuffling: Strict chronological time-series split (80% Train, 20% Test).
  - Scalers fit strictly on training bars.
  - Strict lag alignment: morning same-day predictions only use $t-1$ indicators and today's $Open_t$.
- **Model Ensembles & Benchmarks:**
  - Regression: Ridge Regression, Random Forest Regressor, LightGBM Regressor, XGBoost Regressor.
  - Classification: Logistic Regression, Random Forest Classifier, LightGBM Classifier, XGBoost Classifier.
  - Automated Champion Model selection based on out-of-sample metrics (RMSE, MAE, MAPE, $R^2$, Accuracy, F1, ROC-AUC).
- **Interactive Web Terminal & CLI:**
  - Terminal CLI with formatted ASCII benchmark tables and PNG export.
  - Dark-mode glassmorphic Web UI with interactive Chart.js charts and live trading gauges.

---

## Project Structure

```
stock-analyser/
├── src/
│   ├── __init__.py
│   ├── data_loader.py        # Step 1: yfinance 5-year OHLCV downloader & validator
│   ├── indicators.py         # Step 2: Technical indicator mathematical formulas
│   ├── features.py           # Step 3: Feature engineering, lagging, and target alignment
│   ├── models.py             # Step 4: Machine learning models (Ridge, RF, LightGBM, XGBoost)
│   ├── pipeline.py           # Step 5: Chronological train/test split & evaluation benchmarks
│   ├── predictor.py          # Step 6: Live forward inference engine for next session
│   └── visualizer.py         # Step 7: High-resolution benchmark and feature importance plots
├── web/
│   ├── app.py                # FastAPI REST API backend
│   ├── static/
│   │   ├── css/style.css     # Premium dark-mode glassmorphic design system
│   │   └── js/app.js         # Interactive Chart.js and UI controller
│   └── templates/
│       └── index.html        # Single-page quantitative dashboard
├── main.py                   # Main CLI executable
├── requirements.txt          # Python dependencies
└── README.md
```

---

## Quickstart

### 1. Activate Environment
```bash
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Run via CLI
Predict **Next-Day Close and Trend** for any stock:
```bash
python main.py --ticker AAPL --mode next_day
```

Predict **Same-Day Close** from market open:
```bash
python main.py --ticker NVDA --mode same_day
```

Options:
- `--ticker`: Any Yahoo Finance ticker symbol (e.g., `AAPL`, `MSFT`, `NVDA`, `TSLA`, `RELIANCE.NS`, `SPY`).
- `--mode`: `next_day` (default) or `same_day`.
- `--split`: Train/Test split ratio (default: `0.8`).
- `--save-chart`: Save high-resolution benchmark chart as PNG (default: `True`).
- `--chart-path`: Output chart file path (default: `evaluation_plot.png`).

### 3. Launch the Interactive Web Dashboard
```bash
python web/app.py
```
Open **[http://localhost:8000](http://localhost:8000)** in your browser.
- Search any ticker or click popular ticker chips (`AAPL`, `NVDA`, `MSFT`, `TSLA`, `SPY`, etc.).
- Switch between Next-Day and Same-Day forecasting modes.
- Inspect the live probability gauge, Bollinger Band overlays, model comparison tables, and top 10 feature drivers.
