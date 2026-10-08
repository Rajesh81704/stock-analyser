"""
Technical Indicators Engine for "Bullish Trending Stocks" Screener
Calculates all required technical indicators:
- EMA, SMA (price & volume)
- Ichimoku Kinko Hyo (3,7,14) and (9,26,52)
- Parabolic SAR (0.02, 0.02, 0.2)
- RSI (10 & 14) and StochRSI (10 & 14)
- CCI (10), MFI (10), Williams %R (10)
- ADX, +DI (10), -DI (10)
- Aroon Up & Aroon Down (10)
- Fast & Slow Stochastic %K & %D (5,3)
- MACD (14,5,3)
- Bollinger Bands (20,2)
"""

from typing import Tuple
import numpy as np
import pandas as pd


def add_screener_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Computes all technical indicators required for the Bullish Trending Stocks filter.
    """
    df = df.copy()

    # Standardize column names
    col_map = {c: c.capitalize() for c in df.columns}
    df.rename(columns=col_map, inplace=True)

    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    volume = df["Volume"]
    open_p = df["Open"]

    # 1. Moving Averages
    df["ema_20"] = close.ewm(span=20, adjust=False).mean()
    df["ema_14"] = close.ewm(span=14, adjust=False).mean()
    df["sma_10"] = close.rolling(10).mean()
    df["vol_sma_20"] = volume.rolling(20).mean()

    # 2. Ichimoku (3, 7, 14)
    conv_3 = (high.rolling(3).max() + low.rolling(3).min()) / 2.0
    base_7 = (high.rolling(7).max() + low.rolling(7).min()) / 2.0
    span_a_3_7 = (conv_3 + base_7) / 2.0
    span_b_14 = (high.rolling(14).max() + low.rolling(14).min()) / 2.0
    cloud_bottom_3_7_14 = np.minimum(span_a_3_7, span_b_14)

    df["ichi_conv_3_7_14"] = conv_3
    df["ichi_base_3_7_14"] = base_7
    df["ichi_span_a_3_7_14"] = span_a_3_7
    df["ichi_span_b_3_7_14"] = span_b_14
    df["ichi_cloud_bottom_3_7_14"] = cloud_bottom_3_7_14

    # Ichimoku (9, 26, 52)
    conv_9 = (high.rolling(9).max() + low.rolling(9).min()) / 2.0
    base_26 = (high.rolling(26).max() + low.rolling(26).min()) / 2.0
    span_a_9_26 = (conv_9 + base_26) / 2.0
    span_b_52 = (high.rolling(52).max() + low.rolling(52).min()) / 2.0
    cloud_bottom_9_26_52 = np.minimum(span_a_9_26, span_b_52)

    df["ichi_cloud_bottom_9_26_52"] = cloud_bottom_9_26_52

    # 3. Parabolic SAR (0.02, 0.02, 0.2)
    df["psar"] = calc_psar(df, af_start=0.02, af_inc=0.02, af_max=0.2)

    # 4. RSI (10 and 14)
    df["rsi_10"] = calc_rsi(close, period=10)
    df["rsi_14"] = calc_rsi(close, period=14)

    # 5. StochRSI (10 and 14)
    df["stoch_rsi_10"] = calc_stoch_rsi(df["rsi_10"], period=10)
    df["stoch_rsi_14"] = calc_stoch_rsi(df["rsi_14"], period=14)

    # 6. CCI (10)
    df["cci_10"] = calc_cci(df, period=10)

    # 7. MFI (10)
    df["mfi_10"] = calc_mfi(df, period=10)

    # 8. Williams %R (10)
    df["williams_r_10"] = calc_williams_r(df, period=10)

    # 9. ADX, +DI (10), -DI (10)
    adx_10, plus_di_10, minus_di_10 = calc_adx_di(df, period=10)
    df["adx_10"] = adx_10
    df["plus_di_10"] = plus_di_10
    df["minus_di_10"] = minus_di_10

    # 10. Aroon Up & Aroon Down (10)
    aroon_up, aroon_down = calc_aroon(df, period=10)
    df["aroon_up_10"] = aroon_up
    df["aroon_down_10"] = aroon_down

    # 11. Stochastics Fast & Slow (5, 3)
    fast_k, fast_d, slow_k, slow_d = calc_stochastics(df, k_period=5, d_period=3)
    df["fast_stoch_k_5_3"] = fast_k
    df["fast_stoch_d_5_3"] = fast_d
    df["slow_stoch_k_5_3"] = slow_k
    df["slow_stoch_d_5_3"] = slow_d

    # 12. MACD (14, 5, 3) -> Fast=5, Slow=14, Signal=3
    macd_line, macd_signal, macd_hist = calc_macd(df, fast=5, slow=14, signal=3)
    df["macd_line_14_5_3"] = macd_line
    df["macd_signal_14_5_3"] = macd_signal
    df["macd_hist_14_5_3"] = macd_hist

    # 13. Bollinger Bands (20, 2)
    bb_upper, bb_mid, bb_lower = calc_bollinger(df, period=20, std_dev=2)
    df["bb_upper_20_2"] = bb_upper
    df["bb_middle_20_2"] = bb_mid
    df["bb_lower_20_2"] = bb_lower

    return df


def calc_psar(df: pd.DataFrame, af_start: float = 0.02, af_inc: float = 0.02, af_max: float = 0.2) -> pd.Series:
    high = df["High"].values
    low = df["Low"].values
    close = df["Close"].values
    n = len(df)
    psar = np.zeros(n)
    if n < 2:
        return pd.Series(close, index=df.index)

    bull = True
    af = af_start
    ep = high[0]
    psar[0] = low[0]

    for i in range(1, n):
        prev_psar = psar[i - 1]
        if bull:
            psar_val = prev_psar + af * (ep - prev_psar)
            psar_val = min(psar_val, low[i - 1], low[i - 2] if i >= 2 else low[i - 1])
            if low[i] < psar_val:
                bull = False
                psar_val = ep
                ep = low[i]
                af = af_start
            else:
                if high[i] > ep:
                    ep = high[i]
                    af = min(af + af_inc, af_max)
        else:
            psar_val = prev_psar + af * (ep - prev_psar)
            psar_val = max(psar_val, high[i - 1], high[i - 2] if i >= 2 else high[i - 1])
            if high[i] > psar_val:
                bull = True
                psar_val = ep
                ep = high[i]
                af = af_start
            else:
                if low[i] < ep:
                    ep = low[i]
                    af = min(af + af_inc, af_max)
        psar[i] = psar_val
    return pd.Series(psar, index=df.index)


def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / (loss + 1e-10)
    return 100.0 - (100.0 / (1.0 + rs))


def calc_stoch_rsi(rsi_series: pd.Series, period: int = 14) -> pd.Series:
    min_rsi = rsi_series.rolling(period).min()
    max_rsi = rsi_series.rolling(period).max()
    stoch_rsi = ((rsi_series - min_rsi) / (max_rsi - min_rsi + 1e-10)) * 100.0
    return stoch_rsi


def calc_cci(df: pd.DataFrame, period: int = 10) -> pd.Series:
    tp = (df["High"] + df["Low"] + df["Close"]) / 3.0
    sma_tp = tp.rolling(period).mean()
    mad = tp.rolling(period).apply(lambda x: np.mean(np.abs(x - np.mean(x))), raw=True)
    cci = (tp - sma_tp) / (0.015 * mad + 1e-10)
    return cci


def calc_mfi(df: pd.DataFrame, period: int = 10) -> pd.Series:
    tp = (df["High"] + df["Low"] + df["Close"]) / 3.0
    money_flow = tp * df["Volume"]
    tp_diff = tp.diff()
    pos_flow = money_flow.where(tp_diff > 0, 0).rolling(period).sum()
    neg_flow = money_flow.where(tp_diff < 0, 0).rolling(period).sum()
    mfi_ratio = pos_flow / (neg_flow + 1e-10)
    mfi = 100.0 - (100.0 / (1.0 + mfi_ratio))
    return mfi


def calc_williams_r(df: pd.DataFrame, period: int = 10) -> pd.Series:
    high_max = df["High"].rolling(period).max()
    low_min = df["Low"].rolling(period).min()
    w_r = ((high_max - df["Close"]) / (high_max - low_min + 1e-10)) * -100.0
    return w_r


def calc_adx_di(df: pd.DataFrame, period: int = 10) -> Tuple[pd.Series, pd.Series, pd.Series]:
    high = df["High"]
    low = df["Low"]
    close = df["Close"]

    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = np.maximum(tr1, np.maximum(tr2, tr3))

    tr_smooth = pd.Series(tr, index=df.index).ewm(alpha=1 / period, adjust=False).mean()
    plus_di = 100.0 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / (tr_smooth + 1e-10)
    minus_di = 100.0 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / (tr_smooth + 1e-10)

    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-10)
    adx = dx.ewm(alpha=1 / period, adjust=False).mean()
    return adx, plus_di, minus_di


def calc_aroon(df: pd.DataFrame, period: int = 10) -> Tuple[pd.Series, pd.Series]:
    aroon_up = df["High"].rolling(period + 1).apply(lambda x: float(np.argmax(x)) / period * 100.0, raw=True)
    aroon_down = df["Low"].rolling(period + 1).apply(lambda x: float(np.argmin(x)) / period * 100.0, raw=True)
    return aroon_up, aroon_down


def calc_stochastics(df: pd.DataFrame, k_period: int = 5, d_period: int = 3) -> Tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    low_min = df["Low"].rolling(k_period).min()
    high_max = df["High"].rolling(k_period).max()
    fast_k = ((df["Close"] - low_min) / (high_max - low_min + 1e-10)) * 100.0
    fast_d = fast_k.rolling(d_period).mean()
    slow_k = fast_d
    slow_d = slow_k.rolling(d_period).mean()
    return fast_k, fast_d, slow_k, slow_d


def calc_macd(df: pd.DataFrame, fast: int = 5, slow: int = 14, signal: int = 3) -> Tuple[pd.Series, pd.Series, pd.Series]:
    ema_fast = df["Close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["Close"].ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    macd_signal = macd_line.ewm(span=signal, adjust=False).mean()
    macd_hist = macd_line - macd_signal
    return macd_line, macd_signal, macd_hist


def calc_bollinger(df: pd.DataFrame, period: int = 20, std_dev: int = 2) -> Tuple[pd.Series, pd.Series, pd.Series]:
    mid = df["Close"].rolling(period).mean()
    std = df["Close"].rolling(period).std()
    upper = mid + (std_dev * std)
    lower = mid - (std_dev * std)
    return upper, mid, lower
