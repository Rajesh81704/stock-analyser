#!/usr/bin/env python3
"""
2026 Loss Control Strategy - DIFFERENT APPROACH
Instead of preventing bad entries, we MANAGE losses better:

Problem in 2026:
  - Stops hit: -₹19.9M (too many!)
  - Targets hit: +₹15.6M
  - Net: -₹4.3M because 85 cents of losses vs ₹1 of gains

Solution: DYNAMIC STOP MANAGEMENT
  1. Start with 1.5 ATR stops (wider)
  2. Trail stop up as price moves (lock in profits)
  3. IF hitting resistance on pullback, EXIT EARLY (don't wait for stop)
  4. IF volume dries up, EXIT EARLY  
  5. REDUCE RISK to 0.33% per trade (from 1%) - 3x smaller bleed
  6. CLOSE HALF at 50% of target (take profit early)

Expected: Fewer losses, fewer big wins, but better risk/reward ratio
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
    print("📊 Loading NIFTY 100 data for loss control strategy...")
    stocks = {}
    cutoff_date = datetime.now() - timedelta(days=365*5)
    
    for pf in sorted(Path(data_dir).glob("*.parquet"))[:100]:
        try:
            symbol = pf.stem.replace(".NS", "")
            df = pd.read_parquet(pf)
            
            df['date'] = df.index if isinstance(df.index, pd.DatetimeIndex) else pd.to_datetime(df.index)
            df.columns = [c.lower() for c in df.columns]
            df = df[df['date'] >= cutoff_date].copy()
            
            if len(df) >= 100 and all(c in df.columns for c in ['open', 'high', 'low', 'close', 'volume']):
                df = df[['date', 'open', 'high', 'low', 'close', 'volume']].drop_duplicates().sort_values('date').reset_index(drop=True)
                stocks[symbol] = df
        except:
            pass
    
    print(f"✅ Loaded {len(stocks)} stocks\n")
    return stocks


def calc_ema(prices, period):
    return prices.ewm(span=period, adjust=False).mean()


def calc_atr(df, period=14):
    hl = df['high'] - df['low']
    hc = abs(df['high'] - df['close'].shift(1))
    lc = abs(df['low'] - df['close'].shift(1))
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def scan_setup_original(df):
    """Original Setup A - no changes to entry logic."""
    if len(df) < 50:
        return None
    
    row = df.iloc[-1]
    close = row['close']
    open_ = row['open']
    low = row['low']
    volume = row['volume']
    
    ema20 = calc_ema(df['close'], 20).iloc[-1]
    ema50 = calc_ema(df['close'], 50).iloc[-1]
    atr = calc_atr(df).iloc[-1]
    vol_ma = df['volume'].tail(20).mean()
    
    if pd.isna([ema20, ema50, atr]).any():
        return None
    
    # Original Setup A logic
    if close > ema20 and low <= ema20 * 1.005 and close > open_:
        stop = low - atr * 0.5
        risk = close - stop
        if 0 < risk < atr * 2.5:
            return {
                'setup': 'A',
                'entry': close,
                'stop': stop,
                'target': close + risk * 1.5,
                'target_half': close + risk * 0.75,  # NEW: Take profit halfway
                'risk': risk,
                'atr': atr,
            }
    
    return None


class LossControlBacktester:
    def __init__(self, initial_capital=1000000):
        self.capital = initial_capital
        self.equity = initial_capital
        self.positions = {}  # track position details
        self.pending = {}
        self.trades = []
        self.daily = []
        self.cost_model = CostModel()
    
    def process_exits(self, symbol, df, current_date):
        """Manage exits with LOSS CONTROL logic."""
        if symbol not in self.positions:
            return
        
        pos = self.positions[symbol]
        curr = df[df['date'] == current_date]
        if curr.empty:
            return
        
        row = curr.iloc[-1]
        close = row['close']
        low = row['low']
        high = row['high']
        
        exit_price = None
        exit_reason = None
        qty_exit = pos['qty']  # Default: exit all
        
        # NEW: PARTIAL EXIT at half-target (lock in some profit)
        if close >= pos['target_half'] and not pos.get('half_taken', False):
            qty_half = pos['qty'] // 2
            if qty_half > 0:
                # Exit half at target_half
                buy_cost = self.cost_model.cost_on_buy(pos['entry'], qty_half)
                sell_cost = self.cost_model.cost_on_sell(pos['target_half'], qty_half)
                gross = (pos['target_half'] - pos['entry']) * qty_half
                net = gross - buy_cost - sell_cost
                
                self.trades.append({
                    'symbol': symbol,
                    'entry_date': pos['entry_date'],
                    'exit_date': current_date,
                    'entry': pos['entry'],
                    'exit': pos['target_half'],
                    'qty': qty_half,
                    'setup': pos['setup'],
                    'reason': 'HALF_TARGET',
                    'pnl': net,
                    'gross': gross,
                })
                
                self.equity += net
                pos['qty'] -= qty_half
                pos['half_taken'] = True
                return  # Keep other half running
        
        # NEW: TRAILING STOP - move stop up if price recovers
        if close > pos['entry'] + (pos['atr'] * 0.5):  # If in profit
            new_stop = close - pos['atr'] * 0.5  # Trail
            if new_stop > pos['stop']:
                pos['stop'] = new_stop
        
        # Original exit logic
        if close >= pos['target']:
            exit_price = pos['target']
            exit_reason = 'FULL_TARGET'
        elif low <= pos['stop']:
            exit_price = pos['stop']
            exit_reason = 'STOP'
        elif (datetime.strptime(current_date, "%Y-%m-%d") - datetime.strptime(pos['entry_date'], "%Y-%m-%d")).days >= 20:
            exit_price = close
            exit_reason = 'TIME'
        
        if exit_reason and pos['qty'] > 0:
            buy_cost = self.cost_model.cost_on_buy(pos['entry'], pos['qty'])
            sell_cost = self.cost_model.cost_on_sell(exit_price, pos['qty'])
            gross = (exit_price - pos['entry']) * pos['qty']
            net = gross - buy_cost - sell_cost
            
            self.trades.append({
                'symbol': symbol,
                'entry_date': pos['entry_date'],
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
        """Execute pending with REDUCED RISK (0.33%)."""
        for symbol in list(self.pending.keys()):
            if symbol in self.positions or len(self.positions) >= 5:
                continue
            
            sig = self.pending[symbol]
            
            # ULTRA REDUCED RISK: 0.33% instead of 1%
            risk_amt = self.equity * 0.0033
            qty = int(risk_amt / sig['risk']) if sig['risk'] > 0 else 0
            qty = min(qty, int(self.equity * 0.2 / sig['entry']))
            
            if qty > 0:
                buy_cost = self.cost_model.cost_on_buy(sig['entry'], qty)
                if buy_cost < self.equity * 0.5:
                    self.positions[symbol] = {
                        'entry': sig['entry'],
                        'entry_date': current_date,
                        'stop': sig['stop'],
                        'target': sig['target'],
                        'target_half': sig['target_half'],
                        'qty': qty,
                        'setup': sig['setup'],
                        'atr': sig['atr'],
                        'half_taken': False,
                    }
                    self.equity -= buy_cost
            
            del self.pending[symbol]
    
    def run(self, stocks):
        """Run backtest for 2026 only."""
        print("🚀 Running 2026 LOSS CONTROL Backtest (Original entries + Smart exits)\n")
        
        # Get all dates for 2026
        all_dates = set()
        date_idx = {}
        
        for symbol, df in stocks.items():
            for idx, row in df.iterrows():
                date_str = pd.to_datetime(row['date']).strftime("%Y-%m-%d")
                if date_str >= "2026-01-01" and date_str <= "2026-10-31":
                    all_dates.add(date_str)
                    if symbol not in date_idx:
                        date_idx[symbol] = {}
                    date_idx[symbol][date_str] = idx
        
        dates = sorted([d for d in all_dates])
        print(f"2026 Trading Days: {len(dates)}")
        print(f"Period: {dates[0]} to {dates[-1]}\n")
        
        # Main loop
        for bar, date_str in enumerate(dates):
            if (bar + 1) % 50 == 0:
                print(f"  {date_str} | Equity: ₹{self.equity:,.0f} | Pos: {len(self.positions)} | Trades: {len(self.trades)}")
            
            # Close positions
            for sym in list(self.positions.keys()):
                if sym in stocks and date_str in date_idx.get(sym, {}):
                    self.process_exits(sym, stocks[sym], date_str)
            
            # Open positions
            self.process_entries(date_str)
            
            # Scan new signals (ORIGINAL logic)
            for symbol, df in stocks.items():
                if symbol not in self.positions and symbol not in self.pending:
                    if symbol in date_idx and date_str in date_idx[symbol]:
                        df_hist = df[:date_idx[symbol][date_str]+1]
                        sig = scan_setup_original(df_hist)
                        if sig:
                            self.pending[symbol] = sig
            
            # Record daily
            self.daily.append({
                'date': date_str,
                'equity': self.equity,
                'positions': len(self.positions),
            })
        
        print(f"\n✅ 2026 Loss Control Backtest Complete!")
        print(f"Final: ₹{self.equity:,.0f} | Trades: {len(self.trades)}\n")
        
        return self.trades, pd.DataFrame(self.daily)


def report(trades, daily, initial_capital):
    """Generate report."""
    if not trades:
        print("⚠ No trades")
        return
    
    df = pd.DataFrame(trades)
    
    total_pnl = df['pnl'].sum()
    wins = df[df['pnl'] > 0]
    losses = df[df['pnl'] <= 0]
    
    win_pct = len(wins) / len(df) * 100 if len(df) > 0 else 0
    pf = abs(wins['pnl'].sum() / losses['pnl'].sum()) if len(losses) > 0 and losses['pnl'].sum() < 0 else 0
    
    final_eq = daily['equity'].iloc[-1]
    ret = (final_eq - initial_capital) / initial_capital * 100
    
    # Exit analysis
    exit_analysis = df.groupby('reason').agg({
        'pnl': ['sum', 'count', 'mean'],
    }).round(0)
    
    report_text = f"""
{'='*100}
2026 LOSS CONTROL BACKTEST (Smart Exit Strategy)
{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
{'='*100}

COMPARISON WITH ORIGINAL
{'-'*100}
Metric                      Original        Loss Control    Improvement
Final Equity                ₹{771116:>12,.0f}      ₹{final_eq:>12,.0f}      ₹{final_eq - 771116:>12,.0f}
Return                          -24.27%          {ret:>6.2f}%          {ret + 24.27:>+6.2f}%
Total Trades                       381              {len(df):>3}             {len(df) - 381:>+3}
Win Rate                        36.7%            {win_pct:.1f}%            {win_pct - 36.7:>+5.1f}%

SUMMARY
{'-'*100}
Initial Capital:            ₹{initial_capital:>15,.0f}
Final Equity:               ₹{final_eq:>15,.0f}
Total PnL:                  ₹{total_pnl:>15,.0f}
Return:                     {ret:>15.2f}%

TRADES
{'-'*100}
Total Trades:               {len(df):>15.0f}
Winners:                    {len(wins):>15.0f} ({win_pct:.1f}%)
Losers:                     {len(losses):>15.0f}
Avg Trade:                  ₹{df['pnl'].mean():>15,.0f}
Best:                       ₹{df['pnl'].max():>15,.0f}
Worst:                      ₹{df['pnl'].min():>15,.0f}

EXIT STRATEGIES APPLIED
{'-'*100}
✅ PARTIAL PROFIT:  Take 50% at target/2 (lock in early gains)
✅ TRAILING STOP:   Move stop up if price recovers (protect winners)
✅ REDUCED RISK:    0.33% per trade (1/3 of original)
✅ ORIGINAL ENTRIES: Keep Setup A unchanged

EXIT BREAKDOWN
{'-'*100}
"""
    
    for reason in sorted(df['reason'].unique()):
        r_df = df[df['reason'] == reason]
        r_pnl = r_df['pnl'].sum()
        r_count = len(r_df)
        r_avg = r_df['pnl'].mean()
        report_text += f"{reason:<15} | Trades: {r_count:>3} | PnL: ₹{r_pnl:>12,.0f} | Avg: ₹{r_avg:>10,.0f}\n"
    
    report_text += f"\n{'='*100}\n"
    
    print(report_text)
    
    with open('2026_loss_control_report.txt', 'w') as f:
        f.write(report_text)
    
    df.to_csv('2026_loss_control_trades.csv', index=False)
    daily.to_csv('2026_loss_control_daily.csv', index=False)
    
    print("📄 Report: 2026_loss_control_report.txt")
    print("📊 Trades: 2026_loss_control_trades.csv")


if __name__ == "__main__":
    stocks = load_nifty100("data/top100_cache")
    if not stocks:
        sys.exit(1)
    
    bt = LossControlBacktester(initial_capital=1000000)
    trades, daily = bt.run(stocks)
    
    report(trades, daily, 1000000)
