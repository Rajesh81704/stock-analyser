"""
Cost model for backtesting - Zerodha CNC delivery
"""


class CostModel:
    """Realistic cost model for NSE CNC delivery trades"""
    
    # Zerodha brokerage (as of 2024)
    BROKERAGE_BUY_PCT = 0.0  # Free on buy
    BROKERAGE_SELL_PCT = 0.001  # 0.1% on sell (capped at ₹20/trade)
    BROKERAGE_MIN = 0
    BROKERAGE_MAX_SELL = 20
    
    # STT (Securities Transaction Tax) - Zerodha pays, adds to cost
    STT_BUY_PCT = 0.0  # No STT on buy
    STT_SELL_PCT = 0.001  # 0.1% on sell (delivery)
    
    # Turnover charges (exchange + SEBI)
    EXCHANGE_TURNOVER_SELL_PCT = 0.00003  # ~3 paise per ₹1000
    
    # DP charges (Depository Participant)
    DP_CHARGES_SELL = 13.50  # ₹13.50 per sell transaction (fixed)
    
    # Slippage assumption (entry/exit)
    SLIPPAGE_BUY_PCT = 0.001  # 0.1% entry slippage
    SLIPPAGE_SELL_PCT = 0.001  # 0.1% exit slippage
    
    @staticmethod
    def cost_on_buy(price: float, qty: int) -> float:
        """
        Calculate total cost on buy.
        
        Args:
            price: Entry price
            qty: Quantity
        
        Returns:
            Total cost in rupees
        """
        notional = price * qty
        
        # Brokerage (typically free for buy in CNC)
        brokerage = 0
        
        # Slippage (assumed paid)
        slippage = notional * CostModel.SLIPPAGE_BUY_PCT
        
        return brokerage + slippage
    
    @staticmethod
    def cost_on_sell(price: float, qty: int) -> float:
        """
        Calculate total cost on sell (exit).
        
        Args:
            price: Exit price
            qty: Quantity
        
        Returns:
            Total cost in rupees
        """
        notional = price * qty
        
        # Brokerage
        brokerage = min(
            notional * CostModel.BROKERAGE_SELL_PCT,
            CostModel.BROKERAGE_MAX_SELL
        )
        
        # STT
        stt = notional * CostModel.STT_SELL_PCT
        
        # Exchange turnover
        exchange = notional * CostModel.EXCHANGE_TURNOVER_SELL_PCT
        
        # DP charges
        dp = CostModel.DP_CHARGES_SELL
        
        # Slippage
        slippage = notional * CostModel.SLIPPAGE_SELL_PCT
        
        total = brokerage + stt + exchange + dp + slippage
        return total
    
    @staticmethod
    def cost_round_trip(entry_price: float, exit_price: float, qty: int) -> dict:
        """
        Calculate cost for entire round-trip trade.
        
        Args:
            entry_price: Entry price
            exit_price: Exit price
            qty: Quantity
        
        Returns:
            Dict with breakdown: {'buy': x, 'sell': y, 'total': z, 'pct_of_notional': w}
        """
        entry_notional = entry_price * qty
        exit_notional = exit_price * qty
        
        buy_cost = CostModel.cost_on_buy(entry_price, qty)
        sell_cost = CostModel.cost_on_sell(exit_price, qty)
        total_cost = buy_cost + sell_cost
        
        avg_notional = (entry_notional + exit_notional) / 2
        pct = (total_cost / avg_notional * 100) if avg_notional > 0 else 0
        
        return {
            'buy': buy_cost,
            'sell': sell_cost,
            'total': total_cost,
            'pct_of_avg_notional': pct
        }
    
    @staticmethod
    def cost_partial_exit(exit_price: float, qty: int, exit_fraction: float = 0.5) -> float:
        """
        Cost for partial exit (e.g., 50% of position).
        
        Args:
            exit_price: Exit price
            qty: Total quantity
            exit_fraction: Fraction to exit (0.5 = 50%)
        
        Returns:
            Cost for the partial exit
        """
        exit_qty = int(qty * exit_fraction)
        return CostModel.cost_on_sell(exit_price, exit_qty)


def cost_adjusted_pnl(gross_pnl: float, cost_model_result: dict) -> float:
    """
    Calculate net P&L after costs.
    
    Args:
        gross_pnl: Gross P&L before costs
        cost_model_result: Output from cost_round_trip()
    
    Returns:
        Net P&L after costs
    """
    return gross_pnl - cost_model_result['total']
