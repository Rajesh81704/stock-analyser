#!/usr/bin/env python3
"""
CLI Script: Historical Equity Candle Downloader for AlgoDesk.

Downloads 5-minute historical candles from Zerodha Kite Connect API in 90-day chunks,
validates market hours (09:15-15:30 IST), deduplicates, and logs corporate action anomalies.

Supports:
  --login-url          Print manual Kite web login URL
  --request-token STR  Exchange request token for daily access token
  --resume             Skip symbols already downloaded
  --days INT           Days of history to fetch (default: 500)
  --synthetic          Generate synthetic random-walk data for offline smoke-testing
"""

import argparse
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.algodesk.config.settings import settings
from src.algodesk.data.downloader import HistoricalDownloader
from src.algodesk.data.instruments import InstrumentMaster, load_nifty500_universe
from src.algodesk.data.kite_client import KiteClientWrapper, StaticIPRestrictionError
from src.algodesk.data.synthetic import generate_synthetic_dataset
from src.algodesk.db.base import init_db, SessionLocal


def main():
    parser = argparse.ArgumentParser(description="AlgoDesk Historical Data Fetcher & Kite Session Manager.")
    parser.add_argument("--login-url", action="store_true", help="Print Kite Connect web login URL and exit")
    parser.add_argument("--request-token", type=str, help="Exchange login request token for a daily access token")
    parser.add_argument("--days", type=int, default=500, help="Days of history to fetch (default: 500)")
    parser.add_argument("--resume", action="store_true", help="Skip symbols already present in data directory")
    parser.add_argument("--synthetic", action="store_true", help="Generate synthetic data for offline testing")
    parser.add_argument("--symbols-limit", type=int, default=None, help="Limit number of symbols to fetch")
    args = parser.parse_args()

    # 1. Manual Login Flow Helpers
    if args.login_url:
        try:
            url = KiteClientWrapper.get_login_url()
            print("\n" + "=" * 65)
            print("ZERODHA KITE CONNECT MANUAL DAILY LOGIN")
            print("=" * 65)
            print("1. Open the following URL in your browser:")
            print(f"   {url}\n")
            print("2. Authenticate with your Zerodha user ID, password, and TOTP 2FA.")
            print("3. Upon redirect, copy the 'request_token' parameter from your browser address bar.")
            print("4. Run: python scripts/fetch_data.py --request-token <COPIED_TOKEN>\n")
            print("=" * 65)
            return
        except Exception as e:
            print(f"[ERROR] Failed to generate login URL: {e}", file=sys.stderr)
            sys.exit(1)

    if args.request_token:
        try:
            token = KiteClientWrapper.generate_session_token(args.request_token)
            print("\n" + "=" * 65)
            print("KITE ACCESS TOKEN GENERATED SUCCESSFULLY")
            print("=" * 65)
            print(f"KITE_ACCESS_TOKEN={token}")
            print("\nExport to your environment:")
            print(f"export KITE_ACCESS_TOKEN=\"{token}\"\n")
            print("=" * 65)
            return
        except StaticIPRestrictionError as se:
            print(f"\n[STATIC IP RESTRICTION]: {se}\n", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"[ERROR] Session exchange failed: {e}", file=sys.stderr)
            sys.exit(1)

    # 2. Synthetic Data Mode for Offline Testing
    if args.synthetic:
        generate_synthetic_dataset(output_dir=str(settings.data_dir), trading_days=70)
        return

    # 3. Live Historical Download
    if not settings.kite_api_key or not settings.kite_access_token:
        print("\n[ERROR] Missing KITE_API_KEY or KITE_ACCESS_TOKEN environment variables.", file=sys.stderr)
        print("Set your credentials in .env or run with --synthetic for offline testing:\n", file=sys.stderr)
        print("  python scripts/fetch_data.py --synthetic\n", file=sys.stderr)
        sys.exit(1)

    init_db()
    db = SessionLocal()

    try:
        client = KiteClientWrapper()
        # Verify connectivity
        conn = client.check_connection()
        if conn.get("status") != "CONNECTED":
            print(f"[ERROR] Unable to connect to Kite: {conn}", file=sys.stderr)
            sys.exit(1)
        print(f"[KITE AUTH] Connected successfully as user: {conn.get('user_id')} ({conn.get('user_name')})")

        inst_master = InstrumentMaster(db_session=db)
        print("[INSTRUMENTS] Syncing NSE instrument master from Kite...")
        synced = inst_master.sync_from_kite(client, exchange="NSE")
        print(f"[INSTRUMENTS] Synced {synced} new equity instruments.")

        universe = load_nifty500_universe("ind_nifty500list.csv")
        if args.symbols_limit:
            universe = universe[: args.symbols_limit]

        downloader = HistoricalDownloader(
            kite_client=client,
            instrument_master=inst_master,
            db_session=db,
            output_dir=str(settings.data_dir),
        )

        downloader.download_universe(symbols=universe, days=args.days, resume=args.resume)

    except StaticIPRestrictionError as se:
        print(f"\n[CRITICAL VPS STATIC IP ERROR]: {se}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] Historical data download failed: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
