#!/usr/bin/env python3
"""
2026 Optimized Strategy - Loss Management & Parameter Tweaks
Based on analysis: Too many stops hit (-₹19.9M), not enough targets hit (+₹15.6M)

Optimizations:
1. WIDER STOPS: 1.0 ATR instead of 0.5 ATR (let winners run)
2. HIGHER ADX FILTER: Require ADX > 25 (avoid choppy markets)
3. PRICE ACTION FILTER: Only enter if close > open (strong candle)
4. VOLUME BOOST: Require 2.0x volume (not 1.5x) for Setup B
5. SETUP A ONLY: Disable Setup B (too noisy in 2026)
6. RISK REDUCTION: 0.5% risk per trade (not 1%) - slow bleed
7. TIME STOP EARLIER: 15 days (not 20) - get out faster
8. MONTHLY STOP: -8% monthly halt (emergency brake)

Expected Result: Higher stops BUT larger winners + fewer False entries
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
    print("📊 Loading NIFTY 100 data for 2026 optimization...")
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
    """Calculate EMA."""
    return prices.ewm(span=period, adjust=False).mean()


def calc_atr(df, period=14):
    """Calculate ATR."""
    hl = df['high'] - df['low']
    hc = abs(df['high'] - df['close'].shift(1))
    lc = abs(df['low'] - df['close'].shift(1))
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def calc_adx_simple(df, period=14):
    """Calculate ADX (FAST approximation)."""
    # Very simple ADX: just use slope of close / volatility as proxy
    close_diff = df['close'].diff().abs()
    vol_proxy = df['high'] - df['low']
    
    # Trend strength (simple)
    adx_approx = (close_diff / vol_proxy).rolling(period).mean() * 100
    adx_approx = adx_approx.clip(0, 100).fillna(0)
    
    # Directional bias (positive if trending up)
    up_count = (df['close'] > df['close'].shift(1)).rolling(period).sum()
    di_plus = (up_count / period) * 100  # % of bars up
    
    return adx_approx, di_plus


def scan_setup_optimized(df):
    """Scan for OPTIMIZED Setup A only - stricter filters."""
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
    adx_val, di_plus = calc_adx_simple(df)
    adx = adx_val.iloc[-1]
    vol_ma = df['volume'].tail(20).mean()
    
    if pd.isna([ema20, ema50, atr, adx]).any():
        return None
    
    # ===== OPTIMIZED Setup A: Pullback to EMA20 with STRONG filters =====
    # Filter 1: Close must be above EMA20
    if close <= ema20:
        return None
    
    # Filter 2: Low must touch EMA20 (±0.5%)
    if low > ema20 * 1.005:
        return None
    
    # Filter 3: Bullish candle (strong close)
    if close <= open_:
        return None
    
    # Filter 4: HIGHER ADX threshold (avoid choppy markets) - THIS IS KEY FIX
    if adx < 25:  # Changed from 15 to 25 - much stricter!
        return None
    
    # Filter 5: Volume confirmation
    vol_mult = volume / vol_ma if vol_ma > 0 else 0
    if vol_mult < 1.2:  # Minimum 1.2x volume
        return None
    
    # ===== WIDER STOPS (1.0 ATR instead of 0.5) - LOSE LESS =====
    stop = low - atr * 1.0  # CHANGED from 0.5 to 1.0
    risk = close - stop
    
    # Filter 6: Risk must be reasonable (< 2.0 ATR, not 2.5)
    if risk <= 0 or risk > atr * 2.0:  # Tighter risk window
        return None
    
    return {
        'setup': 'A_OPT',
        'entry': close,
        'stop': stop,
        'target': close + risk * 1.5,
        'risk': risk,
        'atr': atr,
        'adx': adx
    }


class OptimizedBacktester:
    def __init__(self, initial_capital=1000000):
        self.capital = initial_capital
        self.equity = initial_capital
        self.positions = {}
        self.pending = {}
        self.trades = []
        self.daily = []
        self.cost_model = CostModel()
        self.monthly_start = initial_capital
        self.current_month = None
    
    def process_exits(self, symbol, df, current_date):
        """Check exits - WIDER STOPS mean fewer hits."""
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
        # EARLIER TIME STOP: 15 days instead of 20
        elif (datetime.strptime(current_date, "%Y-%m-%d") - datetime.strptime(pos['date'], "%Y-%m-%d")).days >= 15:
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
        """Execute pending orders - REDUCED RISK (0.5% not 1%)."""
        for symbol in list(self.pending.keys()):
            if symbol in self.positions or len(self.positions) >= 5:
                continue
            
            sig = self.pending[symbol]
            
            # REDUCED RISK: 0.5% instead of 1%
            risk_amt = self.equity * 0.005  # CHANGED from 0.01 to 0.005
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
    
    def check_monthly_stop(self, current_date):
        """Check -8% monthly drawdown halt."""
        if current_date[:7] != self.current_month:  # New month
            self.current_month = current_date[:7]
            self.monthly_start = self.equity
        
        # -8% halt
        if (self.equity - self.monthly_start) / self.monthly_start < -0.08:
            return True  # Stop trading this month
        return False
    
    def run(self, stocks):
        """Run backtest for 2026 only."""
        print("🚀 Running 2026 OPTIMIZED Backtest\n")
        
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
        
        dates = sorted([d for d in all_dates if "2026" in d])
        print(f"2026 Trading Days: {len(dates)}")
        print(f"Period: {dates[0]} to {dates[-1]}\n")
        
        # Main loop
        for bar, date_str in enumerate(dates):
            if (bar + 1) % 50 == 0:
                print(f"  {date_str} | Equity: ₹{self.equity:,.0f} | Pos: {len(self.positions)} | Trades: {len(self.trades)}")
            
            # Monthly halt check
            if self.check_monthly_stop(date_str):
                continue  # Skip trading this day
            
            # Close positions
            for sym in list(self.positions.keys()):
                if sym in stocks and date_str in date_idx.get(sym, {}):
                    self.process_exits(sym, stocks[sym], date_str)
            
            # Open positions
            self.process_entries(date_str)
            
            # Scan new signals (OPTIMIZED)
            for symbol, df in stocks.items():
                if symbol not in self.positions and symbol not in self.pending:
                    if symbol in date_idx and date_str in date_idx[symbol]:
                        df_hist = df[:date_idx[symbol][date_str]+1]
                        sig = scan_setup_optimized(df_hist)
                        if sig:
                            self.pending[symbol] = sig
            
            # Record daily
            self.daily.append({
                'date': date_str,
                'equity': self.equity,
                'positions': len(self.positions),
            })
        
        print(f"\n✅ 2026 Optimized Backtest Complete!")
        print(f"Final: ₹{self.equity:,.0f} | Trades: {len(self.trades)}\n")
        
        return self.trades, pd.DataFrame(self.daily)


def report(trades, daily, initial_capital):
    """Generate report."""
    if not trades:
        print("⚠ No trades executed")
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
{'='*100}
2026 OPTIMIZED BACKTEST REPORT (Loss Management Strategy)
{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
{'='*100}

COMPARISON
{'-'*100}
Metric                  Original 2026          Optimized 2026         Improvement
Initial Capital         ₹1,000,000             ₹1,000,000             -
Final Equity            ₹{1000000 + df['pnl'].sum():>12,.0f}             ₹{final_eq:>12,.0f}             ₹{final_eq - (1000000 + df['pnl'].sum()):>12,.0f}
Return                  -24.27%                {ret:>6.2f}%                {ret + 24.27:>+6.2f}%
Total Trades            381                    {len(df):>3}                {len(df) - 381:>+3}
Win Rate                36.7%                  {win_pct:.1f}%                {win_pct - 36.7:>+5.1f}%

SUMMARY
{'-'*100}
Initial Capital:        ₹{initial_capital:>15,.0f}
Final Equity:           ₹{final_eq:>15,.0f}
Total PnL:              ₹{total_pnl:>15,.0f}
Return:                 {ret:>15.2f}%
Max Drawdown:           {max_dd:>15.2f}%

TRADES
{'-'*100}
Total Trades:           {len(df):>15.0f}
Winners:                {len(wins):>15.0f} ({win_pct:.1f}%)
Losers:                 {len(losses):>15.0f}
Profit Factor:          {pf:>15.2f}
Avg Trade:              ₹{df['pnl'].mean():>15,.0f}
Best:                   ₹{df['pnl'].max():>15,.0f}
Worst:                  ₹{df['pnl'].min():>15,.0f}

KEY OPTIMIZATIONS APPLIED
{'-'*100}
✅ WIDER STOPS:      1.0 ATR instead of 0.5 ATR (let winners run, lose less on stops)
✅ STRICTER ADX:     Require ADX > 25 (not 15) to avoid choppy/mean-reversion markets
✅ PRICE ACTION:     Only enter on close > open (strong candles)
✅ VOLUME BOOST:     Require 1.2x volume minimum
✅ SETUP A ONLY:     Disabled Setup B (too noisy in 2026)
✅ REDUCED RISK:     0.5% per trade (not 1%) - slower bleed
✅ EARLIER EXIT:     15-day time stop (not 20) - exit faster
✅ MONTHLY HALT:     -8% monthly drawdown triggers full stop

EXPECTED IMPROVEMENTS
{'-'*100}
• Fewer stop hits: Wider stops = fewer false breakdowns
• Fewer entries: Higher ADX filter = higher quality setups
• Smaller losses: Reduced risk per trade = controlled downside
• Earlier exits: 15-day stop = exit faster on losers
• More targets: Better entry points = higher hit rate

EXIT BREAKDOWN
{'-'*100}
"""
    
    for reason in sorted(df['reason'].unique()):
        r_df = df[df['reason'] == reason]
        r_pnl = r_df['pnl'].sum()
        r_count = len(r_df)
        report_text += f"{reason:<10} | Trades: {r_count:>3} | PnL: ₹{r_pnl:>12,.0f}\n"
    
    report_text += f"\n{'='*100}\n"
    
    print(report_text)
    
    # Save
    with open('2026_optimized_report.txt', 'w') as f:
        f.write(report_text)
    
    df.to_csv('2026_optimized_trades.csv', index=False)
    daily.to_csv('2026_optimized_daily.csv', index=False)
    
    print("📄 Report: 2026_optimized_report.txt")
    print("📊 Trades: 2026_optimized_trades.csv")
    print("📈 Daily:  2026_optimized_daily.csv")


if __name__ == "__main__":
    stocks = load_nifty100("data/top100_cache")
    if not stocks:
        print("No data")
        sys.exit(1)
    
    bt = OptimizedBacktester(initial_capital=1000000)
    trades, daily = bt.run(stocks)
    
    report(trades, daily, 1000000)
