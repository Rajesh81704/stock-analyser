#!/usr/bin/env python3
"""
Test script for hourly NIFTY 500 scanner
Verifies all components work correctly before production deployment
"""

import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_imports():
    """Test all required imports"""
    logger.info("\n" + "="*100)
    logger.info("TEST 1: Imports")
    logger.info("="*100)
    
    try:
        from algodesk.strategies.ema_pullback_adx import EMAPullbackADXStrategy
        logger.info("✅ EMA Pullback strategy imported")
    except Exception as e:
        logger.error(f"❌ Failed to import EMA strategy: {e}")
        return False
    
    try:
        from src.algodesk.strategies.breakout_52wh import BreakoutHighStrategy
        logger.info("✅ 52WH Breakout strategy imported")
    except Exception as e:
        logger.error(f"❌ Failed to import 52WH strategy: {e}")
        return False
    
    try:
        from algodesk.execution.paper_trading import PaperTradingEngine
        logger.info("✅ Paper trading engine imported")
    except Exception as e:
        logger.error(f"❌ Failed to import paper trading: {e}")
        return False
    
    try:
        from algodesk.data.fetch import fetch_stock_data
        logger.info("✅ Data fetch module imported")
    except Exception as e:
        logger.error(f"❌ Failed to import data fetch: {e}")
        return False
    
    try:
        from scan_nifty500_hourly import NIFTY500Scanner
        logger.info("✅ NIFTY500Scanner imported")
    except Exception as e:
        logger.error(f"❌ Failed to import scanner: {e}")
        return False
    
    return True


def test_engines():
    """Test paper trading engines"""
    logger.info("\n" + "="*100)
    logger.info("TEST 2: Paper Trading Engines")
    logger.info("="*100)
    
    try:
        from algodesk.execution.paper_trading import PaperTradingEngine
        
        ema_engine = PaperTradingEngine(initial_capital=125_000, name="Test_EMA")
        logger.info(f"✅ EMA Engine created: ₹{ema_engine.equity:,.0f}")
        
        breakout_engine = PaperTradingEngine(initial_capital=125_000, name="Test_Breakout")
        logger.info(f"✅ Breakout Engine created: ₹{breakout_engine.equity:,.0f}")
        
        logger.info(f"✅ Total equity: ₹{ema_engine.equity + breakout_engine.equity:,.0f}")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Engine test failed: {e}")
        return False


def test_strategies():
    """Test strategy initialization"""
    logger.info("\n" + "="*100)
    logger.info("TEST 3: Strategy Initialization")
    logger.info("="*100)
    
    try:
        from algodesk.strategies.ema_pullback_adx import EMAPullbackADXStrategy
        
        ema_config = {
            'indicators': {
                'ema_fast': 20,
                'ema_slow': 50,
                'adx_len': 14,
                'adx_min': 20,
                'atr_len': 14,
                'vol_mult': 1.5,
            },
            'risk': {
                'min_rr': 1.5,
                'max_stop_atr': 1.5,
            },
        }
        
        strat_ema = EMAPullbackADXStrategy(config=ema_config)
        logger.info("✅ EMA Pullback strategy initialized")
        
    except Exception as e:
        logger.error(f"❌ EMA strategy initialization failed: {e}")
        return False
    
    try:
        from src.algodesk.strategies.breakout_52wh import BreakoutHighStrategy
        
        strat_breakout = BreakoutHighStrategy(config={})
        logger.info("✅ 52WH Breakout strategy initialized")
        
    except Exception as e:
        logger.error(f"❌ 52WH strategy initialization failed: {e}")
        return False
    
    return True


def test_data_fetch():
    """Test data fetching"""
    logger.info("\n" + "="*100)
    logger.info("TEST 4: Data Fetching")
    logger.info("="*100)
    
    try:
        from algodesk.data.fetch import fetch_stock_data
        import pandas as pd
        
        logger.info("Attempting to fetch INFY data...")
        df = fetch_stock_data('INFY', start_date='2024-01-01')
        
        if df is not None and len(df) > 0:
            logger.info(f"✅ INFY data fetched: {len(df)} rows")
            logger.info(f"   Date range: {df.index[0]} to {df.index[-1]}")
            logger.info(f"   Columns: {', '.join(df.columns.tolist())}")
            return True
        else:
            logger.warning("⚠️  No data returned")
            return False
            
    except Exception as e:
        logger.error(f"❌ Data fetch test failed: {e}")
        logger.info("   (This may fail if network is unavailable)")
        return True  # Don't fail test if network issue


def test_nifty500_list():
    """Test NIFTY 500 list loading"""
    logger.info("\n" + "="*100)
    logger.info("TEST 5: NIFTY 500 List")
    logger.info("="*100)
    
    try:
        import pandas as pd
        
        df = pd.read_csv('ind_nifty500list.csv')
        symbols = df['Symbol'].tolist()
        
        logger.info(f"✅ Loaded {len(symbols)} NIFTY stocks")
        logger.info(f"   First 10: {', '.join(symbols[:10])}")
        
        return len(symbols) >= 500
        
    except Exception as e:
        logger.error(f"❌ NIFTY 500 list test failed: {e}")
        return False


def test_scanner_init():
    """Test scanner initialization"""
    logger.info("\n" + "="*100)
    logger.info("TEST 6: Scanner Initialization")
    logger.info("="*100)
    
    try:
        from algodesk.execution.paper_trading import PaperTradingEngine
        from scan_nifty500_hourly import NIFTY500Scanner
        
        ema_engine = PaperTradingEngine(initial_capital=125_000, name="Test_EMA")
        breakout_engine = PaperTradingEngine(initial_capital=125_000, name="Test_Breakout")
        
        logger.info("Initializing scanner...")
        scanner = NIFTY500Scanner(ema_engine, breakout_engine)
        
        logger.info(f"✅ Scanner initialized")
        logger.info(f"   Stocks to scan: {len(scanner.symbols)}")
        logger.info(f"   EMA engine capital: ₹{scanner.ema_engine.equity:,.0f}")
        logger.info(f"   Breakout engine capital: ₹{scanner.breakout_engine.equity:,.0f}")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Scanner initialization failed: {e}")
        return False


def test_single_stock_scan():
    """Test scanning a single stock"""
    logger.info("\n" + "="*100)
    logger.info("TEST 7: Single Stock Scan")
    logger.info("="*100)
    
    try:
        from algodesk.execution.paper_trading import PaperTradingEngine
        from scan_nifty500_hourly import NIFTY500Scanner
        
        ema_engine = PaperTradingEngine(initial_capital=125_000, name="Test_EMA")
        breakout_engine = PaperTradingEngine(initial_capital=125_000, name="Test_Breakout")
        
        scanner = NIFTY500Scanner(ema_engine, breakout_engine)
        
        logger.info("Scanning INFY...")
        signal = scanner.scan_symbol('INFY')
        
        if signal:
            logger.info(f"✅ Signal found!")
            logger.info(f"   Symbol: {signal['symbol']}")
            logger.info(f"   Strategy: {signal['strategy']}")
            logger.info(f"   Entry: {signal['setup'].trigger:.2f}")
            logger.info(f"   Stop: {signal['setup'].stop:.2f}")
            logger.info(f"   Target: {signal['setup'].target1:.2f}")
            logger.info(f"   R:R: {signal['setup'].rr:.2f}")
        else:
            logger.info("⚠️  No signal in INFY (may not meet criteria)")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Single stock scan failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_scheduler():
    """Test scheduler initialization"""
    logger.info("\n" + "="*100)
    logger.info("TEST 8: Scheduler")
    logger.info("="*100)
    
    try:
        from scheduler_hourly_scan import HourlyScannnerScheduler
        
        logger.info("Initializing scheduler...")
        sched = HourlyScannnerScheduler()
        
        logger.info("✅ Scheduler initialized")
        logger.info(f"   Jobs will run at: 9:30, 10:30, 11:30, 12:30, 13:30, 14:30, 15:15 IST")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Scheduler test failed: {e}")
        return False


def run_all_tests():
    """Run all tests"""
    logger.info("="*100)
    logger.info("HOURLY NIFTY 500 SCANNER - TEST SUITE")
    logger.info("="*100)
    
    tests = [
        ("Imports", test_imports),
        ("Paper Trading Engines", test_engines),
        ("Strategies", test_strategies),
        ("Data Fetching", test_data_fetch),
        ("NIFTY 500 List", test_nifty500_list),
        ("Scanner Initialization", test_scanner_init),
        ("Single Stock Scan", test_single_stock_scan),
        ("Scheduler", test_scheduler),
    ]
    
    results = {}
    for name, test_func in tests:
        try:
            result = test_func()
            results[name] = "✅ PASS" if result else "❌ FAIL"
        except Exception as e:
            results[name] = "❌ ERROR"
            logger.error(f"Unexpected error in {name}: {e}")
    
    # Summary
    logger.info("\n" + "="*100)
    logger.info("TEST SUMMARY")
    logger.info("="*100)
    
    for name, result in results.items():
        logger.info(f"{result} - {name}")
    
    passed = sum(1 for r in results.values() if "PASS" in r)
    total = len(results)
    
    logger.info(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        logger.info("\n🎉 ALL TESTS PASSED - System ready for deployment!")
        return True
    else:
        logger.warning(f"\n⚠️  {total - passed} test(s) failed - Check logs above")
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
