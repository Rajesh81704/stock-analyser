#!/usr/bin/env python3
"""
CLI entrypoint to run 4-Year Daily Intraday Backtesting on Top 20 NSE Stocks
and log every day's trade and PnL to SQLite database (data/stock_screener.db).
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from src.algodesk.backtesting.daily_intraday_backtester import DailyIntradayBacktester


def main():
    print("🚀 Initializing 4-Year Daily Intraday Backtester...")
    backtester = DailyIntradayBacktester(
        db_path="data/stock_screener.db",
        initial_capital=100000.0,
        risk_per_trade=50000.0,
        years=4
    )
    backtester.run_backtest(
        strategy_name="Alpha_ORB_TrailingBreakeven_75",
        target_pct=0.0135,       # 1.35% target
        stop_loss_pct=0.0065,    # 0.65% stop loss
        breakout_k=0.25,         # 0.25 * ATR range expansion
        trailing_progress=0.40,  # Ratchet stop to breakeven after 40% target progress
        min_vol_mult=1.10        # Minimum relative volume expansion
    )


if __name__ == "__main__":
    main()
