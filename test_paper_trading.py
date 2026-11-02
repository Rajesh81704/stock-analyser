#!/usr/bin/env python3
"""
Quick test of paper trading engine to verify equity tracking fix
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from algodesk.execution.paper_trading import PaperTradingEngine

def test_equity_tracking():
    """Test that equity is correctly tracked through entries and exits."""
    
    print("\n" + "="*80)
    print("PAPER TRADING ENGINE - EQUITY TRACKING TEST")
    print("="*80)
    
    # Create engine
    engine = PaperTradingEngine(initial_capital=250000.0, name="Test_Engine")
    print(f"\n✅ Engine created with ₹{engine.initial_capital:,.0f} capital")
    print(f"   Current equity: ₹{engine.equity:,.0f}")
    
    # Place and fill first order (INFY)
    print("\n📌 Scenario 1: INFY Entry")
    success, msg = engine.place_order(
        symbol='INFY',
        qty=25,
        side='BUY',
        entry_price=2850.0,
        stop_loss=2750.0,
        target=3050.0,
        setup_type='A_OPT'
    )
    print(f"   Order placed: {msg}")
    
    order_id = list(engine.orders.keys())[0]
    success, msg = engine.fill_order(order_id, fill_price=2850.0, fill_qty=25)
    print(f"   Order filled: {msg}")
    print(f"   Capital used: ₹{2850.0 * 25:,.0f}")
    print(f"   Remaining equity: ₹{engine.equity:,.0f}")
    
    # Place and fill second order (HDFC)
    print("\n📌 Scenario 2: HDFC Entry")
    success, msg = engine.place_order(
        symbol='HDFC',
        qty=17,
        side='BUY',
        entry_price=2650.0,
        stop_loss=2550.0,
        target=2850.0,
        setup_type='A_OPT'
    )
    print(f"   Order placed: {msg}")
    
    order_id = list(engine.orders.keys())[-1]
    success, msg = engine.fill_order(order_id, fill_price=2650.0, fill_qty=17)
    print(f"   Order filled: {msg}")
    print(f"   Capital used: ₹{2650.0 * 17:,.0f}")
    print(f"   Remaining equity: ₹{engine.equity:,.0f}")
    
    # Close INFY at target
    print("\n📌 Scenario 3: INFY Exit at Target (+₹5,000)")
    success, trade = engine.close_position('INFY', exit_price=3050.0, exit_reason='TARGET')
    print(f"   Position closed: {trade.symbol}")
    print(f"   PnL: ₹{trade.net_pnl:,.0f} ({trade.net_pnl_pct:+.2f}%)")
    print(f"   Capital returned + profit: ₹{engine.equity:,.0f}")
    
    # Close HDFC at target
    print("\n📌 Scenario 4: HDFC Exit at Target (+₹3,400)")
    success, trade = engine.close_position('HDFC', exit_price=2850.0, exit_reason='TARGET')
    print(f"   Position closed: {trade.symbol}")
    print(f"   PnL: ₹{trade.net_pnl:,.0f} ({trade.net_pnl_pct:+.2f}%)")
    print(f"   Capital returned + profit: ₹{engine.equity:,.0f}")
    
    # Print final summary
    print("\n" + "="*80)
    print("FINAL SUMMARY")
    print("="*80)
    summary = engine.get_portfolio_summary()
    print(f"Initial Capital:       ₹{summary['initial_capital']:,.0f}")
    print(f"Current Equity:        ₹{summary['current_equity']:,.0f}")
    print(f"Total Return:          {summary['total_return_pct']:+.2f}%")
    print(f"Closed PnL:            ₹{summary['closed_pnl']:,.0f}")
    print(f"Total Trades:          {summary['trades_count']}")
    print(f"Win Rate:              {summary['win_rate']:.1f}%")
    
    # Verify correctness
    expected_equity = 250000.0 + 5000.0 + 3400.0  # = ₹258,400
    actual_equity = summary['current_equity']
    
    print("\n" + "="*80)
    print("VERIFICATION")
    print("="*80)
    print(f"Expected Equity:       ₹{expected_equity:,.0f}")
    print(f"Actual Equity:         ₹{actual_equity:,.0f}")
    
    if abs(expected_equity - actual_equity) < 1.0:
        print("✅ PASS - Equity tracking is correct!")
        return True
    else:
        print(f"❌ FAIL - Equity mismatch: ₹{expected_equity - actual_equity:,.2f}")
        return False

if __name__ == "__main__":
    success = test_equity_tracking()
    sys.exit(0 if success else 1)
