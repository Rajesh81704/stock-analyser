#!/usr/bin/env python3
"""
CLI Runner for NIFTY 500 10-Year Intraday Backtesting
===================================================
Runs institutional morning volume breakout & breakdown strategy across all 501 Nifty 500 stocks
from 2016 to 2026 (or listing date). Logs all daily trades, stock PnLs, and equity curves into SQLite.

Usage:
    .venv/bin/python backtest_nifty500_10y.py
"""

import sys
import json
import logging
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from algodesk.backtesting.nifty500_10y_backtester import Nifty500TenYearBacktester

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("CLI_Nifty500_10Y")


def main():
    print("=" * 78)
    print("  🚀 NIFTY 500 - 10-YEAR INTRADAY INSTITUTIONAL BACKTEST SUITE (2016-2026)")
    print("  Universe: 501 Equities | Period: 10 Years / Listing Date | Bi-Directional")
    print("=" * 78)

    backtester = Nifty500TenYearBacktester(
        initial_capital=100000.0,
        risk_per_trade=50000.0
    )

    print(f"\n[1/3] Universe confirmed with {len(backtester.tickers)} Nifty 500 symbols.")
    print("[2/3] Checking 10-year data cache and fetching historical bars...")
    
    results = backtester.run_backtest(
        strategy_name="Nifty500_10Y_Intraday_Alpha",
        target_pct=0.0135,
        stop_loss_pct=0.0065,
        breakout_k=0.25,
        trailing_progress=0.40,
        min_vol_mult=1.15,
        max_daily_picks=6,
        enable_short=True
    )

    if not results:
        print("❌ Error: Backtest returned no results.")
        sys.exit(1)

    print("\n" + "=" * 78)
    print("  📊 10-YEAR BACKTEST PERFORMANCE SUMMARY")
    print("=" * 78)
    print(f"  Period               : {results['start_date']} to {results['end_date']} (10 Years)")
    print(f"  Total Trading Days   : {results['total_trading_days']:,}")
    print(f"  Constituents Traded  : {results['stocks_traded']} / {results['universe_size']} stocks")
    print(f"  Total Trades Taken   : {results['total_trades']:,}")
    print(f"  Winning Trades       : {results['win_trades']:,}")
    print(f"  Losing Trades        : {results['loss_trades']:,}")
    print(f"  Win Rate             : {results['win_rate']:.2f}%")
    print(f"  Profit Factor        : {results['profit_factor']:.2f}")
    print(f"  Max Drawdown         : {results['max_drawdown_pct']:.2f}%")
    print(f"  Initial Capital      : Rs {results['initial_capital']:,.2f}")
    print(f"  Ending Portfolio PnL : Rs {results['total_net_pnl']:,.2f}")
    print(f"  Ending Equity        : Rs {results['ending_equity']:,.2f} (+{results['total_return_pct']:,.1f}%)")
    print("=" * 78)

    print("\n📅 YEAR-BY-YEAR INTRADAY BREAKDOWN:")
    print(f"  {'Year':<6} | {'Trades':<8} | {'Win Rate':<10} | {'Net PnL (Rs)':<16} | {'Return %':<10}")
    print("  " + "-" * 62)
    for y in results.get("yearly_breakdown", []):
        print(f"  {y['year']:<6} | {y['trades']:<8} | {y['win_rate']:>6.1f}%    | Rs {y['net_pnl']:>12,.2f} | +{y['return_on_capital']:>6.1f}%")
    print("=" * 78)
    print("✅ All individual trades and everyday stock PnL stored in data/stock_screener.db")
    print("✅ Web UI available at: http://localhost:8000/backtests\n")


if __name__ == "__main__":
    main()
