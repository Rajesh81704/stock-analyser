#!/usr/bin/env python3
"""
Dual Swing Strategy Backtest: EMA Pullback vs 52-Week High Breakout
Compares two strategies side-by-side on NIFTY 100 stocks (5-year history)
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json
from tqdm import tqdm

from algodesk.execution.paper_trading import PaperTradingEngine
from algodesk.strategies.ema_pullback_adx import EMAPullbackADXStrategy
from src.algodesk.strategies.breakout_52wh import BreakoutHighStrategy


def load_nifty_data():
    """Load NIFTY 100 stock data from cache."""
    cache_dir = Path("data/top100_cache")
    if not cache_dir.exists():
        print("❌ Cache dir not found. Run backtest_final_5y.py first to generate data.")
        return {}
    
    stocks = {}
    for pq_file in cache_dir.glob("*.parquet"):
        symbol = pq_file.stem
        try:
            df = pd.read_parquet(pq_file)
            df = df.sort_values('date').reset_index(drop=True)
            stocks[symbol] = df
        except Exception as e:
            print(f"⚠️  Error loading {symbol}: {e}")
    
    print(f"✅ Loaded {len(stocks)} stocks from cache")
    return stocks


def get_nifty_context(nifty_data, date):
    """Get Nifty context (close, EMA50, etc.) for market regime check."""
    nifty = nifty_data[nifty_data['date'] <= date].iloc[-1] if len(nifty_data[nifty_data['date'] <= date]) > 0 else None
    
    if nifty is None:
        return {}
    
    return {
        'nifty_close': nifty['close'],
        'nifty_ema50': nifty.get('ema_50', nifty['close']),
        'nifty_return_3m': 0,  # Simplified
    }


def backtest_dual_strategy(stocks, nifty_data, start_date, end_date):
    """Run backtest for both strategies on the same period."""
    
    # Engines
    engine_ema = PaperTradingEngine(initial_capital=1_000_000, name="EMA_Pullback_1M")
    engine_52wh = PaperTradingEngine(initial_capital=1_000_000, name="BreakoutHigh_1M")
    
    # Strategies
    strat_ema = EMAPullbackADXStrategy(config={})
    strat_52wh = BreakoutHighStrategy(config={})
    
    # Date range
    start = pd.to_datetime(start_date).date()
    end = pd.to_datetime(end_date).date()
    
    all_dates = sorted(set(
        d for stock_df in stocks.values() 
        for d in pd.to_datetime(stock_df['date']).dt.date 
        if start <= d <= end
    ))
    
    stats_ema = {'trades': 0, 'wins': 0, 'losses': 0, 'pnl': 0}
    stats_52wh = {'trades': 0, 'wins': 0, 'losses': 0, 'pnl': 0}
    
    print(f"\n🔄 Backtesting {len(all_dates)} days across {len(stocks)} stocks...")
    print(f"   Period: {start} to {end}")
    
    for date_idx, curr_date in enumerate(tqdm(all_dates, desc="Backtest Progress")):
        # Market regime
        nifty_ctx = get_nifty_context(nifty_data, curr_date)
        
        # Scan for new signals (EMA strategy)
        for symbol, stock_df in stocks.items():
            df_by_date = stock_df[pd.to_datetime(stock_df['date']).dt.date <= curr_date]
            if len(df_by_date) < 50:
                continue
            
            df = df_by_date.tail(300).copy()
            ctx = {'symbol': symbol, 'current_date': curr_date, **nifty_ctx}
            
            # EMA strategy scan
            signal_ema = strat_ema.scan(df, ctx)
            if signal_ema and symbol not in engine_ema.positions:
                try:
                    engine_ema.place_order(
                        symbol=symbol,
                        qty=max(1, int(10000 / signal_ema.entry_price)),
                        side='BUY',
                        entry_price=signal_ema.entry_price,
                        stop_loss=signal_ema.stop_loss,
                        target=signal_ema.target1,
                        setup_type='EMA_A'
                    )
                    order_id = list(engine_ema.orders.keys())[-1]
                    engine_ema.fill_order(order_id, fill_price=signal_ema.entry_price, 
                                        fill_qty=max(1, int(10000 / signal_ema.entry_price)))
                except:
                    pass
            
            # 52WH strategy scan
            signal_52wh = strat_52wh.scan(df, ctx)
            if signal_52wh and symbol not in engine_52wh.positions:
                try:
                    engine_52wh.place_order(
                        symbol=symbol,
                        qty=max(1, int(10000 / signal_52wh.entry_price)),
                        side='BUY',
                        entry_price=signal_52wh.entry_price,
                        stop_loss=signal_52wh.stop_loss,
                        target=signal_52wh.target1,
                        setup_type='52WH'
                    )
                    order_id = list(engine_52wh.orders.keys())[-1]
                    engine_52wh.fill_order(order_id, fill_price=signal_52wh.entry_price,
                                         fill_qty=max(1, int(10000 / signal_52wh.entry_price)))
                except:
                    pass
        
        # Manage positions
        for symbol in list(engine_ema.positions.keys()):
            df_by_date = stocks[symbol][pd.to_datetime(stocks[symbol]['date']).dt.date <= curr_date]
            if len(df_by_date) > 0:
                df = df_by_date.tail(50).copy()
                ctx = {'symbol': symbol, 'current_date': curr_date}
                exit_ema = strat_ema.manage(engine_ema.positions[symbol], df, ctx)
                
                if exit_ema:
                    engine_ema.close_position(symbol, exit_price=exit_ema.exit_price, 
                                             exit_reason=exit_ema.reason)
                    trade = engine_ema.trades[-1] if engine_ema.trades else None
                    if trade:
                        stats_ema['trades'] += 1
                        if trade.net_pnl > 0:
                            stats_ema['wins'] += 1
                        else:
                            stats_ema['losses'] += 1
                        stats_ema['pnl'] += trade.net_pnl
        
        for symbol in list(engine_52wh.positions.keys()):
            df_by_date = stocks[symbol][pd.to_datetime(stocks[symbol]['date']).dt.date <= curr_date]
            if len(df_by_date) > 0:
                df = df_by_date.tail(50).copy()
                ctx = {'symbol': symbol, 'current_date': curr_date}
                exit_52wh = strat_52wh.manage(engine_52wh.positions[symbol], df, ctx)
                
                if exit_52wh:
                    engine_52wh.close_position(symbol, exit_price=exit_52wh.exit_price,
                                              exit_reason=exit_52wh.reason)
                    trade = engine_52wh.trades[-1] if engine_52wh.trades else None
                    if trade:
                        stats_52wh['trades'] += 1
                        if trade.net_pnl > 0:
                            stats_52wh['wins'] += 1
                        else:
                            stats_52wh['losses'] += 1
                        stats_52wh['pnl'] += trade.net_pnl
    
    return engine_ema, engine_52wh, stats_ema, stats_52wh


def print_comparison(engine_ema, engine_52wh, stats_ema, stats_52wh):
    """Print side-by-side comparison."""
    
    summary_ema = engine_ema.get_portfolio_summary()
    summary_52wh = engine_52wh.get_portfolio_summary()
    
    print("\n" + "="*100)
    print("DUAL SWING STRATEGY BACKTEST RESULTS".center(100))
    print("="*100)
    
    print(f"\n{'METRIC':<40} {'EMA PULLBACK + ADX':<30} {'52-WEEK HIGH BREAKOUT':<30}")
    print("-"*100)
    
    metrics = [
        ('Initial Capital', f"₹{summary_ema['initial_capital']:,.0f}", f"₹{summary_52wh['initial_capital']:,.0f}"),
        ('Final Equity', f"₹{summary_ema['current_equity']:,.0f}", f"₹{summary_52wh['current_equity']:,.0f}"),
        ('Total Return', f"{summary_ema['total_return_pct']:+.2f}%", f"{summary_52wh['total_return_pct']:+.2f}%"),
        ('Total PnL', f"₹{summary_ema['closed_pnl']:,.0f}", f"₹{summary_52wh['closed_pnl']:,.0f}"),
        ('', '', ''),
        ('Total Trades', f"{stats_ema['trades']}", f"{stats_52wh['trades']}"),
        ('Wins', f"{stats_ema['wins']}", f"{stats_52wh['wins']}"),
        ('Losses', f"{stats_ema['losses']}", f"{stats_52wh['losses']}"),
        ('Win Rate', f"{100*stats_ema['wins']/max(1, stats_ema['trades']):.1f}%", 
         f"{100*stats_52wh['wins']/max(1, stats_52wh['trades']):.1f}%"),
        ('Avg Win', f"₹{stats_ema['pnl']/max(1, stats_ema['wins']):,.0f}", 
         f"₹{stats_52wh['pnl']/max(1, stats_52wh['wins']):,.0f}"),
        ('Max Drawdown', f"{summary_ema['max_drawdown_pct']:.2f}%", f"{summary_52wh['max_drawdown_pct']:.2f}%"),
    ]
    
    for row in metrics:
        if row[0] == '':
            print("-"*100)
        else:
            print(f"{row[0]:<40} {row[1]:<30} {row[2]:<30}")
    
    print("\n" + "="*100)
    
    # Recommendation
    if summary_ema['total_return_pct'] > summary_52wh['total_return_pct']:
        winner = "EMA Pullback + ADX"
        margin = summary_ema['total_return_pct'] - summary_52wh['total_return_pct']
    else:
        winner = "52-Week High Breakout"
        margin = summary_52wh['total_return_pct'] - summary_ema['total_return_pct']
    
    print(f"\n🏆 WINNER: {winner} (+{margin:.2f}% advantage)")
    print("="*100)


if __name__ == "__main__":
    # Load data
    stocks = load_nifty_data()
    
    # Load Nifty for market regime
    nifty_file = Path("data/nifty_cache/NIFTY.parquet")
    if nifty_file.exists():
        nifty_data = pd.read_parquet(nifty_file)
        nifty_data['date'] = pd.to_datetime(nifty_data['date'])
    else:
        nifty_data = pd.DataFrame()
    
    # Run backtest
    engine_ema, engine_52wh, stats_ema, stats_52wh = backtest_dual_strategy(
        stocks, nifty_data,
        start_date='2022-10-01',
        end_date='2026-10-31'
    )
    
    # Print results
    print_comparison(engine_ema, engine_52wh, stats_ema, stats_52wh)
    
    print("\n✅ Backtest complete! Export results:")
    print(f"   EMA:  {len(engine_ema.trades)} trades, +{engine_ema.get_portfolio_summary()['total_return_pct']:.2f}%")
    print(f"   52WH: {len(engine_52wh.trades)} trades, +{engine_52wh.get_portfolio_summary()['total_return_pct']:.2f}%")
