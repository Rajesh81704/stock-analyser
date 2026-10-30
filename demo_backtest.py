#!/usr/bin/env python3
"""
Demo: Run a quick 30-day NIFTY 100 backtest with synthetic data.
Perfect for testing the pipeline end-to-end.
"""

import sys
sys.path.insert(0, '.')

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import logging
import os

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(message)s')
logger = logging.getLogger(__name__)

# ============================================================================
# STEP 1: Generate Synthetic Data
# ============================================================================
logger.info("="*80)
logger.info("STEP 1: Generating synthetic 5-minute candle data")
logger.info("="*80)

def generate_synthetic_5m(symbol, days=30):
    """Generate synthetic OHLCV data with proper format."""
    np.random.seed(hash(symbol) % 2**32)
    records = []
    current_date = pd.to_datetime("2026-08-01")
    
    for d in range(days):
        if current_date.weekday() >= 5:
            current_date += timedelta(days=1)
            continue
        
        day_price = 100 + np.random.normal(0, 5) + d * 0.1
        
        for bar_num in range(75):
            bar_time = current_date.replace(hour=9, minute=15) + timedelta(minutes=bar_num*5)
            if bar_time.hour > 15 or (bar_time.hour == 15 and bar_time.minute >= 31):
                break
            
            open_p = day_price + np.random.normal(0, 1)
            close_p = open_p + np.random.normal(0, 0.5)
            high_p = max(open_p, close_p) + abs(np.random.normal(0, 0.5))
            low_p = min(open_p, close_p) - abs(np.random.normal(0, 0.5))
            volume = np.random.randint(10000, 100000)
            
            records.append({
                'date': bar_time,
                'open': max(low_p, open_p),
                'high': high_p,
                'low': low_p,
                'close': max(low_p, close_p),
                'volume': volume,
            })
        
        current_date += timedelta(days=1)
    
    df = pd.DataFrame(records)
    df['date'] = pd.to_datetime(df['date'])
    return df

# Generate data for 5 stocks (quick demo)
tickers = ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ICICIBANK.NS"]
data_stores_dict = {}

from src.data.loader import process_symbol_candles
from src.strategy.config import StrategyConfig

config = StrategyConfig(
    initial_capital=100000.0,
    top_n=3,
    or_minutes=5,
    stop_atr=0.10,
)

logger.info(f"Generating synthetic data for {len(tickers)} stocks (60 days minimum)...")
for ticker in tickers:
    df = generate_synthetic_5m(ticker, days=60)  # Increased to 60 days
    store = process_symbol_candles(ticker, df, config)
    if store:
        data_stores_dict[ticker] = store
        logger.info(f"  ✓ {ticker}: {len(store.bars_5m)} bars, {len(store.daily_df)} days")
    else:
        logger.warning(f"  ✗ {ticker}: Failed to create store (insufficient data or hygiene check failed)")

logger.info(f"\n✓ Created {len(data_stores_dict)} data stores")

# ============================================================================
# STEP 2: Run Backtest
# ============================================================================
logger.info("\n" + "="*80)
logger.info("STEP 2: Running backtest engine")
logger.info("="*80)

from src.engine.backtester import BacktestEngine
from src.costs.calculator import CostCalculator

cost_calc = CostCalculator()
engine = BacktestEngine(config, cost_calc)

logger.info(f"Backtesting with capital: ₹{config.initial_capital:,.0f}")
logger.info(f"Configuration: top_n={config.top_n}, or_minutes={config.or_minutes}min, stop_atr={config.stop_atr}x ATR")

result = engine.run(data_stores_dict, cost_multiplier=1.0, slippage_multiplier=1.0)

logger.info(f"\n✓ Backtest complete")
logger.info(f"  Trading Days: {result.total_trading_days}")
logger.info(f"  In-Sample: {result.is_trading_days}, Out-of-Sample: {result.oos_trading_days}")
logger.info(f"  Split Date: {result.split_date}")
logger.info(f"  Start Equity: ₹{result.start_equity:,.2f}")
logger.info(f"  End Equity: ₹{result.end_equity:,.2f}")
total_return_pct = ((result.end_equity / result.start_equity) - 1) * 100
logger.info(f"  Total Return: {total_return_pct:+.2f}%")

# ============================================================================
# STEP 3: Compute Metrics
# ============================================================================
logger.info("\n" + "="*80)
logger.info("STEP 3: Computing performance metrics")
logger.info("="*80)

from src.metrics.performance import PerformanceMetrics

metrics = PerformanceMetrics.from_backtest_result(result)

logger.info(f"\n📊 Performance Summary:")
logger.info(f"  Total Trades: {metrics.total_trades}")
logger.info(f"  Winning Trades: {metrics.winning_trades} ({metrics.win_rate*100:.1f}%)")
logger.info(f"  Losing Trades: {metrics.losing_trades}")
logger.info(f"  Gross P&L: ₹{metrics.total_gross_pnl:,.2f}")
logger.info(f"  Total Costs: ₹{metrics.total_costs:,.2f}")
logger.info(f"  Net P&L: ₹{metrics.total_net_pnl:,.2f}")
logger.info(f"  Profit Factor: {metrics.profit_factor:.2f}")
logger.info(f"  Sharpe Ratio: {metrics.sharpe_ratio:.3f}")
logger.info(f"  Max Drawdown: {metrics.max_drawdown*100:.2f}%")

logger.info(f"\n📈 In-Sample ({result.is_trading_days} days):")
logger.info(f"  Trades: {metrics.is_metrics['trades']}")
logger.info(f"  Win Rate: {metrics.is_metrics['win_rate']*100:.1f}%")
logger.info(f"  Net P&L: ₹{metrics.is_metrics['net_pnl']:,.2f}")
logger.info(f"  Sharpe: {metrics.is_metrics['sharpe']:.3f}")

logger.info(f"\n📉 Out-of-Sample ({result.oos_trading_days} days):")
logger.info(f"  Trades: {metrics.oos_metrics['trades']}")
logger.info(f"  Win Rate: {metrics.oos_metrics['win_rate']*100:.1f}%")
logger.info(f"  Net P&L: ₹{metrics.oos_metrics['net_pnl']:,.2f}")
logger.info(f"  Sharpe: {metrics.oos_metrics['sharpe']:.3f}")

# ============================================================================
# STEP 4: Generate Report
# ============================================================================
logger.info("\n" + "="*80)
logger.info("STEP 4: Generating reports and artifacts")
logger.info("="*80)

os.makedirs("demo_results", exist_ok=True)

# Save trades CSV
trades_file = "demo_results/trades.csv"
result.trades_df.to_csv(trades_file, index=False)
logger.info(f"✓ Trades saved: {trades_file} ({len(result.trades_df)} trades)")

# Save daily CSV
daily_file = "demo_results/daily.csv"
result.daily_df.to_csv(daily_file, index=False)
logger.info(f"✓ Daily P&L saved: {daily_file} ({len(result.daily_df)} days)")

# Generate markdown report
from src.report.generator import ReportGenerator
report_gen = ReportGenerator("demo_results")
output_files = report_gen.generate_all(result, cost_multiplier=1.0, slippage_multiplier=1.0, is_synthetic=True)

logger.info(f"✓ Report saved: {output_files['report_md']}")
logger.info(f"✓ Equity curve saved: {output_files['equity_curve']}")

logger.info("\n" + "="*80)
logger.info("✓ DEMO BACKTEST COMPLETE!")
logger.info("="*80)
logger.info(f"\n📁 Output Directory: demo_results/")
logger.info(f"  - trades.csv (trade-by-trade ledger)")
logger.info(f"  - daily.csv (daily equity progression)")
logger.info(f"  - report.md (comprehensive research report)")
logger.info(f"  - equity_curve.png (visual equity curve)")
logger.info("\n💡 Next: Review results or run full NIFTY 100 backtest with:")
logger.info("  python scripts/nifty100_4y_backtest.py --synthetic")
