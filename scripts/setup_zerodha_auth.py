#!/usr/bin/env python3
"""
Zerodha Kite Connect Authentication Setup

This script helps you:
1. Generate a login URL
2. Exchange auth code for access token
3. Save credentials to .env file

IMPORTANT: Zerodha requires 2FA TOTP. You must manually login and provide the request token.
"""

import argparse
import os
import sys
from pathlib import Path
from kiteconnect import KiteConnect

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

def get_login_url(api_key):
    """Generate Kite login URL."""
    kite = KiteConnect(api_key=api_key)
    login_url = kite.login_url()
    return login_url

def exchange_request_token(api_key, api_secret, request_token):
    """Exchange request token for access token."""
    kite = KiteConnect(api_key=api_key)
    
    try:
        # Generate session with request token
        data = kite.generate_session(request_token, api_secret=api_secret)
        access_token = data['access_token']
        return access_token
    except Exception as e:
        print(f"❌ Error: {e}")
        return None

def save_credentials(api_key, api_secret, access_token):
    """Save credentials to .env file."""
    env_path = Path(".env")
    
    # Read existing .env
    env_vars = {}
    if env_path.exists():
        with open(env_path, 'r') as f:
            for line in f:
                if line.strip() and not line.startswith('#'):
                    if '=' in line:
                        key, val = line.split('=', 1)
                        env_vars[key.strip()] = val.strip()
    
    # Update with new credentials
    env_vars['KITE_API_KEY'] = api_key
    env_vars['KITE_API_SECRET'] = api_secret
    env_vars['KITE_ACCESS_TOKEN'] = access_token
    
    # Write back to .env
    with open(env_path, 'w') as f:
        for key, val in env_vars.items():
            f.write(f"{key}={val}\n")
    
    print(f"✓ Credentials saved to .env")

def main():
    parser = argparse.ArgumentParser(
        description="Zerodha Kite Connect Authentication Setup"
    )
    parser.add_argument(
        "--api-key",
        type=str,
        help="Your Kite API Key (or set KITE_API_KEY env var)"
    )
    parser.add_argument(
        "--api-secret",
        type=str,
        help="Your Kite API Secret (or set KITE_API_SECRET env var)"
    )
    parser.add_argument(
        "--login-url",
        action="store_true",
        help="Generate and print login URL"
    )
    parser.add_argument(
        "--request-token",
        type=str,
        help="Request token from login redirect URL (e.g., 'H12ABC34...')"
    )
    
    args = parser.parse_args()
    
    # Get credentials from args or environment
    api_key = args.api_key or os.getenv('KITE_API_KEY')
    api_secret = args.api_secret or os.getenv('KITE_API_SECRET')
    
    if not api_key:
        print("❌ Error: KITE_API_KEY not provided")
        print("   Usage: python setup_zerodha_auth.py --api-key YOUR_KEY --login-url")
        sys.exit(1)
    
    # Generate login URL
    if args.login_url:
        print("\n" + "="*80)
        print("ZERODHA KITE CONNECT LOGIN")
        print("="*80)
        
        login_url = get_login_url(api_key)
        print("\n1. Open this URL in your browser:")
        print(f"   {login_url}\n")
        print("2. Log in with your Zerodha user ID and password")
        print("3. Complete 2FA authentication (TOTP)\n")
        print("4. After login, your browser will redirect.")
        print("   Copy the 'request_token' parameter from the redirect URL.\n")
        print("5. Then run:")
        print(f"   python setup_zerodha_auth.py --api-key {api_key} --api-secret YOUR_SECRET --request-token REQUEST_TOKEN_HERE\n")
        return
    
    # Exchange request token for access token
    if args.request_token:
        if not api_secret:
            print("❌ Error: KITE_API_SECRET required to exchange token")
            sys.exit(1)
        
        print("\n" + "="*80)
        print("EXCHANGING REQUEST TOKEN FOR ACCESS TOKEN")
        print("="*80 + "\n")
        
        print(f"API Key: {api_key[:10]}...")
        print(f"Request Token: {args.request_token[:20]}...\n")
        
        access_token = exchange_request_token(api_key, api_secret, args.request_token)
        
        if access_token:
            print(f"✓ Access Token Generated!")
            print(f"  Token: {access_token[:20]}...")
            print(f"\n⚠️  This token expires at 6:00 AM IST tomorrow!")
            print(f"⚠️  You'll need to generate a new one each trading day.\n")
            
            # Save to .env
            save_credentials(api_key, api_secret, access_token)
            
            print(f"\n✓ Ready to fetch data!")
            print(f"  Run: python scripts/fetch_zerodha_data.py\n")
        else:
            print("❌ Failed to exchange token. Check your API key, secret, and request token.")
            sys.exit(1)

if __name__ == "__main__":
    main()
