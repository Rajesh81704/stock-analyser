"""
Strategy Configuration Dataclass for Opening Range Breakout (ORB).
"""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class StrategyConfig:
    """Parameters governing the ORB strategy, risk management, and universe filtering."""

    # Opening Range Configuration
    or_minutes: int = 30                 # 30-minute opening range [OPTIMIZED]
    rvol_window: int = 14                # 14 prior trading days for OR RVOL baseline (shifted)
    min_rvol: float = 1.0                # Minimum RVOL required to be eligible

    # Peak Entry Window (NEW - 0.8% Daily Strategy)
    peak_entry_start: str = "09:45:00"   # Start trading after opening range [NEW: IMPROVED STRATEGY]
    peak_entry_end: str = "11:30:00"     # Stop new entries after peak window [NEW: IMPROVED STRATEGY]
    trade_until: str = "15:30:00"        # Existing positions can ride until EOD [NEW: IMPROVED STRATEGY]

    # Liquidity & Universe Filters (TIGHTENED)
    atr_window: int = 14                 # Daily ATR window (shifted 1 day)
    turnover_window: int = 20            # Trailing 20 trading days for average turnover (shifted)
    min_turnover_cr: float = 500.0       # ₹500Cr minimum daily turnover [IMPROVED: Was 20Cr, now 500Cr]
    min_price: float = 50.0              # Minimum previous day close price
    top_n: int = 10                      # Top 10 mega-cap candidates [IMPROVED: Was 5, now 10 for better filtering]
    mega_cap_only: bool = True           # Only trade top 20 mega-caps [NEW: IMPROVED STRATEGY]

    # Exit Rules (CHANGED FROM TIME EXIT TO PROFIT TARGETS)
    exit_type: str = "profit_target"     # Use profit targets instead of time exit [NEW: IMPROVED STRATEGY]
    risk_reward_ratio: float = 2.0       # 2:1 risk/reward on profit targets [NEW: IMPROVED STRATEGY]

    # Direction and Execution Switches
    direction_mode: Literal["both", "long_only", "short_only"] = "both"
    stop_atr: float = 0.45               # Stop distance = 0.45 × ATR(14) [KEPT: OPTIMIZED]

    # Trend Filter (NEW - 0.8% Daily Strategy)
    use_trend_filter: bool = True        # Only trade in direction of trend [NEW: IMPROVED STRATEGY]
    trend_ma_period: int = 20            # 20-day moving average for trend [NEW: IMPROVED STRATEGY]
    trend_requirement: str = "must_match" # Entry must align with daily trend [NEW: IMPROVED STRATEGY]
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
