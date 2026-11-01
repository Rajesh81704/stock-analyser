#!/usr/bin/env python3
"""
V2.1 REALISTIC FULL-DAY SIMULATION - ₹12K CAPITAL WITH 5X LEVERAGE
Simulates v2.1 strategy with your actual capital and leverage
"""

import pandas as pd
import numpy as np
from datetime import datetime, time
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

# ACTUAL TRADING PARAMETERS
INITIAL_CAPITAL = 12000  # Your actual capital
LEVERAGE = 5.0
EFFECTIVE_CAPITAL = INITIAL_CAPITAL * LEVERAGE  # ₹60,000 trading power
MIN_POSITION_SIZE = 12000  # ₹12K minimum per trade (with leverage)
MAX_TRADES_PER_DAY = 3
OR_MINUTES = 6
PEAK_ENTRY_START = "09:45:00"
PEAK_ENTRY_END = "11:30:00"
SQUARE_OFF_TIME = "15:10:00"
STOP_ATR_MULTIPLIER = 0.45
RISK_REWARD_RATIO = 2.0
ATR_WINDOW = 14
RISK_PER_TRADE = 0.01  # 1% risk = ₹120 max loss per trade

MEGA_CAPS = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "WIPRO", "AXISBANK", "LT", "MARUTI", "BAJAJFINSV"
]


def calculate_atr(df, window=ATR_WINDOW):
    """Calculate ATR for dataframe."""
    df = df.copy()
    df['TR'] = np.maximum(
        df['high'] - df['low'],
        np.maximum(
            abs(df['high'] - df['close'].shift(1)),
            abs(df['low'] - df['close'].shift(1))
        )
    )
    df['ATR'] = df['TR'].rolling(window=window).mean()
    return df


def is_in_peak_window(dt):
    """Check if time is in peak window."""
    t = dt.time()
    peak_start = datetime.strptime(PEAK_ENTRY_START, "%H:%M:%S").time()
    peak_end = datetime.strptime(PEAK_ENTRY_END, "%H:%M:%S").time()
    return peak_start <= t <= peak_end


def simulate_ticker(ticker, df):
    """Simulate v2.1 strategy for a ticker."""
    if len(df) < OR_MINUTES + 10:
        return []
    
    df = df.copy()
    df = calculate_atr(df)
    df['date'] = pd.to_datetime(df['date'])
    
    trades = []
    position = None
    
    # Get opening range
    or_data = df.iloc[:OR_MINUTES]
    or_high = or_data['high'].max()
    or_low = or_data['low'].min()
    or_close = or_data.iloc[-1]['close']
    or_range = or_high - or_low
    
    logger.debug(f"{ticker}: OR High={or_high:.2f}, OR Low={or_low:.2f}, Range={or_range:.2f}")
    
    # Scan for trades
    for idx in range(OR_MINUTES, len(df)):
        row = df.iloc[idx]
        current_time = row['date']
        
        # Exit management
        if position is not None:
            # Check for profit target
            if position['direction'] == 'LONG' and row['high'] >= position['target']:
                trade = {
                    'ticker': ticker,
                    'entry_time': position['entry_time'],
                    'entry_price': position['entry_price'],
                    'exit_time': current_time,
                    'exit_price': position['target'],
                    'quantity': position['quantity'],
                    'direction': 'LONG',
                    'exit_reason': 'Target Hit',
                    'position_size': position['position_size']
                }
                trade['gross_pnl'] = (trade['exit_price'] - trade['entry_price']) * trade['quantity']
                trades.append(trade)
                position = None
            
            # Check for stop loss
            elif position['direction'] == 'LONG' and row['low'] <= position['stop_loss']:
                trade = {
                    'ticker': ticker,
                    'entry_time': position['entry_time'],
                    'entry_price': position['entry_price'],
                    'exit_time': current_time,
                    'exit_price': position['stop_loss'],
                    'quantity': position['quantity'],
                    'direction': 'LONG',
                    'exit_reason': 'Stop Loss Hit',
                    'position_size': position['position_size']
                }
                trade['gross_pnl'] = (trade['exit_price'] - trade['entry_price']) * trade['quantity']
                trades.append(trade)
                position = None
            
            # Similar for SHORT positions
            elif position['direction'] == 'SHORT' and row['low'] <= position['target']:
                trade = {
                    'ticker': ticker,
                    'entry_time': position['entry_time'],
                    'entry_price': position['entry_price'],
                    'exit_time': current_time,
                    'exit_price': position['target'],
                    'quantity': position['quantity'],
                    'direction': 'SHORT',
                    'exit_reason': 'Target Hit',
                    'position_size': position['position_size']
                }
                trade['gross_pnl'] = (position['entry_price'] - trade['exit_price']) * trade['quantity']
                trades.append(trade)
                position = None
            
            elif position['direction'] == 'SHORT' and row['high'] >= position['stop_loss']:
                trade = {
                    'ticker': ticker,
                    'entry_time': position['entry_time'],
                    'entry_price': position['entry_price'],
                    'exit_time': current_time,
                    'exit_price': position['stop_loss'],
                    'quantity': position['quantity'],
                    'direction': 'SHORT',
                    'exit_reason': 'Stop Loss Hit',
                    'position_size': position['position_size']
                }
                trade['gross_pnl'] = (position['entry_price'] - trade['exit_price']) * trade['quantity']
                trades.append(trade)
                position = None
            
            # Force close at square-off time
            square_off = datetime.strptime(SQUARE_OFF_TIME, "%H:%M:%S").time()
            if current_time.time() >= square_off and position is not None:
                exit_price = row['close']
                if position['direction'] == 'LONG':
                    gross_pnl = (exit_price - position['entry_price']) * position['quantity']
                else:
                    gross_pnl = (position['entry_price'] - exit_price) * position['quantity']
                
                trade = {
                    'ticker': ticker,
                    'entry_time': position['entry_time'],
                    'entry_price': position['entry_price'],
                    'exit_time': current_time,
                    'exit_price': exit_price,
                    'quantity': position['quantity'],
                    'direction': position['direction'],
                    'exit_reason': 'Forced Close (15:10)',
                    'position_size': position['position_size'],
                    'gross_pnl': gross_pnl
                }
                trades.append(trade)
                position = None
        
        # Entry logic
        if position is None and is_in_peak_window(current_time):
            atr = row.get('ATR', 0)
            if atr <= 0:
                continue
            
            # Breakout detection
            is_upbreak = row['close'] > or_high and row['close'] > or_close + (or_range * 0.3)
            is_downbreak = row['close'] < or_low and row['close'] < or_close - (or_range * 0.3)
            
            if is_upbreak or is_downbreak:
                entry_price = row['close']
                stop_distance = STOP_ATR_MULTIPLIER * atr
                
                # Position sizing: Use ₹12K per trade with leverage
                quantity = max(1, int(MIN_POSITION_SIZE / entry_price))
                actual_position_size = quantity * entry_price
                
                if is_upbreak:
                    stop_loss = entry_price - stop_distance
                    target = entry_price + (stop_distance * RISK_REWARD_RATIO)
                    direction = 'LONG'
                else:
                    stop_loss = entry_price + stop_distance
                    target = entry_price - (stop_distance * RISK_REWARD_RATIO)
                    direction = 'SHORT'
                
                position = {
                    'entry_time': current_time,
                    'entry_price': entry_price,
                    'stop_loss': stop_loss,
                    'target': target,
                    'quantity': quantity,
                    'position_size': actual_position_size,
                    'direction': direction
                }
                
                logger.debug(f"{ticker} {direction}: Entry={entry_price:.2f}, SL={stop_loss:.2f}, Target={target:.2f}")
    
    # Force close any remaining position
    if position is not None:
        exit_price = df.iloc[-1]['close']
        if position['direction'] == 'LONG':
            gross_pnl = (exit_price - position['entry_price']) * position['quantity']
        else:
            gross_pnl = (position['entry_price'] - exit_price) * position['quantity']
        
        trade = {
            'ticker': ticker,
            'entry_time': position['entry_time'],
            'entry_price': position['entry_price'],
            'exit_time': df.iloc[-1]['date'],
            'exit_price': exit_price,
            'quantity': position['quantity'],
            'direction': position['direction'],
            'exit_reason': 'End of Day',
            'position_size': position['position_size'],
            'gross_pnl': gross_pnl
        }
        trades.append(trade)
    
    return trades


def main():
    logger.info("=" * 90)
    logger.info("V2.1 STRATEGY - FULL DAY SIMULATION (₹12K CAPITAL WITH 5X LEVERAGE)")
    logger.info("=" * 90)
    logger.info(f"\nCapital Configuration:")
    logger.info(f"  Actual Capital:        ₹{INITIAL_CAPITAL:,}")
    logger.info(f"  Leverage:              {LEVERAGE}x")
    logger.info(f"  Effective Trading:     ₹{EFFECTIVE_CAPITAL:,}")
    logger.info(f"  Risk per Trade:        ₹{int(INITIAL_CAPITAL * RISK_PER_TRADE)} (1%)")
    logger.info("")
    
    # Load latest data
    all_trades = []
    trading_date = None
    
    for ticker in MEGA_CAPS:
        try:
            df = pd.read_csv(f"data/{ticker}.csv")
            df['date'] = pd.to_datetime(df['date'])
            
            # Get latest date
            latest_date = df['date'].dt.date.max()
            df_today = df[df['date'].dt.date == latest_date]
            
            if trading_date is None:
                trading_date = latest_date
            
            if len(df_today) > 0:
                trades = simulate_ticker(ticker, df_today)
                all_trades.extend(trades)
                
                if trades:
                    ticker_pnl = sum(t['gross_pnl'] for t in trades)
                    logger.info(f"✓ {ticker:12}: {len(trades)} trade(s), Gross P&L: ₹{ticker_pnl:8.2f}")
        except Exception as e:
            logger.warning(f"✗ {ticker}: {e}")
    
    logger.info("")
    logger.info("=" * 90)
    logger.info("DAILY P&L REPORT - V2.1 STRATEGY (₹12K WITH 5X LEVERAGE)")
    logger.info("=" * 90)
    logger.info(f"Date: {trading_date}\n")
    
    if all_trades:
        # Calculate metrics
        total_trades = len(all_trades)
        winning_trades = len([t for t in all_trades if t['gross_pnl'] > 0])
        losing_trades = total_trades - winning_trades
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        
        gross_pnl = sum(t['gross_pnl'] for t in all_trades)
        
        # Calculate costs (realistic estimate)
        costs_per_trade = 30  # ₹30 per trade (brokerage + STT + GST)
        total_costs = costs_per_trade * total_trades
        net_pnl = gross_pnl - total_costs
        
        logger.info("TRADE SUMMARY")
        logger.info("─" * 90)
        logger.info(f"Total Trades: {total_trades}")
        logger.info(f"Winning Trades: {winning_trades}")
        logger.info(f"Losing Trades: {losing_trades}")
        logger.info(f"Win Rate: {win_rate:.1f}%\n")
        
        logger.info("P&L BREAKDOWN")
        logger.info("─" * 90)
        logger.info(f"Gross P&L: ₹{gross_pnl:,.2f}")
        logger.info(f"Total Costs: ₹{total_costs:,.2f}")
        logger.info(f"Net P&L: ₹{net_pnl:,.2f}\n")
        
        if gross_pnl != 0:
            cost_ratio = (total_costs / abs(gross_pnl)) * 100
        else:
            cost_ratio = 0
        
        logger.info("COST ANALYSIS")
        logger.info("─" * 90)
        logger.info(f"Cost Ratio: {cost_ratio:.2f}% of Gross P&L")
        logger.info(f"Target: < 2.2%")
        logger.info(f"Status: {'✓ PASS' if cost_ratio < 2.2 else '⚠️ REVIEW'}\n")
        
        final_capital = INITIAL_CAPITAL + net_pnl
        daily_return = (net_pnl / INITIAL_CAPITAL * 100)
        
        logger.info("CAPITAL IMPACT (₹12K Base Capital)")
        logger.info("─" * 90)
        logger.info(f"Starting Capital: ₹{INITIAL_CAPITAL:,}")
        logger.info(f"Net P&L: ₹{net_pnl:,.2f}")
        logger.info(f"Ending Capital: ₹{final_capital:,.2f}")
        logger.info(f"Daily Return: {daily_return:.2f}%")
        logger.info(f"Target (0.8%): ₹{INITIAL_CAPITAL * 0.008:,.2f}\n")
        
        logger.info("DAILY TARGET ACHIEVED")
        logger.info("─" * 90)
        daily_target = INITIAL_CAPITAL * 0.008
        if net_pnl >= daily_target:
            logger.info(f"✅ YES - Achieved ₹{net_pnl:,.2f} (Target: ₹{daily_target:,.2f})")
        else:
            shortfall = daily_target - net_pnl
            logger.info(f"⚠️ NO - Got ₹{net_pnl:,.2f}, Shortfall: ₹{shortfall:,.2f}")
        logger.info("")
        
        logger.info("INDIVIDUAL TRADES")
        logger.info("─" * 90)
        for i, trade in enumerate(all_trades, 1):
            logger.info(
                f"Trade {i:2d}: {trade['ticker']:12} {trade['direction']:5} | "
                f"Entry: ₹{trade['entry_price']:8.2f} → Exit: ₹{trade['exit_price']:8.2f} | "
                f"Qty: {trade['quantity']:4} | "
                f"Gross: ₹{trade['gross_pnl']:8.2f} | "
                f"Costs: ₹{costs_per_trade:5} | "
                f"Net: ₹{trade['gross_pnl'] - costs_per_trade:8.2f} | "
                f"{trade['exit_reason']}"
            )
        
        # Save to CSV
        trades_df = pd.DataFrame(all_trades)
        trades_df.to_csv("results/today_trades_12k_5x.csv", index=False)
        logger.info("")
        logger.info(f"✓ Trades saved to: results/today_trades_12k_5x.csv")
    else:
        logger.info("No trades executed today")
    
    logger.info("=" * 90)
    logger.info("END OF REPORT")
    logger.info("=" * 90)


if __name__ == "__main__":
    main()
