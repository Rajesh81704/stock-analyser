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


import os
from datetime import datetime, timedelta

# Global Zerodha Kite Connect Configuration & Instrument Master Cache
KITE_API_KEY = os.getenv("KITE_API_KEY", "zgktuz1hr11f8scf")
KITE_ACCESS_TOKEN = os.getenv("KITE_ACCESS_TOKEN", "e02iio4s7sc4nptcp8picsdy0i14brq5")
KITE_INSTRUMENTS_CACHE = None

TOKEN_FILE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".kite_token")
if os.path.exists(TOKEN_FILE_PATH):
    try:
        with open(TOKEN_FILE_PATH, "r") as tf:
            cached_token = tf.read().strip()
            if cached_token:
                KITE_ACCESS_TOKEN = cached_token
    except Exception:
        pass


def set_active_kite_access_token(token: str) -> None:
    """Dynamically sets/updates the active Zerodha KiteConnect access token for live API data pulling."""
    global KITE_ACCESS_TOKEN
    KITE_ACCESS_TOKEN = token.strip()
    os.environ["KITE_ACCESS_TOKEN"] = KITE_ACCESS_TOKEN
    try:
        with open(TOKEN_FILE_PATH, "w") as f:
            f.write(KITE_ACCESS_TOKEN)
    except Exception:
        pass
    print(f"[DataLoader] Updated active Zerodha KiteConnect access token: {KITE_ACCESS_TOKEN[:10]}...")


def get_kite_instrument_token(kite, symbol: str, exchange: str = "NSE") -> Optional[int]:
    """Looks up Zerodha's integer instrument_token for a trading symbol (e.g. RELIANCE)."""
    global KITE_INSTRUMENTS_CACHE
    clean_sym = symbol.strip().upper().replace(".NS", "").replace("NSE:", "")
    try:
        if KITE_INSTRUMENTS_CACHE is None:
            KITE_INSTRUMENTS_CACHE = kite.instruments(exchange)
        for inst in KITE_INSTRUMENTS_CACHE:
            if inst.get("tradingsymbol") == clean_sym:
                return inst.get("instrument_token")
    except Exception as e:
        print(f"[DataLoader] Kite instrument lookup warning: {e}")
    return None


def fetch_from_kiteconnect(
    symbol: str,
    period: str = "6mo",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    api_key: Optional[str] = None,
    access_token: Optional[str] = None
) -> Optional[pd.DataFrame]:
    """
    Fetches historical OHLCV data using Zerodha's official KiteConnect API.
    Returns cleaned pandas DataFrame or None if unavailable/expired session.
    """
    key = api_key or KITE_API_KEY
    token_str = access_token or KITE_ACCESS_TOKEN
    if not key or not token_str:
        return None

    try:
        from kiteconnect import KiteConnect
        kite = KiteConnect(api_key=key)
        kite.set_access_token(token_str)

        inst_token = get_kite_instrument_token(kite, symbol)
        if not inst_token:
            return None

        to_dt = datetime.now() if not end_date else datetime.strptime(end_date, "%Y-%m-%d")
        if start_date:
            from_dt = datetime.strptime(start_date, "%Y-%m-%d")
        else:
            days_map = {"1d": 5, "1w": 14, "1m": 35, "3m": 90, "6m": 180, "1y": 365, "5y": 1825}
            days = days_map.get(period.lower().strip(), 180)
            from_dt = to_dt - timedelta(days=days)

        print(f"[DataLoader] Fetching historical OHLCV from Zerodha KiteConnect for {symbol} (Token: {inst_token})...")
        records = kite.historical_data(
            instrument_token=inst_token,
            from_date=from_dt.strftime("%Y-%m-%d"),
            to_date=to_dt.strftime("%Y-%m-%d"),
            interval="day",
            continuous=False,
            oi=False
        )

        if not records:
            return None

        df = pd.DataFrame(records)
        df.rename(columns={
            "date": "Date",
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume"
        }, inplace=True)

        df["Date"] = pd.to_datetime(df["Date"])
        if df["Date"].dt.tz is not None:
            df["Date"] = df["Date"].dt.tz_localize(None)

        df.set_index("Date", inplace=True)
        required = ["Open", "High", "Low", "Close", "Volume"]
        return df[required].copy()

    except Exception as err:
        print(f"[DataLoader] Zerodha KiteConnect notice: {err} (Falling back to Yahoo Finance/SQLite DB)")
        return None


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
    Downloads historical daily stock data using Zerodha KiteConnect as primary engine,
    with automatic fallback to Yahoo Finance & SQLite DB cache.

    Returns:
        pd.DataFrame: Cleaned DataFrame with standard columns ['Open', 'High', 'Low', 'Close', 'Volume'].
    """
    original_ticker = ticker.strip().upper()
    resolved_ticker = resolve_ticker(original_ticker)

    # 0. Primary Fetch: Try Zerodha KiteConnect
    kite_df = fetch_from_kiteconnect(resolved_ticker, period=period, start_date=start_date, end_date=end_date)
    if kite_df is not None and not kite_df.empty and len(kite_df) >= 5:
        print(f"[DataLoader] Successfully loaded {len(kite_df)} bars via Zerodha KiteConnect for {resolved_ticker}")
        kite_df.attrs["ticker"] = resolved_ticker
        try:
            from src.database import save_ohlcv_to_db, load_ohlcv_from_db
            save_ohlcv_to_db(resolved_ticker, kite_df)
            full_df = load_ohlcv_from_db(resolved_ticker)
            if full_df is not None and not full_df.empty:
                full_df.attrs["ticker"] = resolved_ticker
                return full_df
        except Exception:
            pass
        return kite_df

    # Check if stock has trailing OHLCV history stored in SQLite DB
    latest_db_date = None
    try:
        from src.database import get_latest_ohlcv_date_from_db
        latest_db_date = get_latest_ohlcv_date_from_db(resolved_ticker)
    except Exception:
        pass

    YF_PERIOD_MAP = {
        "1d": "5d",
        "1w": "1mo",
        "1m": "1mo",
        "3m": "3mo",
        "6m": "6mo",
        "1y": "1y",
        "5y": "5y",
    }
    fetch_period = YF_PERIOD_MAP.get(period.lower().strip(), period)

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
    Market Cap (₹ Cr), P/E Ratio, P/B Ratio, EPS (₹), Dividend Yield (%), ROE (%), 52W High/Low,
    Quarterly Financials (Revenue, Net Profit, QoQ/YoY Growth) and Annual Financials.
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

        # Extract Quarterly & Annual Income Statement (Revenue, Net Profit, Growth)
        q_data = {}
        a_data = {}
        try:
            q_stmt = getattr(t, "quarterly_income_stmt", None)
            if q_stmt is None or getattr(q_stmt, "empty", True):
                q_stmt = getattr(t, "quarterly_financials", None)

            a_stmt = getattr(t, "income_stmt", None)
            if a_stmt is None or getattr(a_stmt, "empty", True):
                a_stmt = getattr(t, "financials", None)

            if q_stmt is not None and not q_stmt.empty:
                cols = sorted(list(q_stmt.columns))
                rev_row = q_stmt.loc["Total Revenue"] if "Total Revenue" in q_stmt.index else (q_stmt.loc["Operating Revenue"] if "Operating Revenue" in q_stmt.index else None)
                ni_row = q_stmt.loc["Net Income"] if "Net Income" in q_stmt.index else (q_stmt.loc["Net Income Common Stockholders"] if "Net Income Common Stockholders" in q_stmt.index else None)

                if len(cols) >= 1:
                    q_curr = cols[-1]
                    q_prev = cols[-2] if len(cols) >= 2 else None
                    q_yoy = cols[-5] if len(cols) >= 5 else None

                    curr_rev = float(rev_row[q_curr]) / 1e7 if rev_row is not None and q_curr in rev_row and pd.notna(rev_row[q_curr]) else None
                    prev_rev = float(rev_row[q_prev]) / 1e7 if rev_row is not None and q_prev and q_prev in rev_row and pd.notna(rev_row[q_prev]) else None
                    yoy_rev = float(rev_row[q_yoy]) / 1e7 if rev_row is not None and q_yoy and q_yoy in rev_row and pd.notna(rev_row[q_yoy]) else None

                    curr_ni = float(ni_row[q_curr]) / 1e7 if ni_row is not None and q_curr in ni_row and pd.notna(ni_row[q_curr]) else None
                    prev_ni = float(ni_row[q_prev]) / 1e7 if ni_row is not None and q_prev and q_prev in ni_row and pd.notna(ni_row[q_prev]) else None
                    yoy_ni = float(ni_row[q_yoy]) / 1e7 if ni_row is not None and q_yoy and q_yoy in ni_row and pd.notna(ni_row[q_yoy]) else None

                    rev_qoq = round(((curr_rev - prev_rev) / abs(prev_rev)) * 100, 2) if curr_rev and prev_rev else None
                    rev_yoy = round(((curr_rev - yoy_rev) / abs(yoy_rev)) * 100, 2) if curr_rev and yoy_rev else None

                    ni_qoq = round(((curr_ni - prev_ni) / abs(prev_ni)) * 100, 2) if (curr_ni is not None and prev_ni is not None and prev_ni != 0) else None
                    ni_yoy = round(((curr_ni - yoy_ni) / abs(yoy_ni)) * 100, 2) if (curr_ni is not None and yoy_ni is not None and yoy_ni != 0) else None

                    q_data = {
                        "period": str(q_curr.date()) if hasattr(q_curr, "date") else str(q_curr),
                        "revenue_cr": round(curr_rev, 2) if curr_rev is not None else None,
                        "net_profit_cr": round(curr_ni, 2) if curr_ni is not None else None,
                        "rev_growth_qoq_pct": rev_qoq,
                        "rev_growth_yoy_pct": rev_yoy,
                        "profit_growth_qoq_pct": ni_qoq,
                        "profit_growth_yoy_pct": ni_yoy,
                    }

            if a_stmt is not None and not a_stmt.empty:
                cols = sorted(list(a_stmt.columns))
                rev_row = a_stmt.loc["Total Revenue"] if "Total Revenue" in a_stmt.index else (a_stmt.loc["Operating Revenue"] if "Operating Revenue" in a_stmt.index else None)
                ni_row = a_stmt.loc["Net Income"] if "Net Income" in a_stmt.index else (a_stmt.loc["Net Income Common Stockholders"] if "Net Income Common Stockholders" in a_stmt.index else None)

                if len(cols) >= 1:
                    a_curr = cols[-1]
                    a_prev = cols[-2] if len(cols) >= 2 else None

                    curr_rev = float(rev_row[a_curr]) / 1e7 if rev_row is not None and a_curr in rev_row and pd.notna(rev_row[a_curr]) else None
                    prev_rev = float(rev_row[a_prev]) / 1e7 if rev_row is not None and a_prev and a_prev in rev_row and pd.notna(rev_row[a_prev]) else None

                    curr_ni = float(ni_row[a_curr]) / 1e7 if ni_row is not None and a_curr in ni_row and pd.notna(ni_row[a_curr]) else None
                    prev_ni = float(ni_row[a_prev]) / 1e7 if ni_row is not None and a_prev and a_prev in ni_row and pd.notna(ni_row[a_prev]) else None

                    rev_yoy = round(((curr_rev - prev_rev) / abs(prev_rev)) * 100, 2) if curr_rev and prev_rev else None
                    ni_yoy = round(((curr_ni - prev_ni) / abs(prev_ni)) * 100, 2) if (curr_ni is not None and prev_ni is not None and prev_ni != 0) else None

                    a_data = {
                        "year": str(a_curr.date())[:4] if hasattr(a_curr, "date") else str(a_curr)[:4],
                        "revenue_cr": round(curr_rev, 2) if curr_rev is not None else None,
                        "net_profit_cr": round(curr_ni, 2) if curr_ni is not None else None,
                        "rev_growth_yoy_pct": rev_yoy,
                        "profit_growth_yoy_pct": ni_yoy,
                    }
        except Exception as fin_err:
            print(f"[DataLoader] Detailed financials extraction error: {fin_err}")

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
            "quarterly_financials": q_data,
            "annual_financials": a_data,
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
            "quarterly_financials": {},
            "annual_financials": {},
        }


def validate_data_sufficiency(df: pd.DataFrame, min_records: int = 50) -> bool:
    """Validates data length sufficiency."""
    if len(df) < min_records:
        raise ValueError(f"Dataset has only {len(df)} records, required minimum is {min_records}.")
    return True
