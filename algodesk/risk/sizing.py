"""
Position sizing and risk management
"""
from typing import Tuple


def kelly_fraction(win_rate: float, avg_win: float, avg_loss: float, kelly_factor: float = 0.25) -> float:
    """
    Kelly criterion for position sizing (fractional Kelly for safety).
    
    Args:
        win_rate: Probability of winning (0-1)
        avg_win: Average win in units of risk
        avg_loss: Average loss in units of risk (positive)
        kelly_factor: Fraction of full Kelly to use (0.25 = 25% Kelly)
    
    Returns:
        Position size as fraction of equity (0-1)
    """
    if avg_loss <= 0:
        return 0
    
    # Kelly: f = (p * b - q) / b
    # p = win_rate, q = 1-win_rate, b = avg_win/avg_loss
    p = win_rate
    q = 1 - win_rate
    b = avg_win / avg_loss
    
    kelly = (p * b - q) / b if b > 0 else 0
    kelly = max(0, min(kelly, 1))  # Clamp to [0, 1]
    
    # Apply fraction for safety
    return kelly * kelly_factor


def position_size_from_risk(equity: float, risk_amount: float, trigger: float, stop: float) -> Tuple[float, float]:
    """
    Calculate shares based on fixed risk amount and stop loss distance.
    
    Args:
        equity: Current equity in ₹
        risk_amount: Maximum loss acceptable (₹)
        trigger: Entry price
        stop: Stop-loss price
    
    Returns:
        Tuple of (num_shares, notional_size_in_rupees)
    """
    if trigger <= stop or trigger == stop:
        return 0, 0
    
    risk_per_share = abs(trigger - stop)
    num_shares = int(risk_amount / risk_per_share)
    notional_size = num_shares * trigger
    
    return num_shares, notional_size


def validate_position_limits(
    equity: float,
    total_exposure: float,
    open_positions: int,
    proposed_size: float,
    max_position_pct: float = 0.20,
    max_positions: int = 5,
    max_open_risk_pct: float = 0.05
) -> Tuple[bool, str]:
    """
    Validate position against portfolio limits.
    
    Args:
        equity: Current equity
        total_exposure: Total notional exposure
        open_positions: Number of open positions
        proposed_size: Proposed position notional size
        max_position_pct: Max single position as % of equity
        max_positions: Max number of open positions
        max_open_risk_pct: Max open risk as % of equity
    
    Returns:
        Tuple of (is_valid, reason_if_not)
    """
    
    # Check position count
    if open_positions >= max_positions:
        return False, f"Max positions ({max_positions}) reached"
    
    # Check single position size
    max_position_size = equity * max_position_pct
    if proposed_size > max_position_size:
        return False, f"Position {proposed_size:,.0f} exceeds max {max_position_size:,.0f}"
    
    # Check total exposure
    max_total_exposure = equity * 1.0  # Typically allow up to 100% notional (with leverage)
    if total_exposure + proposed_size > max_total_exposure:
        return False, f"Total exposure {total_exposure + proposed_size:,.0f} exceeds max {max_total_exposure:,.0f}"
    
    return True, "OK"


def sector_position_count(positions: list, sector: str) -> int:
    """
    Count open positions in a specific sector.
    
    Args:
        positions: List of open position dicts (must have 'sector' key)
        sector: Sector name
    
    Returns:
        Count of positions in sector
    """
    return len([p for p in positions if p.get('sector') == sector])


def validate_sector_limit(
    positions: list,
    symbol_sector: str,
    max_per_sector: int = 2
) -> Tuple[bool, str]:
    """
    Check if adding a new position would violate sector limits.
    
    Args:
        positions: List of open positions
        symbol_sector: Sector of proposed position
        max_per_sector: Max positions per sector
    
    Returns:
        Tuple of (is_valid, reason)
    """
    sector_count = sector_position_count(positions, symbol_sector)
    
    if sector_count >= max_per_sector:
        return False, f"Sector {symbol_sector} already has {sector_count} positions (max {max_per_sector})"
    
    return True, "OK"
