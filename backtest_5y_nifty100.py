#!/usr/bin/env python3
"""
5-Year Swing Trading Backtest: EMA Pullback + ADX Strategy on NIFTY 100
- No look-ahead bias (signal T, entry T+1)
- Realistic Zerodha costs and position limits
- Daily position compounding with 1% risk per trade
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from algodesk.indicators.ema import calc_ema_trend
from algodesk.indicators.atr import calc_atr
from algodesk.indicators.adx import calc_adx
from algodesk.backtest.costs import CostModel


def load_nifty100_data(data_dir: str = "data/top100_cache") -> Dict[str, pd.DataFrame]:
    """Load all NIFTY 100 parquet files (last 5 years)."""
    print(f"📊 Loading NIFTY 100 data from {data_dir}...")
    
    stocks_df = {}
    cutoff_date = datetime.now() - timedelta(days=365*5)
    
    data_path = Path(data_dir)
    if not data_path.exists():
        raise FileNotFoundError(f"Data directory {data_dir} not found")
    
    parquet_files = sorted(list(data_path.glob("*.parquet")))[:100]
    print(f"Found {len(parquet_files)} stock files\n")
    
    loaded = 0
    for pf in parquet_files:
        try:
            symbol = pf.stem.replace(".NS", "")
            df = pd.read_parquet(pf)
            
            # Normalize date column
            if 'Date' in df.columns:
                df['Date'] = pd.to_datetime(df['Date'])
                df = df.rename(columns={'Date': 'date'})
            elif 'date' in df.columns:
                df['date'] = pd.to_datetime(df['date'])
            else:
                df.index.name = 'date'
                df = df.reset_index()
                df['date'] = pd.to_datetime(df['date'])
            
            # Filter 5 years
            df = df[df['date'] >= cutoff_date].reset_index(drop=True)
            
            # Normalize column names
            df.columns = [c.lower() for c in df.columns]
            
            required = ['date', 'open', 'high', 'low', 'close', 'volume']
            if all(c in df.columns for c in required):
                df = df[required].copy()
                df = df.drop_duplicates(subset=['date']).sort_values('date').reset_index(drop=True)
                
                if len(df) >= 100:
                    stocks_df[symbol] = df
                    loaded += 1
                    print(f"  ✓ {symbol:<12} {len(df):>4} candles")
        except Exception as e:
            pass
    
    print(f"\n✅ Loaded {loaded} stocks\n")
    return stocks_df


def scan_signals(symbol: str, df: pd.DataFrame, date_str: str) -> Optional[dict]:
    """Scan for Setup A (Pullback) or Setup B (Breakout)."""
    try:
        # Get current bar
        df_date = df[df['date'] == date_str]
        if df_date.empty:
            return None
        
        curr_idx = df_date.index[-1]
        if curr_idx < 50:
            return None
        
        # Add indicators
        df_ind = df.iloc[:curr_idx+1].copy()
        df_ind = calc_ema_trend(df_ind, fast=20, slow=50)
        df_ind = calc_atr(df_ind, period=14)
        df_ind = calc_adx(df_ind, period=14)
        
        curr = df_ind.iloc[-1]
        
        # Extract values
        close = float(curr['close'])
        low = float(curr['low'])
        high = float(curr['high'])
        open_ = float(curr['open'])
        volume = float(curr['volume'])
        
        ema20 = curr.get('ema_20', np.nan)
        ema50 = curr.get('ema_50', np.nan)
        atr14 = curr.get('atr_14', np.nan)
        adx14 = curr.get('adx_14', np.nan)
        di_plus = curr.get('di_plus', 0)
        
        if pd.isna([ema20, ema50, atr14, adx14]).any():
            return None
        
        # Volume multiple
        vol_20 = df_ind['volume'].tail(20).mean()
        vol_mult = volume / vol_20 if vol_20 > 0 else 1.0
        
        # SETUP A: Pullback to EMA20 with bullish candle
        if (close > ema20 and low <= ema20 * 1.005 and 
            close > open_ and adx14 > 15):
            
            stop = low - atr14 * 0.5
            risk = close - stop
            if risk > 0 and risk < atr14 * 2.5:
                return {
                    'symbol': symbol,
                    'date': date_str,
                    'setup': 'PULLBACK_A',
                    'entry': close,
                    'stop': stop,
                    'target1': close + risk * 1.5,
                    'target2': close + risk * 2.5,
                    'atr': atr14,
                    'reason': f"Pullback EMA20, ADX={adx14:.1f}"
                }
        
        # SETUP B: Breakout with ADX and volume
        if (close > ema50 and adx14 > 20 and di_plus > 20 and vol_mult > 1.3):
            swing_low = df_ind[max(0, curr_idx-20):curr_idx]['low'].min()
            stop = swing_low - atr14 * 0.3
            risk = close - stop
            
            if risk > 0 and risk < atr14 * 2.5:
                return {
                    'symbol': symbol,
                    'date': date_str,
                    'setup': 'BREAKOUT_B',
                    'entry': close,
                    'stop': stop,
                    'target1': close + risk * 1.5,
                    'target2': close + risk * 2.5,
                    'atr': atr14,
                    'reason': f"Breakout ADX={adx14:.1f} Vol={vol_mult:.2f}x"
                }
        
        return None
    except Exception as e:
        return None


class SimpleBacktester:
    def __init__(self, initial_capital: float = 1000000.0):
        self.capital = initial_capital
        self.equity = initial_capital
        self.positions = {}
        self.pending_signals = {}
        self.trades = []
        self.daily_equity = []
        self.cost_model = CostModel()
        
    def manage_positions(self, date: str, stocks_df: Dict) -> List[dict]:
        """Close positions on target/stop/time."""
        closed = []
        to_remove = []
        
        for symbol, pos in self.positions.items():
            if symbol not in stocks_df:
                continue
            
            df = stocks_df[symbol]
            df_date = df[df['date'] == date]
            if df_date.empty:
                continue
            
            curr = df_date.iloc[-1]
            close = float(curr['close'])
            low = float(curr['low'])
            
            exit_price = None
            exit_reason = None
            
            # Hit target
            if close >= pos['target1']:
                exit_price = pos['target1']
                exit_reason = 'TARGET'
            # Hit stop
            elif low <= pos['stop']:
                exit_price = pos['stop']
                exit_reason = 'STOP'
            # Time stop (20 days)
            elif (datetime.strptime(date, "%Y-%m-%d") - datetime.strptime(pos['entry_date'], "%Y-%m-%d")).days >= 20:
                exit_price = close
                exit_reason = 'TIME'
            
            if exit_reason:
                # Calculate PnL
                buy_cost = self.cost_model.cost_on_buy(pos['entry'], pos['qty'])
                sell_cost = self.cost_model.cost_on_sell(exit_price, pos['qty'])
                total_cost = buy_cost + sell_cost
                
                gross_pnl = (exit_price - pos['entry']) * pos['qty']
                net_pnl = gross_pnl - total_cost
                
                closed.append({
                    'symbol': symbol,
                    'entry_date': pos['entry_date'],
                    'exit_date': date,
                    'entry': pos['entry'],
                    'exit': exit_price,
                    'qty': pos['qty'],
                    'setup': pos['setup'],
                    'reason': exit_reason,
                    'pnl': net_pnl,
                    'cost': total_cost,
                    'gross_pnl': gross_pnl
                })
                
                self.equity += net_pnl
                to_remove.append(symbol)
        
        for sym in to_remove:
            del self.positions[sym]
        
        return closed
    
    def enter_signals(self, date: str, stocks_df: Dict):
        """Execute pending signals from previous day."""
        for signal in self.pending_signals.values():
            if signal['symbol'] in self.positions:
                continue
            
            # Position size (1% risk rule)
            risk_amt = self.equity * 0.01
            risk_per_share = signal['entry'] - signal['stop']
            
            if risk_per_share > 0:
                qty = int(risk_amt / risk_per_share)
                max_qty = int(self.equity * 0.20 / signal['entry'])
                qty = min(qty, max_qty)
                
                if qty > 0 and len(self.positions) < 5:  # Max 5 positions
                    buy_cost = self.cost_model.cost_on_buy(signal['entry'], qty)
                    if buy_cost < self.equity * 0.5:  # Check capital
                        self.positions[signal['symbol']] = {
                            'entry': signal['entry'],
                            'stop': signal['stop'],
                            'target1': signal['target1'],
                            'target2': signal['target2'],
                            'qty': qty,
                            'entry_date': date,
                            'setup': signal['setup'],
                            'risk': risk_amt
                        }
                        self.equity -= buy_cost
        
        self.pending_signals.clear()
    
    def run(self, stocks_df: Dict) -> Tuple[List, pd.DataFrame]:
        """Run chronological backtest."""
        print("\n🚀 Starting 5-Year Backtest (EMA Pullback + ADX)\n")
        
        # Get all trading dates
        all_dates = set()
        for df in stocks_df.values():
            all_dates.update(df['date'].unique())
        
        sorted_dates = sorted([pd.to_datetime(d).strftime("%Y-%m-%d") for d in all_dates])
        print(f"Trading Days: {len(sorted_dates)}")
        print(f"Period: {sorted_dates[0]} to {sorted_dates[-1]}\n")
        
        for i, date in enumerate(sorted_dates):
            if (i + 1) % 250 == 0:
                print(f"  {date} | Equity: ₹{self.equity:,.0f} | Positions: {len(self.positions)}")
            
            # 1. Manage existing positions (exits)
            trades_today = self.manage_positions(date, stocks_df)
            self.trades.extend(trades_today)
            
            # 2. Execute pending signals from yesterday
            self.enter_signals(date, stocks_df)
            
            # 3. Scan for new signals (queue for tomorrow)
            df_date = {sym: df[df['date'] <= date] for sym, df in stocks_df.items()}
            
            for symbol, df in df_date.items():
                if len(df) > 50 and symbol not in self.positions:
                    signal = scan_signals(symbol, df, date)
                    if signal and symbol not in self.pending_signals:
                        self.pending_signals[symbol] = signal
            
            # 4. Record daily equity
            self.daily_equity.append({
                'date': date,
                'equity': self.equity,
                'positions': len(self.positions),
                'trades_closed': len(trades_today)
            })
        
        print(f"\n✅ Backtest Complete!")
        print(f"Final Equity: ₹{self.equity:,.0f}")
        print(f"Total Trades: {len(self.trades)}\n")
        
        daily_df = pd.DataFrame(self.daily_equity)
        daily_df['date'] = pd.to_datetime(daily_df['date'])
        
        return self.trades, daily_df


def generate_report(trades: List, daily_df: pd.DataFrame, initial_capital: float):
    """Generate PNL report."""
    if not trades:
        print("⚠ No trades executed")
        return
    
    trades_df = pd.DataFrame(trades)
    
    # Metrics
    total_pnl = trades_df['pnl'].sum()
    total_cost = trades_df['cost'].sum()
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
Average PnL per Trade:    ₹{avg_trade:>15,.0f}
Best Trade:               ₹{best_trade:>15,.0f}
Worst Trade:              ₹{worst_trade:>15,.0f}
Total Trading Costs:      ₹{total_cost:>15,.0f}
Profit Factor:            {profit_factor:>15.2f}

SETUP BREAKDOWN
{'-'*80}
"""
    
    for setup in trades_df['setup'].unique():
        setup_trades = trades_df[trades_df['setup'] == setup]
        setup_pnl = setup_trades['pnl'].sum()
        setup_wr = len(setup_trades[setup_trades['pnl'] > 0]) / len(setup_trades) * 100
        report += f"{setup:<20} | Trades: {len(setup_trades):>3} | PnL: ₹{setup_pnl:>12,.0f} | WR: {setup_wr:>5.1f}%\n"
    
    report += f"""
EXIT REASON BREAKDOWN
{'-'*80}
"""
    
    for reason in trades_df['reason'].unique():
        reason_trades = trades_df[trades_df['reason'] == reason]
        reason_pnl = reason_trades['pnl'].sum()
        reason_wr = len(reason_trades[reason_trades['pnl'] > 0]) / len(reason_trades) * 100
        report += f"{reason:<20} | Trades: {len(reason_trades):>3} | PnL: ₹{reason_pnl:>12,.0f} | WR: {reason_wr:>5.1f}%\n"
    
    report += f"""
TOP 10 WINNING TRADES
{'-'*80}
"""
    
    for idx, trade in trades_df.nlargest(10, 'pnl').iterrows():
        report += f"{trade['symbol']:<10} | {trade['entry_date']} | ₹{trade['pnl']:>10,.0f} | {trade['reason']}\n"
    
    report += f"""
TOP 10 LOSING TRADES
{'-'*80}
"""
    
    for idx, trade in trades_df.nsmallest(10, 'pnl').iterrows():
        report += f"{trade['symbol']:<10} | {trade['entry_date']} | ₹{trade['pnl']:>10,.0f} | {trade['reason']}\n"
    
    report += f"\n{'='*80}\n"
    
    print(report)
    
    # Save files
    with open('nifty100_5y_backtest_report.txt', 'w') as f:
        f.write(report)
    
    trades_df.to_csv('nifty100_5y_trades.csv', index=False)
    daily_df.to_csv('nifty100_5y_daily.csv', index=False)
    
    print("📄 Report saved: nifty100_5y_backtest_report.txt")
    print("📊 Trades CSV:   nifty100_5y_trades.csv")
    print("📈 Daily CSV:    nifty100_5y_daily.csv")


if __name__ == "__main__":
    # Load data
    stocks_df = load_nifty100_data("data/top100_cache")
    
    if not stocks_df:
        print("❌ No data loaded")
        sys.exit(1)
    
    # Run backtest
    backtester = SimpleBacktester(initial_capital=1000000.0)
    trades, daily_df = backtester.run(stocks_df)
    
    # Generate report
    generate_report(trades, daily_df, 1000000.0)
