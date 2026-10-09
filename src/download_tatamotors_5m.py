"""
5-Year Intraday 5-Minute Candle Downloader for TATAMOTORS
Downloads 5-minute OHLCV candles for TATAMOTORS over the last 5 years
in 60-day date chunks and saves to CSV & JSON.
"""

from datetime import datetime, timedelta
import os
import sys
import pandas as pd
import yfinance as yf
from kiteconnect import KiteConnect

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.data_loader import KITE_API_KEY, KITE_ACCESS_TOKEN, get_kite_instrument_token


def download_5m_candles_kite(symbol: str = "TATAMOTORS", years: int = 5) -> pd.DataFrame:
    """
    Downloads 5-minute candles using Zerodha Kite Connect API in 60-day chunks.
    """
    print(f"[5m Downloader] Attempting Zerodha KiteConnect download for {symbol} ({years} years)...")
    try:
        kite = KiteConnect(api_key=KITE_API_KEY)
        kite.set_access_token(KITE_ACCESS_TOKEN)

        token = get_kite_instrument_token(kite, symbol) or 884737  # TATAMOTORS token

        to_dt = datetime.now()
        start_dt = to_dt - timedelta(days=years * 365)
        
        all_chunks = []
        curr_start = start_dt

        # Zerodha allows up to 60-100 days per 5-minute historical request
        chunk_days = 60
        while curr_start < to_dt:
            curr_end = min(curr_start + timedelta(days=chunk_days), to_dt)
            print(f"  • Fetching chunk: {curr_start.strftime('%Y-%m-%d')} to {curr_end.strftime('%Y-%m-%d')}...")

            try:
                records = kite.historical_data(
                    instrument_token=token,
                    from_date=curr_start.strftime("%Y-%m-%d"),
                    to_date=curr_end.strftime("%Y-%m-%d"),
                    interval="5minute",
                    continuous=False,
                    oi=False
                )
                if records:
                    chunk_df = pd.DataFrame(records)
                    all_chunks.append(chunk_df)
                    print(f"    -> Downloaded {len(records):,} candles.")
            except Exception as chunk_err:
                print(f"    -> Notice on chunk: {chunk_err}")

            curr_start = curr_end + timedelta(days=1)

        if all_chunks:
            df = pd.concat(all_chunks, ignore_index=True)
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
            df.sort_values("Date", inplace=True)
            df.drop_duplicates(subset=["Date"], keep="last", inplace=True)
            return df
    except Exception as e:
        print(f"[5m Downloader] Zerodha KiteConnect error: {e}")

    return pd.DataFrame()


def download_5m_candles_yfinance(symbol: str = "TMCV.NS") -> pd.DataFrame:
    """
    Fallback: Downloads available 5-minute intraday candles via Yahoo Finance.
    Handles Tata Motors ticker alias (TMCV.NS / TATAMOTORS.BO).
    """
    symbols_to_try = [symbol, "TMCV.NS", "TATAMOTORS.BO"]
    for sym in symbols_to_try:
        try:
            print(f"[5m Downloader] Fetching 5-minute candles via Yahoo Finance for {sym}...")
            df = yf.download(
                sym,
                period="60d",
                interval="5m",
                progress=False,
                multi_level_index=False
            )
            if df is not None and not df.empty and len(df) >= 10:
                df.reset_index(inplace=True)
                date_col = "Datetime" if "Datetime" in df.columns else ("Date" if "Date" in df.columns else df.columns[0])
                df.rename(columns={
                    date_col: "Date",
                    "open": "Open",
                    "high": "High",
                    "low": "Low",
                    "close": "Close",
                    "volume": "Volume"
                }, inplace=True)
                df["Date"] = pd.to_datetime(df["Date"])
                if df["Date"].dt.tz is not None:
                    df["Date"] = df["Date"].dt.tz_localize(None)
                required = ["Date", "Open", "High", "Low", "Close", "Volume"]
                return df[required].copy()
        except Exception as e:
            continue
    return pd.DataFrame()


def main():
    print("=" * 70)
    print("  TATAMOTORS 5-MINUTE CANDLE DATA DOWNLOADER & FILE EXPORTER")
    print("=" * 70)

    # 1. Try Zerodha KiteConnect 5-year 5-minute download
    df = download_5m_candles_kite("TATAMOTORS", years=5)

    # 2. Fallback to Yahoo Finance if Kite session is unauthenticated
    if df.empty:
        print("\n[Notice] Zerodha session expired. Using trailing 60-day 5-minute dataset...")
        df = download_5m_candles_yfinance("TATAMOTORS.NS")

    if not df.empty:
        # Prepare output directory
        data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
        os.makedirs(data_dir, exist_ok=True)

        csv_path = os.path.join(data_dir, "tatamotors_5min_candles.csv")
        json_path = os.path.join(data_dir, "tatamotors_5min_candles.json")

        df.to_csv(csv_path, index=False)
        
        # Save JSON representation
        df_json = df.copy()
        df_json["Date"] = df_json["Date"].dt.strftime("%Y-%m-%d %H:%M:%S")
        df_json.to_json(json_path, orient="records", indent=2)

        print("\n" + "=" * 70)
        print(f"  🎉 SUCCESS! SAVED {len(df):,} 5-MINUTE CANDLES FOR TATAMOTORS")
        print("=" * 70)
        print(f"  • CSV File:  {csv_path}")
        print(f"  • JSON File: {json_path}")
        print("=" * 70)
        print("\nFirst 5 Candles:")
        print(df.head())
        print("\nLatest 5 Candles:")
        print(df.tail())
        print("=" * 70)
    else:
        print("\n[Error] Unable to download 5-minute candles.")


if __name__ == "__main__":
    main()
