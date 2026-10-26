"""
NIFTY 500 Equities Master & Market-Type Categorization Service.

Provides:
- 501 Nifty 500 constituents with Industry and Market-Cap classification (Large, Mid, Small).
- Point-in-time latest prices, volumes, and percentage returns from local database / Kite.
- High-performance filtering by Market Cap Type and Sector.
"""

from __future__ import annotations
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional
import pandas as pd

# Top blue-chip large caps in NIFTY 100
LARGE_CAP_SYMBOLS = {
    "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY", "BHARTIARTL", "ITC", "SBIN", "LT", "HINDUNILVR",
    "BAJFINANCE", "HCLTECH", "MARUTI", "SUNPHARMA", "TATAMOTORS", "AXISBANK", "NTPC", "ONGC", "KOTAKBANK",
    "TITAN", "POWERGRID", "ADANIENT", "COALINDIA", "ULTRACEMCO", "M&M", "TATASTEEL", "BAJAJFINSV", "JSWSTEEL",
    "ADANIPORTS", "ASIANPAINT", "WIPRO", "SIEMENS", "DMART", "NESTLEIND", "HAL", "IOC", "BEL", "GRASIM",
    "DLF", "ZOMATO", "TECHM", "SBILIFE", "VEDL", "LICI", "PFC", "RECLTD", "HDFCLIFE", "INDUSINDBK", "ADANIPOWER",
    "BRITANNIA", "GODREJCP", "CHOLAFIN", "HAVELLS", "PIDILITIND", "GAIL", "EICHERMOT", "SHRIRAMFIN", "TRENT",
    "BANKBARODA", "ABB", "AMBUJACEM", "CIPLA", "TVSMOTOR", "BPCL", "DABUR", "DRREDDY", "APOLLOHOSP", "DIVISLAB",
    "BAJAJ-AUTO", "INDIGO", "PNB", "CANBK", "JIOFIN", "POLYCAB", "PERSISTENT", "LTIM", "MAXHEALTH", "TATAPOWER",
    "IRFC", "UNIONBANK", "CGPOWER", "DIXON", "CUMMINSIND", "COLPAL", "MOTHERSON", "BERGEPAINT", "JSWENERGY",
    "PHOENIXLTD", "BOSCHLTD", "TORNTPOWER", "SUPREMEIND", "IDFCFIRSTB", "PETRONET", "AUROPHARMA", "MARICO",
    "SOLARINDS", "PRESTIGE", "POLICYBZR", "OBEROIRLTY", "INDIANB", "NHPC", "LUPIN", "SUZLON"
}

# Standardized Sector Buckets
SECTOR_MAPPING = {
    "Financial Services": "Financials",
    "Information Technology": "Technology",
    "Healthcare": "Healthcare",
    "Automobile and Auto Components": "Automobile",
    "Fast Moving Consumer Goods": "FMCG",
    "Consumer Durables": "Consumer",
    "Consumer Services": "Consumer",
    "Power": "Energy & Power",
    "Oil Gas & Consumable Fuels": "Energy & Power",
    "Metals & Mining": "Metals & Mining",
    "Capital Goods": "Capital Goods",
    "Chemicals": "Chemicals",
    "Construction": "Infra & Realty",
    "Construction Materials": "Infra & Realty",
    "Realty": "Infra & Realty",
    "Telecommunication": "Telecom & Media",
    "Media Entertainment & Publication": "Telecom & Media",
    "Services": "Services",
    "Textiles": "Textiles & Misc",
    "Diversified": "Textiles & Misc",
}

_CACHE: Optional[List[Dict[str, Any]]] = None


class Nifty500Service:
    """Service for querying and categorizing NIFTY 500 stocks."""

    @classmethod
    def get_all_stocks(cls, force_reload: bool = False) -> List[Dict[str, Any]]:
        """Loads and returns all 501 NIFTY 500 constituents categorized by market type and industry."""
        global _CACHE
        if _CACHE is not None and not force_reload:
            return _CACHE

        csv_path = Path("ind_nifty500list.csv")
        if not csv_path.exists():
            csv_path = Path("data/ind_nifty500list.csv")

        if not csv_path.exists():
            return []

        df = pd.read_csv(csv_path)

        # Fetch latest prices from data/stock_screener.db if present
        prices_map: Dict[str, Dict[str, Any]] = {}
        db_path = Path("data/stock_screener.db")
        if db_path.exists():
            try:
                conn = sqlite3.connect(str(db_path))
                query = """
                    WITH ranked AS (
                        SELECT ticker, close, volume, date,
                               ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) as rn
                        FROM ohlcv_data
                    )
                    SELECT r1.ticker, r1.close as latest_close, r1.volume, r1.date,
                           r2.close as prev_close,
                           ROUND(((r1.close - r2.close) / r2.close) * 100, 2) as pct_change
                    FROM ranked r1
                    LEFT JOIN ranked r2 ON r1.ticker = r2.ticker AND r2.rn = 2
                    WHERE r1.rn = 1
                """
                p_df = pd.read_sql(query, conn)
                conn.close()
                for _, r in p_df.iterrows():
                    raw_ticker = str(r["ticker"]).replace(".NS", "")
                    prices_map[raw_ticker] = {
                        "close": float(r["latest_close"]) if pd.notnull(r["latest_close"]) else 0.0,
                        "volume": int(r["volume"]) if pd.notnull(r["volume"]) else 0,
                        "change_pct": float(r["pct_change"]) if pd.notnull(r["pct_change"]) else 0.0,
                        "date": str(r["date"]),
                    }
            except Exception:
                pass

        stocks = []
        for idx, row in df.iterrows():
            sym = str(row["Symbol"]).strip()
            name = str(row["Company Name"]).strip()
            industry = str(row["Industry"]).strip()

            # Determine Market Cap Type
            if sym in LARGE_CAP_SYMBOLS or idx < 100:
                market_cap = "Large Cap"
            elif idx < 250:
                market_cap = "Mid Cap"
            else:
                market_cap = "Small Cap"

            sector_group = SECTOR_MAPPING.get(industry, "Other")

            p_info = prices_map.get(sym, {"close": 0.0, "volume": 0, "change_pct": 0.0, "date": ""})

            stocks.append({
                "symbol": sym,
                "ticker": f"{sym}.NS",
                "name": name,
                "industry": industry,
                "sector_group": sector_group,
                "market_cap": market_cap,
                "series": str(row.get("Series", "EQ")),
                "isin": str(row.get("ISIN Code", "")),
                "close": p_info["close"],
                "volume": p_info["volume"],
                "change_pct": p_info["change_pct"],
                "date": p_info["date"],
            })

        _CACHE = stocks
        return stocks

    @classmethod
    def filter_stocks(
        cls,
        market_type: Optional[str] = None,
        sector: Optional[str] = None,
        query: Optional[str] = None,
        sort_by: str = "symbol",
        desc: bool = False,
    ) -> List[Dict[str, Any]]:
        """Filters stocks by market cap category, sector, and search keyword."""
        stocks = cls.get_all_stocks()

        if market_type and market_type.lower() != "all":
            mt_norm = market_type.lower().replace("-", " ").replace("_", " ")
            stocks = [s for s in stocks if s["market_cap"].lower() == mt_norm]

        if sector and sector.lower() != "all":
            sec_norm = sector.lower()
            stocks = [s for s in stocks if s["sector_group"].lower() == sec_norm or s["industry"].lower() == sec_norm]

        if query:
            q = query.lower().strip()
            stocks = [s for s in stocks if q in s["symbol"].lower() or q in s["name"].lower() or q in s["industry"].lower()]

        # Sorting
        if sort_by == "change":
            stocks = sorted(stocks, key=lambda x: x["change_pct"], reverse=desc)
        elif sort_by == "volume":
            stocks = sorted(stocks, key=lambda x: x["volume"], reverse=desc)
        elif sort_by == "price":
            stocks = sorted(stocks, key=lambda x: x["close"], reverse=desc)
        else:
            stocks = sorted(stocks, key=lambda x: x["symbol"], reverse=desc)

        return stocks

    @classmethod
    def get_summary_stats(cls) -> Dict[str, Any]:
        """Returns count statistics per market cap and sector."""
        stocks = cls.get_all_stocks()
        cap_counts: Dict[str, int] = {}
        sector_counts: Dict[str, int] = {}

        for s in stocks:
            mc = s["market_cap"]
            cap_counts[mc] = cap_counts.get(mc, 0) + 1
            sec = s["sector_group"]
            sector_counts[sec] = sector_counts.get(sec, 0) + 1

        return {
            "total": len(stocks),
            "by_market_cap": cap_counts,
            "by_sector": sector_counts,
        }
