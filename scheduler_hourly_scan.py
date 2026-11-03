#!/usr/bin/env python3
"""
APScheduler for Hourly NIFTY 500 Scans
Runs every hour during market hours (9:15 AM - 3:30 PM IST)
Automatically enters trades when signals detected
"""

import sys
import logging
from pathlib import Path
from datetime import datetime, time, timedelta
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import json

sys.path.insert(0, str(Path(__file__).parent))

from scan_nifty500_hourly import NIFTY500Scanner
from algodesk.execution.paper_trading import PaperTradingEngine

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('algodesk/paper_trading_logs/scheduler.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

IST = pytz.timezone('Asia/Kolkata')


class HourlyScannnerScheduler:
    """Manages hourly NIFTY 500 scanning"""
    
    def __init__(self):
        """Initialize scheduler"""
        self.scheduler = BackgroundScheduler(timezone=IST)
        self.scanner = None
        self.scan_history = []
        self.scan_results_file = 'algodesk/paper_trading_logs/hourly_scan_results.json'
        
        logger.info("Hourly Scanner Scheduler initialized")
    
    def initialize_engines(self):
        """Create trading engines"""
        self.ema_engine = PaperTradingEngine(
            initial_capital=125_000,
            name="EMA_Pullback_Scanner"
        )
        self.breakout_engine = PaperTradingEngine(
            initial_capital=125_000,
            name="Breakout52WH_Scanner"
        )
        
        self.scanner = NIFTY500Scanner(self.ema_engine, self.breakout_engine)
        
        logger.info(f"Engines initialized:")
        logger.info(f"  - EMA: ₹{self.ema_engine.equity:,.0f}")
        logger.info(f"  - Breakout: ₹{self.breakout_engine.equity:,.0f}")
    
    def scan_job(self):
        """Scheduled scan job"""
        try:
            now = datetime.now(IST)
            logger.info(f"\n{'='*100}")
            logger.info(f"HOURLY SCAN STARTING AT {now.strftime('%Y-%m-%d %H:%M:%S IST')}")
            logger.info(f"{'='*100}")
            
            # Run scan
            result = self.scanner.hourly_scan_and_enter()
            
            # Add to history
            self.scan_history.append({
                'timestamp': now.isoformat(),
                'result': result,
            })
            
            # Get stats
            stats = self.scanner.get_stats()
            
            # Log summary
            logger.info(f"\n✅ SCAN COMPLETE")
            logger.info(f"   Signals found: {result.get('signals_found', 0)}")
            logger.info(f"   Entries made: {result.get('entries_made', 0)}")
            logger.info(f"   EMA Equity: ₹{stats['ema_equity']:,.0f}")
            logger.info(f"   Breakout Equity: ₹{stats['breakout_equity']:,.0f}")
            logger.info(f"   Total Equity: ₹{stats['total_equity']:,.0f}")
            logger.info(f"   Open Positions: {stats['ema_positions'] + stats['breakout_positions']}")
            
            # Save results
            self._save_results()
            
            return result
            
        except Exception as e:
            logger.error(f"Error in scan job: {e}", exc_info=True)
            return {'status': 'ERROR', 'error': str(e)}
    
    def _save_results(self):
        """Save scan results to file"""
        try:
            data = {
                'last_update': datetime.now(IST).isoformat(),
                'total_scans': len(self.scan_history),
                'stats': self.scanner.get_stats() if self.scanner else {},
                'recent_scans': self.scan_history[-10:],  # Last 10 scans
                'entries_made': self.scanner.entries_made if self.scanner else [],
            }
            
            with open(self.scan_results_file, 'w') as f:
                json.dump(data, f, indent=2, default=str)
                
        except Exception as e:
            logger.error(f"Failed to save results: {e}")
    
    def start_scheduler(self):
        """Start the scheduler"""
        self.initialize_engines()
        
        logger.info("\n" + "="*100)
        logger.info("STARTING HOURLY SCHEDULER")
        logger.info("="*100)
        
        # Schedule jobs for each hour during market hours
        # 9:30 AM IST
        self.scheduler.add_job(
            self.scan_job,
            CronTrigger(hour=9, minute=30, day_of_week='mon-fri'),
            id='scan_09_30',
            name='Scan 09:30 AM'
        )
        
        # 10:30 AM IST
        self.scheduler.add_job(
            self.scan_job,
            CronTrigger(hour=10, minute=30, day_of_week='mon-fri'),
            id='scan_10_30',
            name='Scan 10:30 AM'
        )
        
        # 11:30 AM IST
        self.scheduler.add_job(
            self.scan_job,
            CronTrigger(hour=11, minute=30, day_of_week='mon-fri'),
            id='scan_11_30',
            name='Scan 11:30 AM'
        )
        
        # 12:30 PM IST
        self.scheduler.add_job(
            self.scan_job,
            CronTrigger(hour=12, minute=30, day_of_week='mon-fri'),
            id='scan_12_30',
            name='Scan 12:30 PM'
        )
        
        # 1:30 PM IST
        self.scheduler.add_job(
            self.scan_job,
            CronTrigger(hour=13, minute=30, day_of_week='mon-fri'),
            id='scan_13_30',
            name='Scan 1:30 PM'
        )
        
        # 2:30 PM IST
        self.scheduler.add_job(
            self.scan_job,
            CronTrigger(hour=14, minute=30, day_of_week='mon-fri'),
            id='scan_14_30',
            name='Scan 2:30 PM'
        )
        
        # 3:15 PM IST (final scan before close)
        self.scheduler.add_job(
            self.scan_job,
            CronTrigger(hour=15, minute=15, day_of_week='mon-fri'),
            id='scan_15_15',
            name='Scan 3:15 PM (Final)'
        )
        
        # Start scheduler
        self.scheduler.start()
        
        logger.info("\n✅ Scheduler started!")
        logger.info("Jobs scheduled:")
        for job in self.scheduler.get_jobs():
            logger.info(f"   - {job.name} ({job.trigger})")
        
        logger.info("\nMarket Hours: Mon-Fri 9:15 AM - 3:30 PM IST")
        logger.info("Scans run: 9:30 AM, 10:30 AM, 11:30 AM, 12:30 PM, 1:30 PM, 2:30 PM, 3:15 PM (7 scans/day)")
        logger.info("\nScheduler running... Press Ctrl+C to stop")
        
        return self.scheduler
    
    def run_forever(self):
        """Run scheduler forever"""
        try:
            self.scheduler.start()
            while True:
                pass
        except KeyboardInterrupt:
            logger.info("\nShutting down scheduler...")
            self.scheduler.shutdown()
            logger.info("✅ Scheduler stopped")


def main():
    """Main entry point"""
    logger.info("="*100)
    logger.info("NIFTY 500 HOURLY SCANNER - APScheduler")
    logger.info("="*100)
    
    scheduler = HourlyScannnerScheduler()
    scheduler.start_scheduler()
    scheduler.run_forever()


if __name__ == "__main__":
    main()
