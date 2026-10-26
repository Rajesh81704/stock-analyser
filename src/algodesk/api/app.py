"""
AlgoDesk: Personal Self-Hosted Intraday Algo Trading Platform.
Unified Application: Re-exports unified FastAPI application from web.app.
Provides Screener, Algo Desk Workstation, Backtester, Strategies & AI Quant in a single server.
"""

from web.app import (
    app,
    risk_engine,
    paper_broker,
    order_manager,
    gemini_client,
    templates,
    api_kite_status,
)

__all__ = [
    "app",
    "risk_engine",
    "paper_broker",
    "order_manager",
    "gemini_client",
    "templates",
    "api_kite_status",
]
