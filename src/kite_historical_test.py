"""
Zerodha Kite Connect Historical Data Fetcher Test Script
Fetches daily OHLCV historical candle data using Zerodha's KiteConnect API.
"""

from datetime import datetime, timedelta
from typing import Optional
import pandas as pd
from kiteconnect import KiteConnect

API_KEY = "zgktuz1hr11f8scf"
ACCESS_TOKEN = "e02iio4s7sc4nptcp8picsdy0i14brq5"


def get_instrument_token(kite: KiteConnect, symbol: str, exchange: str = "NSE") -> Optional[int]:
    """
    Looks up Zerodha's integer instrument_token for a trading symbol (e.g., RELIANCE).
    """
    clean_sym = symbol.strip().upper().replace(".NS", "").replace("NSE:", "")
    try:
        print(f"[Kite] Fetching instrument master for {exchange}...")
        instruments = kite.instruments(exchange)
        for inst in instruments:
            if inst["tradingsymbol"] == clean_sym:
                print(f"[Kite] Found instrument_token for {clean_sym}: {inst['instrument_token']}")
                return inst["instrument_token"]
    except Exception as err:
        print(f"[Kite] Instrument lookup error: {err}")
    return None


def fetch_kite_historical_data(
    kite: KiteConnect,
    instrument_token: int,
    from_date: str = "2026-01-01",
    to_date: str = "2026-10-08",
    interval: str = "day"
) -> pd.DataFrame:
    """
    Calls kite.historical_data() and converts the returned records into a clean pandas DataFrame.
    Interval options: 'minute', '3minute', '5minute', '15minute', '30minute', '60minute', 'day'.
    """
    print(f"[Kite] Requesting historical data ({interval}) for token {instrument_token} from {from_date} to {to_date}...")
    records = kite.historical_data(
        instrument_token=instrument_token,
        from_date=from_date,
        to_date=to_date,
        interval=interval,
        continuous=False,
        oi=False
    )

    if not records:
        print("[Kite] No historical records returned.")
        return pd.DataFrame()

    df = pd.DataFrame(records)
    # Ensure standardized column names
    df.rename(columns={
        "date": "Date",
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume"
    }, inplace=True)

    df["Date"] = pd.to_datetime(df["Date"])
    df.set_index("Date", inplace=True)
    return df


def main():
    print("=" * 70)
    print("  ZERODHA KITE CONNECT - HISTORICAL DATA FETCH TEST")
    print("=" * 70)

    kite = KiteConnect(api_key=API_KEY)
    kite.set_access_token(ACCESS_TOKEN)

    # Sample stock details
    symbol = "RELIANCE"
    exchange = "NSE"
    
    # 1. Lookup Instrument Token (or use hardcoded token if known, e.g., RELIANCE = 738561)
    inst_token = get_instrument_token(kite, symbol, exchange) or 738561

    # 2. Set date range (e.g. last 180 days)
    to_dt = datetime.now()
    from_dt = to_dt - timedelta(days=180)

    try:
        df = fetch_kite_historical_data(
            kite=kite,
            instrument_token=inst_token,
            from_date=from_dt.strftime("%Y-%m-%d"),
            to_date=to_dt.strftime("%Y-%m-%d"),
            interval="day"
        )

        if not df.empty:
            print("\n" + "=" * 70)
            print(f"  SUCCESSFULLY FETCHED {len(df)} HISTORICAL DAILY CANDLES FOR {symbol}")
            print("=" * 70)
            print(df.tail(10))
            print("=" * 70)
        else:
            print("[Result] DataFrame is empty.")

    except Exception as e:
        print(f"\n[Kite Historical Error] {e}")
        print("Tip: If getting 'Incorrect api_key or access_token', generate a fresh daily ACCESS_TOKEN via login callback.")


if __name__ == "__main__":
    main()
