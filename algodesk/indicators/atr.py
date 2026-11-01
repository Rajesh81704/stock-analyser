"""
ATR (Average True Range) indicator
"""
import pandas as pd
import numpy as np


def true_range(df: pd.DataFrame) -> pd.Series:
    """
    Calculate True Range.
    
    Args:
        df: OHLC DataFrame
    
    Returns:
        pd.Series: True Range values
    """
    df = df.copy()
    
    # TR = max(high - low, abs(high - prev_close), abs(low - prev_close))
    hl = df['high'] - df['low']
    hc = np.abs(df['high'] - df['close'].shift(1))
    lc = np.abs(df['low'] - df['close'].shift(1))
    
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Calculate Average True Range.
    
    Args:
        df: OHLC DataFrame
        period: ATR period
    
    Returns:
        pd.Series: ATR values
    """
    tr = true_range(df)
    return tr.rolling(window=period).mean()


def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """
    Add ATR column to DataFrame.
    
    Args:
        df: OHLCV DataFrame
        period: ATR period
    
    Returns:
        DataFrame with 'atr' column
    """
    df = df.copy()
    df['atr'] = atr(df, period)
    return df
