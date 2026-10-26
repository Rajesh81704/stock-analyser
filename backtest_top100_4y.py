#!/usr/bin/env python3
"""
CLI entrypoint to run 4-Year Daily Intraday Backtesting on Top 100 Volume-Based NSE Stocks
and log every day's trade and each stock's PnL to SQLite database (data/stock_screener.db).
"""

import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent))

from src.algodesk.backtesting.top100_intraday_backtester import Top100IntradayBacktester


def main():
    print("🚀 Initializing 4-Year Daily Intraday Backtester for Top 100 Volume NSE Stocks...")
    backtester = Top100IntradayBacktester(
        db_path="data/stock_screener.db",
        cache_dir="data/top100_cache",
        initial_capital=100000.0,
        risk_per_trade=50000.0,
        years=4
    )
    backtester.run_backtest(
        strategy_name="Top100_ORB_TrailingBreakeven_75",
        target_pct=0.0135,       # 1.35% intraday target
        stop_loss_pct=0.0065,    # 0.65% stop loss
        breakout_k=0.25,         # Breakout above Open by 0.25 * ATR
        trailing_progress=0.40,  # Move to breakeven after 40% progress toward target
        min_vol_mult=1.15,       # Require 1.15x relative volume expansion
        max_daily_picks=5        # Trade top 5 volume expansion stocks per day
    )


if __name__ == "__main__":
    main()
