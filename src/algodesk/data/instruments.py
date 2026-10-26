"""
NSE & Nifty 500 Instrument Master Management.

Loads Nifty 500 constituents list, queries Zerodha Kite instruments endpoint,
and caches mappings between tradingsymbol and instrument_token.
"""

from pathlib import Path
from typing import Dict, List, Optional
import pandas as pd
from sqlalchemy.orm import Session

from src.algodesk.db.models import Instrument


def load_nifty500_universe(csv_path: str = "ind_nifty500list.csv") -> List[str]:
    """
    Loads symbols from NSE's official Nifty 500 constituents CSV.
    
    WARNING ON SURVIVORSHIP BIAS:
    Using current constituents for historical backtesting introduces survivorship bias.
    Companies that deteriorated, merged, or went bankrupt during the backtest window
    are excluded from today's list, which can artificially inflate historical performance.
    """
    candidate_paths = [
        Path(csv_path),
        Path("data") / Path(csv_path).name,
        Path("data/ind_nifty500list.csv"),
    ]

    found = None
    for p in candidate_paths:
        if p.exists():
            found = p
            break

    if not found:
        raise FileNotFoundError(f"Nifty 500 universe file '{csv_path}' not found.")

    df = pd.read_csv(found)
    col = "Symbol" if "Symbol" in df.columns else df.columns[0]
    symbols = df[col].dropna().astype(str).str.strip().tolist()
    clean_symbols = [s for s in symbols if s and s.upper() != "SYMBOL"]
    return sorted(list(set(clean_symbols)))


class InstrumentMaster:
    """Manages instrument master lookups, synchronization with Kite, and DB persistence."""

    def __init__(self, db_session: Optional[Session] = None):
        self.db = db_session
        self._symbol_to_token: Dict[str, int] = {}
        self._token_to_symbol: Dict[int, str] = {}

    def sync_from_kite(self, kite_client, exchange: str = "NSE") -> int:
        """Fetches active instruments from Kite API and stores them in memory / database."""
        instruments = kite_client.kite.instruments(exchange)
        count = 0

        for item in instruments:
            token = item.get("instrument_token")
            symbol = item.get("tradingsymbol")
            segment = item.get("segment")

            # Focus on cash equities
            if token and symbol and segment in ("NSE", "EQ"):
                self._symbol_to_token[symbol] = int(token)
                self._token_to_symbol[int(token)] = symbol

                if self.db is not None:
                    existing = self.db.query(Instrument).filter(Instrument.instrument_token == token).first()
                    if not existing:
                        inst = Instrument(
                            instrument_token=int(token),
                            tradingsymbol=symbol,
                            name=item.get("name"),
                            exchange=exchange,
                            segment=segment,
                            tick_size=float(item.get("tick_size", 0.05)),
                            lot_size=int(item.get("lot_size", 1)),
                            is_active=True,
                        )
                        self.db.add(inst)
                        count += 1

        if self.db is not None:
            self.db.commit()

        return count

    def get_token(self, symbol: str) -> Optional[int]:
        """Returns the instrument token for a symbol."""
        if symbol in self._symbol_to_token:
            return self._symbol_to_token[symbol]

        if self.db is not None:
            inst = self.db.query(Instrument).filter(Instrument.tradingsymbol == symbol).first()
            if inst:
                self._symbol_to_token[symbol] = inst.instrument_token
                self._token_to_symbol[inst.instrument_token] = symbol
                return inst.instrument_token
        return None

    def get_symbol(self, token: int) -> Optional[str]:
        """Returns the tradingsymbol for an instrument token."""
        if token in self._token_to_symbol:
            return self._token_to_symbol[token]

        if self.db is not None:
            inst = self.db.query(Instrument).filter(Instrument.instrument_token == token).first()
            if inst:
                self._symbol_to_token[inst.tradingsymbol] = token
                self._token_to_symbol[token] = inst.tradingsymbol
                return inst.tradingsymbol
        return None
