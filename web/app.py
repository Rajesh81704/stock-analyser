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


app = FastAPI(
    title="FastDesk MarketX - Quantitative Screener & Stock Evaluation API",
    description="Quantitative Technical Screener API & Individual Stock Evaluator for NIFTY 500. Evaluates 26 strict technical rules, fundamentals, percentage returns, and candlestick series.",
    version="3.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
            print(f"[Startup] ⚡ Running automatic multi-node NIFTY 500 bulk scan & analysis to update database...")
            print("=" * 75 + "\n")
            res = run_automatic_scheduled_scan(trigger_name="SERVER_STARTUP_SYNC")
            print(f"\n[Startup] 🎉 Startup multi-node sync complete! Processed {res.get('total_stocks_evaluated')} stocks across 5 screener nodes for {target_date}.\n")
    except Exception as sync_err:
        print(f"[Startup] Warning during startup DB sync: {sync_err}")


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
}

def check_kite_session_status(force: bool = False) -> Dict[str, Any]:
    """Checks whether the current Zerodha KiteConnect session is authenticated and active."""
    import time
    now = time.time()
    # Cache result for 45s to prevent unnecessary external API roundtrips
    if not force and (now - _KITE_STATUS_CACHE["last_checked"] < 45):
        return _KITE_STATUS_CACHE

    from src.data_loader import KITE_API_KEY, KITE_ACCESS_TOKEN
    from kiteconnect import KiteConnect
    try:
        kite = KiteConnect(api_key=KITE_API_KEY)
        kite.set_access_token(KITE_ACCESS_TOKEN)
        profile = kite.profile()
        _KITE_STATUS_CACHE.update({
            "active": True,
            "user_name": profile.get("user_name"),
            "user_id": profile.get("user_id"),
            "last_checked": now,
            "error": None
        })
    except Exception as e:
        _KITE_STATUS_CACHE.update({
            "active": False,
            "user_name": None,
            "user_id": None,
            "last_checked": now,
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
                check_kite_session_status(force=True)
                print(f"[Kite AutoAuth] 🎉 AUTOMATICALLY GENERATED & ACTIVATED KITE ACCESS TOKEN: {acc_token}")
                # Redirect user directly back to the workstation with success indicator
                return RedirectResponse(url="/?kite_auth=success", status_code=303)
        except Exception as err:
            print(f"[Kite AutoAuth Error] {err}")
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
