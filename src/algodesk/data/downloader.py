"""
Historical 5-Minute Candle Downloader for Nifty 500 Universe.

Downloads historical candles in 90-day chunked intervals via Kite Connect API,
applies quality hygiene cleaning, and saves to Parquet / CSV storage.
"""

import time
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple
import pandas as pd
from sqlalchemy.orm import Session

from src.algodesk.data.hygiene import clean_intraday_candles, QualityReport
from src.algodesk.data.instruments import InstrumentMaster
from src.algodesk.data.kite_client import KiteClientWrapper
from src.algodesk.db.models import DataQualityLog

logger = logging.getLogger(__name__)


class HistoricalDownloader:
    """Orchestrates chunked downloads of historical 5-minute bars for the equity universe."""

    def __init__(
        self,
        kite_client: KiteClientWrapper,
        instrument_master: InstrumentMaster,
        db_session: Optional[Session] = None,
        output_dir: str = "data",
    ):
        self.client = kite_client
        self.instruments = instrument_master
        self.db = db_session
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def download_symbol(
        self,
        symbol: str,
        days: int = 500,
        resume: bool = True,
    ) -> Tuple[Optional[pd.DataFrame], Optional[QualityReport]]:
        """
        Downloads, cleans, and stores 5-minute candles for a single symbol.
        Supports resume mode to skip already downloaded data.
        """
        parquet_file = self.output_dir / f"{symbol}.parquet"
        csv_file = self.output_dir / f"{symbol}.csv"

        if resume and (parquet_file.exists() or csv_file.exists()):
            try:
                if parquet_file.exists():
                    df = pd.read_parquet(parquet_file)
                else:
                    df = pd.read_csv(csv_file)
                cleaned, report = clean_intraday_candles(df, symbol)
                return cleaned, report
            except Exception as e:
                logger.warning(f"{symbol}: Existing file unreadable ({e}), re-downloading...")

        token = self.instruments.get_token(symbol)
        if not token:
            logger.error(f"{symbol}: No instrument token found on NSE.")
            return None, None

        to_date = datetime.now()
        from_date = to_date - timedelta(days=days)

        raw_df = self.client.fetch_historical_candles_chunked(
            instrument_token=token,
            from_date=from_date,
            to_date=to_date,
            interval="5minute",
            max_chunk_days=90,
            rate_limit_sleep=0.5,
        )

        if raw_df.empty:
            logger.warning(f"{symbol}: No historical data returned from Kite.")
            return None, None

        cleaned_df, report = clean_intraday_candles(raw_df, symbol)

        # Save to Parquet and CSV
        cleaned_df.reset_index().to_parquet(parquet_file, index=False)
        cleaned_df.reset_index().to_csv(csv_file, index=False)

        # Log anomalies to database if session available
        if self.db is not None:
            for flag in report.corporate_action_flags:
                log_entry = DataQualityLog(
                    symbol=symbol,
                    check_type="LARGE_RETURN_SPLIT",
                    severity="WARNING",
                    message=flag,
                )
                self.db.add(log_entry)
            for gap in report.gap_warnings:
                log_entry = DataQualityLog(
                    symbol=symbol,
                    check_type="GAP",
                    severity="INFO",
                    message=gap,
                )
                self.db.add(log_entry)
            self.db.commit()

        return cleaned_df, report

    def download_universe(
        self,
        symbols: List[str],
        days: int = 500,
        resume: bool = True,
    ) -> List[QualityReport]:
        """Iterates over universe symbols with rate limiting and progress logging."""
        reports = []
        total = len(symbols)

        print(f"\n[DOWNLOADER] Starting download for {total} symbols over past {days} days...")
        for idx, sym in enumerate(symbols, 1):
            target_file = self.output_dir / f"{sym}.parquet"
            if resume and target_file.exists() and target_file.stat().st_size > 100:
                print(f"[{idx}/{total}] {sym}: already exists (skipped)")
                continue

            try:
                df, report = self.download_symbol(sym, days=days, resume=resume)
                if df is not None and report is not None:
                    print(f"[{idx}/{total}] {sym}: {report.cleaned_bars} bars saved")
                    reports.append(report)
                else:
                    print(f"[{idx}/{total}] {sym}: NO DATA")
            except Exception as e:
                print(f"[{idx}/{total}] {sym}: FAILED ({e})")

        print(f"\n[DOWNLOADER] Completed batch download for {total} symbols.\n")
        return reports
