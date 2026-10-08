"""
"Bullish Trending Stocks" & NIFTY 500 Stock Evaluator CLI
Runs comprehensive individual stock evaluations (Fundamentals, Technicals, 1-Day & 1-Week Returns, Filter Nodes)
or screens the NIFTY 500 stock universe.

Usage:
    python main.py --ticker RELIANCE.NS
    python main.py --scan-nifty500
    python main.py --serve
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import sys

from src.data_loader import fetch_stock_data, resolve_ticker
from src.screener import BullishTrendingScreenerNode
from src.stock_evaluator import evaluate_individual_stock
from src.universe import get_default_universe, load_tickers_from_csv


def print_banner():
    print("""
========================================================================
                      FastDesk MarketX
     NIFTY 500 QUANTITATIVE SCREENER & STOCK EVALUATOR ENGINE
========================================================================
""")


def _screen_worker(ticker: str):
    try:
        resolved = resolve_ticker(ticker)
        df = fetch_stock_data(resolved, period="6mo")
        screener = BullishTrendingScreenerNode(df)
        res = screener.evaluate_latest()
        return {
            "ticker": ticker,
            "passed_all": res["passed_all"],
            "passed_count": res["passed_count"],
            "pass_percentage": res["pass_percentage"],
            "close": res["latest_bar"].get("close", 0.0),
            "volume": res["latest_bar"].get("volume", 0),
            "rsi_14": res["latest_bar"].get("rsi_14", 0.0),
        }
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser(description="NIFTY 500 Individual Stock Evaluator & Screener Node Pipeline")
    parser.add_argument("--ticker", type=str, default="RELIANCE.NS", help="NSE stock ticker symbol (e.g. RELIANCE.NS, TCS.NS, INFY.NS)")
    parser.add_argument("--scan-nifty500", action="store_true", help="Scan full NIFTY 500 stock universe")
    parser.add_argument("--csv", type=str, default=None, help="Path to a custom CSV file containing tickers")
    parser.add_argument("--period", type=str, default="6mo", help="Historical data period (default: 6mo)")
    parser.add_argument("--serve", action="store_true", help="Launch FastAPI web server on http://localhost:8000")
    parser.add_argument("--port", type=int, default=8000, help="Port to run FastAPI server on")

    args = parser.parse_args()

    if args.serve:
        print_banner()
        print(f"Starting FastAPI Web Server & API on http://localhost:{args.port}...")
        import uvicorn
        uvicorn.run("web.app:app", host="0.0.0.0", port=args.port, reload=True)
        return

    if args.scan_nifty500 or args.csv:
        print_banner()
        csv_file = args.csv if args.csv and os.path.exists(args.csv) else os.path.abspath(os.path.join(os.path.dirname(__file__), "data", "nifty500.csv"))
        tickers = load_tickers_from_csv(csv_file)
        print(f"[CLI] Loaded {len(tickers)} tickers for NIFTY 500 screening: {csv_file}")
        print(f"[CLI] Screening tickers using Screener Node #1 (26 Rules)...\n")

        scanned = []
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {executor.submit(_screen_worker, t): t for t in tickers}
            for future in as_completed(futures):
                res = future.result()
                if res:
                    scanned.append(res)
                    if res["passed_all"]:
                        print(f"  🟢 100% MATCH: {res['ticker']} (Close: ₹{res['close']:.2f}, Volume: {res['volume']:,})")

        scanned.sort(key=lambda x: x["pass_percentage"], reverse=True)
        matched = [s for s in scanned if s["passed_all"]]

        print("\n" + "=" * 80)
        print(f"  NIFTY 500 SCREENING SUMMARY: {len(matched)} / {len(scanned)} STOCKS PASSED ALL 26 RULES")
        print("=" * 80)
        print(f"{'RANK':<5} | {'TICKER':<15} | {'PASS RATIO':<12} | {'CLOSE PRICE':<12} | {'RSI (14)':<10}")
        print("-" * 80)
        for i, item in enumerate(scanned[:25]):
            match_mark = " [100% MATCH]" if item["passed_all"] else ""
            print(f"{i+1:<5} | {item['ticker']:<15} | {item['passed_count']}/26 ({item['pass_percentage']}%) | ₹{item['close']:<11.2f} | {item['rsi_14']:<10.1f}{match_mark}")
        print("=" * 80)
        return

    # Single Stock Evaluation
    print_banner()
    ticker = args.ticker.strip().upper()
    print(f"[CLI] Running Comprehensive Evaluation for {ticker}...\n")

    try:
        eval_data = evaluate_individual_stock(ticker, period=args.period)
        f = eval_data["fundamentals"]
        r = eval_data["returns"]
        node1 = eval_data["screener_nodes"][0]

        print("=" * 75)
        print(f"  STOCK EVALUATION FOR {eval_data['ticker']}")
        print(f"  Company: {f['company_name']} | Sector: {f['sector']} / {f['industry']}")
        print("=" * 75)
        print(f"  LATEST CLOSE PRICE:     ₹{eval_data['latest_close']:.2f}  (As-of: {eval_data['as_of_date']})")
        print(f"  LAST DAY RETURN:        {r['last_day_return_pct']:+.2f}%  ({r['last_day_change']:+.2f} ₹)")
        print(f"  LAST WEEK RETURN (5D):  {r['last_week_return_pct']:+.2f}%  ({r['last_week_change']:+.2f} ₹)")
        print("-" * 75)
        print("  FUNDAMENTAL FINANCIAL PARAMETERS:")
        print(f"  - Market Cap:           ₹ {f['market_cap_cr'] or 'N/A'} Cr")
        print(f"  - Trailing P/E Ratio:   {f['pe_ratio'] or 'N/A'}")
        print(f"  - Price-to-Book (P/B):  {f['pb_ratio'] or 'N/A'}")
        print(f"  - Trailing EPS (TTM):   ₹ {f['eps'] or 'N/A'}")
        print(f"  - Dividend Yield:       {f['dividend_yield'] or 'N/A'}%")
        print(f"  - Return on Equity:     {f['roe'] or 'N/A'}%")
        print(f"  - 52-Week Range:        High: ₹{f['fifty_two_week_high'] or 'N/A'} | Low: ₹{f['fifty_two_week_low'] or 'N/A'}")
        print("-" * 75)
        print("  SCREENER FILTER NODES STATUS:")
        print(f"  - Node #1 (Bullish Trending): {node1['passed_count']}/26 Rules Passed ({node1['pass_percentage']}%) -> {'100% MATCH' if node1['passed_all'] else 'PARTIAL MATCH'}")
        print("=" * 75)

    except Exception as e:
        print(f"[Error] Evaluation failed for {ticker}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
