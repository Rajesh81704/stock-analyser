"""
NIFTY 500 Universe Manager
Ingests official NIFTY 500 constituents directly from NSE Archives,
formats symbols for Yahoo Finance (.NS), applies corporate restructuring mappings,
and maintains offline fallback storage.
"""

import io
import os
import urllib.request
from typing import Dict, List, Optional
import pandas as pd

NSE_NIFTY500_URL = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
LOCAL_CSV_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "nifty500_constituents.csv"))

# Corporate restructuring & demerger mapping overrides for Yahoo Finance
KNOWN_OVERRIDE_MAPPINGS = {
    "TATAMOTORS": "TMCV.NS",
    "TATAMTRDVR": "TMCV.NS",
    "M&M": "M&M.NS",
    "BAJAJ-AUTO": "BAJAJ-AUTO.NS",
    "MCDOWELL-N": "UNITDSPR.NS",
}


def fetch_nifty500_constituents(save_local_backup: bool = True) -> pd.DataFrame:
    """
    Fetches the official NIFTY 500 constituents list from NSE India.
    Falls back to local cached copy if offline or blocked.

    Returns:
        pd.DataFrame: Cleaned DataFrame with columns ['Ticker', 'Company_Name', 'Industry', 'Symbol'].
    """
    df = None
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    try:
        print("[Universe] Fetching official NIFTY 500 constituents from NSE Archives...")
        req = urllib.request.Request(NSE_NIFTY500_URL, headers=headers)
        with urllib.request.urlopen(req, timeout=12) as resp:
            content = resp.read()
            df = pd.read_csv(io.BytesIO(content))
            print(f"[Universe] Successfully downloaded {len(df)} constituents from NSE.")

        if save_local_backup and df is not None and not df.empty:
            os.makedirs(os.path.dirname(LOCAL_CSV_PATH), exist_ok=True)
            df.to_csv(LOCAL_CSV_PATH, index=False)
            print(f"[Universe] Cached NIFTY 500 list to {LOCAL_CSV_PATH}")

    except Exception as e:
        print(f"[Universe] NSE Archives request failed ({e}). Checking local backup...")
        if os.path.exists(LOCAL_CSV_PATH):
            df = pd.read_csv(LOCAL_CSV_PATH)
            print(f"[Universe] Loaded {len(df)} constituents from local backup.")
        else:
            raise RuntimeError(f"Could not load NIFTY 500 constituents: {e}")

    # Standardize columns
    col_map = {}
    for c in df.columns:
        c_clean = c.strip().lower()
        if "symbol" in c_clean:
            col_map[c] = "Symbol"
        elif "company" in c_clean:
            col_map[c] = "Company_Name"
        elif "industry" in c_clean:
            col_map[c] = "Industry"

    df.rename(columns=col_map, inplace=True)
    df = df[["Symbol", "Company_Name", "Industry"]].dropna(subset=["Symbol"]).copy()

    # Apply Yahoo Finance ticker formatting (.NS) & overrides
    def format_ticker(symbol: str) -> str:
        s = str(symbol).strip().upper()
        if s in KNOWN_OVERRIDE_MAPPINGS:
            return KNOWN_OVERRIDE_MAPPINGS[s]
        return f"{s}.NS"

    df["Ticker"] = df["Symbol"].apply(format_ticker)
    df = df[~df["Ticker"].duplicated(keep="first")]

    print(f"[Universe] NIFTY 500 constituents ready: {len(df)} unique tickers.")
    return df


def get_nifty500_tickers_list() -> List[str]:
    """Returns list of formatted Yahoo Finance tickers (e.g. ['RELIANCE.NS', 'TCS.NS', ...])."""
    df = fetch_nifty500_constituents()
    return df["Ticker"].tolist()


if __name__ == "__main__":
    df_uni = fetch_nifty500_constituents()
    print("Sample Tickers:", df_uni[["Ticker", "Company_Name", "Industry"]].head(10))
