"""
Strategy Configuration Dataclass for Opening Range Breakout (ORB).
"""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class StrategyConfig:
    """Parameters governing the ORB strategy, risk management, and universe filtering."""

    # Opening Range Configuration
    or_minutes: int = 5                  # 5, 15, or 30 minutes
    rvol_window: int = 14                # 14 prior trading days for OR RVOL baseline (shifted)
    min_rvol: float = 1.0                # Minimum RVOL required to be eligible

    # Liquidity & Universe Filters
    atr_window: int = 14                 # Daily ATR window (shifted 1 day)
    turnover_window: int = 20            # Trailing 20 trading days for average turnover (shifted)
    min_turnover_cr: float = 20.0        # Trailing average daily turnover in Rs Crore (close * vol)
    min_price: float = 50.0              # Minimum previous day close price
    top_n: int = 5                       # Max number of stocks to trade per day

    # Direction and Execution Switches
    direction_mode: Literal["both", "long_only", "short_only"] = "both"
    stop_atr: float = 0.10               # Stop distance = stop_atr * daily_atr14
    conservative_intrabar: bool = True   # If entry bar touches stop, assume stop hit immediately

    # Intraday Timing (IST)
    market_open_time: str = "09:15:00"
    market_close_time: str = "15:30:00"
    square_off_time: str = "15:10:00"    # Close of last bar before 15:15 auto square-off

    # Sizing & Compounding
    risk_pct: float = 0.01               # 1% risk per trade of start-of-day equity
    max_leverage: float = 5.0            # Max gross leverage across all N positions (Zerodha MIS ~5x)
    initial_capital: float = 100000.0    # Rs 100,000 starting equity
    in_sample_ratio: float = 0.70        # 70% In-Sample, 30% Out-of-Sample
