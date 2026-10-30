#!/usr/bin/env python3
"""
NIFTY 100 Paper Trading Backtest (Last 4 Years, 5-Minute Candles)

Simulates the ORB strategy across NIFTY 100 stocks from October 2022 to October 2026.
Downloads historical 5m data from CSV files or generates synthetic data for testing,
runs strict chronological backtest, computes daily compounded P&L, and generates 
comprehensive performance report.

Usage:
    python scripts/nifty100_4y_backtest.py --synthetic
    python scripts/nifty100_4y_backtest.py --start-date 2022-10-30 --end-date 2026-10-30
"""

import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
import logging

import pandas as pd
import numpy as np

from src.costs.calculator import CostCalculator
from src.data.loader import SymbolDataStore, process_symbol_candles
from src.engine.backtester import BacktestEngine
from src.strategy.config import StrategyConfig
from src.metrics.performance import PerformanceMetrics
from src.report.generator import ReportGenerator


# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)


def load_nifty100_tickers(csv_path: str = None) -> list:
    """Load NIFTY 100 tickers from CSV or return hardcoded list."""
    nifty100_symbols = [
        "RELIANCE", "TCS", "INFY", "HINDUNILVR", "ICICIBANK", "HDFC", "HDFCBANK",
        "BAJAJFINSV", "MARUTI", "NESTLEIND", "LT", "ADANIPORTS", "ASIANPAINT",
        "ADANIGREEN", "WIPRO", "BAJFINANCE", "POWERGRID", "NTPC", "JSWSTEEL",
        "SBILIFE", "HCLTECH", "INDIGO", "COALINDIA", "ONGC", "SUNPHARMA",
        "TATASTEEL", "BHARTIARTL", "ULTRACEMCO", "DIVISLAB", "TECHM",
        "KOTAKBANK", "AXISBANK", "M&M", "GRASIM", "BRITANNIA", "CSCO",
        "HEROMOTOCO", "ITC", "TITAN", "EICHERMOT", "GAIL", "PIDILITIND",
        "CIPLA", "LUPIN", "BIOCON", "SBIN", "ABBOTINDIA", "LICT", "NTPC",
        "JSWSTEEL", "SHRIRAMFIN", "KAJARIACER", "UPL", "RAMCOCEM", "PAGEIND",
        "MRF", "TATACONSUM", "TATAMOTORS", "TATASTEEL", "THERMAX", "TORNTPHARM",
        "TRENT", "VAROC", "VESTEL", "WHIRLPOOL", "YESBANK", "ACC", "ADANIENSOL",
        "AIAENG", "APLAPOLLO", "AUBANK", "AARTIIND", "AAVAS", "ACE", "ADANIENT",
        "ABCAPITAL", "ABREL", "AEGISLOG", "AETHER", "AGRITECH", "ALEMBICLTD",
        "AMARAJABAT", "AMBUJACEM", "ANUPAMRAKSHA", "APOLLOHOSPITALS", "APTUS",
        "ARVINDFARM", "ASTRAZEN", "ATGL", "AUBANK", "AVANTIFEED", "AVANTI",
        "AXISBANK", "BAJAJCON", "BALMLAWRIES", "BALAJIMOTOR", "BALRAMCHIN",
        "BANKBARODA", "BANKINDIA", "BASF", "BATA", "BATLIBOI", "BAZIGAR"
    ]
    
    # Remove duplicates and append .NS
    nifty100 = sorted(list(set(nifty100_symbols)))
    return [f"{sym}.NS" for sym in nifty100]


def create_backtest_config() -> StrategyConfig:
    """Create strategy configuration for ORB backtesting."""
    return StrategyConfig(
        initial_capital=500000.0,  # ₹5 Lakh starting capital
        risk_pct=0.02,              # 2% risk per trade [IMPROVED: 0.8% daily targeting]
        max_leverage=5.0,           # Zerodha MIS max leverage
        top_n=10,                   # Top 10 mega-cap candidates [IMPROVED]
        or_minutes=30,              # 30-minute opening range
        stop_atr=0.45,              # 45% of ATR(14) for stop
        min_turnover_cr=500.0,      # ₹500Cr minimum daily turnover [IMPROVED: 0.8% daily]
        market_open_time="09:15:00",
        peak_entry_start="09:45:00",  # [NEW: Start after opening range]
        peak_entry_end="11:30:00",    # [NEW: Stop entries at peak window]
        square_off_time="15:10:00",
        min_price=50.0,
        in_sample_ratio=0.70,       # 70% training, 30% validation
        conservative_intrabar=True,
        exit_type="profit_target",  # [NEW: 2:1 targets instead of time exit]
        risk_reward_ratio=2.0,      # [NEW: 2:1 risk/reward]
        use_trend_filter=True,      # [NEW: Only trade with trend]
        trend_ma_period=20,         # [NEW: 20-day MA for trend]
        mega_cap_only=True,         # [NEW: Top 20 mega-caps only]
    )


def download_nifty100_data(
    tickers: list,
    start_date: str,
    end_date: str,
    use_synthetic: bool = False,
    data_dir: str = "data"
) -> dict:
    """
    Load 5-minute OHLCV data for NIFTY 100 stocks.
    
    Tries to load existing CSV files from data_dir.
    If use_synthetic=True, generates synthetic random-walk data.
    
    Args:
        tickers: List of NSE symbols (e.g. ["RELIANCE.NS", "TCS.NS"])
        start_date: YYYY-MM-DD format (for synthetic data only)
        end_date: YYYY-MM-DD format (for synthetic data only)
        use_synthetic: If True, generate synthetic data
        data_dir: Directory containing CSV files
        
    Returns:
        dict of {symbol: SymbolDataStore} with 5m bars and daily metrics
    """
    logger.info(f"Loading data for {len(tickers)} NIFTY 100 stocks")
    if not use_synthetic:
        logger.info(f"  Source: CSV files in {data_dir}/")
    else:
        logger.info(f"  Source: Synthetic random-walk data ({start_date} to {end_date})")
    
    data_stores = {}
    successful = 0
    failed = 0
    config = create_backtest_config()
    
    for i, ticker in enumerate(tickers, 1):
        try:
            # Remove .NS suffix for CSV filename
            csv_name = ticker.replace(".NS", "")
            csv_path = Path(data_dir) / f"{csv_name}.csv"
            
            if use_synthetic:
                # Generate synthetic data
                logger.info(f"[{i}/{len(tickers)}] Generating synthetic data for {ticker}...")
                df = generate_synthetic_5m_candles(
                    symbol=ticker,
                    start_date=start_date,
                    end_date=end_date,
                    num_days=1000
                )
            else:
                # Load from CSV
                if not csv_path.exists():
                    logger.debug(f"  ℹ️ {csv_path} not found, skipping")
                    failed += 1
                    continue
                    
                logger.info(f"[{i}/{len(tickers)}] Loading {csv_name} from CSV...")
                df = pd.read_csv(csv_path)
            
            if df.empty:
                logger.warning(f"  ⚠️ Empty data for {ticker}")
                failed += 1
                continue
            
            # Ensure datetime column
            if 'Date' in df.columns or 'date' in df.columns:
                date_col = 'Date' if 'Date' in df.columns else 'date'
                df['datetime'] = pd.to_datetime(df[date_col])
                df = df.drop(columns=[date_col])
            elif 'datetime' not in df.columns:
                # Assume first column is datetime
                df.columns = ['datetime'] + list(df.columns[1:])
                df['datetime'] = pd.to_datetime(df['datetime'])
            
            # Standardize OHLCV columns
            df = df.rename(columns={
                'Open': 'open', 'open': 'open',
                'High': 'high', 'high': 'high',
                'Low': 'low', 'low': 'low',
                'Close': 'close', 'close': 'close',
                'Volume': 'volume', 'volume': 'volume',
            })
            
            df = df.set_index('datetime')
            df.index = pd.to_datetime(df.index)
            
            # Process through data loader
            store = process_symbol_candles(ticker, df, config)
            
            if store is not None and not store.bars_5m.empty:
                data_stores[ticker] = store
                successful += 1
                logger.info(f"  ✓ {len(store.bars_5m)} bars loaded for {ticker}")
            else:
                logger.warning(f"  ⚠️ Hygiene check failed for {ticker}")
                failed += 1
                
        except Exception as e:
            logger.error(f"  ✗ Error loading {ticker}: {str(e)[:100]}")
            failed += 1
            continue
    
    logger.info(f"\n✓ Successfully loaded {successful} / {len(tickers)} tickers")
    if failed > 0:
        logger.warning(f"⚠️ Failed to load {failed} tickers")
    
    return data_stores


def generate_synthetic_5m_candles(
    symbol: str,
    start_date: str,
    end_date: str,
    num_days: int = 1000,
    drift: float = 0.0001,
    volatility: float = 0.02
) -> pd.DataFrame:
    """
    Generate synthetic random-walk 5-minute OHLCV data for testing.
    
    Args:
        symbol: Stock ticker
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        num_days: Total trading days to generate
        drift: Daily drift (default: 0.01%)
        volatility: Daily volatility (default: 2%)
        
    Returns:
        DataFrame with datetime index and OHLCV columns
    """
    np.random.seed(hash(symbol) % 2**32)  # Deterministic per symbol
    
    # Generate daily price path
    returns = np.random.normal(drift, volatility, num_days)
    daily_prices = 100 * np.exp(np.cumsum(returns))  # Start at 100
    
    records = []
    current_date = pd.to_datetime(start_date)
    end_dt = pd.to_datetime(end_date)
    
    day_count = 0
    while current_date <= end_dt and day_count < num_days:
        # Skip weekends
        if current_date.weekday() >= 5:
            current_date += timedelta(days=1)
            continue
        
        day_price = daily_prices[day_count]
        
        # Generate 5-minute bars for this day (9:15-15:30 = 378 minutes = ~75 bars)
        for bar_num in range(75):
            bar_time = current_date.replace(hour=9, minute=15) + timedelta(minutes=bar_num*5)
            
            if bar_time.hour > 15 or (bar_time.hour == 15 and bar_time.minute >= 31):
                break
            
            # Intraday noise
            bar_return = np.random.normal(0, volatility / np.sqrt(75))
            open_price = day_price * (1 + bar_return)
            close_price = open_price * (1 + np.random.normal(0, volatility / np.sqrt(75)))
            high_price = max(open_price, close_price) * (1 + abs(np.random.normal(0, volatility / np.sqrt(150))))
            low_price = min(open_price, close_price) * (1 - abs(np.random.normal(0, volatility / np.sqrt(150))))
            volume = np.random.randint(10000, 100000)
            
            records.append({
                'datetime': bar_time,
                'open': open_price,
                'high': high_price,
                'low': low_price,
                'close': close_price,
                'volume': volume,
            })
        
        current_date += timedelta(days=1)
        day_count += 1
    
    df = pd.DataFrame(records)
    df['datetime'] = pd.to_datetime(df['datetime'])
    return df


def run_backtest(
    data_stores: dict,
    config: StrategyConfig,
    output_dir: str = "results"
) -> dict:
    """
    Execute chronological backtest with daily compounding.
    
    Returns:
        dict with backtest result, metrics, and file paths
    """
    logger.info("\n" + "="*80)
    logger.info("STARTING CHRONOLOGICAL BACKTEST WITH DAILY COMPOUNDING")
    logger.info("="*80)
    
    if not data_stores:
        raise ValueError("No data stores provided for backtest")
    
    # Initialize engines
    cost_calc = CostCalculator()
    backtest_engine = BacktestEngine(config, cost_calc)
    
    # Run backtest
    logger.info(f"Running backtest from {config.initial_capital:,.0f} capital...")
    result = backtest_engine.run(
        data_stores=data_stores,
        cost_multiplier=1.0,
        slippage_multiplier=1.0
    )
    
    logger.info(f"\n✓ Backtest complete")
    logger.info(f"  Total Trading Days: {result.total_trading_days}")
    logger.info(f"  In-Sample Days: {result.is_trading_days}")
    logger.info(f"  Out-of-Sample Days: {result.oos_trading_days}")
    logger.info(f"  Split Date: {result.split_date}")
    logger.info(f"  Start Equity: ₹{result.start_equity:,.2f}")
    logger.info(f"  End Equity: ₹{result.end_equity:,.2f}")
    logger.info(f"  Total Return: {((result.end_equity / result.start_equity) - 1) * 100:.2f}%")
    
    # Compute performance metrics
    logger.info("\n" + "-"*80)
    logger.info("COMPUTING PERFORMANCE METRICS")
    logger.info("-"*80)
    
    metrics = PerformanceMetrics.from_backtest_result(result)
    
    logger.info(f"\n📊 PERFORMANCE SUMMARY:")
    logger.info(f"  Total Trades: {metrics.total_trades}")
    logger.info(f"  Winning Trades: {metrics.winning_trades} ({metrics.win_rate*100:.1f}%)")
    logger.info(f"  Losing Trades: {metrics.losing_trades}")
    logger.info(f"  Gross P&L: ₹{metrics.total_gross_pnl:,.2f}")
    logger.info(f"  Costs: ₹{metrics.total_costs:,.2f}")
    logger.info(f"  Net P&L: ₹{metrics.total_net_pnl:,.2f}")
    logger.info(f"  Profit Factor: {metrics.profit_factor:.2f}")
    logger.info(f"  Avg Trade P&L: ₹{metrics.avg_trade_pnl:,.2f}")
    logger.info(f"  Sharpe Ratio: {metrics.sharpe_ratio:.2f}")
    logger.info(f"  Max Drawdown: {metrics.max_drawdown*100:.2f}%")
    
    # In-Sample vs Out-of-Sample metrics
    is_metrics = metrics.is_metrics
    oos_metrics = metrics.oos_metrics
    
    logger.info(f"\n📈 IN-SAMPLE METRICS (Training):")
    logger.info(f"  Trades: {is_metrics['trades']}")
    logger.info(f"  Win Rate: {is_metrics['win_rate']*100:.1f}%")
    logger.info(f"  Net P&L: ₹{is_metrics['net_pnl']:,.2f}")
    logger.info(f"  Sharpe: {is_metrics['sharpe']:.2f}")
    
    logger.info(f"\n📉 OUT-OF-SAMPLE METRICS (Validation):")
    logger.info(f"  Trades: {oos_metrics['trades']}")
    logger.info(f"  Win Rate: {oos_metrics['win_rate']*100:.1f}%")
    logger.info(f"  Net P&L: ₹{oos_metrics['net_pnl']:,.2f}")
    logger.info(f"  Sharpe: {oos_metrics['sharpe']:.2f}")
    
    # Generate report and save results using ReportGenerator
    logger.info(f"\n" + "-"*80)
    logger.info("GENERATING RESEARCH REPORT AND ARTIFACTS")
    logger.info("-"*80)
    
    report_gen = ReportGenerator(output_dir=output_dir)
    output_files = report_gen.generate_all(result, cost_multiplier=1.0, slippage_multiplier=1.0, is_synthetic=False)
    
    logger.info(f"✓ Report artifacts generated:")
    logger.info(f"  Trades ledger: {output_files['trades_csv']}")
    logger.info(f"  Daily P&L: {output_files['daily_csv']}")
    logger.info(f"  Equity curve: {output_files['equity_curve']}")
    logger.info(f"  Report: {output_files['report_md']}")
    
    return {
        "result": result,
        "metrics": metrics,
        "trades_file": output_files['trades_csv'],
        "daily_file": output_files['daily_csv'],
        "report_file": output_files['report_md'],
    }


def main():
    parser = argparse.ArgumentParser(
        description="NIFTY 100 ORB Strategy Backtest (Last 4 Years, 5-Min Candles)"
    )
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="Generate synthetic random-walk data for testing (no Kite API needed)"
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default="2022-10-30",
        help="Start date (YYYY-MM-DD, default: 2022-10-30)"
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default="2026-10-30",
        help="End date (YYYY-MM-DD, default: 2026-10-30)"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="results",
        help="Output directory for results"
    )
    parser.add_argument(
        "--tickers",
        type=str,
        default=None,
        help="CSV file with custom ticker list (one symbol per line)"
    )
    
    args = parser.parse_args()
    
    logger.info("="*80)
    logger.info("NIFTY 100 PAPER TRADING BACKTEST (4-YEAR SIMULATION)")
    logger.info("="*80)
    
    # Load tickers
    if args.tickers and os.path.exists(args.tickers):
        logger.info(f"Loading custom tickers from {args.tickers}")
        with open(args.tickers) as f:
            tickers = [line.strip() for line in f if line.strip() and not line.startswith("#")]
        logger.info(f"Loaded {len(tickers)} custom tickers")
    else:
        logger.info("Loading NIFTY 100 stocks...")
        tickers = load_nifty100_tickers()
        logger.info(f"✓ Loaded {len(tickers)} NIFTY 100 stocks")
    
    # Download/generate data
    logger.info(f"\nDate Range: {args.start_date} to {args.end_date}")
    data_stores = download_nifty100_data(
        tickers=tickers,
        start_date=args.start_date,
        end_date=args.end_date,
        use_synthetic=args.synthetic
    )
    
    if not data_stores:
        logger.error("✗ No data available. Exiting.")
        sys.exit(1)
    
    # Create strategy config
    config = create_backtest_config()
    logger.info(f"\n⚙️ STRATEGY CONFIGURATION:")
    logger.info(f"  Initial Capital: ₹{config.initial_capital:,.0f}")
    logger.info(f"  Risk per Trade: {config.risk_pct*100:.1f}%")
    logger.info(f"  Top-N Candidates: {config.top_n}")
    logger.info(f"  Opening Range Window: {config.or_minutes} minutes")
    logger.info(f"  Stop Loss: {config.stop_atr} × ATR(14)")
    logger.info(f"  Min Turnover: ₹{config.min_turnover_cr} Cr")
    
    # Run backtest
    backtest_output = run_backtest(
        data_stores=data_stores,
        config=config,
        output_dir=args.output_dir
    )
    
    logger.info("\n" + "="*80)
    logger.info("✓ BACKTEST COMPLETE - Check results/ directory for outputs")
    logger.info("="*80)
    logger.info(f"\nKey Output Files:")
    logger.info(f"  📋 Trades: {backtest_output['trades_file']}")
    logger.info(f"  📊 Daily P&L: {backtest_output['daily_file']}")
    logger.info(f"  📄 Report: {backtest_output['report_file']}")


if __name__ == "__main__":
    main()
