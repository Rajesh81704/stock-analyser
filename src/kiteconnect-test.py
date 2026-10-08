from kiteconnect import KiteConnect, KiteTicker

API_KEY='zgktuz1hr11f8scf'
ACCESS_TOKEN='e02iio4s7sc4nptcp8picsdy0i14brq5'

kite = KiteConnect(api_key=API_KEY)

print(kite.login_url())