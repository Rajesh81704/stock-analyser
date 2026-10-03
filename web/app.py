"""
FastAPI Enterprise REST API with Interactive Swagger Documentation (OpenAPI 3.1)
Endpoints:
1. GET  /api/stocks               - Directory of NIFTY 500 with search & sector filters
2. GET  /api/stock/{ticker}       - Consolidated Fundamentals + Technicals + Forecast + Chart
3. GET  /api/market/analysis      - Market breadth, advances/declines, sector heat, top breakouts
4. POST /api/cron/run             - Manual trigger for incremental trailing cron worker
"""

import asyncio
from contextlib import asynccontextmanager
import datetime
import os
from typing import Any, Dict, List, Optional
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import BackgroundTasks, FastAPI, HTTPException, Path, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.batch_trainer import batch_manager, run_init_all_models_sync, run_topup_and_update_models_sync
from src.cron_worker import process_single_stock_pipeline, run_trailing_daily_cron
from src.data_loader import fetch_stock_data, resolve_ticker
from src.market_analyzer import compute_market_segmentation
from src.models_registry import train_and_predict_stock
from src.db import (
    bulk_upsert_indicators,
    bulk_upsert_ohlcv,
    bulk_upsert_predictions,
    get_all_stocks_summary_list,
    get_all_tickers,
    get_consolidated_stock_data,
    get_latest_market_analysis_data,
    get_stock_history_df,
    init_db,
)

# Background Scheduler for daily cron
scheduler = BackgroundScheduler()


def scheduled_daily_cron_job():
    print(f"[Scheduler] Triggering scheduled daily trailing cron at {datetime.datetime.now()}...")
    try:
        run_trailing_daily_cron(max_workers=8)
    except Exception as e:
        print(f"[Scheduler] Cron execution error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler.add_job(
        scheduled_daily_cron_job,
        trigger=CronTrigger(day_of_week="mon-fri", hour=16, minute=0, timezone="Asia/Kolkata"),
        id="nifty500_daily_cron",
        replace_existing=True,
    )
    try:
        scheduler.start()
        print("[Server] APScheduler started. Scheduled daily NIFTY 500 cron for Mon-Fri 16:00 IST.")
    except Exception as e:
        print(f"[Server] APScheduler start skipped (serverless environment): {e}")
    yield
    try:
        scheduler.shutdown(wait=False)
    except Exception:
        pass


# =====================================================================
# Pydantic Schemas for Swagger / OpenAPI Documentation
# =====================================================================

class StockSummaryItem(BaseModel):
    ticker: str = Field(..., example="RELIANCE.NS", description="NSE Ticker symbol with .NS suffix")
    company_name: Optional[str] = Field(None, example="Reliance Industries Ltd.", description="Registered Company Name")
    sector: Optional[str] = Field(None, example="Oil Gas & Consumable Fuels", description="Industry Sector")
    industry: Optional[str] = Field(None, example="Refining & Marketing", description="Sub-industry classification")
    market_cap: Optional[float] = Field(None, example=1850000.0, description="Market Capitalization in ₹ Crores")
    latest_close: Optional[float] = Field(None, example=1167.70, description="Latest Close Price in ₹")
    as_of_date: Optional[str] = Field(None, example="2026-10-01", description="Date of latest bar")
    trend_signal: Optional[str] = Field(None, example="BULLISH", description="Predicted trend: BULLISH or BEARISH")
    predicted_close: Optional[float] = Field(None, example=1172.02, description="Target predicted Close price in ₹")
    expected_pct_change: Optional[float] = Field(None, example=0.37, description="Expected price change percentage")
    confidence_pct: Optional[float] = Field(None, example=70.7, description="Model confidence score (0-100%)")


class StocksListResponse(BaseModel):
    status: str = Field("success", example="success")
    count: int = Field(..., example=501, description="Number of stocks returned")
    stocks: List[StockSummaryItem]


class FundamentalsModel(BaseModel):
    ticker: str = Field(..., example="RELIANCE.NS")
    company_name: Optional[str] = Field(None, example="Reliance Industries Ltd.")
    sector: Optional[str] = Field(None, example="Oil Gas & Consumable Fuels")
    industry: Optional[str] = Field(None, example="Refining & Marketing")
    market_cap: Optional[float] = Field(None, example=1850000.0, description="Market Cap in ₹ Crores")
    pe_ratio: Optional[float] = Field(None, example=24.5, description="Trailing Price-to-Earnings Ratio")
    pb_ratio: Optional[float] = Field(None, example=2.8, description="Price-to-Book Ratio")
    eps: Optional[float] = Field(None, example=48.2, description="Trailing Twelve Months EPS in ₹")
    dividend_yield: Optional[float] = Field(None, example=0.85, description="Annual Dividend Yield (%)")
    roe: Optional[float] = Field(None, example=12.4, description="Return on Equity (%)")
    last_fundamental_update: Optional[str] = Field(None, example="2026-10-03 16:30:00")


class OHLCVModel(BaseModel):
    ticker: str = Field(..., example="RELIANCE.NS")
    date: str = Field(..., example="2026-10-01")
    open: float = Field(..., example=1160.00)
    high: float = Field(..., example=1175.50)
    low: float = Field(..., example=1158.20)
    close: float = Field(..., example=1167.70)
    volume: float = Field(..., example=8450000.0)


class TechnicalsModel(BaseModel):
    ticker: str = Field(..., example="RELIANCE.NS")
    date: str = Field(..., example="2026-10-01")
    rsi_14: Optional[float] = Field(None, example=45.2, description="14-day Relative Strength Index (0-100)")
    macd: Optional[float] = Field(None, example=3.21, description="12/26 MACD Line")
    macd_signal: Optional[float] = Field(None, example=2.88, description="9-day MACD Signal Line")
    macd_hist: Optional[float] = Field(None, example=0.33, description="MACD Histogram (MACD - Signal)")
    sma_20: Optional[float] = Field(None, example=1180.20, description="20-day Simple Moving Average")
    sma_50: Optional[float] = Field(None, example=1210.40, description="50-day Simple Moving Average")
    sma_200: Optional[float] = Field(None, example=1250.60, description="200-day Simple Moving Average")
    ema_9: Optional[float] = Field(None, example=1172.50, description="9-day Exponential Moving Average")
    ema_21: Optional[float] = Field(None, example=1185.30, description="21-day Exponential Moving Average")
    bb_upper: Optional[float] = Field(None, example=1220.40, description="Upper Bollinger Band (+2 sigma)")
    bb_middle: Optional[float] = Field(None, example=1180.20, description="Middle Bollinger Band (20 SMA)")
    bb_lower: Optional[float] = Field(None, example=1140.00, description="Lower Bollinger Band (-2 sigma)")
    bb_bandwidth: Optional[float] = Field(None, example=0.065, description="Bollinger Bandwidth ratio")
    atr_14: Optional[float] = Field(None, example=20.10, description="14-day Average True Range in ₹")
    natr_14: Optional[float] = Field(None, example=1.72, description="Normalized ATR (% of Close)")
    adx_14: Optional[float] = Field(None, example=28.4, description="14-day Average Directional Index (Trend Strength)")
    pivot_p: Optional[float] = Field(None, example=1188.40, description="Floor Trader Pivot Point (P)")
    pivot_r1: Optional[float] = Field(None, example=1195.10, description="First Resistance Level (R1)")
    pivot_s1: Optional[float] = Field(None, example=1180.30, description="First Support Level (S1)")


class PredictionModel(BaseModel):
    ticker: str = Field(..., example="RELIANCE.NS")
    date: str = Field(..., example="2026-10-01", description="As-of historical date")
    target_date: str = Field(..., example="2026-10-03", description="Forecast target trading session")
    reference_close: float = Field(..., example=1167.70, description="Current reference price")
    predicted_close: float = Field(..., example=1172.02, description="Predicted target close price in ₹")
    expected_pct_change: float = Field(..., example=0.37, description="Expected percentage change")
    range_low: float = Field(..., example=1161.97, description="Expected lower price bound (ATR based)")
    range_high: float = Field(..., example=1182.06, description="Expected upper price bound (ATR based)")
    trend_signal: str = Field(..., example="BULLISH", description="Trend Direction: BULLISH or BEARISH")
    confidence_pct: float = Field(..., example=70.7, description="Model probability confidence (%)")
    champion_model: str = Field(..., example="Ridge+LogReg", description="Champion ML model identifier")
    elimination_factors: List[str] = Field(default_factory=list, description="Optimization and false positive elimination factors")


class ChartBarModel(BaseModel):
    date: str = Field(..., example="2026-10-01")
    open: float = Field(..., example=1160.00)
    high: float = Field(..., example=1175.50)
    low: float = Field(..., example=1158.20)
    close: float = Field(..., example=1167.70)
    volume: float = Field(..., example=8450000.0)
    sma_20: Optional[float] = Field(None, example=1180.20)
    sma_50: Optional[float] = Field(None, example=1210.40)
    bb_upper: Optional[float] = Field(None, example=1220.40)
    bb_lower: Optional[float] = Field(None, example=1140.00)
    bb_middle: Optional[float] = Field(None, example=1180.20)


class StockDetailResponse(BaseModel):
    status: str = Field("success", example="success")
    ticker: str = Field(..., example="RELIANCE.NS")
    currency_symbol: str = Field("₹", example="₹")
    day_change: float = Field(..., example=5.20, description="1-day price change in ₹")
    day_change_pct: float = Field(..., example=0.45, description="1-day price change percentage")
    fundamentals: Optional[FundamentalsModel]
    latest_ohlcv: Optional[OHLCVModel]
    technicals: Optional[TechnicalsModel]
    prediction: Optional[PredictionModel]
    next_hour_prediction: Optional[PredictionModel] = Field(None, description="Intraday 1-hour horizon forecast")
    chart_history: List[ChartBarModel] = Field(default_factory=list, description="Trailing 90 trading sessions")


class MarketAnalysisResponse(BaseModel):
    status: str = Field("success", example="success")
    market_analysis: Dict[str, Any] = Field(
        ...,
        example={
            "date": "2026-10-01",
            "advances": 285,
            "declines": 215,
            "pct_above_sma50": 62.4,
            "pct_above_sma200": 74.8,
            "top_bullish_tickers": [
                {"ticker": "TCS.NS", "expected_pct_change": 1.14, "confidence_pct": 66.9, "trend_signal": "BULLISH"}
            ],
            "top_bearish_tickers": [
                {"ticker": "TMCV.NS", "expected_pct_change": -2.10, "confidence_pct": 61.1, "trend_signal": "BEARISH"}
            ],
            "sector_performance": {"Financial Services": 0.85, "Information Technology": 1.20}
        }
    )


class CronRunResponse(BaseModel):
    status: str = Field("triggered", example="triggered")
    message: str = Field(..., example="Trailing daily cron worker launched in background.")


class ModelInitResponse(BaseModel):
    status: str = Field(..., example="initiated")
    task: str = Field("init_all_models", example="init_all_models")
    message: str = Field(..., example="Batch creation of all 500 Logistic Regression models started.")
    total_stocks: int = Field(..., example=501, description="Total number of constituent stocks queued for training")
    check_status_url: str = Field("/api/models/status", example="/api/models/status", description="Polling endpoint for real-time progress")


class ModelStatusResponse(BaseModel):
    task_type: str = Field(..., example="init_all_models", description="Active task identifier (init_all_models, topup_and_update, idle)")
    status: str = Field(..., example="running", description="Operational status: idle, running, completed, failed")
    progress_pct: float = Field(..., example=42.5, description="Completion progress percentage (0.0 to 100.0%)")
    total_stocks: int = Field(..., example=501, description="Total constituents in scope")
    completed_stocks: int = Field(..., example=213, description="Models successfully fitted and saved")
    failed_stocks: int = Field(..., example=2, description="Stocks with errors or insufficient trading history")
    current_ticker: Optional[str] = Field(None, example="INFY.NS", description="Stock currently undergoing training/top-up")
    started_at: Optional[str] = Field(None, example="2026-10-03T22:45:00", description="Start timestamp")
    completed_at: Optional[str] = Field(None, example="2026-10-03T22:48:30", description="Finish timestamp")
    elapsed_seconds: Optional[float] = Field(None, example=45.2, description="Elapsed execution seconds")
    message: str = Field(..., example="Training models in progress...")
    details: Dict[str, Any] = Field(default_factory=dict, description="Detailed execution metrics and results")


class ModelTopupResponse(BaseModel):
    status: str = Field("success", example="success")
    message: str = Field(..., example="Today's data topped up and models updated successfully.")
    updated_tickers_count: Optional[int] = Field(None, example=501, description="Constituents evaluated for top-up")
    new_bars_count: Optional[int] = Field(None, example=501, description="Total new OHLCV daily bars ingested")
    predictions_count: Optional[int] = Field(None, example=501, description="New forward predictions generated")
    elapsed_seconds: Optional[float] = Field(None, example=12.4, description="Execution duration in seconds")
    ticker: Optional[str] = Field(None, example="RELIANCE.NS", description="Specific ticker if single-stock top-up")
    latest_prediction: Optional[Dict[str, Any]] = Field(None, description="Forward prediction if single-stock top-up")


class SegmentSentimentItem(BaseModel):
    count: int = Field(..., example=30)
    pct: float = Field(..., example=6.0)
    label: str = Field(..., example="Extreme Bullish")
    color: str = Field(..., example="#00e5ff")
    description: str = Field(..., example="High predicted upside (>= +1.5%) with strong ML model conviction")


class SectorConvictionItem(BaseModel):
    sector: str = Field(..., example="Financial Services")
    total_stocks: int = Field(..., example=98)
    bullish_count: int = Field(..., example=53)
    bearish_count: int = Field(..., example=45)
    bullish_pct: float = Field(..., example=54.1)
    bearish_pct: float = Field(..., example=45.9)
    bias: str = Field(..., example="BULLISH_LEAN")
    counts: Dict[str, int] = Field(..., example={"extreme_bullish": 5, "medium_bullish": 21, "mild_bullish": 27, "mild_bearish": 26, "medium_bearish": 16, "extreme_bearish": 3})


class SegmentedStockItem(BaseModel):
    ticker: str = Field(..., example="TCS.NS")
    company_name: str = Field(..., example="Tata Consultancy Services Ltd.")
    sector: str = Field(..., example="Information Technology")
    industry: str = Field(..., example="Computers - Software & Consulting")
    close: float = Field(..., example=2075.0)
    predicted_close: float = Field(..., example=2110.5)
    expected_pct_change: float = Field(..., example=1.71)
    confidence_pct: float = Field(..., example=72.4)
    trend_signal: str = Field(..., example="BULLISH")
    rsi_14: Optional[float] = Field(None, example=58.4)
    segment_key: str = Field(..., example="extreme_bullish")
    segment_label: str = Field(..., example="Extreme Bullish")


class MarketSegmentationResponse(BaseModel):
    status: str = Field("success", example="success")
    total_stocks: int = Field(..., example=501)
    total_bullish: int = Field(..., example=260)
    total_bearish: int = Field(..., example=241)
    sentiment_counts: Dict[str, SegmentSentimentItem]
    sectors: List[SectorConvictionItem]
    stocks_count: int = Field(..., example=501)
    stocks: List[SegmentedStockItem]


# =====================================================================
# OpenAPI / Swagger Tags & App Metadata
# =====================================================================

tags_metadata = [
    {
        "name": "NIFTY 500 Directory",
        "description": "Browse and search all official NIFTY 500 constituents with real-time sector filtering, latest close price, and trend forecasts.",
    },
    {
        "name": "Stock Analysis & Forecasting",
        "description": "Consolidated single-shot endpoint delivering fundamental valuation, 64+ technical indicators, ML price targets, and 90-day charting data.",
    },
    {
        "name": "Model Training & Lifecycle",
        "description": "Batch creation of all 500 Logistic Regression models with historical data up to today, trailing daily top-up of today's latest bars and model refit, and live training progress monitoring.",
    },
    {
        "name": "Market Breadth & Scanner",
        "description": "Market-wide analytics: Advances vs Declines, percentage of stocks above 50/200 SMA, sector heat, and top 10 breakout/breakdown candidates.",
    },
    {
        "name": "Automated Trailing Cron",
        "description": "Trigger on-demand incremental data ingestion, technical indicator computation, and ML model retraining without re-downloading historical data.",
    },
]

APP_DESCRIPTION = """
# NIFTY 500 Quantitative AI Engine & Prediction API

An automated quantitative trading and market intelligence backend targeting exclusively the **NIFTY 500** universe on the National Stock Exchange of India (NSE).

### Key Architectural Capabilities:
- **SQLite Database with WAL Mode**: High-concurrency Write-Ahead Logging allows continuous, non-blocking API reads during daily background updates.
- **Incremental Trailing Ingestion**: Only missing trailing bars are downloaded, saving network bandwidth and avoiding rate limits.
- **64+ Engineered Indicators**: ATR, Normalized ATR, Historical Volatility, RSI 14, MACD Histogram, Bollinger Bands, MAs (20, 50, 200), Pivot Points ($P, R_1, S_1$), and ADX 14.
- **Persistent ML Ensembles**: Dedicated models per stock (`Ridge` + `LogisticRegression` with `RobustScaler`) saved in `models_registry/` for low-latency inference.
- **Automated Scheduling**: APScheduler configured to run Monday–Friday at 16:00 IST (market close).
"""

app = FastAPI(
    title="NIFTY 500 Quantitative Prediction Engine & Trading Intelligence API",
    description=APP_DESCRIPTION,
    version="2.0.0",
    openapi_tags=tags_metadata,
    docs_url="/docs",          # Interactive Swagger UI
    redoc_url="/redoc",        # ReDoc Documentation
    openapi_url="/openapi.json",
    swagger_ui_parameters={
        "docExpansion": "list",
        "filter": True,
        "syntaxHighlight.theme": "obsidian",
        "persistAuthorization": True,
        "displayRequestDuration": True,
        "tryItOutEnabled": True,
    },
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

static_path = os.path.join(BASE_DIR, "web", "static")
if os.path.exists(static_path):
    app.mount("/static", StaticFiles(directory=static_path), name="static")
else:
    app.mount("/static", StaticFiles(directory="web/static"), name="static")


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def serve_index():
    index_path = os.path.join(BASE_DIR, "web", "templates", "index.html")
    if not os.path.exists(index_path):
        index_path = "web/templates/index.html"
    with open(index_path, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


# Convenient redirects so /DOCS, /swagger, /api-docs effortlessly route to Swagger UI
@app.get("/DOCS", include_in_schema=False)
@app.get("/docs/", include_in_schema=False)
@app.get("/swagger", include_in_schema=False)
@app.get("/swagger/", include_in_schema=False)
@app.get("/swagger-ui", include_in_schema=False)
@app.get("/api-docs", include_in_schema=False)
@app.get("/api/docs", include_in_schema=False)
async def swagger_docs_redirect():
    return RedirectResponse(url="/docs", status_code=307)


# =====================================================================
# Documented REST Endpoints
# =====================================================================

@app.get(
    "/api/stocks",
    response_model=StocksListResponse,
    summary="List all NIFTY 500 Constituents",
    tags=["NIFTY 500 Directory"],
    status_code=status.HTTP_200_OK,
)
async def list_stocks(
    query: Optional[str] = Query(None, description="Search by ticker symbol or company name (e.g. 'RELIANCE', 'TATA', 'HDFC')"),
    sector: Optional[str] = Query(None, description="Filter by sector / industry (e.g. 'Financial Services', 'Information Technology')"),
):
    """
    Returns the complete directory of NIFTY 500 stocks stored in SQLite,
    including latest price, market cap, day change %, and machine learning trend forecast.
    """
    try:
        stocks = get_all_stocks_summary_list(query_filter=query or "", sector_filter=sector or "")
        return {
            "status": "success",
            "count": len(stocks),
            "stocks": stocks,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get(
    "/api/stock/{ticker}",
    response_model=StockDetailResponse,
    summary="Get Consolidated Stock Analytics & Forecast",
    tags=["Stock Analysis & Forecasting"],
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Full stock intelligence packet returned successfully"},
        400: {"description": "Error bootstrapping stock data from provider"},
        404: {"description": "Ticker symbol not found in universe"},
    },
)
async def get_stock_details(
    ticker: str = Path(..., description="Stock ticker symbol (e.g. 'RELIANCE', 'TCS', 'AXISBANK.NS', 'NIFTY')")
):
    """
    **Single-Shot Consolidated Endpoint**:
    Retrieves all essential analytics for a given stock from local SQLite storage:
    - **Fundamental Valuation**: Market Cap (₹ Cr), P/E, P/B, EPS, Dividend Yield, ROE, Sector, Industry.
    - **Technical Indicators**: RSI 14, MACD & Histogram, Bollinger Bands, Moving Averages (20, 50, 200), Pivot Levels (P, R1, S1), ATR 14, ADX 14.
    - **Tomorrow's ML Forecast**: Predicted Close Price (₹), Price Delta, Trading Range (Low - High), Bullish/Bearish Direction, Confidence Score (%).
    - **Historical Chart Bars**: Trailing 90 trading sessions with overlay technical indicators.
    
    *Note: If the stock is not yet cached in the SQLite database, it is dynamically bootstrapped on-the-fly.*
    """
    clean_ticker = resolve_ticker(ticker.strip().upper())
    data = get_consolidated_stock_data(clean_ticker)

    # Dynamic on-the-fly bootstrapping if not in DB cache
    if not data or not data.get("latest_ohlcv"):
        print(f"[API] Ticker {clean_ticker} not in database cache. Initializing on-the-fly...")
        try:
            raw_df = fetch_stock_data(clean_ticker, period="5y")
            records = []
            for idx, row in raw_df.iterrows():
                records.append({
                    "ticker": clean_ticker,
                    "date": idx.strftime("%Y-%m-%d"),
                    "open": round(float(row["Open"]), 2),
                    "high": round(float(row["High"]), 2),
                    "low": round(float(row["Low"]), 2),
                    "close": round(float(row["Close"]), 2),
                    "volume": float(row.get("Volume", 1.0)),
                })
            bulk_upsert_ohlcv(records)

            ind_rec, pred_rec = process_single_stock_pipeline(clean_ticker)
            if ind_rec:
                bulk_upsert_indicators([ind_rec])
            if pred_rec:
                bulk_upsert_predictions([pred_rec])

            data = get_consolidated_stock_data(clean_ticker)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Could not load data for {ticker}: {str(e)}")

    if not data:
        raise HTTPException(status_code=404, detail=f"Stock '{ticker}' could not be resolved.")

    is_indian = (
        clean_ticker.endswith(".NS")
        or clean_ticker.endswith(".BO")
        or clean_ticker.startswith("^")
    )
    data["currency_symbol"] = "₹" if is_indian else "$"

    # Compute Next-Hour Intraday Forecast on-the-fly
    try:
        df_hist = get_stock_history_df(clean_ticker, limit=250)
        if not df_hist.empty and len(df_hist) >= 30:
            next_hour_pred = train_and_predict_stock(clean_ticker, df_hist, mode="next_hour")
            data["next_hour_prediction"] = next_hour_pred
        else:
            data["next_hour_prediction"] = None
    except Exception as e:
        print(f"[API] Error computing next_hour prediction for {clean_ticker}: {e}")
        data["next_hour_prediction"] = None

    data["status"] = "success"
    return data


@app.get(
    "/api/market/analysis",
    response_model=MarketAnalysisResponse,
    summary="Get Daily Market Breadth & Opportunity Scan",
    tags=["Market Breadth & Scanner"],
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Daily market analysis report retrieved"},
        404: {"description": "No analysis report generated yet; run cron first"},
    },
)
async def get_market_analysis():
    """
    Returns market-wide breadth and algorithmic opportunity scans across NIFTY 500:
    - **Market Breadth**: Advances vs Declines count.
    - **Trend Participation**: % of stocks above 50-day and 200-day Simple Moving Averages.
    - **Sector Performance**: Aggregated average returns across all NSE industry sectors.
    - **Top 10 Bullish Breakouts**: Ranked by predicted upside and model confidence.
    - **Top 10 Bearish Breakdowns**: Ranked by predicted downside risk.
    """
    report = get_latest_market_analysis_data()
    if not report:
        raise HTTPException(status_code=404, detail="No market analysis report available yet. Run cron first.")
    return {
        "status": "success",
        "market_analysis": report,
    }


@app.get(
    "/api/market/segmentation",
    response_model=MarketSegmentationResponse,
    summary="Get Industry & Sentiment Segmentation Matrix",
    tags=["Market Breadth & Scanner", "Stock Analysis & Forecasting"],
    status_code=status.HTTP_200_OK,
)
async def get_market_segmentation_endpoint(
    sector: Optional[str] = Query(None, description="Filter stocks to a specific industry / sector (e.g. 'Financial Services', 'Healthcare')"),
    segment: Optional[str] = Query(None, description="Filter by conviction band: 'extreme_bullish', 'medium_bullish', 'mild_bullish', 'mild_bearish', 'medium_bearish', 'extreme_bearish'"),
):
    """
    **Comprehensive Industry & Sentiment Conviction Segmentation**:
    Analyzes all stocks and machine learning models across the NIFTY 500 universe,
    segmenting them into 6 distinct sentiment conviction bands across all industry sectors:
    
    ### 🟢 Bullish Conviction Bands:
    - **Extreme Bullish**: High predicted upside (>= +1.5%) with strong ML model conviction (>= 68%).
    - **Medium Bullish**: Solid predicted upside (+0.4% to +1.5%).
    - **Mild Bullish**: Moderate upward drift (0.0% to +0.4%).
    
    ### 🔴 Bearish Conviction Bands:
    - **Mild Bearish**: Modest downward drift (0.0% to -0.4%).
    - **Medium Bearish**: Moderate downside risk (-0.4% to -1.5%).
    - **Extreme Bearish**: Sharp predicted drop (<= -1.5%) with high model conviction (>= 68%).
    
    Returns universe-wide sentiment counts, industry-by-industry breakdowns, and filtered constituent stocks.
    """
    try:
        data = compute_market_segmentation(target_sector=sector, target_segment=segment)
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post(
    "/api/cron/run",
    response_model=CronRunResponse,
    summary="Trigger Trailing Ingestion Cron Job",
    tags=["Automated Trailing Cron"],
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_cron_manually(background_tasks: BackgroundTasks):
    """
    Triggers the incremental daily trailing workflow asynchronously in the background:
    1. Downloads only missing daily OHLCV bars across NIFTY 500 constituents.
    2. Recomputes technical indicators for the trailing 250 sessions.
    3. Incrementally retrains/updates ML models and regenerates tomorrow's forecasts.
    4. Computes daily market breadth, sector heat, and opportunity rankings.
    """
    background_tasks.add_task(run_trailing_daily_cron, 8)
    return {
        "status": "triggered",
        "message": "Trailing daily cron worker launched in background.",
    }


# =====================================================================
# Model Training & Lifecycle Management Endpoints
# =====================================================================

@app.post(
    "/api/models/init-all",
    response_model=ModelInitResponse,
    summary="Initiate Creation of All 500 Logistic Regression Models",
    tags=["Model Training & Lifecycle"],
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        202: {"description": "Batch model creation initiated in background"},
        409: {"description": "Another training or top-up job is currently running"},
    },
)
async def initiate_all_models(
    background_tasks: BackgroundTasks,
    limit: Optional[int] = Query(None, description="Limit number of stocks to process (e.g. 20 for rapid testing, or omit for all 501)"),
    period: str = Query("5y", description="Historical data period to ingest if missing"),
    max_workers: int = Query(8, description="Worker threads for parallel training"),
    force: bool = Query(False, description="Force start training even if a background task is marked running"),
):
    """
    **Batch-Initiate All 500 NIFTY Logistic Regression Models**:
    1. Ingests historical daily OHLCV bars up to today's latest session across NIFTY 500.
    2. Vectorizes 64+ technical indicators per stock (ATR 14, RSI 14, MACD, Bollinger Bands, SMAs).
    3. Fits a `LogisticRegression` classifier (with `RobustScaler` and `Ridge` price regressor) for every constituent using data up to today.
    4. Serializes models to `models_registry/{ticker}.joblib`.
    5. Generates forward predictions (price target, range, trend signal) into SQLite `predictions`.
    6. Recomputes market-wide breadth and sector scan.
    
    *Execution runs asynchronously in the background. Track live progress using `GET /api/models/status`.*
    """
    current_status = batch_manager.get_status()
    if current_status.get("status") == "running" and not force:
        return {
            "status": "already_running",
            "task": current_status.get("task_type", "init_all_models"),
            "message": f"Task '{current_status.get('task_type')}' is already actively running ({current_status.get('completed_stocks')}/{current_status.get('total_stocks')} stocks completed, {current_status.get('progress_pct')} %). Track progress at /api/models/status.",
            "total_stocks": current_status.get("total_stocks", 501),
            "check_status_url": "/api/models/status",
        }

    all_tickers = get_all_tickers()
    total_target = len(all_tickers[:limit]) if limit else len(all_tickers)

    background_tasks.add_task(run_init_all_models_sync, limit, period, max_workers)

    return {
        "status": "initiated",
        "task": "init_all_models",
        "message": f"Batch creation of {total_target} Logistic Regression models started in background with last today's data.",
        "total_stocks": total_target,
        "check_status_url": "/api/models/status",
    }


@app.post(
    "/api/models/topup-and-update",
    response_model=ModelTopupResponse,
    summary="Top Up Today's Latest Data & Update Model(s)",
    tags=["Model Training & Lifecycle"],
    status_code=status.HTTP_200_OK,
)
async def topup_and_update_models(
    background_tasks: BackgroundTasks,
    ticker: Optional[str] = Query(None, description="Specific ticker symbol (e.g. 'RELIANCE', 'TCS.NS'). If omitted, tops up all 500 NIFTY constituents."),
    background: bool = Query(False, description="Run in background (recommended when updating all 500 stocks)"),
    max_workers: int = Query(8, description="Thread concurrency"),
    force: bool = Query(False, description="Force run top-up even if another task is marked active"),
):
    """
    **Trailing Incremental Data Top-Up & Model Refit**:
    1. Checks the latest recorded bar `MAX(date)` for the targeted stock(s).
    2. Downloads **only today's latest missing daily bar(s)** from Yahoo Finance (zero redundant re-downloads).
    3. Appends new bars into SQLite `daily_ohlcv`.
    4. Recalculates technical indicators with today's new closing price, volume, and range.
    5. Refits/updates the `LogisticRegression` (+ `Ridge`) model with today's latest data.
    6. Produces updated forward forecast for the next trading session.
    7. Updates universe breadth and sector performance metrics.
    """
    current_status = batch_manager.get_status()
    if current_status.get("status") == "running" and not force:
        return {
            "status": "busy",
            "message": f"Task '{current_status.get('task_type')}' is currently running in background ({current_status.get('completed_stocks')}/{current_status.get('total_stocks')} stocks, {current_status.get('progress_pct')} %). Please wait for completion or check /api/models/status.",
            "ticker": ticker,
        }

    if background or (ticker is None):
        background_tasks.add_task(run_topup_and_update_models_sync, ticker, max_workers)
        target_name = "all 500 NIFTY constituents" if not ticker else ticker
        return {
            "status": "triggered",
            "message": f"Top-up of today's latest data and model update launched in background for {target_name}.",
            "ticker": ticker,
        }
    else:
        result = run_topup_and_update_models_sync(ticker=ticker, max_workers=max_workers)
        return {
            "status": "success",
            "message": f"Successfully topped up today's data and updated model for {result.get('ticker')}.",
            "updated_tickers_count": 1,
            "new_bars_count": result.get("new_bars_count", 0),
            "ticker": result.get("ticker"),
            "latest_prediction": result.get("latest_prediction"),
            "elapsed_seconds": result.get("elapsed_seconds"),
        }


@app.post(
    "/api/models/reset-status",
    summary="Reset Training Status to Idle",
    tags=["Model Training & Lifecycle"],
    status_code=status.HTTP_200_OK,
)
async def reset_models_status():
    """Forces the batch manager status back to idle if needed."""
    batch_manager.reset()
    return {"status": "success", "message": "Model training state reset to idle."}


@app.get(
    "/api/models/status",
    response_model=ModelStatusResponse,
    summary="Get Real-Time Model Training Status & Progress",
    tags=["Model Training & Lifecycle"],
    status_code=status.HTTP_200_OK,
)
async def get_models_status():
    """
    Returns real-time operational status and progress of batch training or daily top-up:
    - `task_type`: Active task identifier (`init_all_models`, `topup_and_update`, `idle`).
    - `status`: Execution state (`idle`, `running`, `completed`, `failed`).
    - `progress_pct`: Percentage completed (0.0 to 100.0%).
    - `completed_stocks`: Count of successfully trained models.
    - `failed_stocks`: Count of stocks with errors or insufficient data.
    - `current_ticker`: Currently processing stock symbol.
    - `elapsed_seconds`: Execution duration so far.
    """
    return batch_manager.get_status()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("web.app:app", host="0.0.0.0", port=8000, reload=True)
