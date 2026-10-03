"""
Step 1: Data Acquisition Module
Fetches 5-year historical daily stock data from Yahoo Finance (yfinance).
Handles data cleansing, validation, missing values, and formatting.
"""

from typing import Optional, Tuple
import numpy as np
import pandas as pd
import yfinance as yf


COMMON_INDIAN_INDICES = {
    "NIFTY": "^NSEI",
    "NIFTY50": "^NSEI",
    "NIFTY 50": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "BANK NIFTY": "^NSEBANK",
    "SENSEX": "^BSESN",
    "BSE SENSEX": "^BSESN",
    "TATAMOTORS": "TMCV.NS",
    "TATAMOTORS.NS": "TMCV.NS",
    "TATA MOTORS": "TMCV.NS",
}


def resolve_ticker(ticker: str) -> str:
    """Resolves common ticker aliases (e.g. NIFTY -> ^NSEI, TATAMOTORS -> TMCV.NS, RELIANCE -> RELIANCE.NS)."""
    t = ticker.strip().upper()
    if t in COMMON_INDIAN_INDICES:
        return COMMON_INDIAN_INDICES[t]
    if not t.startswith("^") and "." not in t:
        # If it's a known US ticker, keep as-is; otherwise assume Indian National Stock Exchange (.NS)
        us_tickers = {"AAPL", "MSFT", "GOOG", "GOOGL", "AMZN", "NVDA", "TSLA", "META", "SPY", "QQQ"}
        if t in us_tickers:
            return t
        return f"{t}.NS"
    return t


def fetch_stock_data(
    ticker: str,
    period: str = "5y",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    auto_adjust: bool = True
) -> pd.DataFrame:
    """
    Downloads historical daily stock data from Yahoo Finance.
    Automatically handles Indian stock symbols (.NS / .BO) and index aliases.

    Parameters:
        ticker (str): Stock ticker symbol (e.g., 'RELIANCE.NS', 'TCS', 'AAPL').
        period (str): Data period if start/end not specified (default: '5y').
        start_date (str): Optional 'YYYY-MM-DD' start date.
        end_date (str): Optional 'YYYY-MM-DD' end date.
        auto_adjust (bool): Whether to auto-adjust OHLC for splits and dividends.

    Returns:
        pd.DataFrame: Cleaned DataFrame with standard columns ['Open', 'High', 'Low', 'Close', 'Volume'].
    """
    original_ticker = ticker.strip().upper()
    resolved_ticker = resolve_ticker(original_ticker)

    # Candidate tickers to attempt: if user didn't specify exchange suffix, test original, then .NS, then .BO
    candidates = [resolved_ticker]
    if "." not in resolved_ticker and not resolved_ticker.startswith("^"):
        candidates.append(f"{resolved_ticker}.NS")  # National Stock Exchange of India
        candidates.append(f"{resolved_ticker}.BO")  # Bombay Stock Exchange

    df = None
    successful_ticker = None

    for cand in candidates:
        try:
            print(f"[DataLoader] Attempting to fetch {period} data for symbol: {cand}...")
            stock = yf.Ticker(cand)
            if start_date and end_date:
                temp_df = stock.history(start=start_date, end=end_date, auto_adjust=auto_adjust)
            else:
                temp_df = stock.history(period=period, auto_adjust=auto_adjust)

            if temp_df is not None and not temp_df.empty and len(temp_df) > 30:
                df = temp_df
                successful_ticker = cand
                break

            # Fallback to yf.download with multi_level_index=False
            temp_df = yf.download(
                cand,
                period=period if not start_date else None,
                start=start_date,
                end=end_date,
                auto_adjust=auto_adjust,
                multi_level_index=False,
                progress=False
            )
            if temp_df is not None and not temp_df.empty and len(temp_df) > 30:
                df = temp_df
                successful_ticker = cand
                break
        except Exception:
            continue

    # If direct attempts failed, try dynamic search discovery on Yahoo Finance directory
    if (df is None or df.empty) and len(original_ticker) >= 3:
        try:
            print(f"[DataLoader] Performing dynamic symbol lookup for: {original_ticker}...")
            search_obj = yf.Search(original_ticker)
            discovered = []
            for q in getattr(search_obj, "quotes", []):
                sym = q.get("symbol", "")
                exch = q.get("exchange", "")
                if sym.endswith(".NS") or sym.endswith(".BO") or exch in ["NSI", "BSE"]:
                    discovered.insert(0, sym)
                elif sym:
                    discovered.append(sym)

            for cand in discovered[:4]:
                temp_df = yf.download(
                    cand,
                    period=period if not start_date else None,
                    start=start_date,
                    end=end_date,
                    auto_adjust=auto_adjust,
                    multi_level_index=False,
                    progress=False
                )
                if temp_df is not None and not temp_df.empty and len(temp_df) > 30:
                    df = temp_df
                    successful_ticker = cand
                    print(f"[DataLoader] Discovered active symbol: {cand}")
                    break
        except Exception as search_err:
            print(f"[DataLoader] Search error: {search_err}")

    if df is None or df.empty:
        raise ValueError(
            f"No price data found for ticker '{original_ticker}'. "
            f"For Indian stocks, try appending .NS (e.g., RELIANCE.NS, TCS.NS, INFY.NS, SBIN.NS) or .BO."
        )

    ticker = successful_ticker

    # Ensure index is datetime and clean timezone
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)

    # Standardize column names
    required_cols = ["Open", "High", "Low", "Close", "Volume"]
    for col in required_cols:
        if col not in df.columns:
            # Case-insensitive check
            matched = [c for c in df.columns if c.lower() == col.lower()]
            if matched:
                df.rename(columns={matched[0]: col}, inplace=True)
            else:
                raise KeyError(f"Missing essential price column '{col}' in downloaded data.")

    # Select only required columns and ensure correct datatypes
    df = df[required_cols].copy()
    for col in ["Open", "High", "Low", "Close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # In Indian/global stocks, replace 0 volume from special sessions with prior volume to prevent division by zero
    vol_series = pd.to_numeric(df["Volume"], errors="coerce").fillna(0).astype(float)
    df["Volume"] = vol_series.replace(0, np.nan).ffill().bfill().fillna(1.0)

    # Drop any rows with NaN in Open, High, Low, Close
    initial_len = len(df)
    df.dropna(subset=["Open", "High", "Low", "Close"], inplace=True)
    # Drop rows where prices are <= 0
    df = df[(df["Open"] > 0) & (df["High"] > 0) & (df["Low"] > 0) & (df["Close"] > 0)]

    # Sort chronologically and drop duplicate dates
    df.sort_index(inplace=True)
    df = df[~df.index.duplicated(keep="last")]

    dropped_count = initial_len - len(df)
    if dropped_count > 0:
        print(f"[DataLoader] Cleaned {dropped_count} invalid/corrupt rows.")

    df.attrs["ticker"] = ticker
    return df


def validate_data_sufficiency(df: pd.DataFrame, min_records: int = 250) -> bool:
    """
    Validates that the dataset has sufficient history for calculating 200-day MAs and training ML models.
    """
    if len(df) < min_records:
        raise ValueError(
            f"Dataset has only {len(df)} records, which is less than the required minimum of {min_records} trading days "
            f"for reliable 200-day moving average and feature generation."
        )
    return True
