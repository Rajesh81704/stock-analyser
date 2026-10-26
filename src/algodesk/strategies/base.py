"""
AlgoDesk Strategy Plugin Interface.

Every trading strategy in AlgoDesk inherits from BaseStrategy and emits OrderIntents.
Strategies run identically in BACKTEST, PAPER, and LIVE modes.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel


@dataclass
class OrderIntent:
    """Represents a trading intent emitted by a strategy."""
    symbol: str
    side: Literal["BUY", "SELL"]
    qty: Optional[int] = None
    risk_pct: Optional[float] = None          # E.g. 0.01 for 1% equity risk
    order_type: Literal["MARKET", "LIMIT", "SL"] = "MARKET"
    price: Optional[float] = None             # Limit / fill price
    trigger_price: Optional[float] = None     # Stop entry or stop loss trigger
    stop_loss: Optional[float] = None
    target: Optional[float] = None
    time_in_force: str = "DAY"
    reason: str = ""
    strategy_name: str = ""
    timestamp: Optional[datetime] = None
    intent_id: str = field(default_factory=lambda: "")


class BaseStrategy(ABC):
    """
    Abstract Base Class for all AlgoDesk strategies.
    
    Plugins must not import kiteconnect or place broker orders directly.
    All data is accessed via the StrategyContext object with strict point-in-time guarantees.
    """

    name: str = "base_strategy"
    version: str = "1.0.0"
    timeframe: str = "5m"
    description: str = ""
    parameter_schema: Optional[type[BaseModel]] = None

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.parameters = config.get("parameters", {})

    def select_universe(self, ctx) -> List[str]:
        """
        Optional hook called before or at the start of each trading day to filter/rank candidates.
        Allows keeping 500-symbol daily scans fast.
        """
        return ctx.get_available_symbols()

    def on_session_start(self, ctx):
        """Called at market open (09:15 IST) or start of a backtest day."""
        pass

    @abstractmethod
    def on_bar(self, ctx, symbol: str, bar: Dict[str, Any]) -> List[OrderIntent]:
        """
        Called on every bar closed for the selected candidates.
        Returns a list of OrderIntent objects.
        """
        raise NotImplementedError

    def on_session_end(self, ctx):
        """Called at end of session (15:30 IST) or EOD."""
        pass
