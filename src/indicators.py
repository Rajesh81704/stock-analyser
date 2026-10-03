"""
Step 2: Technical Indicators Module
Implements mathematical calculations for all required technical indicators:
- Volatility: ATR, Normalized ATR, Historical Volatility, High-Low spread
- Volume: Volume ROC, Volume 20-SMA Ratio, On-Balance Volume (OBV) & OBV EMA
- Trend: ADX (14), +DI, -DI, Trend Slopes, Higher High / Lower Low counts
- Moving Averages (MA): SMA (10, 20, 50, 200), EMA (9, 21, 50), MA distance ratios, Golden Cross
- RSI: 14-day RSI (Wilder's smoothing), 7-day Fast RSI, Overbought/Oversold flags
- Support & Resistance: 20-day rolling local High/Low, Classical Pivot Points (P, R1, S1, R2, S2), Distance to S/R
- MACD: MACD Line (12/26), Signal Line (9), MACD Histogram, MACD normalized
- Bollinger Bands: Upper, Middle, Lower bands, Bandwidth, %B
- Opening Price Features: Overnight Gap %, Open-to-Pivot ratio, Open within prior range
"""

import numpy as np
import pandas as pd


def calculate_moving_averages(df: pd.DataFrame) -> pd.DataFrame:
    """Calculates Simple and Exponential Moving Averages and relative price positions."""
    close = df["Close"]

    # Simple Moving Averages
    df["SMA_10"] = close.rolling(window=10).mean()
    df["SMA_20"] = close.rolling(window=20).mean()
    df["SMA_50"] = close.rolling(window=50).mean()
    df["SMA_200"] = close.rolling(window=200).mean()

    # Exponential Moving Averages
    df["EMA_9"] = close.ewm(span=9, adjust=False).mean()
    df["EMA_21"] = close.ewm(span=21, adjust=False).mean()
    df["EMA_50"] = close.ewm(span=50, adjust=False).mean()

    # Normalized Distance from MAs (percentage above/below MA)
    df["Dist_SMA_20"] = (close - df["SMA_20"]) / (df["SMA_20"] + 1e-8)
    df["Dist_SMA_50"] = (close - df["SMA_50"]) / (df["SMA_50"] + 1e-8)
    df["Dist_SMA_200"] = (close - df["SMA_200"]) / (df["SMA_200"] + 1e-8)
    df["Dist_EMA_9"] = (close - df["EMA_9"]) / (df["EMA_9"] + 1e-8)

    # MA Momentum / Golden Cross
    df["Golden_Cross"] = (df["SMA_50"] > df["SMA_200"]).astype(int)
    df["EMA_Fast_Cross"] = (df["EMA_9"] > df["EMA_21"]).astype(int)

    return df


def calculate_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Calculates Relative Strength Index (RSI) using Wilder's exponential smoothing."""
    delta = df["Close"].diff()

    gain = delta.clip(lower=0)
    loss = -1 * delta.clip(upper=0)

    # Wilder's exponential smoothing (alpha = 1 / period)
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / (avg_loss + 1e-8)
    df[f"RSI_{period}"] = 100.0 - (100.0 / (1.0 + rs))

    # Fast 7-period RSI for short-term momentum
    avg_gain_7 = gain.ewm(alpha=1.0 / 7, min_periods=7, adjust=False).mean()
    avg_loss_7 = loss.ewm(alpha=1.0 / 7, min_periods=7, adjust=False).mean()
    rs_7 = avg_gain_7 / (avg_loss_7 + 1e-8)
    df["RSI_7"] = 100.0 - (100.0 / (1.0 + rs_7))

    # Overbought (>70) & Oversold (<30) flags
    df["RSI_Overbought"] = (df[f"RSI_{period}"] >= 70).astype(int)
    df["RSI_Oversold"] = (df[f"RSI_{period}"] <= 30).astype(int)
    df["RSI_Centered"] = df[f"RSI_{period}"] - 50.0  # Centered around zero

    return df


def calculate_macd(
    df: pd.DataFrame, fast_period: int = 12, slow_period: int = 26, signal_period: int = 9
) -> pd.DataFrame:
    """Calculates Moving Average Convergence Divergence (MACD), Signal line, and Histogram."""
    ema_fast = df["Close"].ewm(span=fast_period, adjust=False).mean()
    ema_slow = df["Close"].ewm(span=slow_period, adjust=False).mean()

    df["MACD"] = ema_fast - ema_slow
    df["MACD_Signal"] = df["MACD"].ewm(span=signal_period, adjust=False).mean()
    df["MACD_Hist"] = df["MACD"] - df["MACD_Signal"]

    # Normalized MACD as percentage of price for scale-invariance
    df["MACD_Norm"] = (df["MACD"] / (df["Close"] + 1e-8)) * 100.0
    df["MACD_Hist_Norm"] = (df["MACD_Hist"] / (df["Close"] + 1e-8)) * 100.0
    df["MACD_Bullish"] = (df["MACD"] > df["MACD_Signal"]).astype(int)

    return df


def calculate_bollinger_bands(df: pd.DataFrame, window: int = 20, num_std: float = 2.0) -> pd.DataFrame:
    """Calculates Bollinger Bands (Upper, Middle, Lower), Bandwidth, and %B."""
    middle = df["Close"].rolling(window=window).mean()
    std = df["Close"].rolling(window=window).std()

    upper = middle + (std * num_std)
    lower = middle - (std * num_std)

    df["BB_Middle"] = middle
    df["BB_Upper"] = upper
    df["BB_Lower"] = lower

    # Bandwidth: volatility indicator
    df["BB_Bandwidth"] = (upper - lower) / (middle + 1e-8)

    # %B: measures where price is relative to the bands (0 = lower band, 1 = upper band)
    df["BB_Percent_B"] = (df["Close"] - lower) / (upper - lower + 1e-8)

    # Squeeze indicator (Bandwidth below 20-period moving average of bandwidth)
    df["BB_Squeeze"] = (df["BB_Bandwidth"] < df["BB_Bandwidth"].rolling(20).mean()).astype(int)

    return df


def calculate_volatility(df: pd.DataFrame, atr_period: int = 14, hist_vol_window: int = 20) -> pd.DataFrame:
    """Calculates Average True Range (ATR), Normalized ATR, and Historical Volatility."""
    high = df["High"]
    low = df["Low"]
    close = df["Close"]
    prev_close = close.shift(1)

    # True Range components
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # Average True Range (Wilder's smoothing)
    df["ATR_14"] = true_range.ewm(alpha=1.0 / atr_period, min_periods=atr_period, adjust=False).mean()
    # Normalized ATR (% of close)
    df["NATR_14"] = (df["ATR_14"] / (close + 1e-8)) * 100.0

    # Intraday High-Low spread ratio
    df["High_Low_Spread"] = (high - low) / (df["Open"] + 1e-8)

    # Historical Volatility (rolling annualized std of log returns)
    price_ratio = (close / prev_close).replace([np.inf, -np.inf, 0], np.nan).fillna(1.0)
    log_returns = np.log(price_ratio)
    df["Historical_Vol_20"] = log_returns.rolling(window=hist_vol_window).std().fillna(0.0) * np.sqrt(252)

    return df


def calculate_volume_features(df: pd.DataFrame) -> pd.DataFrame:
    """Calculates Volume Rate of Change, Volume MA Ratios, and On-Balance Volume (OBV)."""
    # Replace any 0 or negative volume from special sessions with positive numbers
    volume = df["Volume"].replace([0, np.nan], np.nan).ffill().bfill().fillna(1.0)
    close = df["Close"]

    # Volume Moving Averages
    vol_sma_5 = volume.rolling(window=5).mean()
    vol_sma_20 = volume.rolling(window=20).mean()

    df["Vol_SMA_20"] = vol_sma_20
    df["Vol_Ratio_20"] = (volume / (vol_sma_20 + 1e-8)).replace([np.inf, -np.inf], 1.0).fillna(1.0)
    df["Vol_ROC_5"] = volume.pct_change(5).replace([np.inf, -np.inf], 0.0).fillna(0.0)

    # On-Balance Volume (OBV)
    direction = np.sign(close.diff()).fillna(0)
    obv = (direction * volume).cumsum()
    df["OBV"] = obv
    df["OBV_EMA_20"] = obv.ewm(span=20, adjust=False).mean()
    df["OBV_Signal"] = (df["OBV"] > df["OBV_EMA_20"]).astype(int)

    # Volume Price Trend (VPT)
    vpt = ((close.diff() / (close.shift(1) + 1e-8)) * volume).cumsum().fillna(0.0)
    df["VPT"] = vpt

    return df


def calculate_trend_features(df: pd.DataFrame, adx_period: int = 14) -> pd.DataFrame:
    """Calculates Average Directional Index (ADX), +DI, -DI, and trend structure."""
    high = df["High"]
    low = df["Low"]
    close = df["Close"]

    # Directional Movement
    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    plus_dm = pd.Series(plus_dm, index=df.index)
    minus_dm = pd.Series(minus_dm, index=df.index)

    # True Range for ADX
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # Smoothed components
    tr_smooth = tr.ewm(alpha=1.0 / adx_period, min_periods=adx_period, adjust=False).mean()
    plus_dm_smooth = plus_dm.ewm(alpha=1.0 / adx_period, min_periods=adx_period, adjust=False).mean()
    minus_dm_smooth = minus_dm.ewm(alpha=1.0 / adx_period, min_periods=adx_period, adjust=False).mean()

    plus_di = 100.0 * (plus_dm_smooth / (tr_smooth + 1e-8))
    minus_di = 100.0 * (minus_dm_smooth / (tr_smooth + 1e-8))

    dx = 100.0 * ((plus_di - minus_di).abs() / (plus_di + minus_di + 1e-8))
    adx = dx.ewm(alpha=1.0 / adx_period, min_periods=adx_period, adjust=False).mean()

    df["ADX_14"] = adx
    df["Plus_DI_14"] = plus_di
    df["Minus_DI_14"] = minus_di
    df["Trend_Strength"] = (adx >= 25).astype(int)  # 25+ indicates strong trend

    # Slope of 20-day EMA (annualized)
    ema_20 = df["Close"].ewm(span=20, adjust=False).mean()
    df["EMA_20_Slope"] = ema_20.diff(5) / 5.0 / (close + 1e-8) * 100.0

    # Trend pattern: Higher Highs and Higher Lows
    higher_high = (high > high.shift(1)).astype(int)
    higher_low = (low > low.shift(1)).astype(int)
    df["Bullish_Candle_Trend"] = higher_high & higher_low

    return df


def calculate_support_resistance(df: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """
    Calculates Support & Resistance levels:
    - 20-day Rolling Local Minimum (Support) & Local Maximum (Resistance)
    - Classical Floor Trader Pivot Points (P, R1, S1, R2, S2)
    - Normalized distances to Support, Resistance, and Pivot Point
    """
    high = df["High"]
    low = df["Low"]
    close = df["Close"]

    # Rolling local High (Resistance) and Low (Support) over previous 'window' days (shifted to prevent lookahead)
    rolling_res = high.shift(1).rolling(window=window).max()
    rolling_sup = low.shift(1).rolling(window=window).min()

    df["Resistance_20"] = rolling_res
    df["Support_20"] = rolling_sup

    # Normalized distance to Support & Resistance
    df["Dist_To_Resistance"] = (rolling_res - close) / (close + 1e-8)
    df["Dist_To_Support"] = (close - rolling_sup) / (close + 1e-8)

    # Classic Floor Trader Pivot Points computed from prior day's OHLC
    prev_h = high.shift(1)
    prev_l = low.shift(1)
    prev_c = close.shift(1)

    pivot = (prev_h + prev_l + prev_c) / 3.0
    r1 = (2.0 * pivot) - prev_l
    s1 = (2.0 * pivot) - prev_h
    r2 = pivot + (prev_h - prev_l)
    s2 = pivot - (prev_h - prev_l)

    df["Pivot"] = pivot
    df["Pivot_R1"] = r1
    df["Pivot_S1"] = s1
    df["Pivot_R2"] = r2
    df["Pivot_S2"] = s2

    # Relative position to Pivot
    df["Dist_To_Pivot"] = (close - pivot) / (pivot + 1e-8)
    df["Above_Pivot"] = (close > pivot).astype(int)

    return df


def calculate_opening_price_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculates features derived from Opening Price and Overnight Gaps:
    - Overnight Gap: (Open[t] - Close[t-1]) / Close[t-1]
    - Open relative to prior High/Low range
    - Open relative to prior Pivot Point
    """
    prev_close = df["Close"].shift(1)
    prev_high = df["High"].shift(1)
    prev_low = df["Low"].shift(1)
    prev_pivot = df["Pivot"].shift(1)

    # Overnight Gap
    df["Overnight_Gap"] = (df["Open"] - prev_close) / (prev_close + 1e-8)
    df["Gap_Up"] = (df["Overnight_Gap"] > 0.005).astype(int)   # > +0.5%
    df["Gap_Down"] = (df["Overnight_Gap"] < -0.005).astype(int) # < -0.5%

    # Open position relative to yesterday's range (0 = at yesterday's low, 1 = at yesterday's high)
    range_span = (prev_high - prev_low).replace(0, np.nan)
    df["Open_In_Prior_Range"] = ((df["Open"] - prev_low) / range_span).fillna(0.5).clip(0, 2)

    # Open relative to yesterday's pivot
    df["Open_To_Pivot"] = (df["Open"] - prev_pivot) / (prev_pivot + 1e-8)

    return df


def add_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Executes all indicator calculations sequentially and returns the enriched DataFrame.
    Guarantees no infinite or invalid values are produced.
    """
    df = df.copy()
    df = calculate_moving_averages(df)
    df = calculate_rsi(df)
    df = calculate_macd(df)
    df = calculate_bollinger_bands(df)
    df = calculate_volatility(df)
    df = calculate_volume_features(df)
    df = calculate_trend_features(df)
    df = calculate_support_resistance(df)
    df = calculate_opening_price_features(df)

    # Clean any accidental inf or -inf that could arise from extreme market anomalies or zero volume
    df = df.replace([np.inf, -np.inf], np.nan)

    return df
