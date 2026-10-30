#!/usr/bin/env python3
"""
Fetch 5-minute historical candles from Zerodha Kite API for NIFTY 100 stocks.

Requirements:
1. KITE_API_KEY environment variable (or in .env)
2. KITE_ACCESS_TOKEN environment variable (or in .env)
   - Token must be generated fresh each day via setup_zerodha_auth.py

Usage:
    # First time: Generate login URL
    python setup_zerodha_auth.py --api-key YOUR_KEY --login-url
    
    # After login: Exchange token
    python setup_zerodha_auth.py --api-key YOUR_KEY --api-secret YOUR_SECRET --request-token TOKEN_FROM_REDIRECT
    
    # Fetch data
    python scripts/fetch_zerodha_data.py --days 500 --output-dir data
    
    # Resume previous download (skip existing files)
    python scripts/fetch_zerodha_data.py --days 500 --resume

Output:
    CSV files in data/ directory: data/RELIANCE.NS.csv, data/TCS.NS.csv, etc.
"""

import argparse
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv
import pandas as pd
import logging

# Load environment variables from .env
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)

try:
    from kiteconnect import KiteConnect
except ImportError:
    logger.error("❌ kiteconnect not installed. Run: pip install kiteconnect")
    sys.exit(1)


class ZerodhaDataFetcher:
    """Fetch 5-minute OHLCV data from Zerodha Kite API."""
    
    NIFTY100_SYMBOLS = [
        "RELIANCE", "TCS", "INFY", "HINDUNILVR", "ICICIBANK", "HDFC", "HDFCBANK",
        "BAJAJFINSV", "MARUTI", "NESTLEIND", "LT", "ADANIPORTS", "ASIANPAINT",
        "ADANIGREEN", "WIPRO", "BAJFINANCE", "POWERGRID", "NTPC", "JSWSTEEL",
        "SBILIFE", "HCLTECH", "INDIGO", "COALINDIA", "ONGC", "SUNPHARMA",
        "TATASTEEL", "BHARTIARTL", "ULTRACEMCO", "DIVISLAB", "TECHM",
        "KOTAKBANK", "AXISBANK", "M&M", "GRASIM", "BRITANNIA", "CSCO",
        "HEROMOTOCO", "ITC", "TITAN", "EICHERMOT", "GAIL", "PIDILITIND",
        "CIPLA", "LUPIN", "BIOCON", "SBIN", "ABBOTINDIA", "LICT",
        "SHRIRAMFIN", "KAJARIACER", "UPL", "RAMCOCEM", "PAGEIND",
        "MRF", "TATACONSUM", "TATAMOTORS", "THERMAX", "TORNTPHARM",
        "TRENT", "VAROC", "WHIRLPOOL", "YESBANK", "ACC", "ADANIENSOL",
        "AIAENG", "APLAPOLLO", "AUBANK", "AARTIIND", "AAVAS", "ACE", "ADANIENT",
        "ABCAPITAL", "ABREL", "AEGISLOG", "AETHER", "ALEMBICLTD",
        "AMARAJABAT", "AMBUJACEM", "ANUPAMRAKSHA", "APOLLOHOSPITALS", "APTUS",
        "ARVINDFARM", "ASTRAZEN", "ATGL", "AVANTIFEED", "AVANTI",
        "BAJAJCON", "BALMLAWRIES", "BALAJIMOTOR", "BALRAMCHIN",
        "BANKBARODA", "BANKINDIA", "BASF", "BATA", "BATLIBOI", "BAZIGAR"
    ]
    
    INSTRUMENT_TOKEN_CACHE = {}
    
    def __init__(self, api_key, access_token):
        self.kite = KiteConnect(api_key=api_key)
        self.kite.set_access_token(access_token)
        logger.info("✓ Zerodha Kite API initialized")
    
    def get_instrument_token(self, symbol):
        """Get instrument token for a symbol (cached)."""
        if symbol in self.INSTRUMENT_TOKEN_CACHE:
            return self.INSTRUMENT_TOKEN_CACHE[symbol]
        
        try:
            # Query instruments
            instruments = self.kite.instruments("NSE")
            for inst in instruments:
                if inst['tradingsymbol'] == symbol:
                    token = inst['instrument_token']
                    self.INSTRUMENT_TOKEN_CACHE[symbol] = token
                    return token
            
            logger.warning(f"⚠️ Instrument token not found for {symbol}")
            return None
        
        except Exception as e:
            logger.error(f"Error fetching instrument token: {e}")
            return None
    
    def fetch_historical_5m(self, symbol, start_date, end_date, interval="5minute"):
        """
        Fetch 5-minute historical candles for a symbol.
        
        Kite API has a limit of ~100 days for 5-minute candles, so we fetch in chunks.
        """
        token = self.get_instrument_token(symbol)
        if not token:
            return pd.DataFrame()
        
        candles = []
        current_date = start_date
        
        while current_date < end_date:
            # Fetch 90-day chunk
            chunk_end = min(current_date + timedelta(days=90), end_date)
            
            try:
                logger.info(f"  Fetching {symbol} from {current_date.date()} to {chunk_end.date()}...")
                
                data = self.kite.historical_data(
                    instrument_token=token,
                    from_date=current_date,
                    to_date=chunk_end,
                    interval=interval
                )
                
                candles.extend(data)
                logger.info(f"    ✓ Got {len(data)} candles")
                
                # Rate limiting: Kite API ~2 req/sec recommended
                time.sleep(0.5)
                
            except Exception as e:
                logger.error(f"    ✗ Error: {str(e)[:100]}")
                # Continue with next chunk
            
            current_date = chunk_end
        
        # Convert to DataFrame
        if candles:
            df = pd.DataFrame(candles)
            df['date'] = pd.to_datetime(df['date'])
            df = df.rename(columns={
                'date': 'date',
                'open': 'open',
                'high': 'high',
                'low': 'low',
                'close': 'close',
                'volume': 'volume'
            })
            df = df[['date', 'open', 'high', 'low', 'close', 'volume']]
            return df.sort_values('date').drop_duplicates(subset=['date'])
        
        return pd.DataFrame()
    
    def fetch_all_symbols(self, start_date, end_date, symbols=None, output_dir="data", resume=False):
        """Fetch data for multiple symbols."""
        if symbols is None:
            symbols = self.NIFTY100_SYMBOLS
        
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        successful = 0
        failed = 0
        skipped = 0
        
        for i, symbol in enumerate(symbols, 1):
            symbol_ns = f"{symbol}.NS"
            csv_file = output_path / f"{symbol_ns}.csv"
            
            # Check if already downloaded
            if resume and csv_file.exists():
                logger.info(f"[{i}/{len(symbols)}] {symbol_ns} - already exists, skipping")
                skipped += 1
                continue
            
            try:
                logger.info(f"[{i}/{len(symbols)}] Downloading {symbol_ns}...")
                df = self.fetch_historical_5m(symbol_ns, start_date, end_date)
                
                if not df.empty:
                    df.to_csv(csv_file, index=False)
                    logger.info(f"  ✓ Saved {len(df)} candles to {csv_file}")
                    successful += 1
                else:
                    logger.warning(f"  ⚠️ No data for {symbol_ns}")
                    failed += 1
            
            except Exception as e:
                logger.error(f"  ✗ Error downloading {symbol_ns}: {str(e)[:100]}")
                failed += 1
        
        logger.info("\n" + "="*80)
        logger.info("DOWNLOAD SUMMARY")
        logger.info("="*80)
        logger.info(f"  Successful: {successful}")
        logger.info(f"  Failed: {failed}")
        logger.info(f"  Skipped (resume): {skipped}")
        logger.info(f"  Total: {len(symbols)}")
        logger.info(f"  Output Directory: {output_path.absolute()}")


def main():
    parser = argparse.ArgumentParser(
        description="Download 5-minute OHLCV data from Zerodha Kite API"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=500,
        help="Number of days of history to fetch (default: 500)"
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default=None,
        help="Start date (YYYY-MM-DD). If not provided, calculated as today - days"
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="End date (YYYY-MM-DD). Default: today"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="data",
        help="Output directory for CSV files (default: data)"
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip symbols that already have CSV files"
    )
    parser.add_argument(
        "--symbols",
        type=str,
        help="Path to CSV file with custom ticker list (one symbol per line)"
    )
    
    args = parser.parse_args()
    
    # Load credentials from environment
    api_key = os.getenv('KITE_API_KEY')
    access_token = os.getenv('KITE_ACCESS_TOKEN')
    
    if not api_key or not access_token:
        logger.error("❌ Missing Zerodha credentials!")
        logger.error("   Set KITE_API_KEY and KITE_ACCESS_TOKEN in .env or environment")
        logger.error("\n   First time setup:")
        logger.error("   1. python setup_zerodha_auth.py --api-key YOUR_KEY --login-url")
        logger.error("   2. python setup_zerodha_auth.py --api-key YOUR_KEY --api-secret SECRET --request-token TOKEN")
        sys.exit(1)
    
    # Calculate date range
    end_date = datetime.strptime(args.end_date, "%Y-%m-%d") if args.end_date else datetime.now()
    start_date = datetime.strptime(args.start_date, "%Y-%m-%d") if args.start_date else (end_date - timedelta(days=args.days))
    
    logger.info("="*80)
    logger.info("ZERODHA KITE API - HISTORICAL DATA DOWNLOADER")
    logger.info("="*80)
    logger.info(f"  API Key: {api_key[:10]}...")
    logger.info(f"  Date Range: {start_date.date()} to {end_date.date()}")
    logger.info(f"  Output: {args.output_dir}/")
    logger.info(f"  Resume Mode: {args.resume}")
    
    # Load custom symbols if provided
    symbols = None
    if args.symbols and os.path.exists(args.symbols):
        with open(args.symbols) as f:
            symbols = [line.strip() for line in f if line.strip() and not line.startswith('#')]
        logger.info(f"  Custom Symbols: {len(symbols)} stocks")
    else:
        logger.info(f"  Symbols: NIFTY 100 ({len(ZerodhaDataFetcher.NIFTY100_SYMBOLS)} stocks)")
    
    logger.info("="*80 + "\n")
    
    # Initialize fetcher and download
    try:
        fetcher = ZerodhaDataFetcher(api_key, access_token)
        fetcher.fetch_all_symbols(
            start_date=start_date,
            end_date=end_date,
            symbols=symbols,
            output_dir=args.output_dir,
            resume=args.resume
        )
        
        logger.info("\n✓ Data download complete!")
        logger.info(f"\nNext: Run backtest with")
        logger.info(f"  python scripts/nifty100_4y_backtest.py\n")
    
    except KeyboardInterrupt:
        logger.info("\n⚠️ Download interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"\n✗ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
