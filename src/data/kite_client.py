"""
Kite Connect Data Fetcher & Session Manager.

Handles:
- KiteConnect authentication via environment variables
- Login URL generator and request token exchange
- Chunked 5-minute historical data downloads (90-day chunks)
- Rate limiting (>= 0.5s sleep) and exponential backoff retry
"""

import os
import sys
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import pandas as pd

try:
    from kiteconnect import KiteConnect
except ImportError:
    KiteConnect = None

logger = logging.getLogger(__name__)


class KiteDataClient:
    """Interface to Zerodha Kite Connect for historical intraday candle fetching."""

    def __init__(self, api_key: Optional[str] = None, access_token: Optional[str] = None):
        self.api_key = api_key or os.getenv("KITE_API_KEY")
        self.access_token = access_token or os.getenv("KITE_ACCESS_TOKEN")

        if KiteConnect is None:
            raise ImportError("kiteconnect package is not installed. Install via pip install kiteconnect.")

        if not self.api_key:
            raise ValueError("KITE_API_KEY environment variable is required.")

        self.kite = KiteConnect(api_key=self.api_key)
        if self.access_token:
            self.kite.set_access_token(self.access_token)
        self._instrument_token_cache: Dict[str, int] = {}

    @classmethod
    def get_login_url(cls, api_key: Optional[str] = None) -> str:
        """Generates the login URL for Zerodha Kite Connect web authentication."""
        key = api_key or os.getenv("KITE_API_KEY")
        if not key:
            raise ValueError("KITE_API_KEY environment variable is missing.")
        if KiteConnect is None:
            raise ImportError("kiteconnect package is not installed.")
        kite = KiteConnect(api_key=key)
        return kite.login_url()

    @classmethod
    def generate_access_token(
        cls,
        request_token: str,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
    ) -> str:
        """
        Exchanges request_token from login redirect with Kite API to generate a session access token.
        """
        key = api_key or os.getenv("KITE_API_KEY")
        secret = api_secret or os.getenv("KITE_API_SECRET")
        if not key or not secret:
            raise ValueError("Both KITE_API_KEY and KITE_API_SECRET are required for token exchange.")
        if KiteConnect is None:
            raise ImportError("kiteconnect package is not installed.")

        kite = KiteConnect(api_key=key)
        session_data = kite.generate_session(request_token=request_token, api_secret=secret)
        access_token = session_data.get("access_token")
        if not access_token:
            raise RuntimeError(f"Failed to obtain access token. Response: {session_data}")
        return access_token

    def load_instrument_tokens(self, exchange: str = "NSE") -> Dict[str, int]:
        """Loads and caches instrument tokens from Kite instruments endpoint."""
        if not self._instrument_token_cache:
            instruments = self.kite.instruments(exchange)
            for item in instruments:
                tradingsymbol = item.get("tradingsymbol")
                token = item.get("instrument_token")
                if tradingsymbol and token:
                    self._instrument_token_cache[tradingsymbol] = token
        return self._instrument_token_cache

    def get_instrument_token(self, symbol: str) -> Optional[int]:
        """Looks up the instrument token for an NSE symbol."""
        if not self._instrument_token_cache:
            self.load_instrument_tokens("NSE")
        return self._instrument_token_cache.get(symbol)

    def fetch_historical_candles_chunked(
        self,
        symbol: str,
        days: int = 500,
        interval: str = "5minute",
        max_chunk_days: int = 90,
        rate_limit_sleep: float = 0.5,
        max_retries: int = 4,
    ) -> pd.DataFrame:
        """
        Downloads 5-minute candles chunked into windows of <= 90 days with rate limiting.
        """
        token = self.get_instrument_token(symbol)
        if not token:
            raise ValueError(f"Instrument token not found for symbol '{symbol}' on NSE.")

        to_date = datetime.now()
        from_date = to_date - timedelta(days=days)

        all_records = []
        current_from = from_date

        while current_from < to_date:
            current_to = min(current_from + timedelta(days=max_chunk_days), to_date)
            chunk_data = None

            for attempt in range(max_retries):
                try:
                    time.sleep(rate_limit_sleep)
                    chunk_data = self.kite.historical_data(
                        instrument_token=token,
                        from_date=current_from.strftime("%Y-%m-%d %H:%M:%S"),
                        to_date=current_to.strftime("%Y-%m-%d %H:%M:%S"),
                        interval=interval,
                    )
                    break
                except Exception as e:
                    backoff = (2 ** attempt) * rate_limit_sleep * 2
                    logger.warning(
                        f"Error fetching {symbol} from {current_from.date()} to {current_to.date()} (attempt {attempt+1}/{max_retries}): {e}. Backing off {backoff:.1f}s"
                    )
                    time.sleep(backoff)
                    if attempt == max_retries - 1:
                        raise RuntimeError(f"Exceeded max retries fetching data for {symbol}: {e}")

            if chunk_data:
                all_records.extend(chunk_data)

            current_from = current_to + timedelta(seconds=1)

        if not all_records:
            return pd.DataFrame()

        df = pd.DataFrame(all_records)
        # Ensure standard column format
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
            if df["date"].dt.tz is not None:
                # Convert to IST naive wall clock time
                df["date"] = df["date"].dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)

        df = df[["date", "open", "high", "low", "close", "volume"]]
        return df
