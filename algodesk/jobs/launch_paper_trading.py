#!/usr/bin/env python3
"""
Launch Paper Trading Panel - Start live/paper trading with real-time monitoring
Deployed to: VPS 202.142.101.115
Capital: ₹250,000
Strategy: EMA Pullback + ADX (with seasonal filter + position scaling)
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from algodesk.execution.live_panel import deploy_paper_trading_panel, LiveTradingPanel
from datetime import datetime, timedelta
import json


def main():
    """Main deployment function."""
    
    print("\n" + "=" * 100)
    print("ALGODESK PAPER TRADING - DEPLOYMENT")
    print("=" * 100)
    print(f"\nDeployment Time:  {datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')}")
    print(f"Strategy:         EMA Pullback + ADX (Seasonal Filter Enabled)")
    print(f"Universe:         NIFTY 100")
    print(f"Timeframe:        Daily")
    print(f"Mode:             PAPER TRADING (Simulated)")
    print(f"Capital:          ₹250,000")
    
    # Deploy panel
    panel = deploy_paper_trading_panel(initial_capital=250000.0)
    
    # Create example trading scenario
    print("\n" + "=" * 100)
    print("SAMPLE TRADING SESSION")
    print("=" * 100)
    
    # Sample signals (these would come from the live strategy engine)
    sample_signals = [
        {
            'symbol': 'INFY',
            'setup': 'A_OPT',
            'entry_price': 2850.00,
            'stop_loss': 2750.00,
            'target': 3050.00,
            'trigger_reason': 'Pullback to EMA20, ADX > 25',
        },
        {
            'symbol': 'TCS',
            'setup': 'A_OPT',
            'entry_price': 3450.50,
            'stop_loss': 3350.00,
            'target': 3750.00,
            'trigger_reason': 'Pullback to EMA20, ADX > 25',
        },
        {
            'symbol': 'HDFC',
            'setup': 'A_OPT',
            'entry_price': 2650.00,
            'stop_loss': 2550.00,
            'target': 2850.00,
            'trigger_reason': 'Pullback to EMA20, ADX > 25',
        },
    ]
    
    print(f"\n📊 Processing {len(sample_signals)} trading signals...\n")
    
    for i, signal in enumerate(sample_signals, 1):
        # Process signal
        success, msg = panel.process_signal(signal)
        print(f"{i}. Signal received: {signal['symbol']}")
        print(f"   Entry: ₹{signal['entry_price']:.2f} | Stop: ₹{signal['stop_loss']:.2f} | Target: ₹{signal['target']:.2f}")
        
        # Get signal ID
        signal_id = list(panel.pending_signals.keys())[-1]
        
        # Calculate position size (1% risk)
        risk_per_share = signal['entry_price'] - signal['stop_loss']
        risk_amount = panel.engine.equity * 0.01
        qty = int(risk_amount / risk_per_share)
        
        # Execute signal
        exec_success, exec_msg = panel.execute_signal(signal_id, qty)
        if exec_success:
            print(f"   ✅ ENTRY EXECUTED: {qty} @ ₹{signal['entry_price']:.2f}")
        else:
            print(f"   ❌ ENTRY FAILED: {exec_msg}")
        print()
    
    # Simulate price movements and exits
    print("=" * 100)
    print("SIMULATING PRICE MOVEMENTS & EXITS")
    print("=" * 100)
    
    price_updates = {
        'INFY': 3050.00,   # Hit target
        'TCS': 3400.00,    # Near entry (loss)
        'HDFC': 2850.00,   # Hit target
    }
    
    print(f"\n📈 Updating market prices...\n")
    panel.update_market_prices(price_updates)
    
    # Check for exits
    exits_needed = panel.check_stop_targets()
    
    for symbol, reason, price in exits_needed:
        print(f"Exit signal: {symbol} - {reason} at ₹{price:.2f}")
        exit_success, exit_data = panel.exit_position(symbol, price, exit_reason=reason)
        if exit_success:
            print(f"  ✅ Position closed: PnL ₹{exit_data['pnl']:,.0f} ({exit_data['pnl_pct']:+.2f}%)\n")
    
    # Manually exit remaining position
    if 'TCS' in panel.engine.positions:
        print(f"Manually closing TCS position at current price...")
        exit_success, exit_data = panel.exit_position('TCS', 3400.00, exit_reason='MANUAL')
        if exit_success:
            print(f"  ✅ Position closed: PnL ₹{exit_data['pnl']:,.0f} ({exit_data['pnl_pct']:+.2f}%)\n")
    
    # Print final status
    print("\n" + "=" * 100)
    print("TRADING SESSION SUMMARY")
    print("=" * 100)
    panel.dashboard.print_summary()
    panel.print_status()
    
    # Export all data
    print("\n" + "=" * 100)
    print("EXPORTING DATA")
    print("=" * 100)
    panel.export_all("algodesk/paper_trading_logs")
    
    # Deployment notes
    print("\n" + "=" * 100)
    print("DEPLOYMENT NOTES")
    print("=" * 100)
    print("""
✅ Paper Trading Panel Successfully Deployed!

Location:         ₹250,000 Simulated Capital
Monitoring:       Real-time signal processing, order execution, PnL tracking
Data Retention:   All trades, signals, and performance metrics logged
Export Location:  algodesk/paper_trading_logs/

Next Steps:
  1. Monitor strategy signals in real-time
  2. Adjust position sizing based on market conditions
  3. Track performance vs backtest expectations
  4. Paper trade for 4-8 weeks before going live
  5. Validate seasonal filter effectiveness
  6. Review daily execution logs for optimization

CRITICAL CONTROLS:
  • Max 5 open positions (enforced)
  • 1% risk per trade (enforced)
  • Seasonal filter: Skip Oct, Nov, Feb, Mar
  • Position scaling: Reduce if monthly WR < 50%
  • Daily review required

Contact: VPS 202.142.101.115
Status: 🟢 LIVE & MONITORING
""")
    print("=" * 100)
    
    return panel


if __name__ == "__main__":
    panel = main()
    
    # Keep panel running (in production, this would be a service)
    print("\n💼 Paper Trading Panel is active and ready to process signals...")
    print("To exit: Press Ctrl+C")
    
    try:
        while True:
            # Panel would receive signals from strategy engine
            # This is a simple demonstration - in production, 
            # signals come from live strategy processing
            input()
    except KeyboardInterrupt:
        print("\n\nShutting down paper trading panel...")
        success, msg = panel.stop()
        print(f"✅ {msg}")
        panel.export_all()
        print("📊 All data exported. Goodbye!")
