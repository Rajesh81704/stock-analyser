"""
FastAPI REST API & Screener Backend for "Bullish Trending Stocks" & Individual Stock Evaluator
Endpoints:
1. GET  /                         - Interactive HTML Screener & Evaluation Dashboard
2. GET  /api/filters/nodes        - Screener Filter Node Pipeline Registry
3. GET  /api/stock/{ticker}/evaluate - Individual Stock Comprehensive Evaluation (Fundamentals + Technicals + Returns + Candlestick Chart)
4. GET  /api/stock/{ticker}/screen - Single Stock Screener Node Evaluation
5. POST /api/screen/bullish-trending - Bulk NIFTY 500 Screener
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from typing import Any, Dict, List, Optional
from fastapi import BackgroundTasks, FastAPI, HTTPException, Path, Query, Request, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.data_loader import fetch_stock_data, fetch_stock_fundamentals, resolve_ticker, fetch_live_chart_candles
from src.screener import FILTER_RULES_SPEC, BullishTrendingScreenerNode, BullishMomentumScreenerNode, list_available_screener_nodes, get_screener_node_by_id
from src.stock_evaluator import evaluate_individual_stock
from src.universe import get_default_universe, load_tickers_from_csv
from src.database import get_expected_market_date, is_db_screener_updated_for_date
from src.scheduler import start_automated_scheduler, run_automatic_scheduled_scan
from src.webhooks import ws_manager, process_incoming_webhook_tick

# AlgoDesk Quant & Execution Workstation imports
from datetime import datetime
import pathlib
from fastapi import Form, Depends
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates

from src.algodesk.config.settings import settings, ExecutionMode
from src.algodesk.config.strategy_config import load_all_strategy_configs, load_strategy_yaml
from src.algodesk.data.kite_client import KiteClientWrapper
from src.algodesk.data.nifty500_service import Nifty500Service
from src.algodesk.execution.order_manager import OrderManager
from src.algodesk.execution.paper_broker import PaperBroker
from src.algodesk.risk.engine import RiskEngine, RiskLimits
from src.algodesk.strategies.registry import StrategyRegistry
from src.algodesk.ai.gemini_client import GeminiClient
from src.algodesk.ai.quant_optimizer import quant_optimizer
from src.engine.backtester import BacktestEngine
from src.strategy.config import StrategyConfig
from src.data.loader import load_dataset
from src.report.generator import ReportGenerator


app = FastAPI(
    title="FastDesk MarketX & AlgoDesk Unified Platform",
    description="Unified Quantitative Intraday Screener, Algorithmic Execution Workstation, Backtester, and Gemini AI Quant Suite.",
    version="4.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Unified AlgoDesk Singletons
risk_engine = RiskEngine()
paper_broker = PaperBroker(initial_capital=100000.0)
order_manager = OrderManager(risk_engine=risk_engine, paper_broker=paper_broker)
gemini_client = GeminiClient()

templates_dir = pathlib.Path("src/algodesk/api/templates")
templates = Jinja2Templates(directory=str(templates_dir))


@app.on_event("startup")
async def on_startup():
    """
    On server startup:
    1. Starts background automated scheduler (30-min intraday & daily EOD jobs).
    2. Verifies if SQLite DB contains latest bullish stock analysis for expected market date.
    3. If DB is missing/stale for expected market date, automatically runs bulk analysis and persists results into DB.
    """
    try:
        start_automated_scheduler()
    except Exception as e:
        print(f"[Startup] Error starting automated scheduler: {e}")

    try:
        target_date = get_expected_market_date()
        node_ids = [
            "NODE_01_BULLISH_TRENDING",
            "NODE_02_BULLISH_MOMENTUM",
            "NODE_03_PROFIT_JUMP_200",
            "NODE_04_HIGH_SALES_GROWTH",
            "NODE_05_BEARISH_TRENDING",
        ]
        missing_nodes = [nid for nid in node_ids if not is_db_screener_updated_for_date(nid, target_date)]

        if not missing_nodes:
            print(f"[Startup] ✅ SQLite DB contains up-to-date quantitative analysis across all 5 screener nodes for market date '{target_date}'. Skipping re-download and scan.")
        else:
            print("\n" + "=" * 75)
            print(f"[Startup] ⚠️  Latest data for market date '{target_date}' NOT found in SQLite DB ({len(missing_nodes)} missing/stale nodes).")
            print(f"[Startup] ⚡ Launching multi-node NIFTY 500 bulk scan in background thread to update database...")
            print("=" * 75 + "\n")
            import threading
            threading.Thread(
                target=run_automatic_scheduled_scan,
                kwargs={"trigger_name": "SERVER_STARTUP_SYNC"},
                daemon=True,
            ).start()
    except Exception as sync_err:
        print(f"[Startup] Warning during startup DB sync: {sync_err}")

    # Launch Continuous Autonomous Gemini Quant Optimizer in background
    try:
        quant_optimizer.start()
        print("[Startup] 🤖 Continuous Autonomous Gemini Quant Optimizer active in background.")
    except Exception as e:
        print(f"[Startup] Error launching Quant Optimizer: {e}")


# =====================================================================
# Pydantic Schemas
# =====================================================================

class FilterRuleSpecItem(BaseModel):
    id: int = Field(..., example=1)
    name: str = Field(..., example="Daily EMA(close,20) > 20")
    desc: str = Field(..., example="EMA 20 value is greater than 20")


class FilterNodeItem(BaseModel):
    node_id: str = Field(..., example="NODE_01_BULLISH_TRENDING")
    node_name: str = Field(..., example="Bullish Trending Stocks")
    category: str = Field(..., example="Momentum & Trend Breakout")
    rule_count: int = Field(..., example=26)
    description: str = Field(...)
    rules_spec: List[FilterRuleSpecItem]


class ReturnsModel(BaseModel):
    last_day_change: float = Field(..., example=5.20)
    last_day_return_pct: float = Field(..., example=1.45)
    last_week_change: float = Field(..., example=24.50)
    last_week_return_pct: float = Field(..., example=3.80)


class FundamentalsModel(BaseModel):
    ticker: str = Field(..., example="RELIANCE.NS")
    company_name: str = Field(..., example="Reliance Industries Limited")
    sector: str = Field(..., example="Energy")
    industry: str = Field(..., example="Oil & Gas Refining")
    market_cap_cr: Optional[float] = Field(None, example=1850000.0)
    pe_ratio: Optional[float] = Field(None, example=24.5)
    pb_ratio: Optional[float] = Field(None, example=2.8)
    eps: Optional[float] = Field(None, example=48.2)
    dividend_yield: Optional[float] = Field(None, example=0.85)
    roe: Optional[float] = Field(None, example=12.4)
    fifty_two_week_high: Optional[float] = Field(None, example=1608.0)
    fifty_two_week_low: Optional[float] = Field(None, example=1150.0)
    quarterly_financials: Optional[Dict[str, Any]] = Field(default_factory=dict)
    annual_financials: Optional[Dict[str, Any]] = Field(default_factory=dict)


class ChartCandleItem(BaseModel):
    date: str = Field(..., example="2026-10-07")
    open: float = Field(..., example=1212.0)
    high: float = Field(..., example=1220.8)
    low: float = Field(..., example=1203.5)
    close: float = Field(..., example=1207.7)
    volume: int = Field(..., example=11880731)
    sma_20: float = Field(..., example=1221.3)


class StockEvaluationResponse(BaseModel):
    status: str = Field("success", example="success")
    ticker: str = Field(..., example="RELIANCE.NS")
    resolved_ticker: str = Field(..., example="RELIANCE.NS")
    as_of_date: str = Field(..., example="2026-10-07")
    latest_close: float = Field(..., example=1207.70)
    currency_symbol: str = Field("₹", example="₹")
    returns: ReturnsModel
    fundamentals: FundamentalsModel
    technicals: Dict[str, Any]
    screener_nodes: List[Dict[str, Any]]
    available_filter_nodes: List[Dict[str, Any]]
    chart_candles: List[ChartCandleItem]


class ScreenRequest(BaseModel):
    node_id: str = Field("NODE_01_BULLISH_TRENDING", example="NODE_01_BULLISH_TRENDING", description="Screener Filter Node Identifier")
    universe: str = Field("nifty500", example="nifty500", description="Universe identifier ('nifty500')")
    custom_tickers: Optional[List[str]] = Field(None, example=["RELIANCE.NS", "TCS.NS"], description="Optional custom list of tickers")
    csv_path: Optional[str] = Field(None, example="data/nifty500.csv", description="Optional CSV file path containing tickers")
    min_pass_pct: float = Field(0.0, example=80.0, description="Minimum pass percentage threshold (0 to 100)")


class StockSummaryScreenItem(BaseModel):
    ticker: str = Field(..., example="RELIANCE.NS")
    passed_all: bool = Field(False, example=True)
    passed_count: int = Field(0, example=26)
    pass_percentage: float = Field(0.0, example=100.0)
    close: Optional[float] = Field(0.0, example=1207.70)
    volume: Optional[int] = Field(0, example=11880731)
    rsi_14: Optional[float] = Field(None, example=62.4)
    macd: Optional[float] = Field(None, example=4.32)
    details: Optional[Dict[str, Any]] = Field(default_factory=dict)


class UniverseScreenResponse(BaseModel):
    status: str = Field("success", example="success")
    screener_name: str = Field("Bullish Screener Node", example="Bullish Screener Node")
    scanned_count: int = Field(..., example=495)
    matched_count: int = Field(..., example=7)
    matched_stocks: List[StockSummaryScreenItem]
    all_ranked_stocks: List[StockSummaryScreenItem]


# =====================================================================
# API Endpoints
# =====================================================================

@app.get(
    "/api/filters/nodes",
    response_model=List[FilterNodeItem],
    summary="Get Registered Screener Filter Nodes from DB",
    tags=["Screener Node Pipeline"],
)
async def get_screener_filter_nodes():
    """Returns all active quantitative screener filter nodes persisted in SQLite Database."""
    try:
        from src.database import get_all_screener_nodes_from_db
        nodes = get_all_screener_nodes_from_db()
        if not nodes:
            return list_available_screener_nodes()
        return nodes
    except Exception:
        return list_available_screener_nodes()


@app.post(
    "/api/filters/nodes",
    summary="Create & Save New Screener Node into SQLite DB",
    tags=["Screener Node Pipeline"],
)
async def create_screener_filter_node(node: FilterNodeItem):
    """Saves a new custom quantitative screener filter node into SQLite Database."""
    try:
        from src.database import save_screener_node_to_db
        save_screener_node_to_db(
            node_id=node.node_id,
            node_name=node.node_name,
            category=node.category,
            description=node.description,
            rule_count=node.rule_count,
            rules_spec=[r.dict() for r in node.rules_spec]
        )
        return {"status": "success", "message": f"Screener node '{node.node_name}' saved to SQLite DB.", "node_id": node.node_id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get(
    "/api/chart/candles",
    summary="Fetch Live Market Candle Data for Building Charts (1m to 4h, 1d to max)",
    tags=["Live Chart & Candle Engine"],
)
async def get_chart_candles_by_query(
    symbol: str = Query(..., description="Stock ticker symbol (e.g. RELIANCE, TCS.NS, INFY, TATAMOTORS, ^NSEI)"),
    interval: str = Query("1d", description="Candle time frame: 1m, 2m, 3m, 5m, 15m, 30m, 60m, 1h, 2h, 4h, 1d, 1w, 1mo"),
    period: Optional[str] = Query(None, description="Historical range: 1d, 5d, 7d, 1mo, 3mo, 6mo, 1y, 2y, 5y, max"),
    start_date: Optional[str] = Query(None, description="Optional start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="Optional end date (YYYY-MM-DD)"),
):
    """
    Fetches live market OHLCV candle data for building interactive charts.
    
    Supported Intervals:
    - **Intraday**: `1m`, `2m`, `3m`, `5m`, `15m`, `30m`, `60m`, `1h`, `2h`, `4h`
    - **Daily / Longer**: `1d` / `day`, `1w` / `week`, `1mo` / `month`

    Supported Periods:
    - `1d`, `5d`, `7d`, `1mo`, `3mo`, `6mo`, `1y`, `2y`, `5y`, `max` (auto-calculated if omitted)
    """
    try:
        data = fetch_live_chart_candles(
            symbol=symbol,
            interval=interval,
            period=period,
            start_date=start_date,
            end_date=end_date
        )
        return data
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error fetching candle data for '{symbol}': {str(e)}")


@app.get(
    "/api/stock/{ticker}/candles",
    summary="Fetch Live Market Candle Data for Building Charts (RESTful path alias)",
    tags=["Live Chart & Candle Engine"],
)
async def get_chart_candles_by_path(
    ticker: str = Path(..., description="Stock ticker symbol in path (e.g. RELIANCE.NS, KARURVYSYA.NS)"),
    interval: str = Query("1d", description="Candle time frame: 1m, 2m, 3m, 5m, 15m, 30m, 60m, 1h, 2h, 4h, 1d, 1w, 1mo"),
    period: Optional[str] = Query(None, description="Historical range: 1d, 5d, 7d, 1mo, 3mo, 6mo, 1y, 2y, 5y, max"),
    start_date: Optional[str] = Query(None, description="Optional start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="Optional end date (YYYY-MM-DD)"),
):
    try:
        data = fetch_live_chart_candles(
            symbol=ticker,
            interval=interval,
            period=period,
            start_date=start_date,
            end_date=end_date
        )
        return data
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error fetching candle data for '{ticker}': {str(e)}")


@app.get(
    "/api/chart/live-tick",
    summary="Get Ultra-Fast Sub-Second Real-Time Live Market Tick for Charting",
    tags=["Live Chart & Candle Engine"],
)
async def get_chart_live_tick(
    symbol: str = Query(..., description="Stock ticker symbol (e.g. MPHASIS.NS, RELIANCE, TCS)")
):
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")
    now_ist = datetime.now(IST)

    clean_sym = symbol.strip().upper().replace(".NS", "").replace(".BO", "")
    resolved = resolve_ticker(symbol)

    live_price = 0.0
    day_high = 0.0
    day_low = 0.0
    day_volume = 0
    change_pct = 0.0
    source = "Zerodha KiteConnect Live"

    best_bid = 0.0
    best_ask = 0.0
    last_qty = 0

    try:
        from src.data_loader import KITE_API_KEY, KITE_ACCESS_TOKEN
        if KITE_API_KEY and KITE_ACCESS_TOKEN:
            from kiteconnect import KiteConnect
            kc = KiteConnect(api_key=KITE_API_KEY)
            kc.set_access_token(KITE_ACCESS_TOKEN)
            q_map = kc.quote([f"NSE:{clean_sym}"])
            if q_map and f"NSE:{clean_sym}" in q_map:
                q = q_map[f"NSE:{clean_sym}"]
                live_price = float(q.get("last_price") or 0.0)
                ohlc = q.get("ohlc", {})
                day_high = float(ohlc.get("high") or live_price)
                day_low = float(ohlc.get("low") or live_price)
                day_volume = int(q.get("volume") or 0)
                open_p = float(ohlc.get("open") or live_price)
                change_pct = round(((live_price - open_p) / max(0.01, open_p)) * 100, 2)
                
                depth = q.get("depth", {})
                bids = depth.get("buy", [])
                asks = depth.get("sell", [])
                best_bid = float(bids[0].get("price") or live_price) if bids else live_price
                best_ask = float(asks[0].get("price") or live_price) if asks else live_price
                last_qty = int(q.get("last_quantity") or 0)
                source = "Zerodha KiteConnect Live"
    except Exception:
        pass

    if live_price <= 0:
        try:
            import yfinance as yf
            ticker = yf.Ticker(resolved)
            fast_info = getattr(ticker, "fast_info", None)
            if fast_info:
                live_price = float(getattr(fast_info, "last_price", 0.0) or 0.0)
                day_high = float(getattr(fast_info, "day_high", live_price) or live_price)
                day_low = float(getattr(fast_info, "day_low", live_price) or live_price)
                day_volume = int(getattr(fast_info, "last_volume", 0) or 0)
                best_bid = live_price
                best_ask = live_price
                source = "Yahoo Finance Fast Quote"
        except Exception:
            pass

    return {
        "status": "success",
        "symbol": symbol,
        "resolved_symbol": resolved,
        "price": live_price,
        "bid": best_bid or live_price,
        "ask": best_ask or live_price,
        "high": day_high,
        "low": day_low,
        "volume": day_volume,
        "change_pct": change_pct,
        "last_quantity": last_qty,
        "time": int(now_ist.timestamp()),
        "timestamp": now_ist.strftime("%Y-%m-%d %H:%M:%S"),
        "source": source
    }


@app.get(
    "/api/stock/{ticker}/evaluate",
    response_model=StockEvaluationResponse,
    summary="Comprehensive Individual Stock Evaluation",
    tags=["Individual Stock Evaluator"],
)
async def evaluate_stock(
    ticker: str = Path(..., description="Stock ticker symbol (e.g. RELIANCE.NS, TCS.NS, INFY.NS)"),
    period: str = Query("6mo", description="Historical period for technical calculation & chart"),
):
    try:
        data = evaluate_individual_stock(ticker, period=period)
        return data
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error evaluating stock '{ticker}': {str(e)}")


@app.get(
    "/api/stock/{ticker}/fundamentals",
    summary="Fetch Fundamental Financials & Inspector Panel Data",
    tags=["Individual Stock Evaluator"],
)
@app.get(
    "/api/stock/{ticker}/summary",
    summary="Fetch Fundamental Financials & Key Metric Summary (Alias)",
    tags=["Individual Stock Evaluator"],
)
async def get_stock_fundamentals_endpoint(
    ticker: str = Path(..., description="Stock ticker symbol (e.g. ALOKINDS.NS, TATAMOTORS.NS, RELIANCE.NS)"),
):
    """
    Fetches fundamental financial parameters, quarterly/annual income statements,
    percentage returns, 20D SMA volume, and market cap specifically for the inspector card.
    """
    try:
        resolved = resolve_ticker(ticker)
        fundamentals = fetch_stock_fundamentals(resolved)

        df = fetch_stock_data(resolved, period="1m")
        latest_price = 0.0
        last_day_change = 0.0
        last_day_return = 0.0
        last_week_return = 0.0
        vol_sma_20 = 0

        if df is not None and not df.empty:
            latest_price = round(float(df["Close"].iloc[-1]), 2)
            if len(df) >= 2:
                prev_close = float(df["Close"].iloc[-2])
                last_day_change = round(latest_price - prev_close, 2)
                last_day_return = round(((latest_price - prev_close) / prev_close) * 100.0, 2)
            if len(df) >= 5:
                w_close = float(df["Close"].iloc[-5])
                last_week_return = round(((latest_price - w_close) / w_close) * 100.0, 2)
            if len(df) >= 20:
                vol_sma_20 = int(df["Volume"].tail(20).mean())
            else:
                vol_sma_20 = int(df["Volume"].mean())

        q = fundamentals.get("quarterly_financials", {})
        a = fundamentals.get("annual_financials", {})

        return {
            "status": "success",
            "ticker": ticker.upper(),
            "resolved_ticker": resolved,
            "company_name": fundamentals.get("company_name", ticker.replace(".NS", "")),
            "latest_price": latest_price,
            "currency_symbol": "₹",
            "last_day_change": last_day_change,
            "last_day_return_pct": last_day_return,
            "sector": fundamentals.get("sector", "Equities"),
            "industry": fundamentals.get("industry", "Cash Segment"),
            "exchange_universe": "NIFTY 500",
            "returns": {
                "last_day_return_pct": last_day_return,
                "last_week_return_pct": last_week_return,
                "last_day_change": last_day_change,
            },
            "key_metrics": {
                "volume_sma_20": vol_sma_20,
                "market_cap_cr": fundamentals.get("market_cap_cr"),
                "pe_ratio": fundamentals.get("pe_ratio"),
                "pb_ratio": fundamentals.get("pb_ratio"),
                "eps": fundamentals.get("eps"),
                "dividend_yield_pct": fundamentals.get("dividend_yield"),
                "roe_pct": fundamentals.get("roe"),
                "fifty_two_week_high": fundamentals.get("fifty_two_week_high"),
                "fifty_two_week_low": fundamentals.get("fifty_two_week_low"),
            },
            "quarterly_financials": {
                "period": q.get("period", "Last Quarter"),
                "quarter_revenue_cr": q.get("revenue_cr"),
                "net_profit_cr": q.get("net_profit_cr"),
                "rev_growth_qoq_pct": q.get("rev_growth_qoq_pct"),
                "rev_growth_yoy_pct": q.get("rev_growth_yoy_pct"),
                "profit_growth_qoq_pct": q.get("profit_growth_qoq_pct"),
                "profit_growth_yoy_pct": q.get("profit_growth_yoy_pct"),
            },
            "annual_financials": {
                "year": a.get("year", "Full Year"),
                "annual_revenue_cr": a.get("revenue_cr"),
                "annual_net_profit_cr": a.get("net_profit_cr"),
                "rev_growth_yoy_pct": a.get("rev_growth_yoy_pct"),
                "profit_growth_yoy_pct": a.get("profit_growth_yoy_pct"),
            }
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to fetch fundamental details for '{ticker}': {str(e)}")


@app.get(
    "/api/stock/{ticker}/screen",
    summary="Evaluate Single Stock on Screener Node #1",
    tags=["Individual Stock Evaluator"],
)
async def screen_single_stock(
    ticker: str = Path(..., description="Stock ticker symbol (e.g. RELIANCE.NS, TCS.NS)"),
    period: str = Query("6mo", description="Historical period"),
):
    try:
        data = evaluate_individual_stock(ticker, period=period)
        node_res = data["screener_nodes"][0]
        return {
            "status": "success",
            "screener_name": node_res["node_name"],
            "ticker": data["ticker"],
            "resolved_ticker": data["resolved_ticker"],
            "passed_all": node_res["passed_all"],
            "passed_count": node_res["passed_count"],
            "total_rules": node_res["total_rules"],
            "pass_percentage": node_res["pass_percentage"],
            "latest_bar": node_res["latest_bar"],
            "filter_results": node_res["filter_results"],
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


def _screen_worker(ticker: str, node_id: str = "NODE_01_BULLISH_TRENDING") -> Optional[Dict[str, Any]]:
    try:
        resolved = resolve_ticker(ticker)
        fundamentals = None
        if node_id in ["NODE_03_PROFIT_JUMP_200", "NODE_04_HIGH_SALES_GROWTH"]:
            try:
                fundamentals = fetch_stock_fundamentals(resolved)
            except Exception:
                pass
        df = fetch_stock_data(resolved, period="6mo")
        if df.empty:
            return None
        screener = get_screener_node_by_id(node_id, df, fundamentals=fundamentals)
        res = screener.evaluate_latest()

        latest_bar = res.get("latest_bar", {})
        return {
            "ticker": ticker,
            "resolved_ticker": resolved,
            "passed_all": res["passed_all"],
            "passed_count": res["passed_count"],
            "pass_percentage": res["pass_percentage"],
            "close": latest_bar.get("close", 0.0),
            "volume": latest_bar.get("volume", 0),
            "rsi_14": latest_bar.get("rsi_14"),
            "macd": latest_bar.get("macd"),
            "details": res,
        }
    except Exception:
        return None


@app.post(
    "/api/screen/bullish-trending",
    response_model=UniverseScreenResponse,
    summary="Bulk Screen NIFTY 500 Universe",
    tags=["Stock Screener Node Pipeline"],
)
async def screen_universe_endpoint(req: ScreenRequest, background_tasks: BackgroundTasks):
    node_names = {
        "NODE_01_BULLISH_TRENDING": "Bullish Trending Stocks (Node #1)",
        "NODE_02_BULLISH_MOMENTUM": "Pure Bullish Momentum Scan (Node #2)",
        "NODE_03_PROFIT_JUMP_200": "Profit Jump by 200% (Node #3)",
        "NODE_04_HIGH_SALES_GROWTH": "High Sales Growth (QoQ & YoY) (Node #4)",
        "NODE_05_BEARISH_TRENDING": "Bearish Trending Stocks (Node #5)",
    }
    node_name = node_names.get(req.node_id, "Bullish Trending Stocks (Node #1)")

    # 1. Fast Path: If cached DB results exist for this node, return INSTANTLY (0.01s)
    try:
        from src.database import get_latest_screener_results_from_db
        db_results = get_latest_screener_results_from_db(node_id=req.node_id, limit=500)
        if db_results and len(db_results) > 0:
            matched = [item for item in db_results if item.get("passed_all")]
            print(f"[Fast Screener] Returning {len(db_results)} instant DB cached results for {req.node_id}.")
            return {
                "status": "success",
                "screener_name": node_name,
                "scanned_count": len(db_results),
                "matched_count": len(matched),
                "matched_stocks": matched,
                "all_ranked_stocks": db_results,
            }
    except Exception as db_err:
        print(f"[Fast Screener] DB lookup info: {db_err}")

    # 2. Live Scan execution if DB has no cached records
    if req.custom_tickers:
        tickers = req.custom_tickers
    elif req.csv_path and os.path.exists(req.csv_path):
        tickers = load_tickers_from_csv(req.csv_path)
    else:
        tickers = get_default_universe(req.universe)

    scanned_results = []
    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = {executor.submit(_screen_worker, t, req.node_id): t for t in tickers}
        for future in as_completed(futures):
            res = future.result()
            if res:
                scanned_results.append(res)

    scanned_results.sort(key=lambda x: x["pass_percentage"], reverse=True)
    matched = [item for item in scanned_results if item["passed_all"]]

    if req.min_pass_pct > 0:
        filtered = [item for item in scanned_results if item["pass_percentage"] >= req.min_pass_pct]
    else:
        filtered = scanned_results

    try:
        from src.database import save_screener_run_to_db
        save_screener_run_to_db(
            node_id=req.node_id,
            universe=req.universe,
            scanned_count=len(scanned_results),
            matched_count=len(matched),
            stock_results=scanned_results
        )
    except Exception:
        pass

    return {
        "status": "success",
        "screener_name": node_name,
        "scanned_count": len(scanned_results),
        "matched_count": len(matched),
        "matched_stocks": matched,
        "all_ranked_stocks": filtered,
    }


@app.get(
    "/api/screener/history",
    summary="Get Historical Screener Results from SQLite DB",
    tags=["Stock Screener Node Pipeline"],
)
async def get_screener_history(
    node_id: str = Query("NODE_01_BULLISH_TRENDING", description="Node identifier"),
    limit: int = Query(100, description="Max result count to return"),
):
    """Retrieves historical screening results persisted in the SQLite database."""
    try:
        from src.database import get_latest_screener_results_from_db
        results = get_latest_screener_results_from_db(node_id=node_id, limit=limit)
        return {
            "status": "success",
            "count": len(results),
            "results": results
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post(
    "/api/scheduler/trigger",
    summary="Instant Trigger for Automated Stock Data Pull & Screening Scan",
    tags=["Stock Screener Node Pipeline"],
)
async def trigger_automated_scan():
    """Triggers an instant automatic data pull and 26-rule technical screening run, persisting results into SQLite DB."""
    try:
        res = run_automatic_scheduled_scan(trigger_name="MANUAL_INSTANT_TRIGGER")
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


_KITE_STATUS_CACHE = {
    "active": False,
    "user_name": None,
    "user_id": None,
    "last_checked": 0,
    "login_url": "https://kite.zerodha.com/connect/login?api_key=zgktuz1hr11f8scf&v=3",
    "api_key": "zgktuz1hr11f8scf",
    "status": "DISCONNECTED",
    "error": None
}

def check_kite_session_status(force: bool = False) -> Dict[str, Any]:
    """Checks whether the current Zerodha KiteConnect session is authenticated and active."""
    import time
    now = time.time()
    if not force and (now - _KITE_STATUS_CACHE["last_checked"] < 45):
        return _KITE_STATUS_CACHE

    token = settings.active_kite_token
    if not settings.kite_api_key or not token:
        _KITE_STATUS_CACHE.update({
            "active": False,
            "user_name": None,
            "user_id": None,
            "last_checked": now,
            "status": "DISCONNECTED",
            "error": "No access token configured"
        })
        return _KITE_STATUS_CACHE

    try:
        client = KiteClientWrapper(access_token=token)
        conn = client.check_connection(force=force)
        is_active = conn.get("status") == "CONNECTED"
        _KITE_STATUS_CACHE.update({
            "active": is_active,
            "user_name": conn.get("user_name"),
            "user_id": conn.get("user_id"),
            "last_checked": now,
            "status": conn.get("status"),
            "error": conn.get("error")
        })
    except Exception as e:
        _KITE_STATUS_CACHE.update({
            "active": False,
            "user_name": None,
            "user_id": None,
            "last_checked": now,
            "status": "ERROR",
            "error": str(e)
        })
    return _KITE_STATUS_CACHE


@app.get(
    "/api/kite/status",
    summary="Get Zerodha KiteConnect Session Status",
    tags=["Kite Connect Integration"],
)
def api_kite_status(force: bool = False):
    """Returns whether KiteConnect session is active or expired, plus the Zerodha login URL."""
    return check_kite_session_status(force=force)


@app.post(
    "/api/kite/set-token",
    summary="Directly Set or Exchange Zerodha Kite Access/Request Token",
    tags=["Kite Connect Integration"],
)
@app.post(
    "/api/kite/session",
    summary="Directly Set or Exchange Zerodha Kite Access/Request Token (Alias)",
    tags=["Kite Connect Integration"],
)
async def api_kite_set_token(request: Request):
    """Allows manual setting of access_token or exchange of request_token from the UI modal."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    raw_token = body.get("token", "").strip()
    is_request_token = body.get("is_request_token", False)

    if not raw_token:
        raise HTTPException(status_code=400, detail="Token or redirect URL is required.")

    # Automatically extract request_token if user pasted a full URL or query string
    token = raw_token
    import re
    from urllib.parse import urlparse, parse_qs
    if "request_token=" in token:
        m = re.search(r'request_token=([a-zA-Z0-9_-]+)', token)
        if m:
            token = m.group(1)
            is_request_token = True
    elif token.startswith("http://") or token.startswith("https://") or "?" in token:
        try:
            parsed = urlparse(token)
            qs = parse_qs(parsed.query or parsed.path)
            if "request_token" in qs and qs["request_token"]:
                token = qs["request_token"][0]
                is_request_token = True
        except Exception:
            pass

    from src.data_loader import set_active_kite_access_token
    user_id = None
    user_name = None

    if is_request_token:
        try:
            from kiteconnect import KiteConnect
            from src.algodesk.config.settings import settings
            api_key = settings.kite_api_key or "zgktuz1hr11f8scf"
            api_secret = settings.kite_api_secret or "pt7gvrbxi23sssa1duvhd6n6bufj8ztj"
            kite = KiteConnect(api_key=api_key)
            session_data = kite.generate_session(token, api_secret=api_secret)
            acc_token = session_data.get("access_token")
            user_id = session_data.get("user_id")
            user_name = session_data.get("user_name")
            if not acc_token:
                raise ValueError("No access token returned from Kite session exchange.")
            token = acc_token
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to exchange request token with Zerodha: {str(e)}")

    settings.save_kite_token(token)
    try:
        set_active_kite_access_token(token)
    except Exception:
        pass

    status = check_kite_session_status(force=True)
    return {
        "status": "success",
        "message": f"Successfully authenticated Kite session as {status.get('user_id') or user_id or 'Zerodha User'}!",
        "user_id": status.get("user_id") or user_id,
        "user_name": status.get("user_name") or user_name,
        "kite_status": status,
        "access_token": token
    }


@app.get(
    "/api/nifty500/stocks",
    summary="List all NIFTY 500 Equities Categorized by Market Type & Sector",
    tags=["NIFTY 500 Universe"],
)
def api_nifty500_stocks(
    market_type: Optional[str] = Query(None, description="Market Cap filter: all, large cap, mid cap, small cap"),
    sector: Optional[str] = Query(None, description="Industry sector filter"),
    query: Optional[str] = Query(None, description="Search symbol or name"),
    sort_by: str = Query("symbol", description="Sort by: symbol, change, volume, price"),
    desc: bool = Query(False, description="Sort descending"),
):
    """Returns NIFTY 500 stocks with market cap tags, sector tags, latest prices and day change %."""
    from src.algodesk.data.nifty500_service import Nifty500Service
    stocks = Nifty500Service.filter_stocks(
        market_type=market_type,
        sector=sector,
        query=query,
        sort_by=sort_by,
        desc=desc,
    )
    return {"count": len(stocks), "stocks": stocks}


@app.get(
    "/api/nifty500/stats",
    summary="Get NIFTY 500 Market Cap & Sector Distribution Statistics",
    tags=["NIFTY 500 Universe"],
)
def api_nifty500_stats():
    """Returns distribution count across Large Cap, Mid Cap, Small Cap and Sectors."""
    from src.algodesk.data.nifty500_service import Nifty500Service
    return Nifty500Service.get_summary_stats()



_MARKET_NEWS_CACHE = {
    "articles": [],
    "last_fetched": 0
}

@app.get(
    "/api/market/news",
    summary="Fetch Latest Top Stock Market Headlines",
    tags=["Market News Wire"],
)
def get_market_news(limit: int = Query(25, ge=1, le=50), force: bool = False):
    """Fetches real-time Indian stock market breaking news headlines with caching."""
    import time
    now = time.time()
    if not force and _MARKET_NEWS_CACHE["articles"] and (now - _MARKET_NEWS_CACHE["last_fetched"] < 120):
        return {"articles": _MARKET_NEWS_CACHE["articles"][:limit], "cached": True}

    import urllib.request
    import xml.etree.ElementTree as ET

    articles = []
    try:
        url = "https://news.google.com/rss/search?q=stock+market+india+nifty+sensex&hl=en-IN&gl=IN&ceid=IN:en"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            xml_data = resp.read()
        root = ET.fromstring(xml_data)
        for item in root.findall(".//item"):
            raw_title = item.find("title").text if item.find("title") is not None else ""
            link = item.find("link").text if item.find("link") is not None else ""
            pub_date_str = item.find("pubDate").text if item.find("pubDate") is not None else ""
            source_el = item.find("source")
            source = source_el.text if source_el is not None else "Market Wire"

            clean_title = raw_title
            if " - " in clean_title:
                clean_title = clean_title.rsplit(" - ", 1)[0].strip()

            if clean_title and link:
                articles.append({
                    "title": clean_title,
                    "link": link,
                    "source": source,
                    "published": pub_date_str,
                })
            if len(articles) >= 40:
                break

        if articles:
            _MARKET_NEWS_CACHE["articles"] = articles
            _MARKET_NEWS_CACHE["last_fetched"] = now
    except Exception as e:
        print(f"[MarketNews Error] {e}")
        if _MARKET_NEWS_CACHE["articles"]:
            return {"articles": _MARKET_NEWS_CACHE["articles"][:limit], "fallback": True}
        return {"articles": [], "error": str(e)}

    return {"articles": _MARKET_NEWS_CACHE["articles"][:limit], "count": len(_MARKET_NEWS_CACHE["articles"][:limit])}


@app.get(
    "/callback",
    summary="Zerodha Kite Connect Auth Callback Handler",
    tags=["Kite Connect Integration"],
)
@app.get(
    "/api/kite/callback",
    summary="Zerodha Kite Connect Auth Callback Handler (Alias)",
    tags=["Kite Connect Integration"],
)
async def kite_callback(request: Request):
    """Callback route for Zerodha Kite Connect login flow. Automatically exchanges request_token for active access_token."""
    params = dict(request.query_params)
    print("\n" + "="*60)
    print("ZERODHA KITE CONNECT CALLBACK RECEIVED:")
    print(params)
    print("="*60 + "\n")

    req_token = params.get("request_token")
    if req_token:
        try:
            from kiteconnect import KiteConnect
            from src.data_loader import set_active_kite_access_token
            kite = KiteConnect(api_key="zgktuz1hr11f8scf")
            data = kite.generate_session(req_token, api_secret="pt7gvrbxi23sssa1duvhd6n6bufj8ztj")
            acc_token = data.get("access_token")
            if acc_token:
                set_active_kite_access_token(acc_token)
                try:
                    from src.algodesk.config.settings import settings
                    settings.save_kite_token(acc_token)
                except Exception:
                    pass
                check_kite_session_status(force=True)
                print(f"[Kite AutoAuth] 🎉 AUTOMATICALLY GENERATED & ACTIVATED KITE ACCESS TOKEN: {acc_token}")
                # Redirect user directly back to the workstation with success indicator
                referer = request.headers.get("referer", "")
                if "8500" in referer or "algodesk" in referer or params.get("from") == "8500":
                    return RedirectResponse(url="http://localhost:8500/dashboard?kite_auth=success", status_code=303)
                return RedirectResponse(url="/?kite_auth=success", status_code=303)
        except Exception as err:
            print(f"[Kite AutoAuth Error] {err}")
            referer = request.headers.get("referer", "")
            if "8500" in referer:
                return RedirectResponse(url=f"http://localhost:8500/dashboard?kite_auth=error&msg={str(err)}", status_code=303)
            return RedirectResponse(url=f"/?kite_auth=error&msg={str(err)}", status_code=303)

    return RedirectResponse(url="/", status_code=303)


# =====================================================================
# Real-time Webhook & WebSocket Endpoints (0 HTTP Polling Architecture)
# =====================================================================

@app.post(
    "/api/webhook/ticks",
    summary="Receive Real-time Live Market Ticks via Webhook",
    tags=["Real-time Webhook Streaming"],
)
@app.post(
    "/api/webhook/zerodha",
    summary="Zerodha Kite Postback & Tick Webhook Listener",
    tags=["Real-time Webhook Streaming"],
)
async def webhook_tick_listener(req: Request):
    """
    Receives live market tick data or Zerodha postback updates via webhook.
    Broadcasts payload instantly to all connected WebSocket clients with 0 HTTP polling.
    """
    try:
        body = await req.json()
    except Exception:
        body = {}

    processed = process_incoming_webhook_tick(body if isinstance(body, dict) else {})
    symbol = processed.get("symbol", "UNKNOWN")

    await ws_manager.broadcast_symbol_tick(symbol, processed)

    return {
        "status": "success",
        "message": "Webhook tick received & broadcasted to live WebSocket clients",
        "processed_tick": processed
    }


@app.websocket("/ws/live")
async def websocket_live_endpoint(websocket: WebSocket):
    """
    WebSocket Endpoint for Real-time Streaming of Stock Prices & Screener Updates.
    No continuous HTTP polling required!
    """
    await ws_manager.connect(websocket)
    try:
        await websocket.send_json({
            "type": "CONNECTION_ESTABLISHED",
            "message": "Connected to FastDesk MarketX Live Real-time WebSocket Stream"
        })
        while True:
            data_str = await websocket.receive_text()
            try:
                msg = json.loads(data_str)
                action = msg.get("action")
                symbol = msg.get("symbol")
                if action == "subscribe" and symbol:
                    ws_manager.subscribe(websocket, symbol)
                    await websocket.send_json({"type": "SUBSCRIBED", "symbol": symbol.upper()})
                elif action == "unsubscribe" and symbol:
                    ws_manager.unsubscribe(websocket, symbol)
                    await websocket.send_json({"type": "UNSUBSCRIBED", "symbol": symbol.upper()})
            except Exception:
                pass
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)


# =====================================================================
# AlgoDesk Quantitative & Execution Workstation Pages & APIs
# =====================================================================

@app.get("/api/status", summary="Get AlgoDesk System Telemetry & Broker State")
def get_system_status():
    """Returns current platform metrics, positions, and connection status."""
    portfolio = paper_broker.get_portfolio_state()
    kite_status = "NOT_CONFIGURED"
    user_id = None
    if settings.kite_api_key and settings.active_kite_token:
        try:
            client = KiteClientWrapper(access_token=settings.active_kite_token)
            conn = client.check_connection()
            kite_status = conn.get("status", "DISCONNECTED")
            user_id = conn.get("user_id")
        except Exception:
            kite_status = "ERROR"

    return {
        "status": "HEALTHY",
        "mode": settings.default_mode.value,
        "kill_switch": risk_engine.kill_switch_active,
        "kite": {
            "status": kite_status,
            "user_id": user_id,
        },
        "portfolio": portfolio,
        "positions_count": len(portfolio.get("positions", {})),
    }


@app.post("/api/order/place", summary="Place Simulated Paper or Live MIS Order")
async def api_place_order(request: Request):
    """Places a simulated paper or live MIS order."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    symbol = body.get("symbol", "").strip()
    side = body.get("side", "BUY").upper()
    qty = int(body.get("quantity", 1))
    price = float(body.get("price", 0.0))
    stop_loss = float(body.get("stop_loss")) if body.get("stop_loss") else None
    target = float(body.get("target")) if body.get("target") else None

    if not symbol:
        raise HTTPException(status_code=400, detail="Stock symbol is required.")

    if price <= 0:
        stocks = Nifty500Service.filter_stocks(query=symbol)
        if stocks and stocks[0]["close"] > 0:
            price = stocks[0]["close"]
        else:
            price = 1000.0

    if risk_engine.kill_switch_active:
        raise HTTPException(status_code=400, detail=f"Order rejected: Kill switch active ({risk_engine.kill_switch_reason})")

    res = paper_broker.execute_order(
        symbol=symbol,
        side=side,
        qty=qty,
        price=price,
        stop_loss=stop_loss,
        target=target,
    )

    return {
        "status": "success",
        "order": res,
        "portfolio": paper_broker.get_portfolio_state(),
    }


@app.post("/api/kill-switch", summary="Toggle Platform Emergency Kill Switch")
def toggle_kill_switch(active: bool = Form(...), reason: str = Form("Dashboard operator trigger")):
    """Toggles platform emergency kill switch."""
    if active:
        risk_engine.activate_kill_switch(reason=reason, actor="operator")
        paper_broker.flatten_all({})
    else:
        risk_engine.reset_kill_switch(actor="operator")
    return RedirectResponse(url="/dashboard", status_code=303)


@app.get("/dashboard", response_class=HTMLResponse, summary="AlgoDesk Live Execution Workstation")
def dashboard(request: Request):
    """Main live/paper operational monitor."""
    portfolio = paper_broker.get_portfolio_state()
    strategies = StrategyRegistry.list_strategies()
    configs = load_all_strategy_configs(settings.configs_dir)
    kite_status = check_kite_session_status()

    # Integrate automated paper trading positions and capital metrics
    auto_open_trades = []
    portfolio_metrics = {
        "simulated_capital": 100000.0,
        "capital_utilized": 0.0,
        "capital_utilization_pct": 0.0,
        "available_cash": 100000.0,
        "portfolio_equity": 100000.0,
        "active_positions_count": 0,
        "max_positions_allowed": 10,
        "execution_mode": settings.default_mode.value,
    }
    try:
        from src.algodesk.automation.daily_screener_trader import daily_auto_trader
        auto_status = daily_auto_trader.get_automation_status()
        auto_open_trades = auto_status.get("open_trades", [])
        if "portfolio_metrics" in auto_status:
            portfolio_metrics = auto_status["portfolio_metrics"]
            portfolio["cash"] = portfolio_metrics["available_cash"]
            portfolio["equity"] = portfolio_metrics["portfolio_equity"]
    except Exception as e_p:
        logger.debug(f"Dashboard portfolio metrics sync notice: {e_p}")

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "active_page": "dashboard",
            "mode": settings.default_mode.value,
            "portfolio": portfolio,
            "portfolio_metrics": portfolio_metrics,
            "auto_open_trades": auto_open_trades,
            "strategies": strategies,
            "configs": configs,
            "kill_switch": risk_engine.kill_switch_active,
            "kill_switch_reason": risk_engine.kill_switch_reason,
            "risk_limits": risk_engine.limits,
            "kite_active": kite_status.get("active", False),
            "kite_user_id": kite_status.get("user_id"),
            "kite_url": kite_status.get("login_url"),
            "trades": list(reversed(paper_broker.trades_history[-15:])),
        },
    )


def get_live_kite_client() -> Optional[KiteClientWrapper]:
    """Helper to return authenticated KiteClientWrapper or None."""
    token = settings.active_kite_token
    if not token or not settings.kite_api_key:
        return None
    try:
        return KiteClientWrapper(access_token=token)
    except Exception as e:
        logger.error(f"Failed to create KiteClientWrapper: {e}")
        return None


@app.get("/live", response_class=HTMLResponse, summary="AlgoDesk REAL Live Trading Workstation (Zerodha NSE)")
def live_trading_view(request: Request):
    """Real live brokerage execution workstation with live margins, positions, order placement, and square-off."""
    kite_status = check_kite_session_status()
    client = get_live_kite_client()

    margins = {
        "status": "disconnected",
        "available_cash": 0.0,
        "opening_balance": 0.0,
        "used_margin": 0.0,
        "collateral": 0.0,
        "net": 0.0,
    }
    positions = {
        "status": "disconnected",
        "net": [],
        "day": [],
        "open_count": 0,
        "unrealized_pnl": 0.0,
        "realized_pnl": 0.0,
        "total_pnl": 0.0,
    }
    orders = []

    if client and kite_status.get("active"):
        try:
            margins = client.get_live_margins()
            positions = client.get_live_positions()
            orders = client.get_live_orders()
        except Exception as e:
            logger.error(f"Error fetching live account data from Kite: {e}")

    return templates.TemplateResponse(
        request=request,
        name="live.html",
        context={
            "active_page": "live",
            "mode": "LIVE (ZERODHA NSE)",
            "kite_active": kite_status.get("active", False),
            "kite_user_id": kite_status.get("user_id"),
            "kite_user_name": kite_status.get("user_name"),
            "kite_url": kite_status.get("login_url"),
            "margins": margins,
            "positions": positions,
            "orders": orders,
            "kill_switch": risk_engine.kill_switch_active,
            "kill_switch_reason": risk_engine.kill_switch_reason,
            "risk_limits": risk_engine.limits,
        },
    )


@app.get("/api/live/telemetry", summary="Get Live Real-time Brokerage Margins, Positions & Orders")
def api_live_telemetry():
    """Polls live broker state: cash, positions, order book."""
    kite_status = check_kite_session_status()
    if not kite_status.get("active"):
        return {
            "status": "error",
            "kite_active": False,
            "message": "Zerodha KiteConnect session is inactive or expired. Please re-authenticate."
        }
    client = get_live_kite_client()
    if not client:
        return {"status": "error", "kite_active": False, "message": "Failed to connect to Kite client."}

    margins = client.get_live_margins()
    positions = client.get_live_positions()
    orders = client.get_live_orders()

    return {
        "status": "success",
        "kite_active": True,
        "margins": margins,
        "positions": positions,
        "orders": orders,
        "kill_switch": risk_engine.kill_switch_active,
    }


@app.post("/api/live/order/place", summary="Place REAL LIVE Order via Zerodha Kite API")
async def api_place_live_order(request: Request):
    """Submits a real monetary order to Zerodha Kite API for execution on NSE."""
    if risk_engine.kill_switch_active:
        raise HTTPException(
            status_code=400,
            detail=f"Real order rejected: Emergency Kill Switch is ACTIVE ({risk_engine.kill_switch_reason})"
        )

    client = get_live_kite_client()
    if not client:
        raise HTTPException(
            status_code=401,
            detail="Kite session expired or missing token. Please click the Kite badge in top navbar to authenticate."
        )

    try:
        body = await request.json()
    except Exception:
        body = {}

    symbol = body.get("symbol", "").strip().upper()
    side = body.get("side", "BUY").strip().upper()
    try:
        qty = int(body.get("quantity") or body.get("qty") or 1)
    except (ValueError, TypeError):
        qty = 1
    order_type = body.get("order_type", "MARKET").strip().upper()
    product = body.get("product", "MIS").strip().upper()
    try:
        price = float(body.get("price") or 0.0)
    except (ValueError, TypeError):
        price = 0.0
    try:
        trigger_price = float(body.get("trigger_price") or 0.0)
    except (ValueError, TypeError):
        trigger_price = 0.0

    if not symbol:
        raise HTTPException(status_code=400, detail="Stock symbol is required.")
    if qty <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be greater than 0.")
    if side not in ("BUY", "SELL"):
        raise HTTPException(status_code=400, detail="Side must be BUY or SELL.")
    if product not in ("MIS", "CNC"):
        raise HTTPException(status_code=400, detail="Product must be MIS (Intraday) or CNC (Cash Delivery).")
    if order_type not in ("MARKET", "LIMIT", "SL", "SL-M"):
        raise HTTPException(status_code=400, detail="Order type must be MARKET or LIMIT.")

    try:
        res = client.place_live_order(
            symbol=symbol,
            side=side,
            qty=qty,
            order_type=order_type,
            product=product,
            price=price,
            trigger_price=trigger_price,
            tag="algodesk_live",
        )
        return res
    except Exception as e:
        logger.error(f"Live order execution failure: {e}")
        raise HTTPException(status_code=500, detail=f"Zerodha Order Failed: {str(e)}")


@app.post("/api/live/order/cancel", summary="Cancel Open Live Order in Zerodha")
async def api_cancel_live_order(request: Request):
    """Cancels an open order in Zerodha Kite."""
    client = get_live_kite_client()
    if not client:
        raise HTTPException(status_code=401, detail="Zerodha Kite session expired or not authenticated.")

    try:
        body = await request.json()
    except Exception:
        body = {}

    order_id = str(body.get("order_id", "")).strip()
    if not order_id:
        raise HTTPException(status_code=400, detail="Order ID is required.")

    res = client.cancel_live_order(order_id=order_id)
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message", "Failed to cancel order"))
    return res


@app.post("/api/live/position/close", summary="Square-off Specific Live Position at Market")
async def api_close_live_position(request: Request):
    """Squares off a specific open position at market price."""
    client = get_live_kite_client()
    if not client:
        raise HTTPException(status_code=401, detail="Zerodha Kite session expired or not authenticated.")

    try:
        body = await request.json()
    except Exception:
        body = {}

    symbol = body.get("symbol", "").strip().upper()
    product = body.get("product", "MIS").strip().upper()
    if not symbol:
        raise HTTPException(status_code=400, detail="Stock symbol is required.")

    res = client.square_off_live_position(symbol=symbol, product=product)
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message", "Failed to square off position"))
    return res


@app.post("/api/live/positions/square-off-all", summary="Emergency Square Off ALL Open Live MIS Positions")
def api_square_off_all_live_positions():
    """Emergency closes all open MIS intraday positions."""
    client = get_live_kite_client()
    if not client:
        raise HTTPException(status_code=401, detail="Zerodha Kite session expired or not authenticated.")

    res = client.square_off_all_live_positions()
    return res


@app.get("/strategies", response_class=HTMLResponse, summary="Strategy Management & Configuration")
def strategies_view(request: Request):
    """Strategy management and configuration view."""
    configs = load_all_strategy_configs(settings.configs_dir)
    registered = StrategyRegistry.list_strategies()
    kite_status = check_kite_session_status()

    return templates.TemplateResponse(
        request=request,
        name="strategies.html",
        context={
            "active_page": "strategies",
            "mode": settings.default_mode.value,
            "configs": configs,
            "registered": registered,
            "kill_switch": risk_engine.kill_switch_active,
            "kite_active": kite_status.get("active", False),
            "kite_user_id": kite_status.get("user_id"),
            "kite_url": kite_status.get("login_url"),
        },
    )


@app.post("/strategies/save")
def save_strategy_config(name: str = Form(...), content: str = Form(...)):
    """Saves modified YAML strategy configuration."""
    cfg_file = settings.configs_dir / f"{name}.yaml"
    cfg_file.write_text(content, encoding="utf-8")
    return RedirectResponse(url="/strategies", status_code=303)


@app.post("/strategies/toggle")
def toggle_strategy_status(name: str = Form(...), enabled: bool = Form(...)):
    """Toggles live_enabled flag in strategy config YAML."""
    cfg_file = settings.configs_dir / f"{name}.yaml"
    if cfg_file.exists():
        data = load_strategy_yaml(cfg_file)
        data["live_enabled"] = enabled
        import yaml
        with open(cfg_file, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False)
    return RedirectResponse(url="/strategies", status_code=303)


@app.get("/backtests", response_class=HTMLResponse, summary="Intraday Quant Backtester")
def backtests_view(request: Request):
    """Backtest execution, IS vs OOS breakdown, and equity curve viewer."""
    report_path = pathlib.Path("results/report.md")
    report_content = ""
    if report_path.exists():
        report_content = report_path.read_text(encoding="utf-8")

    has_plot = pathlib.Path("results/equity_curve.png").exists()
    has_trades = pathlib.Path("results/trades.csv").exists()
    kite_status = check_kite_session_status()

    return templates.TemplateResponse(
        request=request,
        name="backtests.html",
        context={
            "active_page": "backtests",
            "mode": settings.default_mode.value,
            "report_content": report_content,
            "has_plot": has_plot,
            "has_trades": has_trades,
            "kill_switch": risk_engine.kill_switch_active,
            "kite_active": kite_status.get("active", False),
            "kite_user_id": kite_status.get("user_id"),
            "kite_url": kite_status.get("login_url"),
        },
    )


@app.post("/backtests/run")
def run_backtest_action(
    stop_atr: float = Form(0.10),
    top_n: int = Form(5),
    or_minutes: int = Form(5),
    min_turnover_cr: float = Form(20.0),
    capital: float = Form(100000.0),
    risk_pct: float = Form(0.01),
):
    """Executes backtest on existing data store and updates results."""
    cfg = StrategyConfig(
        stop_atr=stop_atr,
        top_n=top_n,
        or_minutes=or_minutes,
        min_turnover_cr=min_turnover_cr,
        initial_capital=capital,
        risk_pct=risk_pct,
    )

    data_stores, _ = load_dataset(data_dir=str(settings.data_dir), config=cfg)
    if not data_stores:
        raise HTTPException(status_code=400, detail="No historical or synthetic data found in data directory.")

    engine = BacktestEngine(config=cfg)
    res = engine.run(data_stores=data_stores)

    rep_gen = ReportGenerator(output_dir=str(settings.results_dir))
    rep_gen.generate_all(result=res, is_synthetic=True)

    return RedirectResponse(url="/backtests", status_code=303)


@app.get("/results/equity_curve.png")
def get_equity_curve_image():
    """Serves the generated equity curve image."""
    plot_file = pathlib.Path("results/equity_curve.png")
    if not plot_file.exists():
        raise HTTPException(status_code=404, detail="Plot not generated yet.")
    return FileResponse(plot_file, media_type="image/png")


@app.get("/results/trades.csv")
def download_trades_csv():
    """Downloads trades CSV ledger."""
    f = pathlib.Path("results/trades.csv")
    if not f.exists():
        raise HTTPException(status_code=404, detail="Trades file not found.")
    return FileResponse(f, media_type="text/csv", filename="trades.csv")


@app.get("/api/backtests/4y-intraday/summary")
def get_4y_intraday_summary():
    """Returns 4-year backtest aggregate metrics, yearly stats, and equity curve points."""
    import sqlite3
    db_path = "data/stock_screener.db"
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        
        cur.execute("""
            SELECT 
                count(*) as total_trades,
                sum(case when is_win = 1 then 1 else 0 end) as win_trades,
                sum(case when is_win = 0 then 1 else 0 end) as loss_trades,
                sum(net_pnl) as total_net_pnl,
                sum(case when gross_pnl > 0 then gross_pnl else 0 end) as gross_profit,
                abs(sum(case when gross_pnl < 0 then gross_pnl else 0 end)) as gross_loss,
                min(trade_date) as start_date,
                max(trade_date) as end_date
            FROM intraday_daily_pnl_logs;
        """)
        row = cur.fetchone()
        total_trades = row[0] or 0
        win_trades = row[1] or 0
        loss_trades = row[2] or 0
        total_net_pnl = round(row[3] or 0.0, 2)
        gross_profit = row[4] or 0.0
        gross_loss = row[5] or 0.0
        start_date = row[6] or ""
        end_date = row[7] or ""
        
        win_rate = round((win_trades / total_trades * 100.0), 1) if total_trades > 0 else 0.0
        profit_factor = round(gross_profit / max(1.0, gross_loss), 2)
        initial_capital = 100000.0
        net_return_pct = round((total_net_pnl / initial_capital) * 100.0, 2)
        
        cur.execute("""
            SELECT substr(trade_date, 1, 4) as yr, round(sum(net_pnl), 2), count(*), sum(is_win)
            FROM intraday_daily_pnl_logs
            GROUP BY yr
            ORDER BY yr ASC;
        """)
        yearly = [
            {"year": r[0], "pnl": r[1], "trades": r[2], "wins": r[3], "win_rate": round(r[3]/r[2]*100, 1) if r[2] else 0}
            for r in cur.fetchall()
        ]
        
        cur.execute("""
            SELECT exit_reason, count(*), round(sum(net_pnl), 2)
            FROM intraday_daily_pnl_logs
            GROUP BY exit_reason;
        """)
        exit_reasons = [{"reason": r[0], "count": r[1], "pnl": r[2]} for r in cur.fetchall()]
        
        cur.execute("""
            SELECT date, daily_net_pnl, cumulative_net_pnl, portfolio_equity, drawdown_pct, trades_count
            FROM intraday_daily_pnl_summary
            ORDER BY date ASC;
        """)
        daily_records = [
            {"date": r[0], "daily_pnl": r[1], "cumulative_pnl": r[2], "equity": r[3], "drawdown": r[4], "trades": r[5]}
            for r in cur.fetchall()
        ]
        
        max_dd = max([r["drawdown"] for r in daily_records], default=0.0)
        conn.close()
        
        return {
            "status": "success",
            "kpi": {
                "strategy_name": "Alpha_ORB_TrailingBreakeven_75",
                "period_years": 4,
                "start_date": start_date,
                "end_date": end_date,
                "initial_capital": initial_capital,
                "ending_equity": round(initial_capital + total_net_pnl, 2),
                "total_trades": total_trades,
                "win_trades": win_trades,
                "loss_trades": loss_trades,
                "win_rate": win_rate,
                "profit_factor": profit_factor,
                "total_net_pnl": total_net_pnl,
                "net_return_pct": net_return_pct,
                "max_drawdown_pct": max_dd,
                "total_days": len(daily_records),
                "days_traded": len([r for r in daily_records if r["trades"] > 0])
            },
            "yearly": yearly,
            "exit_reasons": exit_reasons,
            "equity_curve": daily_records[::2]
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/backtests/4y-intraday/logs")
def get_4y_intraday_logs(limit: int = 50, offset: int = 0, ticker: Optional[str] = None):
    """Returns paginated daily trade logs."""
    import sqlite3
    db_path = "data/stock_screener.db"
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        
        where_clause = ""
        params = []
        if ticker and ticker.strip():
            where_clause = "WHERE ticker LIKE ?"
            params.append(f"%{ticker.strip()}%")
            
        cur.execute(f"SELECT count(*) FROM intraday_daily_pnl_logs {where_clause};", params)
        total = cur.fetchone()[0]
        
        cur.execute(f"""
            SELECT id, trade_date, ticker, side, entry_price, exit_price, exit_reason, qty, gross_pnl, net_pnl, return_pct, is_win
            FROM intraday_daily_pnl_logs
            {where_clause}
            ORDER BY trade_date DESC, id DESC
            LIMIT ? OFFSET ?;
        """, params + [limit, offset])
        
        rows = [
            {
                "id": r[0], "date": r[1], "ticker": r[2], "side": r[3],
                "entry_price": r[4], "exit_price": r[5], "exit_reason": r[6],
                "qty": r[7], "gross_pnl": r[8], "net_pnl": r[9],
                "return_pct": r[10], "is_win": bool(r[11])
            }
            for r in cur.fetchall()
        ]
        conn.close()
        return {"status": "success", "total": total, "limit": limit, "offset": offset, "logs": rows}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/backtests/4y-intraday/run")
def run_4y_intraday_backtest_now():
    """Triggers 4-year backtest execution in background."""
    import threading
    from src.algodesk.backtesting.daily_intraday_backtester import DailyIntradayBacktester
    
    def _worker():
        bt = DailyIntradayBacktester()
        bt.run_backtest()
        
    th = threading.Thread(target=_worker, daemon=True)
    th.start()
    return {"status": "started", "message": "4-Year Intraday Backtester started in background."}


@app.get("/api/backtests/top100-intraday/summary")
def get_top100_intraday_summary():
    """Returns Top 100 volume stocks 4-year backtest summary, yearly PnL, and equity curve."""
    import sqlite3
    db_path = "data/stock_screener.db"
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        
        cur.execute("""
            SELECT 
                count(*) as total_trades,
                sum(case when is_win = 1 then 1 else 0 end) as win_trades,
                sum(case when is_win = 0 then 1 else 0 end) as loss_trades,
                sum(net_pnl) as total_net_pnl,
                sum(case when gross_pnl > 0 then gross_pnl else 0 end) as gross_profit,
                abs(sum(case when gross_pnl < 0 then gross_pnl else 0 end)) as gross_loss,
                min(trade_date) as start_date,
                max(trade_date) as end_date
            FROM top100_daily_trade_logs;
        """)
        row = cur.fetchone()
        total_trades = row[0] or 0
        win_trades = row[1] or 0
        loss_trades = row[2] or 0
        total_net_pnl = round(row[3] or 0.0, 2)
        gross_profit = row[4] or 0.0
        gross_loss = row[5] or 0.0
        start_date = row[6] or ""
        end_date = row[7] or ""
        
        win_rate = round((win_trades / total_trades * 100.0), 1) if total_trades > 0 else 0.0
        profit_factor = round(gross_profit / max(1.0, gross_loss), 2)
        initial_capital = 100000.0
        net_return_pct = round((total_net_pnl / initial_capital) * 100.0, 2)
        
        # Yearly PnL
        cur.execute("""
            SELECT substr(trade_date, 1, 4) as yr, round(sum(net_pnl), 2), count(*), sum(is_win)
            FROM top100_daily_trade_logs
            GROUP BY yr
            ORDER BY yr ASC;
        """)
        yearly = [
            {"year": r[0], "pnl": r[1], "trades": r[2], "wins": r[3], "win_rate": round(r[3]/r[2]*100, 1) if r[2] else 0}
            for r in cur.fetchall()
        ]
        
        # Daily records & Drawdown
        cur.execute("""
            SELECT date, daily_net_pnl, cumulative_net_pnl, portfolio_equity, drawdown_pct, trades_count
            FROM top100_daily_pnl_summary
            ORDER BY date ASC;
        """)
        daily_records = [
            {"date": r[0], "daily_pnl": r[1], "cumulative_pnl": r[2], "equity": r[3], "drawdown": r[4], "trades": r[5]}
            for r in cur.fetchall()
        ]
        max_dd = max([r["drawdown"] for r in daily_records], default=0.0)
        
        # Number of unique stocks traded
        cur.execute("SELECT count(*) FROM top100_stock_pnl_summary;")
        stocks_count = cur.fetchone()[0] or 0
        
        conn.close()
        return {
            "status": "success",
            "kpi": {
                "strategy_name": "Top100_ORB_TrailingBreakeven_75",
                "period_years": 4,
                "universe_size": 100,
                "stocks_traded": stocks_count,
                "start_date": start_date,
                "end_date": end_date,
                "initial_capital": initial_capital,
                "ending_equity": round(initial_capital + total_net_pnl, 2),
                "total_trades": total_trades,
                "win_trades": win_trades,
                "loss_trades": loss_trades,
                "win_rate": win_rate,
                "profit_factor": profit_factor,
                "total_net_pnl": total_net_pnl,
                "net_return_pct": net_return_pct,
                "max_drawdown_pct": max_dd,
                "total_days": len(daily_records),
                "days_traded": len([r for r in daily_records if r["trades"] > 0])
            },
            "yearly": yearly,
            "equity_curve": daily_records[::2]
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/backtests/top100-intraday/stocks")
def get_top100_stocks_performance():
    """Returns 4-year performance summary for EACH of the Top 100 stocks."""
    import sqlite3
    db_path = "data/stock_screener.db"
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("""
            SELECT ticker, company_name, total_trades, win_trades, loss_trades,
                   win_rate, total_net_pnl, total_gross_pnl, profit_factor,
                   avg_trade_pnl, best_trade_pnl, worst_trade_pnl,
                   first_trade_date, last_trade_date
            FROM top100_stock_pnl_summary
            ORDER BY total_net_pnl DESC;
        """)
        rows = [
            {
                "ticker": r[0],
                "clean_ticker": r[1],
                "total_trades": r[2],
                "win_trades": r[3],
                "loss_trades": r[4],
                "win_rate": r[5],
                "total_net_pnl": r[6],
                "total_gross_pnl": r[7],
                "profit_factor": r[8],
                "avg_trade_pnl": r[9],
                "best_trade_pnl": r[10],
                "worst_trade_pnl": r[11],
                "first_trade_date": r[12],
                "last_trade_date": r[13]
            }
            for r in cur.fetchall()
        ]
        conn.close()
        return {"status": "success", "count": len(rows), "stocks": rows}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/backtests/top100-intraday/stock-daily")
def get_top100_stock_daily_trades(ticker: str):
    """Returns everyday date-by-date PnL for a chosen stock across the 4 years."""
    import sqlite3
    db_path = "data/stock_screener.db"
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("""
            SELECT id, trade_date, ticker, side, entry_price, exit_price, exit_reason, qty, gross_pnl, net_pnl, return_pct, is_win
            FROM top100_daily_trade_logs
            WHERE ticker = ? OR ticker = ?
            ORDER BY trade_date DESC, id DESC;
        """, (ticker, f"{ticker}.NS" if not ticker.endswith(".NS") else ticker))
        
        rows = [
            {
                "id": r[0], "date": r[1], "ticker": r[2], "side": r[3],
                "entry_price": r[4], "exit_price": r[5], "exit_reason": r[6],
                "qty": r[7], "gross_pnl": r[8], "net_pnl": r[9],
                "return_pct": r[10], "is_win": bool(r[11])
            }
            for r in cur.fetchall()
        ]
        conn.close()
        return {"status": "success", "ticker": ticker, "total_trades": len(rows), "trades": rows}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/backtests/top100-intraday/logs")
def get_top100_intraday_logs(limit: int = 50, offset: int = 0, ticker: Optional[str] = None):
    """Returns paginated daily trade logs for top 100 stocks."""
    import sqlite3
    db_path = "data/stock_screener.db"
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        
        where_clause = ""
        params = []
        if ticker and ticker.strip():
            where_clause = "WHERE ticker LIKE ?"
            params.append(f"%{ticker.strip()}%")
            
        cur.execute(f"SELECT count(*) FROM top100_daily_trade_logs {where_clause};", params)
        total = cur.fetchone()[0]
        
        cur.execute(f"""
            SELECT id, trade_date, ticker, side, entry_price, exit_price, exit_reason, qty, gross_pnl, net_pnl, return_pct, is_win
            FROM top100_daily_trade_logs
            {where_clause}
            ORDER BY trade_date DESC, id DESC
            LIMIT ? OFFSET ?;
        """, params + [limit, offset])
        
        rows = [
            {
                "id": r[0], "date": r[1], "ticker": r[2], "side": r[3],
                "entry_price": r[4], "exit_price": r[5], "exit_reason": r[6],
                "qty": r[7], "gross_pnl": r[8], "net_pnl": r[9],
                "return_pct": r[10], "is_win": bool(r[11])
            }
            for r in cur.fetchall()
        ]
        conn.close()
        return {"status": "success", "total": total, "limit": limit, "offset": offset, "logs": rows}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/backtests/top100-intraday/run")
def run_top100_intraday_backtest_now():
    """Triggers 4-year backtest on Top 100 stocks in background."""
    import threading
    from src.algodesk.backtesting.top100_intraday_backtester import Top100IntradayBacktester
    
    def _worker():
        bt = Top100IntradayBacktester()
        bt.run_backtest()
        
    th = threading.Thread(target=_worker, daemon=True)
    th.start()
    return {"status": "started", "message": "Top 100 Intraday Backtester started in background."}


@app.get("/api/backtests/nifty500-10y/summary")
def get_nifty500_10y_summary():
    """Returns NIFTY 500 10-year backtest summary, yearly PnL, and equity curve."""
    import sqlite3
    db_path = "data/stock_screener.db"
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        
        cur.execute("""
            SELECT 
                count(*) as total_trades,
                sum(case when is_win = 1 then 1 else 0 end) as win_trades,
                sum(case when is_win = 0 then 1 else 0 end) as loss_trades,
                sum(net_pnl) as total_net_pnl,
                sum(case when gross_pnl > 0 then gross_pnl else 0 end) as gross_profit,
                abs(sum(case when gross_pnl < 0 then gross_pnl else 0 end)) as gross_loss,
                min(trade_date) as start_date,
                max(trade_date) as end_date
            FROM nifty500_10y_trade_logs;
        """)
        row = cur.fetchone()
        total_trades = row[0] or 0
        win_trades = row[1] or 0
        loss_trades = row[2] or 0
        total_net_pnl = round(row[3] or 0.0, 2)
        gross_profit = row[4] or 0.0
        gross_loss = row[5] or 0.0
        start_date = row[6] or ""
        end_date = row[7] or ""
        
        win_rate = round((win_trades / total_trades * 100.0), 1) if total_trades > 0 else 0.0
        profit_factor = round(gross_profit / max(1.0, gross_loss), 2)
        initial_capital = 100000.0
        net_return_pct = round((total_net_pnl / initial_capital) * 100.0, 2)
        
        # Yearly PnL
        cur.execute("""
            SELECT substr(trade_date, 1, 4) as yr, round(sum(net_pnl), 2), count(*), sum(is_win)
            FROM nifty500_10y_trade_logs
            GROUP BY yr
            ORDER BY yr ASC;
        """)
        yearly = [
            {"year": r[0], "pnl": r[1], "trades": r[2], "wins": r[3], "win_rate": round(r[3]/r[2]*100, 1) if r[2] else 0}
            for r in cur.fetchall()
        ]
        
        # Daily records & Drawdown
        cur.execute("""
            SELECT date, daily_net_pnl, cumulative_net_pnl, portfolio_equity, drawdown_pct, trades_count
            FROM nifty500_10y_daily_pnl_summary
            ORDER BY date ASC;
        """)
        daily_records = [
            {"date": r[0], "daily_pnl": r[1], "cumulative_pnl": r[2], "equity": r[3], "drawdown": r[4], "trades": r[5]}
            for r in cur.fetchall()
        ]
        max_dd = max([r["drawdown"] for r in daily_records], default=0.0)
        
        cur.execute("SELECT count(*) FROM nifty500_10y_stock_pnl_summary;")
        stocks_count = cur.fetchone()[0] or 0
        
        conn.close()
        return {
            "status": "success",
            "kpi": {
                "strategy_name": "Nifty500_10Y_Intraday_Alpha",
                "period_years": 10,
                "universe_size": 501,
                "stocks_traded": stocks_count,
                "start_date": start_date,
                "end_date": end_date,
                "initial_capital": initial_capital,
                "ending_equity": round(initial_capital + total_net_pnl, 2),
                "total_trades": total_trades,
                "win_trades": win_trades,
                "loss_trades": loss_trades,
                "win_rate": win_rate,
                "profit_factor": profit_factor,
                "total_net_pnl": total_net_pnl,
                "net_return_pct": net_return_pct,
                "max_drawdown_pct": max_dd,
                "total_days": len(daily_records),
                "days_traded": len([r for r in daily_records if r["trades"] > 0])
            },
            "yearly": yearly,
            "equity_curve": daily_records[::4]  # sampled for smooth charting
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/backtests/nifty500-10y/stocks")
def get_nifty500_10y_stocks_performance():
    """Returns 10-year performance summary for EACH of the 500 NIFTY stocks."""
    import sqlite3
    db_path = "data/stock_screener.db"
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("""
            SELECT ticker, company_name, total_trades, win_trades, loss_trades,
                   win_rate, total_net_pnl, total_gross_pnl, profit_factor,
                   avg_trade_pnl, best_trade_pnl, worst_trade_pnl,
                   first_trade_date, last_trade_date
            FROM nifty500_10y_stock_pnl_summary
            ORDER BY total_net_pnl DESC;
        """)
        rows = [
            {
                "ticker": r[0],
                "clean_ticker": r[1],
                "total_trades": r[2],
                "win_trades": r[3],
                "loss_trades": r[4],
                "win_rate": r[5],
                "total_net_pnl": r[6],
                "total_gross_pnl": r[7],
                "profit_factor": r[8],
                "avg_trade_pnl": r[9],
                "best_trade_pnl": r[10],
                "worst_trade_pnl": r[11],
                "first_trade_date": r[12],
                "last_trade_date": r[13]
            }
            for r in cur.fetchall()
        ]
        conn.close()
        return {"status": "success", "count": len(rows), "stocks": rows}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/backtests/nifty500-10y/stock-daily")
def get_nifty500_10y_stock_daily_trades(ticker: str):
    """Returns everyday chronological trade log and PnL for a selected stock from the 10-year suite."""
    import sqlite3
    db_path = "data/stock_screener.db"
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("""
            SELECT id, trade_date, ticker, side, entry_price, exit_price, exit_reason, qty, gross_pnl, net_pnl, return_pct, is_win
            FROM nifty500_10y_trade_logs
            WHERE ticker = ? OR ticker = ?
            ORDER BY trade_date DESC;
        """, (ticker, f"{ticker}.NS" if not ticker.endswith(".NS") else ticker))
        
        trades = [
            {
                "id": r[0],
                "date": r[1],
                "ticker": r[2],
                "side": r[3],
                "entry_price": r[4],
                "exit_price": r[5],
                "exit_reason": r[6],
                "qty": r[7],
                "gross_pnl": r[8],
                "net_pnl": r[9],
                "return_pct": r[10],
                "is_win": bool(r[11])
            }
            for r in cur.fetchall()
        ]
        conn.close()
        return {"status": "success", "ticker": ticker, "total_trades": len(trades), "trades": trades}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/backtests/stock-chart")
def get_stock_chart_with_trades(ticker: str, mode: str = "nifty500"):
    """
    Returns full OHLCV candlestick data along with trade entry & exit markers
    for charting over the 10-year (or 4-year) backtest period.
    """
    import sqlite3
    import pandas as pd
    from pathlib import Path

    clean_t = ticker.replace(".NS", "").replace(".BO", "")
    full_t = f"{clean_t}.NS"

    # Select cache directory based on mode
    cache_file = Path("data/nifty500_10y_cache") / f"{full_t}.parquet"
    if not cache_file.exists():
        cache_file = Path("data/top100_cache") / f"{full_t}.parquet"
    if not cache_file.exists():
        cache_file = Path(f"data/{clean_t}.parquet")

    if not cache_file.exists():
        return {"status": "error", "message": f"Historical bar data not found for {ticker}"}

    try:
        df = pd.read_parquet(cache_file)
        df.dropna(subset=["Open", "High", "Low", "Close"], inplace=True)
        df["time"] = pd.to_datetime(df.index).strftime("%Y-%m-%d")

        candles = []
        for _, row in df.iterrows():
            candles.append({
                "time": row["time"],
                "open": round(float(row["Open"]), 2),
                "high": round(float(row["High"]), 2),
                "low": round(float(row["Low"]), 2),
                "close": round(float(row["Close"]), 2),
                "volume": int(row.get("Volume", 0))
            })

        db_path = "data/stock_screener.db"
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        table_name = "nifty500_10y_trade_logs" if mode == "nifty500" else "top100_daily_trade_logs"
        cur.execute(f"""
            SELECT id, trade_date, side, entry_price, exit_price, exit_reason, qty, gross_pnl, net_pnl, return_pct, is_win
            FROM {table_name}
            WHERE ticker = ? OR ticker = ?
            ORDER BY trade_date ASC;
        """, (full_t, clean_t))

        trades = []
        markers = []

        for r in cur.fetchall():
            tr = {
                "id": r[0],
                "date": r[1],
                "side": r[2],
                "entry_price": r[3],
                "exit_price": r[4],
                "exit_reason": r[5],
                "qty": r[6],
                "gross_pnl": r[7],
                "net_pnl": r[8],
                "return_pct": r[9],
                "is_win": bool(r[10])
            }
            trades.append(tr)

            # Entry Marker
            if tr["side"] == "BUY":
                markers.append({
                    "time": tr["date"],
                    "position": "belowBar",
                    "color": "#10b981",
                    "shape": "arrowUp",
                    "text": f"BUY ₹{tr['entry_price']:.1f}"
                })
            else:
                markers.append({
                    "time": tr["date"],
                    "position": "aboveBar",
                    "color": "#ef4444",
                    "shape": "arrowDown",
                    "text": f"SHORT ₹{tr['entry_price']:.1f}"
                })

            # Exit / PnL Marker
            pnl_sign = "+" if tr["net_pnl"] >= 0 else ""
            if tr["exit_reason"] == "TARGET":
                m_color = "#059669"
                m_shape = "circle"
                m_text = f"🎯 {pnl_sign}₹{tr['net_pnl']:.0f}"
            elif tr["exit_reason"] == "TRAILING_STOP":
                m_color = "#0284c7"
                m_shape = "circle"
                m_text = f"🛡️ {pnl_sign}₹{tr['net_pnl']:.0f}"
            else:
                m_color = "#dc2626"
                m_shape = "circle"
                m_text = f"🛑 {pnl_sign}₹{tr['net_pnl']:.0f}"

            markers.append({
                "time": tr["date"],
                "position": "aboveBar" if tr["side"] == "BUY" else "belowBar",
                "color": m_color,
                "shape": m_shape,
                "text": m_text
            })

        markers.sort(key=lambda m: m["time"])
        conn.close()

        return {
            "status": "success",
            "ticker": full_t,
            "clean_ticker": clean_t,
            "candles": candles,
            "trades": trades,
            "markers": markers,
            "total_trades": len(trades),
            "total_net_pnl": round(sum(t["net_pnl"] for t in trades), 2),
            "win_rate": round(sum(1 for t in trades if t["is_win"]) / len(trades) * 100.0, 1) if trades else 0.0
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/backtests/nifty500-10y/logs")
def get_nifty500_10y_logs(limit: int = 100, offset: int = 0, ticker: Optional[str] = None):
    """Returns paginated individual daily trade logs from the 10-year Nifty 500 backtest."""
    import sqlite3
    db_path = "data/stock_screener.db"
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        
        query = "SELECT id, trade_date, ticker, strategy_name, side, entry_price, exit_price, exit_reason, qty, gross_pnl, net_pnl, return_pct, is_win FROM nifty500_10y_trade_logs"
        params = []
        if ticker:
            query += " WHERE ticker = ?"
            params.append(ticker if ticker.endswith(".NS") else f"{ticker}.NS")
            
        query += " ORDER BY trade_date DESC LIMIT ? OFFSET ?;"
        params.extend([limit, offset])
        
        cur.execute(query, params)
        trades = [
            {
                "id": r[0],
                "date": r[1],
                "ticker": r[2],
                "strategy": r[3],
                "side": r[4],
                "entry_price": r[5],
                "exit_price": r[6],
                "exit_reason": r[7],
                "qty": r[8],
                "gross_pnl": r[9],
                "net_pnl": r[10],
                "return_pct": r[11],
                "is_win": bool(r[12])
            }
            for r in cur.fetchall()
        ]
        conn.close()
        return {"status": "success", "count": len(trades), "trades": trades}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/backtests/nifty500-10y/run")
def run_nifty500_10y_backtest_now():
    """Triggers 10-year backtest on Nifty 500 stocks in background."""
    import threading
    from src.algodesk.backtesting.nifty500_10y_backtester import Nifty500TenYearBacktester
    
    def _worker():
        bt = Nifty500TenYearBacktester()
        bt.run_backtest()
        
    th = threading.Thread(target=_worker, daemon=True)
    th.start()
    return {"status": "started", "message": "Nifty 500 10-Year Intraday Backtester started in background."}


@app.get("/ai", response_class=HTMLResponse, summary="Gemini AI Quant Lab")
def ai_assistant_view(request: Request):
    """Gemini AI Strategy Assistant & Review."""
    drafts = list(pathlib.Path("drafts").glob("*.py")) if pathlib.Path("drafts").exists() else []
    kite_status = check_kite_session_status()

    return templates.TemplateResponse(
        request=request,
        name="ai.html",
        context={
            "active_page": "ai",
            "mode": settings.default_mode.value,
            "gemini_available": gemini_client.is_available(),
            "drafts": [d.name for d in drafts],
            "kill_switch": risk_engine.kill_switch_active,
            "kite_active": kite_status.get("active", False),
            "kite_user_id": kite_status.get("user_id"),
            "kite_url": kite_status.get("login_url"),
        },
    )


@app.post("/ai/draft-strategy")
def draft_strategy_route(user_prompt: str = Form(...)):
    """Invokes Gemini to draft strategy into drafts/ with static safety check."""
    success, msg, py_p, yaml_p = gemini_client.draft_strategy(user_prompt)
    return JSONResponse({"success": success, "message": msg})


@app.get("/api/ai/quant-engine/status", summary="Get Continuous AI Quant Engine Status & Leaderboard")
def get_ai_quant_status():
    """Returns real-time telemetry from the autonomous Gemini Quant Research & Optimization Engine."""
    return quant_optimizer.get_status_payload()


@app.post("/api/ai/quant-engine/start", summary="Start Continuous Autonomous Optimization Loop")
def start_ai_quant_engine():
    """Starts continuous background generation, backtesting, and parameter tweaking."""
    quant_optimizer.start()
    return {"status": "started", "is_running": quant_optimizer.is_running}


@app.post("/api/ai/quant-engine/stop", summary="Stop Continuous Autonomous Optimization Loop")
def stop_ai_quant_engine():
    """Pauses background optimization."""
    quant_optimizer.stop()
    return {"status": "stopped", "is_running": quant_optimizer.is_running}


@app.post("/api/ai/quant-engine/iterate-now", summary="Execute One Optimization Cycle Immediately")
def iterate_ai_quant_now():
    """Manually triggers one complete AI generation -> historical backtest -> decision -> parameter tweak iteration."""
    res = quant_optimizer.run_one_cycle_now()
    return {"status": "success", "result": res}


@app.post("/api/ai/quant-engine/deploy", summary="Deploy Profitable AI Strategy to AlgoDesk")
async def deploy_ai_quant_strategy(request: Request):
    """Deploys an AI-optimized strategy into AlgoDesk configs and arms it for trading."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    strategy_id = body.get("strategy_id")
    if not strategy_id or strategy_id not in quant_optimizer.strategies:
        raise HTTPException(status_code=404, detail=f"Strategy '{strategy_id}' not found.")

    strat = quant_optimizer.strategies[strategy_id]
    summary = strat.latest_result
    if not summary:
        raise HTTPException(status_code=400, detail="Strategy has not been backtested.")

    cfg_file = settings.configs_dir / f"{strategy_id}.yaml"
    yaml_content = f"""# =====================================================================
# AlgoDesk AI-Generated Strategy Configuration (Auto-Optimized by Gemini)
# Status: {summary.verdict} | Net Return: +{summary.net_return_pct}% | Profit Factor: {summary.profit_factor}
# Deployed: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
# =====================================================================
name: "{strat.strategy_id}"
description: "{strat.hypothesis}"
archetype: "{strat.archetype}"
version: "{strat.version}"
timeframe: "5m"
live_enabled: true

parameters:
{chr(10).join(f"  {k}: {v}" for k, v in strat.parameters.items())}

risk:
  risk_per_trade_pct: 0.01
  max_open_positions: 3
  stop_loss_pct: {strat.parameters.get('stop_loss_pct', 0.01)}
  target_pct: {strat.parameters.get('target_pct', 0.02)}

backtest_metrics:
  net_return_pct: {summary.net_return_pct}
  profit_factor: {summary.profit_factor}
  win_rate_pct: {summary.win_rate}
  sharpe_ratio: {summary.sharpe_ratio}
  max_drawdown_pct: {summary.max_drawdown_pct}
"""
    cfg_file.write_text(yaml_content, encoding="utf-8")
    quant_optimizer.log_event("STRAT_DEPLOYED", f"🚀 Strategy '{strategy_id}' deployed and armed for AlgoDesk execution!")
# =====================================================================
# Automated Daily Top Stock Screener & Trailing SL Paper Trader APIs
# =====================================================================

@app.get("/api/automation/top10/status", summary="Get Daily Automated Intraday Screener & Paper Trade Status")
@app.get("/api/automation/top3/status", summary="Get Daily Automated Intraday Screener & Paper Trade Status")
def get_daily_automation_status():
    """Returns today's picked stocks, active open paper trades with trailing SL, closed trades, and net P&L metrics."""
    try:
        from src.algodesk.automation.daily_screener_trader import daily_auto_trader
        return daily_auto_trader.get_automation_status()
    except Exception as e:
        logger.error(f"Error fetching daily automation status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/automation/top10/run-now", summary="Trigger Morning Screener & Initiate Top 10 Paper Trades On-Demand")
@app.post("/api/automation/top3/run-now", summary="Trigger Morning Screener & Initiate Top 10 Paper Trades On-Demand")
def trigger_daily_automation_run(
    top_n: int = Query(10, ge=1, le=25),
    total_capital: float = Query(100000.0, ge=1000.0, le=50000000.0, description="Total capital (₹) to smartly distribute across trades")
):
    """Runs the morning quantitative screener across NIFTY 500, selects top stocks, and smartly distributes capital using Gemini AI."""
    try:
        from src.algodesk.automation.daily_screener_trader import daily_auto_trader
        picks = daily_auto_trader.run_morning_screener_and_pick(top_n=top_n)
        trades = daily_auto_trader.execute_paper_algo_trades(picks=picks, total_capital=total_capital)
        from src.algodesk.automation.daily_screener_trader import IST
        if not trades and datetime.now(IST).hour >= 15:
            return {
                "status": "success",
                "message": f"Screened {len(picks)} stocks. New trades not opened because market is past 3:00 PM IST intraday cutoff.",
                "picks": picks,
                "trades": [],
                "total_capital": total_capital
            }
        return {
            "status": "success",
            "message": f"Screened top stocks and smartly allocated ₹{total_capital:,.2f} into {len(trades)} trades using Gemini AI.",
            "picks": picks,
            "trades": trades,
            "total_capital": total_capital
        }
    except Exception as e:
        logger.error(f"Error running daily automation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/automation/smart-allocation/preview", summary="Preview Gemini Smart Capital Allocation for an Amount X")
def preview_smart_capital_allocation(
    total_capital: float = Query(100000.0, ge=1000.0, le=50000000.0),
    top_n: int = Query(10, ge=1, le=25)
):
    """Calculates how Gemini AI distributes ₹X across today's top screener picks with conviction weights and rationale."""
    try:
        from src.algodesk.automation.daily_screener_trader import daily_auto_trader
        from src.algodesk.ai.gemini_client import GeminiClient
        status_data = daily_auto_trader.get_automation_status()
        picks = status_data.get("today_picks", [])
        if not picks:
            picks = daily_auto_trader.run_morning_screener_and_pick(top_n=top_n)
        gc = GeminiClient()
        result = gc.optimize_capital_allocation(total_capital=total_capital, picks=picks[:top_n])
        return {
            "status": "success",
            "allocation": result.model_dump()
        }
    except Exception as e:
        logger.error(f"Error previewing smart allocation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/automation/top10/tick-update", summary="Run Trailing SL & Target Price Monitor Check")
@app.post("/api/automation/top3/tick-update", summary="Run Trailing SL & Target Price Monitor Check")
def trigger_trailing_sl_update():
    """Polls latest stock market prices, trails stop-losses upward, and executes exits if target or SL is hit."""
    try:
        from src.algodesk.automation.daily_screener_trader import daily_auto_trader
        updates = daily_auto_trader.monitor_and_update_trailing_sl(force_eod_squareoff=False)
        return {
            "status": "success",
            "message": f"Processed price updates for {len(updates)} active positions.",
            "updates": updates
        }
    except Exception as e:
        logger.error(f"Error updating trailing stop-loss: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/automation/top10/square-off", summary="Force EOD Square-Off for All Open Intraday Positions")
@app.post("/api/automation/top3/square-off", summary="Force EOD Square-Off for All Open Intraday Positions")
def trigger_eod_square_off():
    """Immediately closes all open paper positions at market price and logs final net P&L."""
    try:
        from src.algodesk.automation.daily_screener_trader import daily_auto_trader
        closed = daily_auto_trader.monitor_and_update_trailing_sl(force_eod_squareoff=True)
        return {
            "status": "success",
            "message": f"Closed {len(closed)} open positions.",
            "closed": closed
        }
    except Exception as e:
        logger.error(f"Error during square-off: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/automation/trades/{identifier}/close", summary="Square-Off Specific Open Intraday Trade")
def close_specific_open_trade(identifier: str):
    """Immediately squares off a specific open trade by ID or symbol at current market price."""
    try:
        from src.algodesk.automation.daily_screener_trader import daily_auto_trader
        closed = daily_auto_trader.close_single_position(identifier=identifier)
        if not closed:
            raise HTTPException(status_code=404, detail=f"No open trade found for '{identifier}'")
        return {"status": "success", "closed": closed}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error closing trade {identifier}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/automation/top3/simulate", summary="Run Full Simulation Test (Picks + Trades + Trailing SL Moves)")
def trigger_automation_simulation():
    """Performs an end-to-end simulation cycle demonstrating selection, trailing stop adjustments, and P&L logging."""
    try:
        from src.algodesk.automation.daily_screener_trader import daily_auto_trader
        res = daily_auto_trader.simulate_morning_routine_and_trade()
        return res
    except Exception as e:
        logger.error(f"Error during automation simulation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/lightweight-charts.js", include_in_schema=False)
def serve_lw_charts():
    f = os.path.join(FRONTEND_DIR, "lightweight-charts.js")
    if os.path.exists(f):
        return FileResponse(f, media_type="application/javascript")
    raise HTTPException(status_code=404, detail="lightweight-charts.js not found")


@app.get("/chart.js", include_in_schema=False)
def serve_chart_js():
    f = os.path.join(FRONTEND_DIR, "chart.js")
    if os.path.exists(f):
        return FileResponse(f, media_type="application/javascript")
    raise HTTPException(status_code=404, detail="chart.js not found")


# =====================================================================
# Separate Frontend Directory Mount
# =====================================================================

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")

@app.get("/", include_in_schema=False)
@app.get("/screener", include_in_schema=False)
async def serve_index():
    index_file = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_file):
        with open(index_file, "r", encoding="utf-8") as f:
            content = f.read()
        return HTMLResponse(content=content, headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0"
        })
    return HTMLResponse("<h1>Frontend not found</h1>", status_code=404)

@app.get("/app.js", include_in_schema=False)
async def serve_app_js():
    js_file = os.path.join(FRONTEND_DIR, "app.js")
    if os.path.exists(js_file):
        with open(js_file, "r", encoding="utf-8") as f:
            content = f.read()
        return Response(content=content, media_type="application/javascript", headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0"
        })
    return Response("Not found", status_code=404)

@app.get("/style.css", include_in_schema=False)
async def serve_style_css():
    css_file = os.path.join(FRONTEND_DIR, "style.css")
    if os.path.exists(css_file):
        with open(css_file, "r", encoding="utf-8") as f:
            content = f.read()
        return Response(content=content, media_type="text/css", headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0"
        })
    return Response("Not found", status_code=404)

if os.path.exists(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("web.app:app", host="0.0.0.0", port=8000, reload=True)
