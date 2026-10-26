"""
Point-in-Time Strategy Execution Context.

Prevents lookahead bias by structurally restricting data access to only
bars, indicators, and AI tags known at or before the current timestamp.
"""

from datetime import datetime, date
from typing import Any, Dict, List, Optional
import pandas as pd


class LookaheadViolationError(Exception):
    """Raised if any component attempts to access future market data."""
    pass


class StrategyContext:
    """
    Point-in-time strategy context.
    Exposes history, indicators, portfolio state, and AI tags up to current_timestamp.
    """

    def __init__(
        self,
        current_timestamp: datetime,
        historical_store: Dict[str, pd.DataFrame],
        daily_features: Dict[str, pd.DataFrame],
        portfolio_state: Dict[str, Any],
        ai_tags_store: Optional[List[Dict[str, Any]]] = None,
    ):
        self._current_timestamp = current_timestamp
        self._historical_store = historical_store      # {symbol: DataFrame indexed by timestamp}
        self._daily_features = daily_features          # {symbol: DataFrame indexed by date}
        self._portfolio = portfolio_state              # {"cash": float, "positions": dict, "equity": float}
        self._ai_tags = ai_tags_store or []

    @property
    def current_time(self) -> datetime:
        return self._current_timestamp

    @property
    def current_date(self) -> date:
        return self._current_timestamp.date()

    @property
    def equity(self) -> float:
        return float(self._portfolio.get("equity", 100000.0))

    @property
    def cash(self) -> float:
        return float(self._portfolio.get("cash", 100000.0))

    def get_available_symbols(self) -> List[str]:
        """Returns list of symbols available in data store."""
        return list(self._historical_store.keys())

    def get_history(self, symbol: str, n_bars: int = 50) -> pd.DataFrame:
        """
        Returns the last n_bars for the symbol up to and including self._current_timestamp.
        STRUCTURALLY IMPOSSIBLE to return future bars: filters on index <= self._current_timestamp.
        """
        if symbol not in self._historical_store:
            return pd.DataFrame()

        df = self._historical_store[symbol]
        # Strict Point-in-Time slicing
        point_in_time_slice = df[df.index <= self._current_timestamp]
        return point_in_time_slice.tail(n_bars).copy()

    def get_daily_feature(self, symbol: str, feature_name: str) -> Optional[float]:
        """
        Returns a precomputed daily feature known at the start of current_date (strictly shifted).
        """
        if symbol not in self._daily_features:
            return None

        daily_df = self._daily_features[symbol]
        curr_d = self.current_date
        if curr_d in daily_df.index:
            val = daily_df.loc[curr_d].get(feature_name)
            return float(val) if val is not None and not pd.isna(val) else None
        return None

    def get_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Returns active position details for the symbol, if any."""
        positions = self._portfolio.get("positions", {})
        return positions.get(symbol)

    def get_ai_tags(self, symbol: str) -> List[Dict[str, Any]]:
        """
        POINT-IN-TIME AI TAGS:
        Only returns tags that were created in the database at or before self._current_timestamp.
        Tags created in the future are strictly filtered out!
        """
        valid_tags = []
        for tag in self._ai_tags:
            if tag.get("symbol") == symbol:
                created_at = tag.get("created_at")
                if created_at and created_at <= self._current_timestamp:
                    valid_tags.append(tag)
        return valid_tags
