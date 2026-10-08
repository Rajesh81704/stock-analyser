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
import os
from typing import Any, Dict, List, Optional
from fastapi import BackgroundTasks, FastAPI, HTTPException, Path, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.data_loader import fetch_stock_data, fetch_stock_fundamentals, resolve_ticker
from src.screener import FILTER_RULES_SPEC, BullishTrendingScreenerNode, BullishMomentumScreenerNode, list_available_screener_nodes, get_screener_node_by_id
from src.stock_evaluator import evaluate_individual_stock
from src.universe import get_default_universe, load_tickers_from_csv
from src.scheduler import start_automated_scheduler, run_automatic_scheduled_scan


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
    """Starts the background automated stock data puller & 30-min / EOD screener scheduler on application start."""
    try:
        start_automated_scheduler()
    except Exception as e:
        print(f"[Startup] Error starting automated scheduler: {e}")


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
        df = fetch_stock_data(resolved, period="6mo")
        screener = get_screener_node_by_id(node_id, df)
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
    """
    Executes parallel technical screening across NIFTY 500 stocks or returns instant cached DB results.
    """
    node_name = "Pure Bullish Momentum Scan (Node #2)" if req.node_id == "NODE_02_BULLISH_MOMENTUM" else "Bullish Trending Stocks (Node #1)"

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
                print(f"[Kite AutoAuth] 🎉 AUTOMATICALLY GENERATED & ACTIVATED KITE ACCESS TOKEN: {acc_token}")
                return {
                    "status": "success",
                    "message": "🎉 Zerodha Kite Connect Session Activated Successfully! Live market data active.",
                    "access_token": acc_token,
                    "user_name": data.get("user_name"),
                    "user_id": data.get("user_id"),
                    "params": params
                }
        except Exception as err:
            print(f"[Kite AutoAuth Error] {err}")

    return {
        "status": "success",
        "message": "Zerodha Kite Connect login callback received.",
        "params": params
    }


# =====================================================================
# Separate Frontend Directory Mount
# =====================================================================

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")

if os.path.exists(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("web.app:app", host="0.0.0.0", port=8000, reload=True)
