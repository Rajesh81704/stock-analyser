#!/usr/bin/env python3
"""
Hourly NIFTY 500 Scanner with Automatic Entry System
Runs every hour (market hours), scans all NIFTY 500 stocks
Detects EMA Pullback + 52WH Breakout signals
Automatically enters trades in paper trading engine
"""

import sys
import logging
from pathlib import Path
from datetime import datetime, time
import pandas as pd
import pytz
from typing import List, Dict, Optional

sys.path.insert(0, str(Path(__file__).parent))

from algodesk.strategies.ema_pullback_adx import EMAPullbackADXStrategy
from src.algodesk.strategies.breakout_52wh import BreakoutHighStrategy
from algodesk.execution.paper_trading import PaperTradingEngine
from algodesk.data.fetch import fetch_stock_data

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('algodesk/paper_trading_logs/nifty500_scan.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Market hours (IST)
MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)
IST = pytz.timezone('Asia/Kolkata')


class NIFTY500Scanner:
    """Scans NIFTY 500 for trading signals every hour"""
    
    def __init__(self, ema_engine: PaperTradingEngine, breakout_engine: PaperTradingEngine):
        """Initialize scanner with dual engines"""
        self.ema_engine = ema_engine
        self.breakout_engine = breakout_engine
        
        # Load NIFTY 500 symbols
        self.symbols = self._load_nifty500_symbols()
        logger.info(f"Loaded {len(self.symbols)} NIFTY 500 stocks")
        
        # Initialize strategies
        self.ema_strategy = EMAPullbackADXStrategy(config={
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
                'max_stop_atr': 1.5,  # TIGHT
            },
            'setup': {
                'gap_max_atr': 0.5,
            },
            'filters': {
                'min_traded_value_20d': 1_000_000,
                'skip_circuit_limit': 0.95,
            }
        })
        
        self.breakout_strategy = BreakoutHighStrategy(config={})
        
        # Stats
        self.scan_count = 0
        self.signals_found = []
        self.entries_made = []
        self.errors = []
        
    def _load_nifty500_symbols(self) -> List[str]:
        """Load NIFTY 500 symbols from CSV"""
        try:
            df = pd.read_csv('ind_nifty500list.csv')
            return df['Symbol'].tolist()
        except Exception as e:
            logger.error(f"Failed to load NIFTY 500 list: {e}")
            return []
    
    def is_market_hours(self) -> bool:
        """Check if current time is within market hours"""
        now = datetime.now(IST).time()
        return MARKET_OPEN <= now <= MARKET_CLOSE
    
    def scan_symbol(self, symbol: str) -> Optional[Dict]:
        """Scan single symbol for signals"""
        try:
            # Fetch daily data (1-2 years for backtest context)
            df = fetch_stock_data(symbol, start_date='2024-01-01', interval='1d')
            
            if df is None or len(df) < 100:
                return None  # Not enough data
            
            # Context for strategy
            ctx = {'symbol': symbol}
            
            # Scan EMA Pullback
            ema_setup = self.ema_strategy.scan(df, ctx)
            if ema_setup:
                return {
                    'symbol': symbol,
                    'strategy': 'EMA_Pullback',
                    'setup': ema_setup,
                    'timestamp': datetime.now(IST).isoformat(),
                }
            
            # Scan 52WH Breakout
            breakout_setup = self.breakout_strategy.scan(df, ctx)
            if breakout_setup:
                return {
                    'symbol': symbol,
                    'strategy': 'Breakout52WH',
                    'setup': breakout_setup,
                    'timestamp': datetime.now(IST).isoformat(),
                }
            
            return None
            
        except Exception as e:
            self.errors.append({'symbol': symbol, 'error': str(e)})
            logger.debug(f"Error scanning {symbol}: {e}")
            return None
    
    def scan_all(self) -> List[Dict]:
        """Scan all NIFTY 500 stocks for signals"""
        logger.info(f"Starting scan of {len(self.symbols)} stocks...")
        self.scan_count += 1
        
        signals = []
        for i, symbol in enumerate(self.symbols):
            signal = self.scan_symbol(symbol)
            if signal:
                signals.append(signal)
                self.signals_found.append(signal)
            
            # Progress logging every 50 stocks
            if (i + 1) % 50 == 0:
                logger.info(f"Scanned {i+1}/{len(self.symbols)} stocks, {len(signals)} signals found")
        
        logger.info(f"Scan complete: {len(signals)} signals found from {len(self.symbols)} stocks")
        return signals
    
    def process_signal(self, signal: Dict) -> bool:
        """Process signal and enter trade"""
        try:
            symbol = signal['symbol']
            strategy_name = signal['strategy']
            setup = signal['setup']
            
            # Choose engine based on strategy
            if strategy_name == 'EMA_Pullback':
                engine = self.ema_engine
                entry_reason = f"EMA Pullback: {setup.kind} at {setup.trigger:.2f}"
            else:
                engine = self.breakout_engine
                entry_reason = f"52WH Breakout at {setup.trigger:.2f}"
            
            # Check if already in position
            if symbol in engine.positions:
                logger.warning(f"{symbol}: Already in position, skipping")
                return False
            
            # Check risk management
            if not self._check_portfolio_limits(symbol, engine):
                logger.warning(f"{symbol}: Portfolio limits exceeded")
                return False
            
            # Calculate position size (1% risk)
            risk_amount = engine.equity * 0.01  # 1% risk
            position_size = int(risk_amount / setup.risk)
            
            # Verify minimum requirements
            if position_size < 1:
                logger.warning(f"{symbol}: Position size too small ({position_size})")
                return False
            
            # Enter trade
            order_id = engine.open_position(
                symbol=symbol,
                qty=position_size,
                entry_price=setup.trigger,
                stop_loss=setup.stop,
                target=setup.target1,
                reason=entry_reason
            )
            
            if order_id:
                self.entries_made.append({
                    'symbol': symbol,
                    'strategy': strategy_name,
                    'entry_price': setup.trigger,
                    'stop': setup.stop,
                    'target': setup.target1,
                    'qty': position_size,
                    'risk': risk_amount,
                    'rr': setup.rr,
                    'timestamp': signal['timestamp'],
                    'order_id': order_id,
                })
                
                logger.info(f"✅ ENTRY: {symbol} @ {setup.trigger:.2f} | SL: {setup.stop:.2f} | TGT: {setup.target1:.2f} | QTY: {position_size} | RR: {setup.rr:.2f}")
                return True
            else:
                logger.error(f"Failed to create order for {symbol}")
                return False
                
        except Exception as e:
            logger.error(f"Error processing signal for {signal.get('symbol')}: {e}")
            return False
    
    def _check_portfolio_limits(self, symbol: str, engine: PaperTradingEngine) -> bool:
        """Check if symbol passes portfolio limits"""
        # Max 5 positions total (shared across both engines)
        total_positions = len(self.ema_engine.positions) + len(self.breakout_engine.positions)
        if total_positions >= 5:
            return False
        
        # Max 2 per sector (simplified - would need sector mapping)
        # For now, allow duplicate sectors but limit to 5 total
        
        return True
    
    def hourly_scan_and_enter(self) -> Dict:
        """Run hourly scan and auto-enter trades"""
        timestamp = datetime.now(IST).isoformat()
        
        # Check market hours
        if not self.is_market_hours():
            logger.info(f"Outside market hours ({datetime.now(IST).strftime('%H:%M')}), skipping scan")
            return {
                'status': 'SKIPPED',
                'reason': 'Outside market hours',
                'timestamp': timestamp,
            }
        
        try:
            # Scan all stocks
            signals = self.scan_all()
            
            if not signals:
                logger.info("No signals found in this scan")
                return {
                    'status': 'COMPLETE',
                    'signals_found': 0,
                    'entries_made': 0,
                    'timestamp': timestamp,
                }
            
            # Process each signal
            entries = 0
            for signal in signals:
                if self.process_signal(signal):
                    entries += 1
            
            # Log results
            logger.info(f"Scan complete: {len(signals)} signals, {entries} entries")
            
            return {
                'status': 'COMPLETE',
                'signals_found': len(signals),
                'entries_made': entries,
                'ema_engine_equity': self.ema_engine.equity,
                'breakout_engine_equity': self.breakout_engine.equity,
                'timestamp': timestamp,
            }
            
        except Exception as e:
            logger.error(f"Error in hourly scan: {e}")
            return {
                'status': 'ERROR',
                'error': str(e),
                'timestamp': timestamp,
            }
    
    def get_stats(self) -> Dict:
        """Get scanner statistics"""
        return {
            'total_scans': self.scan_count,
            'total_signals': len(self.signals_found),
            'total_entries': len(self.entries_made),
            'errors': len(self.errors),
            'ema_equity': self.ema_engine.equity,
            'breakout_equity': self.breakout_engine.equity,
            'total_equity': self.ema_engine.equity + self.breakout_engine.equity,
            'ema_positions': len(self.ema_engine.positions),
            'breakout_positions': len(self.breakout_engine.positions),
        }


def main():
    """Main entry point"""
    logger.info("="*100)
    logger.info("NIFTY 500 HOURLY SCANNER - AUTO ENTRY SYSTEM")
    logger.info("="*100)
    
    # Create engines
    ema_engine = PaperTradingEngine(initial_capital=125_000, name="EMA_Pullback_Scanner")
    breakout_engine = PaperTradingEngine(initial_capital=125_000, name="Breakout52WH_Scanner")
    
    logger.info(f"✅ EMA Engine: ₹{ema_engine.equity:,.0f}")
    logger.info(f"✅ Breakout Engine: ₹{breakout_engine.equity:,.0f}")
    logger.info(f"✅ Total Capital: ₹{ema_engine.equity + breakout_engine.equity:,.0f}")
    
    # Create scanner
    scanner = NIFTY500Scanner(ema_engine, breakout_engine)
    
    # Run single scan
    logger.info("\nStarting first scan...")
    result = scanner.hourly_scan_and_enter()
    
    logger.info(f"\nScan Result: {result}")
    logger.info(f"\nScanner Stats: {scanner.get_stats()}")
    
    # Log entries made
    if scanner.entries_made:
        logger.info("\n" + "="*100)
        logger.info("ENTRIES MADE THIS SCAN")
        logger.info("="*100)
        for entry in scanner.entries_made:
            logger.info(f"{entry['symbol']}: {entry['entry_price']:.2f} | SL: {entry['stop']:.2f} | TGT: {entry['target']:.2f} | QTY: {entry['qty']} | RR: {entry['rr']:.2f}")
    
    logger.info("\n✅ Scanner ready for scheduling")


if __name__ == "__main__":
    main()
