"""
ADX (Average Directional Index) and directional indicators
"""
import pandas as pd
import numpy as np


def dm_directional_movement(df: pd.DataFrame) -> tuple:
    """
    Calculate Plus DM and Minus DM.
    
    Args:
        df: OHLC DataFrame
    
    Returns:
        Tuple of (plus_dm, minus_dm) Series
    """
    df = df.copy()
    
    # Directional movements
    up_move = df['high'].diff()
    down_move = -df['low'].diff()
    
    # Initialize DMs
    plus_dm = pd.Series(0.0, index=df.index)
    minus_dm = pd.Series(0.0, index=df.index)
    
    for i in range(1, len(df)):
        if up_move.iloc[i] > down_move.iloc[i] and up_move.iloc[i] > 0:
            plus_dm.iloc[i] = up_move.iloc[i]
        
        if down_move.iloc[i] > up_move.iloc[i] and down_move.iloc[i] > 0:
            minus_dm.iloc[i] = down_move.iloc[i]
    
    return plus_dm, minus_dm


def di_directional_index(df: pd.DataFrame, period: int = 14) -> tuple:
    """
    Calculate Plus DI and Minus DI.
    
    Args:
        df: OHLC DataFrame
        period: DI period
    
    Returns:
        Tuple of (plus_di, minus_di) Series
    """
    # True Range
    hl = df['high'] - df['low']
    hc = np.abs(df['high'] - df['close'].shift(1))
    lc = np.abs(df['low'] - df['close'].shift(1))
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    
    # DMs
    plus_dm, minus_dm = dm_directional_movement(df)
    
    # Smooth using Wilder's smoothing (like ATR)
    plus_dm_smooth = plus_dm.rolling(window=period).mean()
    minus_dm_smooth = minus_dm.rolling(window=period).mean()
    
    # DI
    plus_di = 100 * (plus_dm_smooth / atr)
    minus_di = 100 * (minus_dm_smooth / atr)
    
    return plus_di.fillna(0), minus_di.fillna(0)


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Calculate ADX (Average Directional Index).
    
    Args:
        df: OHLC DataFrame
        period: ADX period
    
    Returns:
        pd.Series: ADX values
    """
    plus_di, minus_di = di_directional_index(df, period)
    
    # DX
    dx_numerator = np.abs(plus_di - minus_di)
    dx_denominator = plus_di + minus_di
    dx = 100 * (dx_numerator / dx_denominator).fillna(0)
    
    # ADX (smooth DX with Wilder's method)
    adx_val = dx.rolling(window=period).mean()
    
    return adx_val


def calc_adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """
    Add ADX and DI columns to DataFrame.
    
    Args:
        df: OHLCV DataFrame
        period: ADX period
    
    Returns:
        DataFrame with 'adx', 'plus_di', 'minus_di' columns
    """
    df = df.copy()
    df['adx'] = adx(df, period)
    df['plus_di'], df['minus_di'] = di_directional_index(df, period)
    return df
