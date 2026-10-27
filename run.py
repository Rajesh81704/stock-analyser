#!/usr/bin/env python3
"""
AlgoDesk MarketX - Local Server Launcher
========================================
Starts the FastAPI local development server for the AlgoDesk MarketX dashboard.

Usage:
    python3 run.py                  # Start local server on http://localhost:8000
    python3 run.py --port 8500      # Custom port
    python3 run.py --host 0.0.0.0   # Allow LAN/remote access
    python3 run.py --no-reload      # Disable hot-reloading (production/PM2 mode)
    python3 run.py --open           # Open browser automatically
"""

import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# 1. Automatic Virtual Environment Bootstrap
# If running with system python, auto-switch to .venv if available
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent

if sys.prefix == sys.base_prefix:
    for venv_candidate in [".venv", "venv", "stock_venv"]:
        venv_python = PROJECT_ROOT / venv_candidate / "bin" / "python"
        if venv_python.is_file() and os.access(venv_python, os.X_OK):
            # Re-execute this script with the virtual environment python
            os.execv(str(venv_python), [str(venv_python)] + sys.argv)

# Ensure project root is in sys.path
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import argparse
import threading
import time
import webbrowser

BANNER = r"""
========================================================================
   ___   __             ___            __   __  ___           __        _  __
  / _ | / /__ ____  ___/ _ \___ ___   / /__/  |/  /__ _____  / /_____  | |/ /
 / __ |/ / _ `/ _ \/ _  / // / -_|_-< /  '_/ /|_/ / _ `/ __/ /  '_/ -_) >  < 
/_/ |_/_/\_, /\___/\_,_/____/\__/___//_/\_\_/  /_/\_,_/_/   /_/\_\\__/ /_/|_| 
        /___/        Autonomous Intraday Suite (5x MIS Leverage)        
========================================================================
"""


def open_browser_delayed(url: str, delay: float = 1.2):
    """Opens default browser after server starts."""
    def _open():
        time.sleep(delay)
        try:
            webbrowser.open(url)
        except Exception:
            pass
    threading.Thread(target=_open, daemon=True).start()


def start_server(host: str, port: int, reload: bool, workers: int = 1, open_browser: bool = False):
    """Starts the FastAPI Web Dashboard & REST API server."""
    print(BANNER)
    
    display_host = "localhost" if host in ("127.0.0.1", "0.0.0.0") else host
    local_url = f"http://{display_host}:{port}"
    docs_url = f"http://{display_host}:{port}/docs"
    
    print("🚀 Starting AlgoDesk MarketX Local Server...")
    print(f"   👉 Web Dashboard: {local_url}")
    print(f"   👉 REST API Docs: {docs_url}")
    print(f"   • Host:           {host}")
    print(f"   • Port:           {port}")
    print(f"   • Auto-Reload:    {'Enabled (hot-reload on file save)' if reload and workers == 1 else 'Disabled'}")
    print(f"   • Leverage:       5.0x Intraday MIS Margin")
    print(f"   • Python:         {sys.executable}")
    print("   • Exit:           Press Ctrl+C to stop\n" + "-" * 72 + "\n")

    if open_browser:
        open_browser_delayed(local_url)

    import uvicorn
    uvicorn.run(
        "web.app:app",
        host=host,
        port=port,
        reload=reload and workers == 1,
        workers=workers if not reload else None,
        log_level="info",
    )


# ---------------------------------------------------------------------------
# CLI Helpers (Screener, Paper Trading, Diagnostics)
# ---------------------------------------------------------------------------

def run_screener(top_n: int = 10):
    """Runs the autonomous morning screener and prints ranked stock picks."""
    print(BANNER)
    print(f"🔍 Running Autonomous Morning Screener (Top {top_n} Stocks in Play)...")
    from src.algodesk.automation.daily_screener_trader import daily_auto_trader
    picks = daily_auto_trader.run_morning_screener_and_pick(top_n=top_n)
    if not picks:
        print("⚠️ No stocks qualified under intraday screener criteria today.")
        return

    print("\n" + "=" * 88)
    print(f"{'RANK':<5} | {'SYMBOL':<14} | {'SCORE':<7} | {'RVOL':<7} | {'PRICE (₹)':<10} | {'SL (₹)':<9} | {'TARGET (₹)':<10} | {'STRATEGY':<12}")
    print("-" * 88)
    for p in picks:
        score_val = f"{p.get('conviction_score', 0):.1f}"
        rvol_val = f"{p.get('rvol', 1.0):.2f}x"
        px = f"₹{p.get('price', 0):.2f}"
        sl = f"₹{p.get('initial_sl', 0):.2f}"
        tgt = f"₹{p.get('target_price', 0):.2f}"
        strat = str(p.get('strategy_name', 'Breakout'))[:12]
        print(f"#{p.get('rank', 1):<4} | {p.get('symbol', ''):<14} | {score_val:<7} | {rvol_val:<7} | {px:<10} | {sl:<9} | {tgt:<10} | {strat:<12}")
    print("=" * 88)
    print(f"✅ Screened & recorded {len(picks)} picks in SQLite database.")


def run_trades(capital: float, top_n: int = 10):
    """Runs the screener + Gemini smart distribution + places paper trades with 5x leverage."""
    print(BANNER)
    print(f"⚡ Executing Smart AI Paper Trades with 5x Intraday Leverage...")
    print(f"   • Margin Capital:  ₹{capital:,.2f}")
    print(f"   • 5x Buying Power: ₹{capital * 5.0:,.2f}")
    from src.algodesk.automation.daily_screener_trader import daily_auto_trader
    picks = daily_auto_trader.run_morning_screener_and_pick(top_n=top_n)
    trades = daily_auto_trader.execute_paper_algo_trades(picks=picks, total_capital=capital)
    if not trades:
        print("⚠️ No trades were entered (market cutoff passed or duplicate check).")
        return

    print("\n" + "=" * 96)
    print(f"{'SYMBOL':<14} | {'QTY (5x)':<9} | {'MARGIN (₹)':<13} | {'5x EXPOSURE (₹)':<16} | {'ENTRY (₹)':<10} | {'SL (₹)':<9} | {'TARGET (₹)':<10}")
    print("-" * 96)
    for t in trades:
        sym = t.get("symbol", "")
        qty = t.get("qty", 0)
        margin = f"₹{t.get('allocated_capital', 0):,.2f}"
        exp = f"₹{qty * t.get('entry_price', 0):,.2f}"
        entry = f"₹{t.get('entry_price', 0):.2f}"
        sl = f"₹{t.get('initial_sl', 0):.2f}"
        tgt = f"₹{t.get('target_price', 0):.2f}"
        print(f"{sym:<14} | {qty:<9} | {margin:<13} | {exp:<16} | {entry:<10} | {sl:<9} | {tgt:<10}")
    print("=" * 96)
    print(f"✅ Executed {len(trades)} paper trades with 5x MIS leverage.")


def run_square_off():
    """Forces square-off on all open intraday positions."""
    print(BANNER)
    print("🛑 Squaring off all open intraday positions at market prices...")
    from src.algodesk.automation.daily_screener_trader import daily_auto_trader
    closed = daily_auto_trader.monitor_and_update_trailing_sl(force_eod_squareoff=True)
    print(f"✅ Closed {len(closed)} open positions.")
    for c in closed:
        sign = "+" if (c.get("net_pnl") or 0) >= 0 else ""
        print(f"   • {c.get('symbol')}: Exit ₹{c.get('exit_price')} | Net P&L: {sign}₹{c.get('net_pnl')} ({c.get('return_pct')}%) | Reason: {c.get('exit_reason')}")


def run_simulation():
    """Runs a full end-to-end simulation cycle."""
    print(BANNER)
    print("🧪 Running End-to-End Simulation Routine...")
    from src.algodesk.automation.daily_screener_trader import daily_auto_trader
    res = daily_auto_trader.simulate_morning_routine_and_trade()
    print("✅ Simulation Complete!")
    print(f"   • Picks Generated:    {len(res.get('picks', []))}")
    print(f"   • Trades Placed (5x): {len(res.get('trades', []))}")
    print(f"   • Trailing SL Ticks:  {len(res.get('simulated_trailing_updates', []))}")
    perf = res.get("performance", {})
    sign = "+" if perf.get("total_net_pnl", 0) >= 0 else ""
    print(f"   • Final Realized P&L: {sign}₹{perf.get('total_net_pnl', 0):.2f} (Win Rate: {perf.get('win_rate', 0)}%)")


def run_check():
    """Validates local environment, SQLite DB, Kite credentials, and Gemini API keys."""
    print(BANNER)
    print("🩺 Running AlgoDesk System & API Health Checks...\n")
    print(f"   [1/4] Python Version:        {sys.version.split()[0]} ({sys.executable})")

    from src.algodesk.automation.daily_screener_trader import daily_auto_trader
    db_file = daily_auto_trader.db_path
    if os.path.exists(db_file):
        size_kb = os.path.getsize(db_file) / 1024.0
        print(f"   [2/4] SQLite Database:       CONNECTED ({db_file} - {size_kb:.1f} KB)")
    else:
        print(f"   [2/4] SQLite Database:       INITIALIZED ({db_file})")

    from src.algodesk.ai.gemini_client import GeminiClient
    gc = GeminiClient()
    if gc.is_available():
        print(f"   [3/4] Gemini AI Engine:      ONLINE ({gc.fast_model})")
    else:
        print("   [3/4] Gemini AI Engine:      OFFLINE / Key not configured (Quant Fallback Active)")

    from src.algodesk.config import settings
    if settings.active_kite_token and settings.kite_api_key:
        print(f"   [4/4] Zerodha Kite Connect:  CONFIGURED (API Key: {settings.kite_api_key[:4]}***)")
    else:
        print("   [4/4] Zerodha Kite Connect:  STANDBY / Mock Feed Active (Daily 2FA token required for live)")

    print("\n✅ System diagnostics completed successfully.")


def run_export_csv(date_str: str):
    """Exports trading history to CSV."""
    from src.algodesk.automation.daily_screener_trader import daily_auto_trader
    csv_text = daily_auto_trader.export_trades_csv(date_str=date_str)
    filename = f"algo_trades_{date_str}.csv"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(csv_text)
    print(f"✅ Exported trades to {os.path.abspath(filename)}")


def main():
    default_port = int(os.getenv("PORT", 8000))
    default_host = os.getenv("HOST", "127.0.0.1")

    parser = argparse.ArgumentParser(
        description="AlgoDesk MarketX - Local Server Launcher & Control Suite",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    # Server arguments
    parser.add_argument("--host", type=str, default=default_host, help="Host IP address to bind to (e.g. 127.0.0.1 or 0.0.0.0)")
    parser.add_argument("--port", type=int, default=default_port, help="Port to run FastAPI server on")
    parser.add_argument("--no-reload", action="store_true", help="Disable auto-reload mode (production/PM2 mode)")
    parser.add_argument("--reload", action="store_true", help="Explicitly enable auto-reload mode")
    parser.add_argument("--workers", type=int, default=1, help="Number of uvicorn worker processes")
    parser.add_argument("--open", "-b", action="store_true", help="Automatically open browser to the dashboard URL")

    # CLI Utility arguments (optional)
    parser.add_argument("--check", action="store_true", help="Run system diagnostics and API health check")
    parser.add_argument("--screen", action="store_true", help="Run morning stock screener & print picks")
    parser.add_argument("--trade", action="store_true", help="Execute smart AI morning trades with 5x leverage")
    parser.add_argument("--capital", type=float, default=100000.0, help="Margin capital for trading (default: 100000.0)")
    parser.add_argument("--top-n", type=int, default=10, help="Number of top stocks to pick/trade")
    parser.add_argument("--square-off", action="store_true", help="Force square-off all active open positions")
    parser.add_argument("--simulate", action="store_true", help="Run end-to-end simulation cycle")
    parser.add_argument("--export-csv", type=str, metavar="DATE", help="Export trade history to CSV ('all' or 'YYYY-MM-DD')")

    args = parser.parse_args()

    # Route to sub-commands if requested, else default to starting the local server
    if args.check:
        run_check()
    elif args.screen:
        run_screener(top_n=args.top_n)
    elif args.trade:
        run_trades(capital=args.capital, top_n=args.top_n)
    elif args.square_off:
        run_square_off()
    elif args.simulate:
        run_simulation()
    elif args.export_csv:
        run_export_csv(date_str=args.export_csv)
    else:
        # Default behavior: Start local server
        reload_enabled = not args.no_reload
        start_server(
            host=args.host,
            port=args.port,
            reload=reload_enabled,
            workers=args.workers,
            open_browser=args.open,
        )


if __name__ == "__main__":
    main()
