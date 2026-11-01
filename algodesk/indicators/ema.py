"""
EMA (Exponential Moving Average) indicator
"""
import pandas as pd
import numpy as np


def ema(series: pd.Series, period: int) -> pd.Series:
    """
    Calculate Exponential Moving Average.
    
    Args:
        series: Price series (typically close prices)
        period: EMA period
    
    Returns:
        pd.Series: EMA values
    """
    if len(series) < period:
        return pd.Series(index=series.index, dtype=float, data=np.nan)
    
    return series.ewm(span=period, adjust=False).mean()


def calc_ema_trend(df: pd.DataFrame, fast: int = 20, slow: int = 50) -> pd.DataFrame:
    """
    Calculate fast and slow EMAs and identify trend direction.
    
    Args:
        df: OHLCV DataFrame with 'close' column
        fast: Fast EMA period
        slow: Slow EMA period
    
    Returns:
        DataFrame with EMA columns added
    """
    df = df.copy()
    df['ema_fast'] = ema(df['close'], fast)
    df['ema_slow'] = ema(df['close'], slow)
    
    # Trend: 1 = uptrend, 0 = no clear, -1 = downtrend
    df['trend'] = 0
    df.loc[df['ema_fast'] > df['ema_slow'], 'trend'] = 1
    df.loc[df['ema_fast'] <= df['ema_slow'], 'trend'] = 0
    
    return df
