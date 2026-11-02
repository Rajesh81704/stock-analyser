"""
Paper Trading Engine - Simulates live trading with real-time position management
Tracks: orders, fills, positions, PnL, drawdowns, risk metrics
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import json
from pathlib import Path


@dataclass
class PaperOrder:
    """Represents a paper trading order."""
    order_id: str
    symbol: str
    side: str  # BUY or SELL
    qty: int
    price: float
    entry_price: float
    stop_loss: float
    target: float
    status: str  # PENDING, FILLED, PARTIAL, CLOSED
    created_at: datetime
    filled_at: Optional[datetime] = None
    filled_qty: int = 0
    filled_price: float = 0.0


@dataclass
class PaperPosition:
    """Represents an open position in paper trading."""
    symbol: str
    qty: int
    entry_price: float
    entry_date: str
    stop_loss: float
    target: float
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    unrealized_pnl_pct: float = 0.0
    setup_type: str = ""
    days_held: int = 0


@dataclass
class PaperTrade:
    """Represents a closed trade."""
    symbol: str
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    qty: int
    setup_type: str
    exit_reason: str
    gross_pnl: float
    costs: float
    net_pnl: float
    net_pnl_pct: float


class PaperTradingEngine:
    """Live paper trading simulation engine."""
    
    def __init__(self, initial_capital: float = 250000.0, name: str = "Paper_Trading_250K"):
        """Initialize paper trading engine."""
        self.initial_capital = initial_capital
        self.current_capital = initial_capital
        self.equity = initial_capital
        self.name = name
        
        # Trading state
        self.positions: Dict[str, PaperPosition] = {}
        self.orders: Dict[str, PaperOrder] = {}
        self.trades: List[PaperTrade] = []
        
        # Daily tracking
        self.daily_records: List[dict] = []
        self.equity_history: List[Tuple[str, float]] = []
        
        # Risk metrics
        self.peak_equity = initial_capital
        self.max_drawdown = 0.0
        self.max_drawdown_pct = 0.0
        self.monthly_pnl = {}
        self.monthly_start = initial_capital
        self.current_month = None
        
        # Metadata
        self.started_at = datetime.now()
        self.last_updated = datetime.now()
        self.trade_count = 0
        
    def place_order(self, symbol: str, qty: int, side: str, 
                   entry_price: float, stop_loss: float, target: float,
                   setup_type: str = "") -> Tuple[bool, str]:
        """Place a new order."""
        try:
            # Risk check
            if side == "BUY":
                required_capital = entry_price * qty
                if required_capital > self.equity * 0.3:  # Max 30% per trade
                    return False, f"Order too large: needs ₹{required_capital:,.0f}, have ₹{self.equity:,.0f}"
            
            # Create order
            order_id = f"{symbol}_{datetime.now().strftime('%H%M%S%f')[:10]}"
            order = PaperOrder(
                order_id=order_id,
                symbol=symbol,
                side=side,
                qty=qty,
                price=entry_price,
                entry_price=entry_price,
                stop_loss=stop_loss,
                target=target,
                status="PENDING",
                created_at=datetime.now()
            )
            
            self.orders[order_id] = order
            return True, f"Order {order_id} placed"
        
        except Exception as e:
            return False, f"Error placing order: {str(e)}"
    
    def fill_order(self, order_id: str, fill_price: float, fill_qty: int) -> Tuple[bool, str]:
        """Fill an order and create position."""
        try:
            if order_id not in self.orders:
                return False, f"Order {order_id} not found"
            
            order = self.orders[order_id]
            
            if order.status == "CLOSED":
                return False, f"Order {order_id} already closed"
            
            # Update order
            order.filled_qty = fill_qty
            order.filled_price = fill_price
            order.filled_at = datetime.now()
            order.status = "FILLED" if fill_qty == order.qty else "PARTIAL"
            
            # Deduct capital
            capital_used = fill_price * fill_qty
            self.equity -= capital_used
            
            # Create position
            if order.symbol not in self.positions:
                self.positions[order.symbol] = PaperPosition(
                    symbol=order.symbol,
                    qty=fill_qty,
                    entry_price=fill_price,
                    entry_date=datetime.now().strftime("%Y-%m-%d"),
                    stop_loss=order.stop_loss,
                    target=order.target,
                    setup_type=order.side.upper()
                )
            
            return True, f"Order {order_id} filled: {fill_qty}@₹{fill_price}"
        
        except Exception as e:
            return False, f"Error filling order: {str(e)}"
    
    def update_position(self, symbol: str, current_price: float) -> Optional[PaperPosition]:
        """Update position with current market price."""
        if symbol not in self.positions:
            return None
        
        pos = self.positions[symbol]
        pos.current_price = current_price
        pos.unrealized_pnl = (current_price - pos.entry_price) * pos.qty
        pos.unrealized_pnl_pct = ((current_price - pos.entry_price) / pos.entry_price) * 100
        pos.days_held = (datetime.now() - datetime.strptime(pos.entry_date, "%Y-%m-%d")).days
        
        return pos
    
    def close_position(self, symbol: str, exit_price: float, 
                      exit_reason: str = "TARGET") -> Tuple[bool, PaperTrade]:
        """Close a position."""
        try:
            if symbol not in self.positions:
                return False, None
            
            pos = self.positions[symbol]
            
            # Calculate PnL
            gross_pnl = (exit_price - pos.entry_price) * pos.qty
            costs = 0  # Simplified - no transaction costs in paper trading
            net_pnl = gross_pnl - costs
            net_pnl_pct = (net_pnl / (pos.entry_price * pos.qty)) * 100 if pos.entry_price > 0 else 0
            
            # Create trade record
            trade = PaperTrade(
                symbol=symbol,
                entry_date=pos.entry_date,
                exit_date=datetime.now().strftime("%Y-%m-%d"),
                entry_price=pos.entry_price,
                exit_price=exit_price,
                qty=pos.qty,
                setup_type=pos.setup_type,
                exit_reason=exit_reason,
                gross_pnl=gross_pnl,
                costs=costs,
                net_pnl=net_pnl,
                net_pnl_pct=net_pnl_pct
            )
            
            # Update equity: return invested capital + add profit
            capital_returned = pos.entry_price * pos.qty
            self.equity += capital_returned
            self.equity += net_pnl
            self.trades.append(trade)
            self.trade_count += 1
            
            # Remove position
            del self.positions[symbol]
            
            return True, trade
        
        except Exception as e:
            return False, None
    
    def get_portfolio_summary(self) -> dict:
        """Get current portfolio summary."""
        open_pnl = sum(pos.unrealized_pnl for pos in self.positions.values())
        closed_pnl = sum(trade.net_pnl for trade in self.trades)
        total_pnl = open_pnl + closed_pnl
        
        wins = len([t for t in self.trades if t.net_pnl > 0])
        losses = len([t for t in self.trades if t.net_pnl <= 0])
        win_rate = (wins / len(self.trades) * 100) if self.trades else 0
        
        return {
            'timestamp': datetime.now().isoformat(),
            'initial_capital': self.initial_capital,
            'current_equity': self.equity,
            'total_return_pct': ((self.equity - self.initial_capital) / self.initial_capital * 100),
            'open_positions': len(self.positions),
            'open_pnl': open_pnl,
            'closed_pnl': closed_pnl,
            'total_pnl': total_pnl,
            'trades_count': self.trade_count,
            'wins': wins,
            'losses': losses,
            'win_rate': win_rate,
            'max_drawdown_pct': self.max_drawdown_pct,
            'peak_equity': self.peak_equity,
        }
    
    def record_daily(self, date: str) -> None:
        """Record daily snapshot."""
        summary = self.get_portfolio_summary()
        summary['date'] = date
        self.daily_records.append(summary)
        self.equity_history.append((date, self.equity))
        
        # Update peak and drawdown
        if self.equity > self.peak_equity:
            self.peak_equity = self.equity
        
        if self.peak_equity > 0:
            dd = (self.peak_equity - self.equity) / self.peak_equity * 100
            if dd > self.max_drawdown_pct:
                self.max_drawdown_pct = dd
                self.max_drawdown = self.peak_equity - self.equity
    
    def export_trades(self, filepath: str) -> bool:
        """Export trades to CSV."""
        try:
            if not self.trades:
                return False
            
            df = pd.DataFrame([{
                'symbol': t.symbol,
                'entry_date': t.entry_date,
                'exit_date': t.exit_date,
                'entry_price': t.entry_price,
                'exit_price': t.exit_price,
                'qty': t.qty,
                'setup': t.setup_type,
                'exit_reason': t.exit_reason,
                'gross_pnl': t.gross_pnl,
                'net_pnl': t.net_pnl,
                'net_pnl_pct': t.net_pnl_pct,
            } for t in self.trades])
            
            df.to_csv(filepath, index=False)
            return True
        except:
            return False
    
    def export_daily(self, filepath: str) -> bool:
        """Export daily records to CSV."""
        try:
            if not self.daily_records:
                return False
            
            df = pd.DataFrame(self.daily_records)
            df.to_csv(filepath, index=False)
            return True
        except:
            return False
    
    def export_state(self, filepath: str) -> bool:
        """Export full state to JSON."""
        try:
            state = {
                'engine': {
                    'name': self.name,
                    'initial_capital': self.initial_capital,
                    'current_equity': self.equity,
                    'started_at': self.started_at.isoformat(),
                    'last_updated': self.last_updated.isoformat(),
                },
                'summary': self.get_portfolio_summary(),
                'positions': {
                    symbol: {
                        'qty': pos.qty,
                        'entry_price': pos.entry_price,
                        'entry_date': pos.entry_date,
                        'stop_loss': pos.stop_loss,
                        'target': pos.target,
                        'current_price': pos.current_price,
                        'unrealized_pnl': pos.unrealized_pnl,
                        'unrealized_pnl_pct': pos.unrealized_pnl_pct,
                    }
                    for symbol, pos in self.positions.items()
                },
                'trades': [
                    {
                        'symbol': t.symbol,
                        'entry_date': t.entry_date,
                        'exit_date': t.exit_date,
                        'entry_price': t.entry_price,
                        'exit_price': t.exit_price,
                        'qty': t.qty,
                        'net_pnl': t.net_pnl,
                        'net_pnl_pct': t.net_pnl_pct,
                    }
                    for t in self.trades
                ],
            }
            
            with open(filepath, 'w') as f:
                json.dump(state, f, indent=2)
            
            return True
        except:
            return False


# Example usage dashboard
class PaperTradingDashboard:
    """Real-time dashboard for paper trading."""
    
    def __init__(self, engine: PaperTradingEngine):
        self.engine = engine
    
    def print_summary(self) -> None:
        """Print dashboard summary."""
        summary = self.engine.get_portfolio_summary()
        
        print("\n" + "=" * 100)
        print("PAPER TRADING DASHBOARD - " + self.engine.name)
        print("=" * 100)
        print(f"\nTime: {summary['timestamp']}")
        print(f"\nCAPITAL:")
        print(f"  Initial:        ₹{summary['initial_capital']:>15,.0f}")
        print(f"  Current:        ₹{summary['current_equity']:>15,.0f}")
        print(f"  Total Return:   {summary['total_return_pct']:>15.2f}%")
        
        print(f"\nPOSITIONS & PnL:")
        print(f"  Open Positions: {summary['open_positions']:>15}")
        print(f"  Open PnL:       ₹{summary['open_pnl']:>15,.0f}")
        print(f"  Closed PnL:     ₹{summary['closed_pnl']:>15,.0f}")
        print(f"  Total PnL:      ₹{summary['total_pnl']:>15,.0f}")
        
        print(f"\nTRADES:")
        print(f"  Total Trades:   {summary['trades_count']:>15}")
        print(f"  Wins:           {summary['wins']:>15}")
        print(f"  Losses:         {summary['losses']:>15}")
        print(f"  Win Rate:       {summary['win_rate']:>15.1f}%")
        
        print(f"\nRISK:")
        print(f"  Peak Equity:    ₹{summary['peak_equity']:>15,.0f}")
        print(f"  Max Drawdown:   {summary['max_drawdown_pct']:>15.2f}%")
        
        print(f"\nOPEN POSITIONS:")
        if self.engine.positions:
            for symbol, pos in self.engine.positions.items():
                print(f"  {symbol:<10} | Qty: {pos.qty:>5} | Entry: ₹{pos.entry_price:>10.2f} | "
                      f"Current: ₹{pos.current_price:>10.2f} | PnL: ₹{pos.unrealized_pnl:>10,.0f} ({pos.unrealized_pnl_pct:>6.2f}%)")
        else:
            print("  (None)")
        
        print("\n" + "=" * 100)
