# Bullish Trending Stocks — Quantitative Technical Analysis Screener & API

A pure algorithmic quantitative technical screener and REST API that evaluates stocks against the 26 strict technical indicator rules of the **"Bullish Trending Stocks"** algorithm.

---

## 26 Filter Rules Specification

1. **Daily EMA(close, 20)** > 20
2. **Daily SMA(volume, 20)** >= 100,000
3. **Daily Ichimoku Conversion Line(3,7,14)** >= Daily Ichimoku Base Line(3,7,14)
4. **Daily Ichimoku Span A(3,7,14)** >= Daily Ichimoku Span B(3,7,14)
5. **Daily Close** >= Daily Ichimoku Cloud Bottom(3,7,14)
6. **Daily Close** >= Daily Parabolic SAR(0.02, 0.02, 0.2)
7. **Daily RSI(10)** >= 20
8. **Daily StochRSI(10)** >= 20
9. **Daily CCI(10)** >= 0
10. **Daily MFI(10)** >= 20
11. **Daily Williams %R(10)** >= -80
12. **Daily Close** >= Daily EMA(close, 14)
13. **Daily ADX +DI(10)** >= Daily ADX -DI(10)
14. **Daily Aroon Up(10)** >= Daily Aroon Down(10)
15. **Daily Slow Stochastic %K(5,3)** >= Daily Slow Stochastic %D(5,3)
16. **Daily Fast Stochastic %K(5,3)** >= Daily Fast Stochastic %D(5,3)
17. **Daily Close** >= Daily SMA(close, 10)
18. **Daily MACD Line(14,5,3)** >= Daily MACD Signal(14,5,3)
19. **Daily MACD Histogram(14,5,3)** >= 0
20. **Daily RSI(14)** > 50
21. **Daily StochRSI(14)** > 50
22. **Daily RSI(10)** < 80
23. **Daily Close** >= Daily Upper Bollinger Band(20,2)
24. **Daily Close** >= Daily Ichimoku Cloud Bottom(9,26,52)
25. **Daily Close** > Daily Open (Green Candle Body)
26. **Daily Volume** > 100,000

---

## Quickstart

### 1. Run via CLI
```bash
# Evaluate a single stock
python main.py --ticker RELIANCE.NS
python main.py --ticker AAPL

# Launch Interactive Web Dashboard & REST API
python main.py --serve
```

---

## REST API Endpoints

Once the server is running on `http://localhost:8000`:

- `GET /` : Interactive Web Dashboard
- `GET /api/filters/spec` : Returns detailed JSON specification of all 26 rules
- `GET /api/stock/{ticker}/screen` : Evaluates all 26 rules on a specific stock ticker
- `POST /api/screen/bullish-trending` : Runs bulk screening across a stock universe (`'nse'`, `'us'`, `'all'`) or custom ticker list
