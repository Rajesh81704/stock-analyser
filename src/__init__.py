"""
Stock Market Data Acquisition Package
"""

from src.data_loader import fetch_stock_data, resolve_ticker, validate_data_sufficiency

__all__ = [
    "fetch_stock_data",
    "resolve_ticker",
    "validate_data_sufficiency",
]
