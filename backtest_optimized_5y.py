#!/usr/bin/env python3
"""
Optimized 5-Year Backtest: EMA Pullback + ADX Strategy on NIFTY 100
- Pre-compute all indicators for speed
- Simple position management logic
- Fast backtest loop
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List

from algodesk.indicators.ema import calc_ema_trend
from algodesk.indicators.atr import calc_atr
from algodesk.indicators.adx import calc_adx
from algodesk.backtest.costs import CostModel


def load_and_prepare_data(data_dir: str = "data/top100_cache") -> Dict[str, pd.DataFrame]:
    """Load all NIFTY 100 data and pre-compute indicators."""
    print("📊 Loading NIFTY 100 data...")
    
    stocks_df = {}
    cutoff_date = datetime.now() - timedelta(days=365*5)
    
    data_path = Path(data_dir)
    parquet_files = sorted(list(data_path.glob("*.parquet")))[:100]
    
    loaded = 0
    for pf in parquet_files:
        try:
            symbol = pf.stem.replace(".NS", "")
            df = pd.read_parquet(pf)
            
            # Reset index if date is in index
            if isinstance(df.index, pd.DatetimeIndex):
                df['date'] = df.index
            elif df.index.name and 'date' in df.index.name.lower():
                df['date'] = df.index
            else:
                # Find date column
                date_col = None
                for col in df.columns:
                    if 'date' in col.lower():
                        date_col = col
                        break
                if date_col:
                    df['date'] = df[date_col]
                else:
                    continue
            
            # Normalize columns
            df.columns = [c.lower() for c in df.columns]
            df['date'] = pd.to_datetime(df['date'])
            df = df[df['date'] >= cutoff_date].copy()
            
            if len(df) < 100:
                continue
            
            # Keep only needed columns
            required = ['date', 'open', 'high', 'low', 'close', 'volume']
            available = [c for c in required if c in df.columns]
            if len(available) < len(required):
                continue
            
            df = df[available].copy()
            df = df.drop_duplicates(subset=['date']).sort_values('date').reset_index(drop=True)
            
            # Pre-compute indicators
            df = calc_ema_trend(df, fast=20, slow=50)
            df = calc_atr(df, period=14)
            df = calc_adx(df, period=14)
            
            # Compute volume MA
            df['vol_ma_20'] = df['volume'].rolling(20).mean()
            df['vol_mult'] = df['volume'] / df['vol_ma_20']
            
            stocks_df[symbol] = df
            loaded += 1
            if loaded % 10 == 0:
                print(f"  Loaded {loaded} stocks...")
        except Exception as e:
            pass
    
    print(f"✅ Loaded {loaded} stocks with indicators\n")
    return stocks_df


def check_setup_a(row, prev_row=None) -> bool:
    """Pullback to EMA20 with bullish candle."""
    if pd.isna([row['close'], row['low'], row['open'], row['ema_fast'], row['adx_14']]).any():
        return False
    
    return (row['close'] > row['ema_fast'] and 
            row['low'] <= row['ema_fast'] * 1.005 and 
            row['close'] > row['open'] and 
            row['adx_14'] > 15)


def check_setup_b(row) -> bool:
    """Breakout with ADX and volume."""
    if pd.isna([row['close'], row['ema_slow'], row['adx_14'], row['vol_mult']]).any():
        return False
    
    return (row['close'] > row['ema_slow'] and 
            row['adx_14'] > 20 and 
            row.get('di_plus', 0) > 20 and 
            row['vol_mult'] > 1.3)


def scan_signals(df: pd.DataFrame, current_idx: int) -> List[dict]:
    """Scan current bar for signals."""
    signals = []
    
    if current_idx < 50 or current_idx >= len(df):
        return signals
    
    row = df.iloc[current_idx]
    date_str = pd.to_datetime(row['date']).strftime("%Y-%m-%d")
    
    # Setup A
    if check_setup_a(row):
        atr = row.get('atr_14', 0.1)
        stop = row['low'] - atr * 0.5
        risk = row['close'] - stop
        
        if 0 < risk < atr * 2.5:
            signals.append({
                'setup': 'A',
                'entry': row['close'],
                'stop': stop,
                'target1': row['close'] + risk * 1.5,
                'target2': row['close'] + risk * 2.5,
            })
    
    # Setup B
    if check_setup_b(row):
        atr = row.get('atr_14', 0.1)
        swing_low = df[max(0, current_idx-20):current_idx]['low'].min()
        stop = swing_low - atr * 0.3
        risk = row['close'] - stop
        
        if 0 < risk < atr * 2.5:
            signals.append({
                'setup': 'B',
                'entry': row['close'],
                'stop': stop,
                'target1': row['close'] + risk * 1.5,
                'target2': row['close'] + risk * 2.5,
            })
    
    return signals


class FastBacktester:
    def __init__(self, initial_capital: float = 1000000.0):
        self.capital = initial_capital
        self.equity = initial_capital
        self.positions = {}
        self.pending_signals = {}
        self.trades = []
        self.daily_equity = []
        self.cost_model = CostModel()
        
    def process_exits(self, symbol: str, df: pd.DataFrame, current_idx: int) -> List[dict]:
        """Check and process exits for a position."""
        trades_closed = []
        
        if symbol not in self.positions:
            return trades_closed
        
        pos = self.positions[symbol]
        if current_idx < len(df):
            row = df.iloc[current_idx]
            close = row['close']
            low = row['low']
            date_str = pd.to_datetime(row['date']).strftime("%Y-%m-%d")
            
            exit_price = None
            exit_reason = None
            
            # Target hit
            if close >= pos['target1']:
                exit_price = pos['target1']
                exit_reason = 'TARGET'
            # Stop hit
            elif low <= pos['stop']:
                exit_price = pos['stop']
                exit_reason = 'STOP'
            # Time stop (20 days)
            elif (datetime.strptime(date_str, "%Y-%m-%d") - 
                  datetime.strptime(pos['entry_date'], "%Y-%m-%d")).days >= 20:
                exit_price = close
                exit_reason = 'TIME'
            
            if exit_reason:
                buy_cost = self.cost_model.cost_on_buy(pos['entry'], pos['qty'])
                sell_cost = self.cost_model.cost_on_sell(exit_price, pos['qty'])
                total_cost = buy_cost + sell_cost
                
                gross_pnl = (exit_price - pos['entry']) * pos['qty']
                net_pnl = gross_pnl - total_cost
                
                trades_closed.append({
                    'symbol': symbol,
                    'entry_date': pos['entry_date'],
                    'exit_date': date_str,
                    'entry': pos['entry'],
                    'exit': exit_price,
                    'qty': pos['qty'],
                    'setup': pos['setup'],
                    'reason': exit_reason,
                    'pnl': net_pnl,
                    'gross_pnl': gross_pnl,
                })
                
                self.equity += net_pnl
                del self.positions[symbol]
        
        return trades_closed
    
    def process_entries(self, date_str: str) -> int:
        """Execute pending signals from previous day."""
        entries = 0
        
        for symbol in list(self.pending_signals.keys()):
            if symbol in self.positions or len(self.positions) >= 5:
                continue
            
            signal = self.pending_signals[symbol]
            
            # Position size (1% risk)
            risk_amt = self.equity * 0.01
            risk_per_share = signal['entry'] - signal['stop']
            
            if risk_per_share > 0:
                qty = int(risk_amt / risk_per_share)
                max_qty = int(self.equity * 0.20 / signal['entry'])
                qty = min(qty, max_qty)
                
                if qty > 0:
                    buy_cost = self.cost_model.cost_on_buy(signal['entry'], qty)
                    if buy_cost < self.equity * 0.5:
                        self.positions[symbol] = {
                            'entry': signal['entry'],
                            'stop': signal['stop'],
                            'target1': signal['target1'],
                            'target2': signal['target2'],
                            'qty': qty,
                            'entry_date': date_str,
                            'setup': signal['setup'],
                        }
                        self.equity -= buy_cost
                        entries += 1
            
            del self.pending_signals[symbol]
        
        return entries
    
    def run(self, stocks_df: Dict[str, pd.DataFrame]):
        """Run backtest."""
        print("\n🚀 Starting Optimized 5-Year Backtest\n")
        
        # Align all dates
        all_dates = set()
        date_to_idx = {}
        
        for symbol, df in stocks_df.items():
            for idx, row in df.iterrows():
                date_str = pd.to_datetime(row['date']).strftime("%Y-%m-%d")
                all_dates.add(date_str)
                if symbol not in date_to_idx:
                    date_to_idx[symbol] = {}
                date_to_idx[symbol][date_str] = idx
        
        sorted_dates = sorted(list(all_dates))
        print(f"Trading Days: {len(sorted_dates)}")
        print(f"Period: {sorted_dates[0]} to {sorted_dates[-1]}\n")
        
        # Main loop
        for bar_num, date_str in enumerate(sorted_dates):
            if (bar_num + 1) % 250 == 0:
                print(f"  {date_str} | Equity: ₹{self.equity:,.0f} | Pos: {len(self.positions)} | Trades: {len(self.trades)}")
            
            # 1. Manage existing positions
            for symbol in list(self.positions.keys()):
                if symbol in date_to_idx and date_str in date_to_idx[symbol]:
                    df = stocks_df[symbol]
                    idx = date_to_idx[symbol][date_str]
                    trades_today = self.process_exits(symbol, df, idx)
                    self.trades.extend(trades_today)
            
            # 2. Enter pending signals from yesterday
            entries = self.process_entries(date_str)
            
            # 3. Scan for new signals
            for symbol, df in stocks_df.items():
                if symbol not in self.positions and symbol not in self.pending_signals:
                    if symbol in date_to_idx and date_str in date_to_idx[symbol]:
                        idx = date_to_idx[symbol][date_str]
                        signals = scan_signals(df, idx)
                        
                        if signals:
                            # Take best signal
                            signal = max(signals, key=lambda x: (x['target2'] - x['entry']))
                            self.pending_signals[symbol] = signal
            
            # 4. Record daily equity
            self.daily_equity.append({
                'date': date_str,
                'equity': self.equity,
                'positions': len(self.positions),
            })
        
        print(f"\n✅ Backtest Complete!")
        print(f"Final Equity: ₹{self.equity:,.0f}")
        print(f"Total Trades: {len(self.trades)}\n")
        
        return self.trades, pd.DataFrame(self.daily_equity)


def generate_report(trades: List, daily_df: pd.DataFrame, initial_capital: float):
    """Generate report."""
    if not trades:
        print("⚠ No trades executed")
        return
    
    trades_df = pd.DataFrame(trades)
    
    # Metrics
    total_pnl = trades_df['pnl'].sum()
    wins = trades_df[trades_df['pnl'] > 0]
    losses = trades_df[trades_df['pnl'] <= 0]
    
    win_rate = len(wins) / len(trades_df) * 100 if len(trades_df) > 0 else 0
    profit_factor = abs(wins['pnl'].sum() / losses['pnl'].sum()) if len(losses) > 0 and losses['pnl'].sum() < 0 else 0
    
    final_equity = daily_df['equity'].iloc[-1]
    total_ret = (final_equity - initial_capital) / initial_capital * 100
    
    max_dd = ((daily_df['equity'].cummax() - daily_df['equity']) / daily_df['equity'].cummax()).max() * 100
    
    avg_trade = trades_df['pnl'].mean()
    best_trade = trades_df['pnl'].max()
    worst_trade = trades_df['pnl'].min()
    
    report = f"""
{'='*80}
NIFTY 100 | 5-YEAR EMA PULLBACK + ADX BACKTEST REPORT
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
{'='*80}

PORTFOLIO SUMMARY
{'-'*80}
Initial Capital:          ₹{initial_capital:>15,.0f}
Final Equity:             ₹{final_equity:>15,.0f}
Total PnL:                ₹{total_pnl:>15,.0f}
Total Return:             {total_ret:>15.2f}%
Max Drawdown:             {max_dd:>15.2f}%

TRADE STATISTICS
{'-'*80}
Total Trades:             {len(trades_df):>15.0f}
Winning Trades:           {len(wins):>15.0f} ({win_rate:.1f}%)
Losing Trades:            {len(losses):>15.0f}
Average PnL/Trade:        ₹{avg_trade:>15,.0f}
Best Trade:               ₹{best_trade:>15,.0f}
Worst Trade:              ₹{worst_trade:>15,.0f}
Profit Factor:            {profit_factor:>15.2f}

SETUP BREAKDOWN
{'-'*80}
"""
    
    for setup in sorted(trades_df['setup'].unique()):
        setup_trades = trades_df[trades_df['setup'] == setup]
        setup_pnl = setup_trades['pnl'].sum()
        setup_wr = len(setup_trades[setup_trades['pnl'] > 0]) / len(setup_trades) * 100 if len(setup_trades) > 0 else 0
        report += f"Setup {setup:<15} | Trades: {len(setup_trades):>3} | PnL: ₹{setup_pnl:>12,.0f} | WR: {setup_wr:>5.1f}%\n"
    
    report += f"""
EXIT REASON BREAKDOWN
{'-'*80}
"""
    
    for reason in sorted(trades_df['reason'].unique()):
        reason_trades = trades_df[trades_df['reason'] == reason]
        reason_pnl = reason_trades['pnl'].sum()
        reason_wr = len(reason_trades[reason_trades['pnl'] > 0]) / len(reason_trades) * 100 if len(reason_trades) > 0 else 0
        report += f"{reason:<20} | Trades: {reason_trades:>3} | PnL: ₹{reason_pnl:>12,.0f} | WR: {reason_wr:>5.1f}%\n"
    
    report += f"""
TOP 10 WINNING TRADES
{'-'*80}
"""
    
    for idx, trade in trades_df.nlargest(10, 'pnl').iterrows():
        report += f"{trade['symbol']:<10} {trade['entry_date']} → {trade['exit_date']} | ₹{trade['pnl']:>10,.0f} | {trade['reason']}\n"
    
    report += f"""
TOP 10 LOSING TRADES
{'-'*80}
"""
    
    for idx, trade in trades_df.nsmallest(10, 'pnl').iterrows():
        report += f"{trade['symbol']:<10} {trade['entry_date']} → {trade['exit_date']} | ₹{trade['pnl']:>10,.0f} | {trade['reason']}\n"
    
    report += f"\n{'='*80}\n"
    
    print(report)
    
    # Save outputs
    with open('nifty100_5y_backtest_report.txt', 'w') as f:
        f.write(report)
    
    trades_df.to_csv('nifty100_5y_trades.csv', index=False)
    daily_df.to_csv('nifty100_5y_daily.csv', index=False)
    
    print("📄 Report saved: nifty100_5y_backtest_report.txt")
    print("📊 Trades CSV:   nifty100_5y_trades.csv")
    print("📈 Daily CSV:    nifty100_5y_daily.csv")


if __name__ == "__main__":
    # Load and prepare data
    stocks_df = load_and_prepare_data("data/top100_cache")
    
    if not stocks_df:
        print("❌ No data loaded")
        sys.exit(1)
    
    # Run backtest
    backtester = FastBacktester(initial_capital=1000000.0)
    trades, daily_df = backtester.run(stocks_df)
    
    # Generate report
    generate_report(trades, daily_df, 1000000.0)
