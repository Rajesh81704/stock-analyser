#!/usr/bin/env python3
"""
5-Year Backtest: EMA Pullback + ADX Strategy on NIFTY 100
Simplified, fast, self-contained.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List
from algodesk.backtest.costs import CostModel


def load_nifty100(data_dir: str = "data/top100_cache") -> Dict[str, pd.DataFrame]:
    """Load NIFTY 100 data."""
    print("📊 Loading NIFTY 100 data...")
    stocks = {}
    cutoff_date = datetime.now() - timedelta(days=365*5)
    
    for pf in sorted(Path(data_dir).glob("*.parquet"))[:100]:
        try:
            symbol = pf.stem.replace(".NS", "")
            df = pd.read_parquet(pf)
            
            # Reset index
            df['date'] = df.index if isinstance(df.index, pd.DatetimeIndex) else pd.to_datetime(df.index)
            df.columns = [c.lower() for c in df.columns]
            df = df[df['date'] >= cutoff_date].copy()
            
            if len(df) >= 100 and all(c in df.columns for c in ['open', 'high', 'low', 'close', 'volume']):
                df = df[['date', 'open', 'high', 'low', 'close', 'volume']].drop_duplicates().sort_values('date').reset_index(drop=True)
                stocks[symbol] = df
                if len(stocks) % 10 == 0:
                    print(f"  Loaded {len(stocks)} stocks...")
        except:
            pass
    
    print(f"✅ Loaded {len(stocks)} stocks\n")
    return stocks


def calc_ema(prices, period):
    """Calculate EMA."""
    return prices.ewm(span=period, adjust=False).mean()


def calc_atr(df, period=14):
    """Calculate ATR."""
    hl = df['high'] - df['low']
    hc = abs(df['high'] - df['close'].shift(1))
    lc = abs(df['low'] - df['close'].shift(1))
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def scan_setup(df):
    """Scan for entry setups."""
    if len(df) < 50:
        return None
    
    row = df.iloc[-1]
    close = row['close']
    open_ = row['open']
    low = row['low']
    high = row['high']
    volume = row['volume']
    
    # Calculate indicators
    ema20 = calc_ema(df['close'], 20).iloc[-1]
    ema50 = calc_ema(df['close'], 50).iloc[-1]
    atr = calc_atr(df).iloc[-1]
    vol_ma = df['volume'].tail(20).mean()
    vol_mult = volume / vol_ma if vol_ma > 0 else 0
    
    if pd.isna([ema20, ema50, atr]).any():
        return None
    
    # Setup A: Pullback to EMA20
    if close > ema20 and low <= ema20 * 1.005 and close > open_:
        stop = low - atr * 0.5
        risk = close - stop
        if 0 < risk < atr * 2.5:
            return {
                'setup': 'A',
                'entry': close,
                'stop': stop,
                'target': close + risk * 1.5,
                'risk': risk
            }
    
    # Setup B: Breakout above EMA50
    if close > ema50 and vol_mult > 1.3:
        swing_low = df.tail(20)['low'].min()
        stop = swing_low - atr * 0.3
        risk = close - stop
        if 0 < risk < atr * 2.5:
            return {
                'setup': 'B',
                'entry': close,
                'stop': stop,
                'target': close + risk * 1.5,
                'risk': risk
            }
    
    return None


class Backtester:
    def __init__(self, capital=1000000):
        self.capital = capital
        self.equity = capital
        self.positions = {}
        self.pending = {}
        self.trades = []
        self.daily = []
        self.cost_model = CostModel()
    
    def process_exits(self, symbol, df, current_date):
        """Check exits."""
        if symbol not in self.positions:
            return
        
        pos = self.positions[symbol]
        curr = df[df['date'] == current_date]
        if curr.empty:
            return
        
        row = curr.iloc[-1]
        close = row['close']
        low = row['low']
        
        exit_price = None
        exit_reason = None
        
        if close >= pos['target']:
            exit_price = pos['target']
            exit_reason = 'TARGET'
        elif low <= pos['stop']:
            exit_price = pos['stop']
            exit_reason = 'STOP'
        elif (datetime.strptime(current_date, "%Y-%m-%d") - datetime.strptime(pos['date'], "%Y-%m-%d")).days >= 20:
            exit_price = close
            exit_reason = 'TIME'
        
        if exit_reason:
            buy_cost = self.cost_model.cost_on_buy(pos['entry'], pos['qty'])
            sell_cost = self.cost_model.cost_on_sell(exit_price, pos['qty'])
            gross = (exit_price - pos['entry']) * pos['qty']
            net = gross - buy_cost - sell_cost
            
            self.trades.append({
                'symbol': symbol,
                'entry_date': pos['date'],
                'exit_date': current_date,
                'entry': pos['entry'],
                'exit': exit_price,
                'qty': pos['qty'],
                'setup': pos['setup'],
                'reason': exit_reason,
                'pnl': net,
                'gross': gross,
            })
            self.equity += net
            del self.positions[symbol]
    
    def process_entries(self, current_date):
        """Execute pending orders."""
        for symbol in list(self.pending.keys()):
            if symbol in self.positions or len(self.positions) >= 5:
                continue
            
            sig = self.pending[symbol]
            risk_amt = self.equity * 0.01
            qty = int(risk_amt / sig['risk']) if sig['risk'] > 0 else 0
            qty = min(qty, int(self.equity * 0.2 / sig['entry']))
            
            if qty > 0:
                buy_cost = self.cost_model.cost_on_buy(sig['entry'], qty)
                if buy_cost < self.equity * 0.5:
                    self.positions[symbol] = {
                        'entry': sig['entry'],
                        'stop': sig['stop'],
                        'target': sig['target'],
                        'qty': qty,
                        'date': current_date,
                        'setup': sig['setup'],
                    }
                    self.equity -= buy_cost
            
            del self.pending[symbol]
    
    def run(self, stocks):
        """Run backtest."""
        print("🚀 Running 5-Year Backtest\n")
        
        # Get all dates
        all_dates = set()
        date_idx = {}
        
        for symbol, df in stocks.items():
            for idx, row in df.iterrows():
                date_str = pd.to_datetime(row['date']).strftime("%Y-%m-%d")
                all_dates.add(date_str)
                if symbol not in date_idx:
                    date_idx[symbol] = {}
                date_idx[symbol][date_str] = idx
        
        dates = sorted(list(all_dates))
        print(f"Trading Days: {len(dates)}")
        print(f"Period: {dates[0]} to {dates[-1]}\n")
        
        # Main loop
        for bar, date_str in enumerate(dates):
            if (bar + 1) % 250 == 0:
                print(f"  {date_str} | Equity: ₹{self.equity:,.0f} | Positions: {len(self.positions)} | Trades: {len(self.trades)}")
            
            # Close positions
            for sym in list(self.positions.keys()):
                if sym in stocks and date_str in date_idx.get(sym, {}):
                    self.process_exits(sym, stocks[sym], date_str)
            
            # Open positions
            self.process_entries(date_str)
            
            # Scan new signals
            for symbol, df in stocks.items():
                if symbol not in self.positions and symbol not in self.pending:
                    if symbol in date_idx and date_str in date_idx[symbol]:
                        df_hist = df[:date_idx[symbol][date_str]+1]
                        sig = scan_setup(df_hist)
                        if sig:
                            self.pending[symbol] = sig
            
            # Record daily
            self.daily.append({
                'date': date_str,
                'equity': self.equity,
                'positions': len(self.positions),
            })
        
        print(f"\n✅ Complete!")
        print(f"Final: ₹{self.equity:,.0f} | Trades: {len(self.trades)}\n")
        
        return self.trades, pd.DataFrame(self.daily)


def report(trades, daily, initial_capital):
    """Generate report."""
    if not trades:
        print("No trades executed")
        return
    
    df = pd.DataFrame(trades)
    
    total_pnl = df['pnl'].sum()
    wins = df[df['pnl'] > 0]
    losses = df[df['pnl'] <= 0]
    
    win_pct = len(wins) / len(df) * 100 if len(df) > 0 else 0
    pf = abs(wins['pnl'].sum() / losses['pnl'].sum()) if len(losses) > 0 and losses['pnl'].sum() < 0 else 0
    
    final_eq = daily['equity'].iloc[-1]
    ret = (final_eq - initial_capital) / initial_capital * 100
    
    max_dd = ((daily['equity'].cummax() - daily['equity']) / daily['equity'].cummax()).max() * 100 if len(daily) > 0 else 0
    
    report_text = f"""
{'='*80}
NIFTY 100 | 5-YEAR EMA PULLBACK + ADX BACKTEST
{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
{'='*80}

SUMMARY
{'-'*80}
Initial Capital:     ₹{initial_capital:>15,.0f}
Final Equity:        ₹{final_eq:>15,.0f}
Total PnL:           ₹{total_pnl:>15,.0f}
Return %:            {ret:>15.2f}%
Max Drawdown:        {max_dd:>15.2f}%

TRADES
{'-'*80}
Total Trades:        {len(df):>15.0f}
Winners:             {len(wins):>15.0f} ({win_pct:.1f}%)
Losers:              {len(losses):>15.0f}
Profit Factor:       {pf:>15.2f}
Avg Trade:           ₹{df['pnl'].mean():>15,.0f}
Best:                ₹{df['pnl'].max():>15,.0f}
Worst:               ₹{df['pnl'].min():>15,.0f}

SETUP BREAKDOWN
{'-'*80}
"""
    
    for setup in sorted(df['setup'].unique()):
        s_df = df[df['setup'] == setup]
        s_pnl = s_df['pnl'].sum()
        s_wr = len(s_df[s_df['pnl'] > 0]) / len(s_df) * 100 if len(s_df) > 0 else 0
        report_text += f"Setup {setup}: {len(s_df):>3} trades | ₹{s_pnl:>10,.0f} | WR: {s_wr:>5.1f}%\n"
    
    report_text += f"""
EXIT REASONS
{'-'*80}
"""
    
    for reason in sorted(df['reason'].unique()):
        r_df = df[df['reason'] == reason]
        r_pnl = r_df['pnl'].sum()
        report_text += f"{reason}: {len(r_df):>3} trades | ₹{r_pnl:>10,.0f}\n"
    
    report_text += f"""
TOP WINNERS
{'-'*80}
"""
    
    for _, trade in df.nlargest(5, 'pnl').iterrows():
        report_text += f"{trade['symbol']:<10} {trade['entry_date']} | ₹{trade['pnl']:>10,.0f}\n"
    
    report_text += f"""
TOP LOSERS
{'-'*80}
"""
    
    for _, trade in df.nsmallest(5, 'pnl').iterrows():
        report_text += f"{trade['symbol']:<10} {trade['entry_date']} | ₹{trade['pnl']:>10,.0f}\n"
    
    report_text += f"\n{'='*80}\n"
    
    print(report_text)
    
    # Save
    with open('nifty100_5y_report.txt', 'w') as f:
        f.write(report_text)
    
    df.to_csv('nifty100_5y_trades.csv', index=False)
    daily.to_csv('nifty100_5y_daily.csv', index=False)
    
    print("📄 Saved: nifty100_5y_report.txt")
    print("📊 Saved: nifty100_5y_trades.csv")
    print("📈 Saved: nifty100_5y_daily.csv")


if __name__ == "__main__":
    stocks = load_nifty100("data/top100_cache")
    if not stocks:
        print("No data")
        sys.exit(1)
    
    bt = Backtester(capital=1000000)
    trades, daily = bt.run(stocks)
    
    report(trades, daily, 1000000)
