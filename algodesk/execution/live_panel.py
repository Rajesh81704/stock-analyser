"""
Live Trading Panel - Central control hub for paper trading
Monitors signals, executes orders, tracks performance in real-time
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import json
from pathlib import Path

from .paper_trading import PaperTradingEngine, PaperTradingDashboard


class LiveTradingPanel:
    """Central control panel for live/paper trading."""
    
    def __init__(self, engine: PaperTradingEngine, 
                 config_path: str = "algodesk/config.yaml"):
        """Initialize live trading panel."""
        self.engine = engine
        self.config_path = config_path
        self.dashboard = PaperTradingDashboard(engine)
        
        # Signal queue
        self.pending_signals: Dict[str, dict] = {}
        self.signal_history: List[dict] = []
        
        # Execution log
        self.execution_log: List[dict] = []
        
        # State
        self.is_running = False
        self.started_at = None
        self.paused_at = None
        
        # Metrics
        self.total_signals = 0
        self.total_entries = 0
        self.total_exits = 0
    
    def start(self) -> Tuple[bool, str]:
        """Start the trading panel."""
        try:
            if self.is_running:
                return False, "Panel already running"
            
            self.is_running = True
            self.started_at = datetime.now()
            
            log_entry = {
                'timestamp': datetime.now().isoformat(),
                'action': 'PANEL_START',
                'status': 'SUCCESS',
                'details': f"Trading panel started with ₹{self.engine.initial_capital:,.0f}"
            }
            self.execution_log.append(log_entry)
            
            return True, "Trading panel started"
        except Exception as e:
            return False, f"Error starting panel: {str(e)}"
    
    def stop(self) -> Tuple[bool, str]:
        """Stop the trading panel."""
        try:
            if not self.is_running:
                return False, "Panel not running"
            
            self.is_running = False
            
            log_entry = {
                'timestamp': datetime.now().isoformat(),
                'action': 'PANEL_STOP',
                'status': 'SUCCESS',
                'details': f"Trading panel stopped. Final equity: ₹{self.engine.equity:,.0f}"
            }
            self.execution_log.append(log_entry)
            
            return True, "Trading panel stopped"
        except Exception as e:
            return False, f"Error stopping panel: {str(e)}"
    
    def process_signal(self, signal: dict) -> Tuple[bool, str]:
        """Process incoming trading signal."""
        try:
            if not self.is_running:
                return False, "Panel not running"
            
            signal_id = f"{signal['symbol']}_{datetime.now().strftime('%H%M%S%f')[:10]}"
            signal['signal_id'] = signal_id
            signal['received_at'] = datetime.now().isoformat()
            signal['status'] = 'RECEIVED'
            
            self.pending_signals[signal_id] = signal
            self.total_signals += 1
            self.signal_history.append(signal)
            
            log_entry = {
                'timestamp': datetime.now().isoformat(),
                'action': 'SIGNAL_RECEIVED',
                'symbol': signal['symbol'],
                'setup': signal.get('setup', ''),
                'entry_price': signal.get('entry_price', 0),
                'signal_id': signal_id,
            }
            self.execution_log.append(log_entry)
            
            return True, f"Signal {signal_id} received"
        except Exception as e:
            return False, f"Error processing signal: {str(e)}"
    
    def execute_signal(self, signal_id: str, qty: int) -> Tuple[bool, str]:
        """Execute pending signal as order."""
        try:
            if signal_id not in self.pending_signals:
                return False, f"Signal {signal_id} not found"
            
            signal = self.pending_signals[signal_id]
            
            # Place order
            success, msg = self.engine.place_order(
                symbol=signal['symbol'],
                qty=qty,
                side='BUY',
                entry_price=signal['entry_price'],
                stop_loss=signal.get('stop_loss', 0),
                target=signal.get('target', 0),
                setup_type=signal.get('setup', '')
            )
            
            if not success:
                return False, msg
            
            # Fill order immediately (paper trading)
            order_id = list(self.engine.orders.keys())[-1]
            fill_success, fill_msg = self.engine.fill_order(
                order_id=order_id,
                fill_price=signal['entry_price'],
                fill_qty=qty
            )
            
            if fill_success:
                self.total_entries += 1
                signal['status'] = 'EXECUTED'
                
                log_entry = {
                    'timestamp': datetime.now().isoformat(),
                    'action': 'ENTRY',
                    'symbol': signal['symbol'],
                    'qty': qty,
                    'entry_price': signal['entry_price'],
                    'stop_loss': signal.get('stop_loss', 0),
                    'target': signal.get('target', 0),
                    'order_id': order_id,
                }
                self.execution_log.append(log_entry)
                
                return True, fill_msg
            else:
                return False, fill_msg
        
        except Exception as e:
            return False, f"Error executing signal: {str(e)}"
    
    def exit_position(self, symbol: str, exit_price: float,
                     exit_reason: str = "MANUAL") -> Tuple[bool, dict]:
        """Exit a position."""
        try:
            if symbol not in self.engine.positions:
                return False, {'error': f"Position {symbol} not found"}
            
            success, trade = self.engine.close_position(
                symbol=symbol,
                exit_price=exit_price,
                exit_reason=exit_reason
            )
            
            if success:
                self.total_exits += 1
                
                log_entry = {
                    'timestamp': datetime.now().isoformat(),
                    'action': 'EXIT',
                    'symbol': symbol,
                    'entry_price': trade.entry_price,
                    'exit_price': exit_price,
                    'qty': trade.qty,
                    'pnl': trade.net_pnl,
                    'pnl_pct': trade.net_pnl_pct,
                    'reason': exit_reason,
                }
                self.execution_log.append(log_entry)
                
                return True, {
                    'symbol': symbol,
                    'pnl': trade.net_pnl,
                    'pnl_pct': trade.net_pnl_pct,
                    'reason': exit_reason,
                }
            else:
                return False, {'error': 'Failed to close position'}
        
        except Exception as e:
            return False, {'error': str(e)}
    
    def update_market_prices(self, prices: Dict[str, float]) -> None:
        """Update market prices for open positions."""
        for symbol, price in prices.items():
            self.engine.update_position(symbol, price)
    
    def check_stop_targets(self) -> List[Tuple[str, str, float]]:
        """Check if any positions hit stop/target."""
        actions = []
        
        for symbol, pos in list(self.engine.positions.items()):
            # Check target
            if pos.current_price >= pos.target:
                actions.append((symbol, 'TARGET', pos.target))
            # Check stop
            elif pos.current_price <= pos.stop_loss:
                actions.append((symbol, 'STOP', pos.stop_loss))
        
        return actions
    
    def get_status(self) -> dict:
        """Get panel status."""
        return {
            'is_running': self.is_running,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'current_time': datetime.now().isoformat(),
            'uptime_seconds': (datetime.now() - self.started_at).total_seconds() if self.started_at else 0,
            'engine_summary': self.engine.get_portfolio_summary(),
            'pending_signals': len(self.pending_signals),
            'open_positions': len(self.engine.positions),
            'total_signals': self.total_signals,
            'total_entries': self.total_entries,
            'total_exits': self.total_exits,
        }
    
    def print_status(self) -> None:
        """Print panel status."""
        status = self.get_status()
        
        print("\n" + "=" * 100)
        print("LIVE TRADING PANEL STATUS")
        print("=" * 100)
        
        print(f"\nPanel Status:       {'RUNNING ✅' if status['is_running'] else 'STOPPED ❌'}")
        print(f"Started:            {status['started_at']}")
        print(f"Uptime:             {status['uptime_seconds']:.0f} seconds")
        print(f"Current Time:       {status['current_time']}")
        
        print(f"\nSignals & Entries:")
        print(f"  Total Signals:    {status['total_signals']}")
        print(f"  Pending Signals:  {status['pending_signals']}")
        print(f"  Total Entries:    {status['total_entries']}")
        print(f"  Total Exits:      {status['total_exits']}")
        
        print(f"\nPortfolio:")
        summary = status['engine_summary']
        print(f"  Capital:          ₹{summary['current_equity']:>12,.0f}")
        print(f"  Return:           {summary['total_return_pct']:>12.2f}%")
        print(f"  Open Positions:   {summary['open_positions']:>12}")
        print(f"  Win Rate:         {summary['win_rate']:>12.1f}%")
        
        print("\n" + "=" * 100)
    
    def export_all(self, output_dir: str = "algodesk/paper_trading_logs") -> None:
        """Export all data and logs."""
        try:
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            
            # Export trades
            self.engine.export_trades(f"{output_dir}/trades.csv")
            
            # Export daily
            self.engine.export_daily(f"{output_dir}/daily.csv")
            
            # Export state
            self.engine.export_state(f"{output_dir}/state.json")
            
            # Export execution log
            with open(f"{output_dir}/execution_log.json", 'w') as f:
                json.dump(self.execution_log, f, indent=2)
            
            # Export signal history
            with open(f"{output_dir}/signal_history.json", 'w') as f:
                json.dump(self.signal_history, f, indent=2)
            
            print(f"✅ Exported all data to {output_dir}/")
        except Exception as e:
            print(f"❌ Error exporting data: {e}")


# Deployment script
def deploy_paper_trading_panel(initial_capital: float = 250000.0) -> LiveTradingPanel:
    """Deploy paper trading panel with specified capital."""
    
    print("\n" + "=" * 100)
    print("DEPLOYING PAPER TRADING PANEL")
    print("=" * 100)
    
    # Create engine
    engine = PaperTradingEngine(
        initial_capital=initial_capital,
        name=f"Paper_Trading_{int(initial_capital/1000)}K"
    )
    print(f"✅ Engine created: {engine.name}")
    print(f"   Initial Capital: ₹{initial_capital:,.0f}")
    
    # Create panel
    panel = LiveTradingPanel(engine)
    print(f"✅ Panel initialized")
    
    # Start panel
    success, msg = panel.start()
    if success:
        print(f"✅ {msg}")
    else:
        print(f"❌ {msg}")
    
    print("\n" + "=" * 100)
    print("PANEL READY FOR TRADING")
    print("=" * 100)
    print(f"\nUsage:")
    print(f"  1. panel.process_signal(signal_dict)      - Process trading signal")
    print(f"  2. panel.execute_signal(signal_id, qty)    - Execute signal as order")
    print(f"  3. panel.update_market_prices(prices)      - Update live prices")
    print(f"  4. panel.check_stop_targets()              - Check stop/target hits")
    print(f"  5. panel.exit_position(symbol, price)      - Exit position manually")
    print(f"  6. panel.print_status()                    - Print status")
    print(f"  7. panel.export_all()                      - Export all data")
    print("\n" + "=" * 100)
    
    return panel


if __name__ == "__main__":
    # Deploy the panel
    panel = deploy_paper_trading_panel(initial_capital=250000.0)
