"""
Base strategy class - plug-in interface
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
import pandas as pd
from typing import Optional


@dataclass
class Setup:
    """Represents a trading setup identified by the scan"""
    symbol: str
    date: str
    kind: str  # 'A_pullback', 'B_breakout'
    trigger: float
    stop: float
    target1: float
    risk: float
    rr: float  # reward/risk ratio
    ema20: float
    ema50: float
    adx: Optional[float]
    atr: float
    volume_ratio: float
    meta: dict  # pattern details, support levels, etc.
    
    @property
    def is_valid(self) -> bool:
        """Validate setup risk/reward"""
        return self.rr >= 1.5 and self.risk > 0


@dataclass
class ExitAction:
    """Represents an exit decision from position management"""
    symbol: str
    action: str  # 'exit_all', 'exit_partial', 'hold', 'tighten_stop'
    reason: str
    exit_price: Optional[float] = None
    new_stop: Optional[float] = None


class Strategy(ABC):
    """
    Abstract base for swing trading strategies.
    
    Implementing strategies must override scan() and manage().
    """
    
    def __init__(self, name: str, config: dict):
        """
        Initialize strategy.
        
        Args:
            name: Strategy identifier
            config: Configuration dict (from config.yaml)
        """
        self.name = name
        self.config = config
    
    @abstractmethod
    def scan(self, df: pd.DataFrame, ctx: dict) -> Optional[Setup]:
        """
        End-of-day scan for setups.
        
        Args:
            df: Historical OHLCV for one symbol (last 200+ bars)
            ctx: Context dict with:
                - 'symbol': stock symbol
                - 'nifty': Nifty OHLCV last 100 bars
                - 'nifty_ema50': Nifty 50-day EMA
                - 'open_positions': count and details
                - 'equity': current equity
                - 'open_risk': total open risk
        
        Returns:
            Setup object if criteria met, else None
        """
        pass
    
    @abstractmethod
    def manage(self, pos: dict, df: pd.DataFrame, ctx: dict) -> Optional[ExitAction]:
        """
        Daily position management for open positions.
        
        Args:
            pos: Position dict with keys:
                - symbol, qty, entry_price, entry_date
                - stop, target1, has_partial_exit, partial_qty
            df: Historical OHLCV for the symbol
            ctx: Context (same as scan)
        
        Returns:
            ExitAction if an exit is warranted, else None (hold)
        """
        pass


class NullStrategy(Strategy):
    """Null strategy - returns no setups (for testing)"""
    
    def __init__(self):
        super().__init__("null", {})
    
    def scan(self, df: pd.DataFrame, ctx: dict) -> Optional[Setup]:
        return None
    
    def manage(self, pos: dict, df: pd.DataFrame, ctx: dict) -> Optional[ExitAction]:
        return None
