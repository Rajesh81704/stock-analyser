"""
Standalone Zerodha Kite Connect SDK Test Script
"""
import sys
from kiteconnect import KiteConnect

API_KEY = "zgktuz1hr11f8scf"
ACCESS_TOKEN = "e02iio4s7sc4nptcp8picsdy0i14brq5"

def test_zerodha_connect():
    print("=" * 65)
    print("      ZERODHA KITE CONNECT SDK INTEGRATION TEST")
    print("=" * 65)

    kite = KiteConnect(api_key=API_KEY)
    
    # 1. Login URL
    login_url = kite.login_url()
    print(f"\n[1] Login URL Generated:")
    print(f"    {login_url}")

    # 2. Set Access Token
    kite.set_access_token(ACCESS_TOKEN)
    print(f"\n[2] Access Token Configured: {ACCESS_TOKEN[:10]}...")

    # 3. Test Instrument Master Fetch
    print("\n[3] Fetching NSE Instrument Master...")
    try:
        instruments = kite.instruments("NSE")
        print(f"    Successfully downloaded {len(instruments):,} instruments from NSE master.")
        
        # Look up RELIANCE token
        reliance_token = next((i["instrument_token"] for i in instruments if i["tradingsymbol"] == "RELIANCE"), None)
        print(f"    Symbol 'RELIANCE' Token -> {reliance_token}")
    except Exception as e:
        print(f"    Instrument Master Notice: {e}")
        reliance_token = 738561

    # 4. Test Profile API
    print("\n[4] Testing kite.profile()...")
    try:
        profile = kite.profile()
        print(f"    Profile Success! User ID: {profile.get('user_id')}, Name: {profile.get('user_name')}")
    except Exception as e:
        print(f"    Profile API Notice: {e}")

    # 5. Test Quote API
    print("\n[5] Testing kite.quote(['NSE:RELIANCE'])...")
    try:
        quote = kite.quote(["NSE:RELIANCE"])
        print(f"    Quote Success! {quote}")
    except Exception as e:
        print(f"    Quote API Notice: {e}")

    # 6. Test Historical Data API
    print(f"\n[6] Testing kite.historical_data({reliance_token}, '2026-10-01', '2026-10-08', 'day')...")
    try:
        hist = kite.historical_data(reliance_token, "2026-10-01", "2026-10-08", "day")
        print(f"    Historical Data Success! Returned {len(hist)} records.")
        for candle in hist:
            print(f"      {candle['date']} -> Open: ₹{candle['open']}, Close: ₹{candle['close']}, Vol: {candle['volume']:,}")
    except Exception as e:
        print(f"    Historical Data API Notice: {e}")

    print("\n" + "=" * 65)

if __name__ == "__main__":
    test_zerodha_connect()
