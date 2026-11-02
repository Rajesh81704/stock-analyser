"""
EMA Pullback + ADX Strategy
Long-only, CNC delivery, daily timeframe.

Setup A: Pullback to EMA20 with bullish rejection
Setup B: Breakout from structure with rising ADX
"""
import pandas as pd
import numpy as np
from typing import Optional
from datetime import datetime, timedelta

from .base import Strategy, Setup, ExitAction
from algodesk.indicators.ema import calc_ema_trend
from algodesk.indicators.atr import calc_atr
from algodesk.indicators.adx import calc_adx


def identify_swing_low(df: pd.DataFrame, bars_back: int = 20) -> float:
    """Find the most recent swing low"""
    return df['low'].tail(bars_back).min()


def identify_swing_high(df: pd.DataFrame, bars_back: int = 20) -> float:
    """Find the most recent swing high"""
    return df['high'].tail(bars_back).max()


def is_bullish_candle(row) -> bool:
    """Check if candle is bullish (close >= open)"""
    return row['close'] >= row['open']


def is_hammer(row, atr_val: float) -> bool:
    """
    Hammer pattern: small body, long lower wick.
    Lower wick > 2x body size.
    """
    body = abs(row['close'] - row['open'])
    wick = row['open'] - row['low'] if row['close'] >= row['open'] else row['close'] - row['low']
    
    return wick > 2 * body and body < atr_val * 0.3


def is_bullish_engulfing(df: pd.DataFrame, idx: int) -> bool:
    """Bullish engulfing: current close > prior open and current open < prior close"""
    if idx < 1:
        return False
    
    curr = df.iloc[idx]
    prev = df.iloc[idx - 1]
    
    return (curr['close'] > prev['open'] and 
            curr['open'] < prev['close'] and 
            is_bullish_candle(curr))


class EMAPullbackADXStrategy(Strategy):
    """
    EMA Pullback + ADX swing trading strategy.
    """
    
    def __init__(self, config: dict):
        super().__init__("ema_pullback_adx", config)
        
        # Unpack config
        ind_cfg = config.get('indicators', {})
        self.ema_fast = ind_cfg.get('ema_fast', 20)
        self.ema_slow = ind_cfg.get('ema_slow', 50)
        self.adx_len = ind_cfg.get('adx_len', 14)
        self.adx_min = ind_cfg.get('adx_min', 20)
        self.atr_len = ind_cfg.get('atr_len', 14)
        self.vol_mult = ind_cfg.get('vol_mult', 1.5)
        
        risk_cfg = config.get('risk', {})
        self.min_rr = risk_cfg.get('min_rr', 1.5)
        self.max_stop_atr = risk_cfg.get('max_stop_atr', 2.5)
        
        setup_cfg = config.get('setup', {})
        self.gap_max_atr = setup_cfg.get('gap_max_atr', 0.5)
        
        filt_cfg = config.get('filters', {})
        self.min_traded_value = filt_cfg.get('min_traded_value_20d', 1000000)
        self.circuit_limit = filt_cfg.get('skip_circuit_limit', 0.95)
    
    def scan(self, df: pd.DataFrame, ctx: dict) -> Optional[Setup]:
        """Scan for setups A (pullback) and B (breakout)"""
        
        if len(df) < max(self.ema_slow + 5, self.adx_len + 5):
            return None  # Not enough data
        
        # Filters
        if not self._pass_filters(df, ctx):
            return None
        
        # Market filter: Nifty must be above 50 EMA
        nifty_df = ctx.get('nifty')
        nifty_ema50 = ctx.get('nifty_ema50')
        if nifty_df is not None and nifty_ema50 is not None:
            nifty_close = nifty_df.iloc[-1]['close']
            if nifty_close <= nifty_ema50:
                return None  # Market in downtrend, skip
        
        # Add indicators
        df = calc_ema_trend(df, self.ema_fast, self.ema_slow)
        df = calc_atr(df, self.atr_len)
        df = calc_adx(df, self.adx_len)
        
        curr = df.iloc[-1]
        
        # Trend check
        if not (curr['close'] > curr['ema_fast'] and curr['ema_fast'] > curr['ema_slow']):
            return None  # Not in uptrend
        
        setup = None
        
        # Setup A: Pullback
        if setup is None:
            setup = self._scan_setup_a(df, ctx)
        
        # Setup B: Breakout
        if setup is None:
            setup = self._scan_setup_b(df, ctx)
        
        return setup
    
    def _pass_filters(self, df: pd.DataFrame, ctx: dict) -> bool:
        """Check basic filters"""
        
        # 20-day avg traded value
        df['traded_value'] = df['close'] * df['volume']
        avg_traded_value = df['traded_value'].tail(20).mean()
        if avg_traded_value < self.min_traded_value:
            return False
        
        # Circuit limit check
        curr_close = df.iloc[-1]['close']
        if ctx.get('symbol_data'):
            sym_data = ctx.get('symbol_data')
            upper_circuit = sym_data.get('upper_circuit')
            if upper_circuit and curr_close > upper_circuit * self.circuit_limit:
                return False
        
        return True
    
    def _scan_setup_a(self, df: pd.DataFrame, ctx: dict) -> Optional[Setup]:
        """
        Setup A: Pullback to EMA20 with bullish rejection
        
        - Low <= EMA20 * 1.005
        - Close > EMA20
        - Bullish rejection (hammer or engulfing)
        """
        
        curr = df.iloc[-1]
        ema20 = curr['ema_fast']
        atr = curr['atr']
        
        # Pullback check
        if not (curr['low'] <= ema20 * 1.005 and curr['close'] > ema20):
            return None
        
        # Bullish rejection check
        if not (is_hammer(curr, atr) or is_bullish_engulfing(df, len(df) - 1)):
            return None
        
        # Trigger and stop
        trigger = curr['high'] * 1.001
        swing_low = identify_swing_low(df, 20)
        stop = swing_low * 0.999
        # Risk/reward
        risk = trigger - stop
        if risk <= 0 or risk > self.max_stop_atr * atr:
            return None

        # Target: use prior swing high or ensure minimum 1.5 R:R
        prior_high = identify_swing_high(df.iloc[:-1], 40)
        target1 = max(prior_high, trigger + self.min_rr * risk)
        
        rr = (target1 - trigger) / risk
        if rr < self.min_rr:
            return None
        
        # Volume check (optional for pullback)
        avg_vol = df['volume'].tail(20).mean()
        vol_ratio = curr['volume'] / avg_vol
        
        return Setup(
            symbol=ctx['symbol'],
            date=df.iloc[-1].name if hasattr(df.index, 'name') else str(curr.name),
            kind='A_pullback',
            trigger=trigger,
            stop=stop,
            target1=target1,
            risk=risk,
            rr=rr,
            ema20=ema20,
            ema50=curr['ema_slow'],
            adx=curr.get('adx'),
            atr=atr,
            volume_ratio=vol_ratio,
            meta={
                'pattern': 'pullback_rejection',
                'swing_high': identify_swing_high(df, 20),
                'swing_low': swing_low
            }
        )
    
    def _scan_setup_b(self, df: pd.DataFrame, ctx: dict) -> Optional[Setup]:
        """
        Setup B: Breakout with rising ADX
        
        - Close > EMA50 and close > resistance
        - ADX > 20 and rising vs 5 sessions ago
        - Volume > VOL_MULT * 30-day avg
        """
        
        curr = df.iloc[-1]
        ema50 = curr['ema_slow']
        atr = curr['atr']
        adx = curr.get('adx', 0)
        
        # EMA50 breakout check
        if not (curr['close'] > ema50):
            return None
        
        # ADX check
        if adx < self.adx_min:
            return None
        
        # ADX rising check
        if len(df) < 6:
            return None
        
        adx_5_bars_ago = df.iloc[-6].get('adx', 0)
        if adx <= adx_5_bars_ago:
            return None  # ADX not rising
        
        # Volume check
        avg_vol_30 = df['volume'].tail(30).mean()
        if curr['volume'] < self.vol_mult * avg_vol_30:
            return None
        
        # Resistance check (prior swing high excluding today's bar)
        resistance = identify_swing_high(df.iloc[:-1], 20)
        if curr['close'] <= resistance:
            return None
        
        # Trigger and stop
        trigger = curr['high'] * 1.001
        breakout_base = df.iloc[:-1].tail(10)['low'].min()  # Base low prior to breakout
        stop = breakout_base * 0.999
        
        # Target
        target1 = max(identify_swing_high(df.iloc[:-1], 40), trigger + self.min_rr * (trigger - stop))
        
        # Risk/reward
        risk = trigger - stop
        if risk <= 0 or risk > self.max_stop_atr * atr:
            return None
        
        rr = (target1 - trigger) / risk
        if rr < self.min_rr:
            return None
        
        vol_ratio = curr['volume'] / avg_vol_30
        
        return Setup(
            symbol=ctx['symbol'],
            date=df.iloc[-1].name if hasattr(df.index, 'name') else str(curr.name),
            kind='B_breakout',
            trigger=trigger,
            stop=stop,
            target1=target1,
            risk=risk,
            rr=rr,
            ema20=curr['ema_fast'],
            ema50=ema50,
            adx=adx,
            atr=atr,
            volume_ratio=vol_ratio,
            meta={
                'pattern': 'breakout_rising_adx',
                'resistance': resistance,
                'adx_5_bars_ago': adx_5_bars_ago,
                'adx_current': adx
            }
        )
    
    def manage(self, pos: dict, df: pd.DataFrame, ctx: dict) -> Optional[ExitAction]:
        """
        Daily position management.
        
        - Exit at market if close <= stop
        - Partial exit at target1
        - Exit remainder when close < EMA20
        - ADX deceleration exit for Setup B
        - Time stop after TIME_STOP_DAYS
        """
        
        if len(df) < self.ema_fast + 5:
            return None
        
        df = calc_ema_trend(df, self.ema_fast, self.ema_slow)
        df = calc_atr(df, self.atr_len)
        df = calc_adx(df, self.adx_len)
        
        curr = df.iloc[-1]
        
        # Stop loss check
        if curr['low'] <= pos['stop']:
            return ExitAction(
                symbol=pos['symbol'],
                action='exit_all',
                reason='stop_hit',
                exit_price=min(curr['open'], pos['stop'])  # Gap-down modeled
            )
        
        # Partial exit at target
        if not pos.get('has_partial_exit', False) and curr['high'] >= pos['target1']:
            return ExitAction(
                symbol=pos['symbol'],
                action='exit_partial',
                reason='target_hit',
                exit_price=pos['target1']
            )
        
        # Remainder exit when close < EMA20
        if pos.get('has_partial_exit', False) and curr['close'] < curr['ema_fast']:
            return ExitAction(
                symbol=pos['symbol'],
                action='exit_all',
                reason='remainder_exit',
                exit_price=curr['close']
            )
        
        # ADX deceleration for Setup B
        if pos.get('kind') == 'B_breakout' and len(df) >= 6:
            adx = curr.get('adx', 0)
            adx_5 = df.iloc[-6].get('adx', 0)
            adx_10 = df.iloc[-11].get('adx', 0) if len(df) >= 11 else 0
            
            # ADX peaked and turning down
            if adx < adx_5 and adx_5 > adx_10 and adx < self.adx_min:
                # Check for structure break
                if curr['close'] < df['low'].tail(5).min():
                    return ExitAction(
                        symbol=pos['symbol'],
                        action='exit_all',
                        reason='adx_decel_structure_break',
                        exit_price=curr['close']
                    )
        
        # Time stop
        ref_date = pd.to_datetime(ctx.get('current_date', datetime.now())).date()
        days_held = (ref_date - pd.to_datetime(pos['entry_date']).date()).days
        if days_held > ctx.get('config', {}).get('setup', {}).get('time_stop_days', 20):
            return ExitAction(
                symbol=pos['symbol'],
                action='exit_all',
                reason='time_stop',
                exit_price=curr['close']
            )
        
        return None  # Hold
