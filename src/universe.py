"""
Stock Universe CSV Manager for NIFTY 500
Loads constituent tickers dynamically from CSV files (e.g. data/nifty500.csv).
Exclusively targets Indian NSE cash segment equities.
"""

import os
from typing import List, Optional
import pandas as pd

# Default CSV filepath
CSV_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "nifty500.csv"))


def load_tickers_from_csv(csv_path: str = CSV_PATH) -> List[str]:
    """
    Loads ticker symbols from a CSV file.
    Ensures all symbols carry the Indian NSE suffix (.NS).
    """
    if not os.path.exists(csv_path):
        print(f"[Universe] CSV file not found at '{csv_path}'. Using fallback ticker list.")
        return FALLBACK_NIFTY_500

    try:
        df = pd.read_csv(csv_path)
        col = None
        for candidate in ["Ticker", "ticker", "Symbol", "symbol", "COL1"]:
            if candidate in df.columns:
                col = candidate
                break

        if col is None and not df.empty:
            col = df.columns[0]

        if col and not df.empty:
            raw_tickers = df[col].dropna().astype(str).str.strip().tolist()
            tickers = []
            for t in raw_tickers:
                if not t.endswith(".NS") and not t.endswith(".BO") and not t.startswith("^"):
                    t = f"{t}.NS"
                tickers.append(t)
            return list(dict.fromkeys(tickers))
    except Exception as e:
        print(f"[Universe] Error reading CSV '{csv_path}': {e}")

    return FALLBACK_NIFTY_500


def get_default_universe(custom_csv: Optional[str] = None) -> List[str]:
    """
    Returns tickers for NIFTY 500 universe or custom CSV path.
    """
    if custom_csv and os.path.exists(custom_csv):
        return load_tickers_from_csv(custom_csv)
    return load_tickers_from_csv(CSV_PATH)


FALLBACK_NIFTY_500 = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "ICICIBANK.NS", "INFY.NS",
    "BHARTIARTL.NS", "ITC.NS", "SBIN.NS", "LTIM.NS", "HINDUNILVR.NS",
    "LT.NS", "BAJFINANCE.NS", "AXISBANK.NS", "ADANIENT.NS", "MARUTI.NS",
    "SUNPHARMA.NS", "TATASTEEL.NS", "TATAMOTORS.NS", "NTPC.NS", "KOTAKBANK.NS"
]
