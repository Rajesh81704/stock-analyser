#!/usr/bin/env python3
"""Quick test of backtest components."""

import sys
sys.path.insert(0, '.')

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

logger.info("1. Testing synthetic data generation...")

def generate_synthetic_5m_candles(symbol, start_date, end_date, num_days=10):
    """Generate small synthetic dataset for quick testing."""
    np.random.seed(hash(symbol) % 2**32)
    
    returns = np.random.normal(0.0001, 0.02, num_days)
    daily_prices = 100 * np.exp(np.cumsum(returns))
    
    records = []
    current_date = pd.to_datetime(start_date)
    end_dt = pd.to_datetime(end_date)
    
    day_count = 0
    while current_date <= end_dt and day_count < num_days:
        if current_date.weekday() >= 5:
            current_date += timedelta(days=1)
            continue
        
        day_price = daily_prices[day_count]
        
        for bar_num in range(75):  # 75 bars = ~6.25 hours
            bar_time = current_date.replace(hour=9, minute=15) + timedelta(minutes=bar_num*5)
            if bar_time.hour > 15 or (bar_time.hour == 15 and bar_time.minute >= 31):
                break
            
            bar_return = np.random.normal(0, 0.02 / np.sqrt(75))
            open_price = day_price * (1 + bar_return)
            close_price = open_price * (1 + np.random.normal(0, 0.02 / np.sqrt(75)))
            high_price = max(open_price, close_price) * (1 + abs(np.random.normal(0, 0.02 / np.sqrt(150))))
            low_price = min(open_price, close_price) * (1 - abs(np.random.normal(0, 0.02 / np.sqrt(150))))
            volume = np.random.randint(10000, 100000)
            
            records.append({
                'datetime': bar_time,
                'open': open_price,
                'high': high_price,
                'low': low_price,
                'close': close_price,
                'volume': volume,
            })
        
        current_date += timedelta(days=1)
        day_count += 1
    
    df = pd.DataFrame(records)
    df['datetime'] = pd.to_datetime(df['datetime'])
    return df

logger.info("✓ Generating 10 days of synthetic data for RELIANCE.NS...")
df = generate_synthetic_5m_candles("RELIANCE.NS", "2022-10-01", "2022-10-31", num_days=10)
logger.info(f"✓ Generated {len(df)} bars")

logger.info("\n2. Testing StrategyConfig...")
from src.strategy.config import StrategyConfig
config = StrategyConfig()
logger.info(f"✓ Config created: top_n={config.top_n}, stop_atr={config.stop_atr}")

logger.info("\n3. Testing data loader...")
from src.data.loader import process_symbol_candles
logger.info("Processing symbol candles...")
store = process_symbol_candles("RELIANCE.NS", df, config)
if store:
    logger.info(f"✓ Store created: {len(store.bars_5m)} 5m bars, {len(store.daily_df)} days")
else:
    logger.error("✗ Store is None")

logger.info("\n✓ All quick tests passed!")
