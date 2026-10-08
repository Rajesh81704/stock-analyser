from kiteconnect import KiteConnect, KiteTicker

API_KEY = 'zgktuz1hr11f8scf'
ACCESS_TOKEN = 'e02iio4s7sc4nptcp8picsdy0i14brq5'

kite = KiteConnect(api_key=API_KEY)
kite.set_access_token(ACCESS_TOKEN)

try:
    print("User Profile:")
    print(kite.profile())
    print("\nQuote for NSE:RELIANCE:")
    print(kite.quote(["NSE:RELIANCE"]))
except Exception as e:
    print(f"Kite API Error: {e}")
