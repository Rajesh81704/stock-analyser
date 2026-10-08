"""
Zerodha Kite Connect Session Token Generator
Pass your API_SECRET and request_token from the browser callback to generate a valid daily ACCESS_TOKEN.
"""

import sys
from kiteconnect import KiteConnect

API_KEY = "zgktuz1hr11f8scf"
REQUEST_TOKEN = "2yZQWkSBocRsKA1Gn82UerTzs6mWg9IK"  # Captured from browser URL bar


def generate_session(api_secret: str, request_token: str = REQUEST_TOKEN):
    print("=" * 65)
    print("      ZERODHA KITE CONNECT SESSION GENERATOR")
    print("=" * 65)
    print(f"API Key:       {API_KEY}")
    print(f"Request Token: {request_token}")
    print("-" * 65)

    kite = KiteConnect(api_key=API_KEY)
    try:
        print("[Kite] Exchanging request_token for daily access_token...")
        data = kite.generate_session(request_token, api_secret=api_secret)
        
        access_token = data.get("access_token")
        public_token = data.get("public_token")
        user_name = data.get("user_name", "User")
        user_id = data.get("user_id", "")

        print("\n" + "=" * 65)
        print("  🎉 SUCCESS! DAILY KITE ACCESS TOKEN GENERATED")
        print("=" * 65)
        print(f"  User:         {user_name} ({user_id})")
        print(f"  ACCESS TOKEN: {access_token}")
        print("=" * 65)
        print("\nTo use this token in your project, set:")
        print(f"  export KITE_ACCESS_TOKEN=\"{access_token}\"")
        print("=" * 65)
        return access_token

    except Exception as e:
        print(f"\n[Session Generation Error] {e}")
        print("Note: Ensure API_SECRET matches your Zerodha app secret and request_token is fresh.")
        return None


if __name__ == "__main__":
    if len(sys.argv) > 1:
        secret = sys.argv[1].strip()
        req_t = sys.argv[2].strip() if len(sys.argv) > 2 else REQUEST_TOKEN
        generate_session(secret, req_t)
    else:
        print("Usage: python src/generate_kite_session.py YOUR_API_SECRET [REQUEST_TOKEN]")
        print("Example: python src/generate_kite_session.py 12345abcdef... 2yZQWkSBocRsKA1Gn82UerTzs6mWg9IK")
