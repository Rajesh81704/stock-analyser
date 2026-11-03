"""
52-Week High Breakout Algorithm (Daily, Long-only, NSE, CNC)
Author: Quantitative Design (Upstox Educational Material + Custom Stop Structure)
Strategy Kind: "52wh"

Approach:
- Filter for stocks within 4% of their 52-week high
- Confirm with trend (EMA50 > EMA200), momentum (RSI 55-78, ADX >= 20)
- Entry: breakout above 52-week high with volume confirmation
- Stop: max(structural_low, 2*ATR back) but never closer than 1 ATR
- Exit: failed breakout (2 consec closes below pivot), no follow-through, or trailing EMA20

Portfolio Guards:
- 1% risk per trade, max 15% position size, max 5 total positions
- Max 2/sector, total open risk <= 5% equity
- Daily loss halt at -6%, Nifty trend filter
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict, List
from datetime import datetime, timedelta

from .base import Setup, ExitAction


# Parameters
NEAR_HIGH_PCT = 0.04           # Within 4% of 52W high
LOOKBACK = 252                  # 52-week lookback
EMA_FAST = 20
EMA_MID = 50
EMA_LONG = 200
RSI_LEN = 14
RSI_MIN = 55
RSI_MAX = 78
ADX_MIN = 20
ATR_LEN = 14
VOL_MULT = 1.5                 # vs 20-day avg
MIN_AVG_VOLUME = 200_000        # shares
MIN_TRADED_VALUE = 10_00_00_000 # ₹10 Cr/day
RISK_PCT = 0.01
MAX_POSITION_PCT = 0.15
MAX_POSITIONS = 5
MAX_EXTENSION_ATR = 1.0
GAP_MAX_ATR = 0.5
MAX_STOP_PCT = 0.07
FOLLOW_THROUGH_DAYS = 5
TIME_STOP_DAYS = 30


def calc_ema(s: pd.Series, period: int) -> pd.Series:
    """Calculate exponential moving average."""
    return s.ewm(span=period, adjust=False).mean()


def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Calculate Average True Range."""
    df = df.copy()
    df['tr'] = np.maximum(
        df['high'] - df['low'],
        np.maximum(
            abs(df['high'] - df['close'].shift(1)),
            abs(df['low'] - df['close'].shift(1))
        )
    )
    df['atr'] = df['tr'].rolling(period).mean()
    return df


def calc_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Calculate Relative Strength Index."""
    df = df.copy()
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    return df


def calc_adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Calculate ADX (simplified version)."""
    df = df.copy()
    
    # Plus/Minus DM
    up = df['high'].diff()
    down = -df['low'].diff()
    
    plus_dm = up.where((up > down) & (up > 0), 0)
    minus_dm = down.where((down > up) & (down > 0), 0)
    
    tr = np.maximum(
        df['high'] - df['low'],
        np.maximum(
            abs(df['high'] - df['close'].shift(1)),
            abs(df['low'] - df['close'].shift(1))
        )
    )
    atr = tr.rolling(period).mean()
    
    plus_di = 100 * (plus_dm.rolling(period).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(period).mean() / atr)
    
    di_diff = abs(plus_di - minus_di)
    di_sum = plus_di + minus_di
    dx = 100 * (di_diff / di_sum)
    df['adx'] = dx.rolling(period).mean()
    
    return df


class BreakoutHighStrategy:
    """52-Week High Breakout Algorithm."""
    
    def __init__(self, config: dict = None):
        """Initialize strategy with config."""
        self.config = config or {}
        self.ema_fast = self.config.get('ema_fast', EMA_FAST)
        self.ema_mid = self.config.get('ema_mid', EMA_MID)
        self.ema_long = self.config.get('ema_long', EMA_LONG)
        self.rsi_len = self.config.get('rsi_len', RSI_LEN)
        self.rsi_min = self.config.get('rsi_min', RSI_MIN)
        self.rsi_max = self.config.get('rsi_max', RSI_MAX)
        self.adx_min = self.config.get('adx_min', ADX_MIN)
        self.atr_len = self.config.get('atr_len', ATR_LEN)
        self.near_high_pct = self.config.get('near_high_pct', NEAR_HIGH_PCT)
        self.lookback = self.config.get('lookback', LOOKBACK)
        self.vol_mult = self.config.get('vol_mult', VOL_MULT)
        self.max_extension_atr = self.config.get('max_extension_atr', MAX_EXTENSION_ATR)
        self.gap_max_atr = self.config.get('gap_max_atr', GAP_MAX_ATR)
        self.max_stop_pct = self.config.get('max_stop_pct', MAX_STOP_PCT)
        self.follow_through_days = self.config.get('follow_through_days', FOLLOW_THROUGH_DAYS)
        self.time_stop_days = self.config.get('time_stop_days', TIME_STOP_DAYS)
    
    def scan(self, df: pd.DataFrame, ctx: dict = None) -> Optional[Setup]:
        """
        Stage 1: End-of-day watchlist scan.
        Filter for stocks near 52-week high with proper trend & momentum.
        """
        ctx = ctx or {}
        
        if len(df) < self.lookback + self.ema_long + 5:
            return None
        
        # Calculate indicators
        df = calc_ema(df, self.ema_fast)
        df = calc_ema(df, self.ema_mid)
        df = calc_ema(df, self.ema_long)
        df = calc_atr(df, self.atr_len)
        df = calc_rsi(df, self.rsi_len)
        df = calc_adx(df, self.atr_len)
        
        curr = df.iloc[-1]
        
        # Market regime filter: Nifty must be above EMA50
        nifty_close = ctx.get('nifty_close')
        nifty_ema50 = ctx.get('nifty_ema50')
        if nifty_close and nifty_ema50:
            if nifty_close <= nifty_ema50:
                return None  # Weak market, skip
        
        # Liquidity filter
        avg_vol = df['volume'].tail(20).mean()
        if avg_vol < MIN_AVG_VOLUME:
            return None
        
        traded_value = curr['close'] * curr['volume']
        if traded_value < MIN_TRADED_VALUE:
            return None
        
        # 52-week high pivot
        pivot = df['high'].tail(self.lookback).max()
        
        # Stage 1 Filters
        near_high = (curr['close'] >= pivot * (1 - self.near_high_pct)) and (curr['close'] < pivot)
        
        trend = (curr['close'] > curr['ema_mid']) and (curr['ema_mid'] > curr['ema_long'])
        
        momentum = (self.rsi_min <= curr.get('rsi', 50) <= self.rsi_max) and (curr.get('adx', 0) >= self.adx_min)
        
        # Relative strength (3-month return vs Nifty)
        stock_ret_3m = (curr['close'] / df.iloc[-63]['close'] - 1) if len(df) > 63 else 0
        nifty_ret_3m = ctx.get('nifty_return_3m', 0)
        rel_str = stock_ret_3m > nifty_ret_3m
        
        # Tight base (coiling under high)
        recent_high_low = df['high'].tail(10).max() - df['low'].tail(10).min()
        tight = recent_high_low <= 3 * curr.get('atr', 1)
        
        # Quiet volume (dry-up in base)
        avg_vol_5d = df['volume'].tail(5).mean()
        avg_vol_50d = df['volume'].tail(50).mean()
        quiet = avg_vol_5d < avg_vol_50d
        
        if near_high and trend and momentum and rel_str and tight and quiet:
            trigger = pivot * 1.001
            base_low = df['low'].tail(10).min()
            
            return Setup(
                symbol=ctx.get('symbol', 'UNKNOWN'),
                kind='52wh',
                entry_price=trigger,
                stop_loss=base_low,
                target1=pivot + 2 * curr.get('atr', 1),
                target2=pivot + 4 * curr.get('atr', 1),
                comment=f'52WH near_high={near_high} trend={trend} mom={momentum}',
                metadata={
                    'pivot': pivot,
                    'base_low': base_low,
                    'atr': curr.get('atr', 0),
                    'rsi': curr.get('rsi', 0),
                    'adx': curr.get('adx', 0),
                }
            )
        
        return None
    
    def calculate_entry_stop(self, df: pd.DataFrame, entry_price: float, base_low: float, 
                            pivot: float, atr: float) -> tuple:
        """
        Calculate proper stop loss and position size.
        stop = max(structural, atr_stop) but never closer than 1 ATR.
        """
        structural = base_low * 0.999
        atr_stop = entry_price - 2 * atr
        
        # Take tighter of the two
        stop = max(structural, atr_stop)
        
        # Never closer than 1 ATR
        stop = min(stop, entry_price - 1 * atr)
        
        # Check if stop % is within max
        stop_pct = (entry_price - stop) / entry_price
        if stop_pct > self.max_stop_pct:
            return None, None  # Skip this trade
        
        return entry_price, stop
    
    def manage(self, pos: dict, df: pd.DataFrame, ctx: dict = None) -> Optional[ExitAction]:
        """
        Daily position management.
        
        Exit rules:
        - Stop loss hit
        - Failed breakout (2 consecutive closes below pivot)
        - No follow-through after FOLLOW_THROUGH_DAYS
        - Trailing stop: close < EMA20
        - Time stop after TIME_STOP_DAYS
        """
        ctx = ctx or {}
        
        if len(df) < self.ema_fast + 5:
            return None
        
        # Calculate indicators
        df = calc_ema(df, self.ema_fast)
        df = calc_ema(df, self.ema_mid)
        df = calc_ema(df, self.ema_long)
        df = calc_atr(df, self.atr_len)
        
        curr = df.iloc[-1]
        
        # Stop loss check
        if curr['low'] <= pos['stop']:
            return ExitAction(
                symbol=pos['symbol'],
                action='exit_all',
                reason='stop_hit',
                exit_price=min(curr['open'], pos['stop'])
            )
        
        # Profit taking at 1R: move stop to entry
        pivot = pos.get('metadata', {}).get('pivot', pos['target1'])
        entry = pos['entry']
        unrealized = curr['close'] - entry
        risk = entry - pos['stop']
        
        if unrealized >= risk and not pos.get('trail_started'):
            # Stop moved to entry (breakeven)
            pos['stop'] = entry
            return None
        
        # Partial exit at 2R
        if unrealized >= 2 * risk and not pos.get('partial_exit_done'):
            return ExitAction(
                symbol=pos['symbol'],
                action='exit_partial',
                qty_ratio=0.33,
                reason='profit_taking_2r',
                exit_price=curr['close']
            )
        
        # Failed breakout: 2 consecutive closes below pivot
        if len(df) >= 2:
            curr_close = df.iloc[-1]['close']
            prev_close = df.iloc[-2]['close']
            if curr_close < pivot and prev_close < pivot:
                return ExitAction(
                    symbol=pos['symbol'],
                    action='exit_all',
                    reason='failed_breakout',
                    exit_price=curr['close']
                )
        
        # No follow-through: after FOLLOW_THROUGH_DAYS, if price < entry + 0.5R
        ref_date = pd.to_datetime(ctx.get('current_date', datetime.now())).date()
        days_held = (ref_date - pd.to_datetime(pos['entry_date']).date()).days
        
        if days_held >= self.follow_through_days:
            min_price_needed = entry + 0.5 * risk
            if curr['close'] < min_price_needed:
                return ExitAction(
                    symbol=pos['symbol'],
                    action='exit_all',
                    reason='no_follow_through',
                    exit_price=curr['close']
                )
        
        # Trailing stop: close < EMA20 (after breakeven)
        if pos.get('stop') >= entry and curr['close'] < curr.get('ema_fast', curr['close']):
            return ExitAction(
                symbol=pos['symbol'],
                action='exit_all',
                reason='trail_ema20',
                exit_price=curr['close']
            )
        
        # Time stop
        if days_held > self.time_stop_days:
            return ExitAction(
                symbol=pos['symbol'],
                action='exit_all',
                reason='time_stop',
                exit_price=curr['close']
            )
        
        return None  # Hold
