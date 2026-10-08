import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta
import pandas as pd

from src.data_loader import fetch_from_kiteconnect, KITE_ACCESS_TOKEN

def main():
    symbol = sys.argv[1].upper() if len(sys.argv) > 1 else "RELIANCE"
    period = sys.argv[2] if len(sys.argv) > 2 else "1m"

    print("=" * 70)
    print(f"  ZERODHA KITE CONNECT HISTORICAL DATA FETCH FOR: {symbol}")
    print(f"  Active Token: {KITE_ACCESS_TOKEN[:10]}...")
    print("=" * 70)

    df = fetch_from_kiteconnect(symbol, period=period)
    if df is not None and not df.empty:
        print(f"\n✅ SUCCESS! Fetched {len(df)} daily candles via Zerodha KiteConnect:\n")
        print(df.tail(10))
        print("=" * 70)
    else:
        print(f"\n❌ Fetch Notice: Token expired or unavailable ({KITE_ACCESS_TOKEN[:10]}...).")
        print("Tip: Click [ 🔑 Login Zerodha ] in the web workstation app to activate a fresh daily session token.")

if __name__ == "__main__":
    main()
