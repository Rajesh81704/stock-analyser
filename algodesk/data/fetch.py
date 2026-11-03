"""
Data fetching module for live and historical stock data
Supports both yfinance and local CSV/Parquet data
"""

import pandas as pd
import yfinance as yf
from pathlib import Path
from typing import Optional, Dict
import logging

logger = logging.getLogger(__name__)


def fetch_stock_data(
    symbol: str,
    start_date: str = '2024-01-01',
    end_date: Optional[str] = None,
    interval: str = '1d'
) -> Optional[pd.DataFrame]:
    """
    Fetch stock data from yfinance or local cache
    
    Args:
        symbol: Stock symbol (e.g., 'INFY')
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD), defaults to today
        interval: '1d', '1h', '5m', etc.
    
    Returns:
        DataFrame with OHLCV data or None if fetch fails
    """
    try:
        # Try local CSV first
        local_csv = Path(f"data/{symbol}.csv")
        if local_csv.exists():
            try:
                df = pd.read_csv(local_csv, index_col=0, parse_dates=True)
                if len(df) > 0:
                    logger.debug(f"Loaded {symbol} from local CSV ({len(df)} rows)")
                    return df.sort_index()
            except Exception as e:
                logger.debug(f"Failed to load local CSV for {symbol}: {e}")
        
        # Try local parquet
        local_parquet = Path(f"data/{symbol}.parquet")
        if local_parquet.exists():
            try:
                df = pd.read_parquet(local_parquet)
                if len(df) > 0:
                    logger.debug(f"Loaded {symbol} from local Parquet ({len(df)} rows)")
                    return df.sort_index()
            except Exception as e:
                logger.debug(f"Failed to load local Parquet for {symbol}: {e}")
        
        # Fallback to yfinance
        ticker = yf.Ticker(f"{symbol}.NS")  # NSE suffix for India stocks
        df = ticker.history(start=start_date, end=end_date, interval=interval)
        
        if len(df) > 0:
            logger.debug(f"Fetched {symbol} from yfinance ({len(df)} rows)")
            return df
        
        logger.warning(f"No data available for {symbol}")
        return None
        
    except Exception as e:
        logger.error(f"Error fetching {symbol}: {e}")
        return None


def fetch_nifty_data(
    start_date: str = '2024-01-01',
    end_date: Optional[str] = None,
    interval: str = '1d'
) -> Optional[pd.DataFrame]:
    """Fetch NIFTY 50 index data for market regime checks"""
    try:
        df = fetch_stock_data('^NSEI', start_date=start_date, end_date=end_date, interval=interval)
        return df
    except Exception as e:
        logger.error(f"Error fetching NIFTY data: {e}")
        return None


def save_to_local(df: pd.DataFrame, symbol: str, format: str = 'csv'):
    """Save data to local CSV or Parquet"""
    try:
        if format == 'csv':
            df.to_csv(f"data/{symbol}.csv")
        elif format == 'parquet':
            df.to_parquet(f"data/{symbol}.parquet")
        logger.debug(f"Saved {symbol} to {format}")
    except Exception as e:
        logger.error(f"Error saving {symbol}: {e}")
