"""
Data Acquisition & Fundamental Analysis Module
Fetches daily OHLCV price series and comprehensive fundamental parameters from Yahoo Finance.
"""

from typing import Any, Dict, Optional, Tuple
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
    """Resolves common ticker aliases to standard Indian NSE symbols (.NS)."""
    t = ticker.strip().upper()
    if t in COMMON_INDIAN_INDICES:
        return COMMON_INDIAN_INDICES[t]
    if not t.startswith("^") and "." not in t:
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

    Returns:
        pd.DataFrame: Cleaned DataFrame with standard columns ['Open', 'High', 'Low', 'Close', 'Volume'].
    """
    original_ticker = ticker.strip().upper()
    resolved_ticker = resolve_ticker(original_ticker)

    # Check if stock has trailing OHLCV history stored in SQLite DB
    latest_db_date = None
    try:
        from src.database import get_latest_ohlcv_date_from_db
        latest_db_date = get_latest_ohlcv_date_from_db(resolved_ticker)
    except Exception:
        pass

    # If DB already has historical data, top-up with recent 5d bars; otherwise full 5y initial hydration
    fetch_period = "5d" if latest_db_date and not start_date else period

    candidates = [resolved_ticker]
    if "." not in resolved_ticker and not resolved_ticker.startswith("^"):
        candidates.append(f"{resolved_ticker}.NS")
        candidates.append(f"{resolved_ticker}.BO")

    df = None
    successful_ticker = None

    for cand in candidates:
        try:
            print(f"[DataLoader] Top-up fetching ({fetch_period}) for symbol: {cand} (Latest DB date: {latest_db_date or 'First Scan'})...")
            stock = yf.Ticker(cand)
            if start_date and end_date:
                temp_df = stock.history(start=start_date, end=end_date, auto_adjust=auto_adjust)
            else:
                temp_df = stock.history(period=fetch_period, auto_adjust=auto_adjust)

            if temp_df is not None and not temp_df.empty and len(temp_df) >= 5:
                df = temp_df
                successful_ticker = cand
                break

            temp_df = yf.download(
                cand,
                period=period if not start_date else None,
                start=start_date,
                end=end_date,
                auto_adjust=auto_adjust,
                multi_level_index=False,
                progress=False
            )
            if temp_df is not None and not temp_df.empty and len(temp_df) >= 5:
                df = temp_df
                successful_ticker = cand
                break
        except Exception:
            continue

    if (df is None or df.empty) and len(original_ticker) >= 3:
        try:
            print(f"[DataLoader] Performing dynamic lookup for: {original_ticker}...")
            search_obj = yf.Search(original_ticker)
            discovered = []
            for q in getattr(search_obj, "quotes", []):
                sym = q.get("symbol", "")
                if sym.endswith(".NS") or sym.endswith(".BO"):
                    discovered.insert(0, sym)

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
                if temp_df is not None and not temp_df.empty and len(temp_df) >= 5:
                    df = temp_df
                    successful_ticker = cand
                    break
        except Exception as search_err:
            print(f"[DataLoader] Search error: {search_err}")

    if df is None or df.empty:
        try:
            from src.database import load_ohlcv_from_db
            cached_df = load_ohlcv_from_db(resolved_ticker)
            if cached_df is not None and not cached_df.empty:
                print(f"[DataLoader] Using cached SQLite OHLCV data for: {resolved_ticker}")
                df = cached_df
                successful_ticker = resolved_ticker
        except Exception as cache_err:
            print(f"[DataLoader] SQLite fallback check failed: {cache_err}")

    if df is None or df.empty:
        raise ValueError(
            f"No price data found for ticker '{original_ticker}'. "
            f"Ensure symbol is listed on National Stock Exchange of India (NSE)."
        )

    ticker = successful_ticker

    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)

    required_cols = ["Open", "High", "Low", "Close", "Volume"]
    for col in required_cols:
        if col not in df.columns:
            matched = [c for c in df.columns if c.lower() == col.lower()]
            if matched:
                df.rename(columns={matched[0]: col}, inplace=True)
            else:
                raise KeyError(f"Missing essential price column '{col}' in downloaded data.")

    df = df[required_cols].copy()
    for col in ["Open", "High", "Low", "Close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    vol_series = pd.to_numeric(df["Volume"], errors="coerce").fillna(0).astype(float)
    df["Volume"] = vol_series.replace(0, np.nan).ffill().bfill().fillna(1.0)

    initial_len = len(df)
    df.dropna(subset=["Open", "High", "Low", "Close"], inplace=True)
    df = df[(df["Open"] > 0) & (df["High"] > 0) & (df["Low"] > 0) & (df["Close"] > 0)]

    df.sort_index(inplace=True)
    df = df[~df.index.duplicated(keep="last")]

    df.attrs["ticker"] = ticker

    # Persist topup OHLCV bars into SQLite Database & load full accumulated trailing series
    try:
        from src.database import save_ohlcv_to_db, load_ohlcv_from_db
        save_ohlcv_to_db(ticker, df)
        full_df = load_ohlcv_from_db(ticker)
        if full_df is not None and not full_df.empty and len(full_df) >= len(df):
            full_df.attrs["ticker"] = ticker
            return full_df
    except Exception as db_err:
        print(f"[DataLoader] Warning: Failed to sync OHLCV with SQLite DB: {db_err}")

    return df


def fetch_stock_fundamentals(ticker: str) -> Dict[str, Any]:
    """
    Fetches fundamental financial parameters from Yahoo Finance:
    Market Cap (₹ Cr), P/E Ratio, P/B Ratio, EPS (₹), Dividend Yield (%), ROE (%), 52W High/Low.
    """
    resolved = resolve_ticker(ticker)
    try:
        t = yf.Ticker(resolved)
        info = getattr(t, "info", {}) or {}

        market_cap_raw = info.get("marketCap")
        market_cap_cr = round(market_cap_raw / 1e7, 2) if market_cap_raw else None

        pe = info.get("trailingPE") or info.get("forwardPE")
        pe_ratio = round(float(pe), 2) if pe else None

        pb = info.get("priceToBook")
        pb_ratio = round(float(pb), 2) if pb else None

        eps_raw = info.get("trailingEps")
        eps = round(float(eps_raw), 2) if eps_raw else None

        div_raw = info.get("dividendYield")
        div_yield = round(float(div_raw) * 100.0, 2) if div_raw else None

        roe_raw = info.get("returnOnEquity")
        roe = round(float(roe_raw) * 100.0, 2) if roe_raw else None

        high_52w = info.get("fiftyTwoWeekHigh")
        low_52w = info.get("fiftyTwoWeekLow")

        return {
            "ticker": resolved,
            "company_name": info.get("longName") or info.get("shortName") or resolved.replace(".NS", ""),
            "sector": info.get("sector") or "N/A",
            "industry": info.get("industry") or "N/A",
            "market_cap_cr": market_cap_cr,
            "pe_ratio": pe_ratio,
            "pb_ratio": pb_ratio,
            "eps": eps,
            "dividend_yield": div_yield,
            "roe": roe,
            "fifty_two_week_high": round(float(high_52w), 2) if high_52w else None,
            "fifty_two_week_low": round(float(low_52w), 2) if low_52w else None,
        }
    except Exception as e:
        print(f"[DataLoader] Fundamental fetch error for {ticker}: {e}")
        return {
            "ticker": resolved,
            "company_name": resolved.replace(".NS", ""),
            "sector": "N/A",
            "industry": "N/A",
            "market_cap_cr": None,
            "pe_ratio": None,
            "pb_ratio": None,
            "eps": None,
            "dividend_yield": None,
            "roe": None,
            "fifty_two_week_high": None,
            "fifty_two_week_low": None,
        }


def validate_data_sufficiency(df: pd.DataFrame, min_records: int = 50) -> bool:
    """Validates data length sufficiency."""
    if len(df) < min_records:
        raise ValueError(f"Dataset has only {len(df)} records, required minimum is {min_records}.")
    return True
