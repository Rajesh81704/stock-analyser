"""
4-Year Daily Intraday Backtesting Engine for Top 100 Volume-Based NSE Stocks.

Backtests intraday trading on an everyday basis across the 100 most liquid,
highest-volume stocks on the National Stock Exchange of India over 4 full years (2022 to 2026).
Computes and logs:
  1. Detailed daily trade logs (every trade entry/exit/PnL)
  2. Per-stock 4-year performance summary (PnL, WinRate, PF, Best Trade for every stock)
  3. Everyday portfolio PnL & compounded equity curve into SQLite (data/stock_screener.db).
"""

import sys
import os
import json
import sqlite3
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import yfinance as yf

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
logger = logging.getLogger("Top100IntradayBacktester")

# Verified Top 100 Volume & Turnover-based Institutional Stocks on NSE
TOP_100_VOLUME_STOCKS = [
    "HDFCBANK.NS", "RELIANCE.NS", "ICICIBANK.NS", "SBIN.NS", "INFY.NS", "TCS.NS",
    "AXISBANK.NS", "TATASTEEL.NS", "KOTAKBANK.NS", "WIPRO.NS", "CANBK.NS", "VEDL.NS",
    "NMDC.NS", "PNB.NS", "ITC.NS", "JIOFIN.NS", "BHARTIARTL.NS", "BAJFINANCE.NS",
    "COALINDIA.NS", "NTPC.NS", "POWERGRID.NS", "BPCL.NS", "BEL.NS", "HINDALCO.NS",
    "TATAPOWER.NS", "DLF.NS", "HCLTECH.NS", "MARUTI.NS", "SUNPHARMA.NS", "LT.NS",
    "ASIANPAINT.NS", "TITAN.NS", "BAJAJFINSV.NS", "M&M.NS", "JSWSTEEL.NS", "ADANIENT.NS",
    "ADANIPORTS.NS", "BHEL.NS", "BANKBARODA.NS", "PFC.NS", "RECLTD.NS", "GAIL.NS",
    "ONGC.NS", "IOC.NS", "NATIONALUM.NS", "FEDERALBNK.NS", "HINDUNILVR.NS", "TATACOMM.NS",
    "GRASIM.NS", "ULTRACEMCO.NS", "TECHM.NS", "INDUSINDBK.NS", "HEROMOTOCO.NS", "EICHERMOT.NS",
    "HINDZINC.NS", "APOLLOHOSP.NS", "CIPLA.NS", "DIVISLAB.NS", "DRREDDY.NS", "TRENT.NS",
    "HAL.NS", "IRFC.NS", "RVNL.NS", "IREDA.NS", "BSE.NS", "VBL.NS", "CHOLAFIN.NS",
    "SHRIRAMFIN.NS", "INDUSTOWER.NS", "POLYCAB.NS", "CUMMINSIND.NS", "PERSISTENT.NS",
    "AUROPHARMA.NS", "LUPIN.NS", "ASHOKLEY.NS", "IDFCFIRSTB.NS", "BANDHANBNK.NS",
    "AMBUJACEM.NS", "SIEMENS.NS", "ABB.NS", "HAVELLS.NS", "DABUR.NS", "GODREJCP.NS",
    "PIDILITIND.NS", "BERGEPAINT.NS", "COLPAL.NS", "MARICO.NS", "BRITANNIA.NS",
    "NESTLEIND.NS", "VOLTAS.NS", "UBL.NS", "TORNTPHARM.NS", "BIOCON.NS", "CONCOR.NS",
    "EXIDEIND.NS", "IGL.NS", "MGL.NS", "PETRONET.NS", "MUTHOOTFIN.NS", "LICHSGFIN.NS"
]


class Top100IntradayBacktester:
    """
    4-Year Intraday Backtesting Engine across Top 100 Volume Stocks with
    per-stock and everyday SQLite logging.
    """

    def __init__(
        self,
        db_path: str = "data/stock_screener.db",
        cache_dir: str = "data/top100_cache",
        initial_capital: float = 100000.0,
        risk_per_trade: float = 50000.0,
        years: int = 4
    ):
        self.db_path = Path(db_path)
        self.cache_dir = Path(cache_dir)
        self.initial_capital = initial_capital
        self.risk_per_trade = risk_per_trade
        self.years = years
        self.tickers = TOP_100_VOLUME_STOCKS

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._init_db_tables()

    def _init_db_tables(self):
        """Initializes tables for individual trade logs, per-stock summaries, and daily equity summaries."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        cur = conn.cursor()

        # Table 1: Individual daily trade logs (all trades taken)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS top100_daily_trade_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_date TEXT NOT NULL,
                ticker TEXT NOT NULL,
                strategy_name TEXT NOT NULL,
                side TEXT NOT NULL,
                entry_price REAL NOT NULL,
                exit_price REAL NOT NULL,
                exit_reason TEXT NOT NULL,
                qty INTEGER NOT NULL,
                gross_pnl REAL NOT NULL,
                net_pnl REAL NOT NULL,
                return_pct REAL NOT NULL,
                is_win INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # Table 2: Per-stock 4-year performance summary (each stock chosen)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS top100_stock_pnl_summary (
                ticker TEXT PRIMARY KEY,
                company_name TEXT,
                total_trades INTEGER NOT NULL,
                win_trades INTEGER NOT NULL,
                loss_trades INTEGER NOT NULL,
                win_rate REAL NOT NULL,
                total_net_pnl REAL NOT NULL,
                total_gross_pnl REAL NOT NULL,
                profit_factor REAL NOT NULL,
                avg_trade_pnl REAL NOT NULL,
                best_trade_pnl REAL NOT NULL,
                worst_trade_pnl REAL NOT NULL,
                first_trade_date TEXT,
                last_trade_date TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # Table 3: Daily portfolio summary (every single calendar trading day)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS top100_daily_pnl_summary (
                date TEXT PRIMARY KEY,
                trades_count INTEGER NOT NULL,
                win_trades INTEGER NOT NULL,
                loss_trades INTEGER NOT NULL,
                daily_gross_pnl REAL NOT NULL,
                daily_net_pnl REAL NOT NULL,
                daily_return_pct REAL NOT NULL,
                cumulative_net_pnl REAL NOT NULL,
                portfolio_equity REAL NOT NULL,
                drawdown_pct REAL NOT NULL,
                stocks_traded TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        cur.execute("CREATE INDEX IF NOT EXISTS idx_top100_logs_date ON top100_daily_trade_logs (trade_date);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_top100_logs_ticker ON top100_daily_trade_logs (ticker);")
        conn.commit()
        conn.close()

    def fetch_historical_data(self, force_refresh: bool = False) -> Dict[str, pd.DataFrame]:
        """Loads cached 4-year data or downloads in parallel chunks."""
        cached_data = {}
        missing_tickers = []

        for t in self.tickers:
            cache_file = self.cache_dir / f"{t}.parquet"
            if not force_refresh and cache_file.exists():
                try:
                    df = pd.read_parquet(cache_file)
                    if len(df) > 100:
                        cached_data[t] = df
                        continue
                except Exception:
                    pass
            missing_tickers.append(t)

        if missing_tickers:
            logger.info(f"Downloading {self.years} years data for {len(missing_tickers)} stocks in parallel batches...")
            # Download in chunks of 25 to maximize throughput and avoid Yahoo limits
            chunk_size = 25
            chunks = [missing_tickers[i:i + chunk_size] for i in range(0, len(missing_tickers), chunk_size)]

            for idx, chunk in enumerate(chunks, 1):
                try:
                    raw = yf.download(chunk, period=f"{self.years}y", group_by="ticker", progress=False)
                    for t in chunk:
                        try:
                            df = raw[t].copy() if len(chunk) > 1 else raw.copy()
                            df.dropna(subset=["Open", "High", "Low", "Close"], inplace=True)
                            if len(df) > 100:
                                cache_file = self.cache_dir / f"{t}.parquet"
                                df.to_parquet(cache_file)
                                cached_data[t] = df
                        except Exception as e:
                            logger.warning(f"Could not parse data for {t}: {e}")
                    logger.info(f"Batch {idx}/{len(chunks)} downloaded successfully ({len(cached_data)} total loaded).")
                except Exception as e:
                    logger.error(f"Error downloading batch {idx}: {e}")

        logger.info(f"Successfully prepared 4-year dataset for {len(cached_data)} / {len(self.tickers)} stocks.")
        return cached_data

    def run_backtest(
        self,
        strategy_name: str = "Top100_ORB_TrailingBreakeven_75",
        target_pct: float = 0.0135,       # 1.35% intraday profit target
        stop_loss_pct: float = 0.0065,    # 0.65% stop loss
        breakout_k: float = 0.25,         # Breakout above Open by 0.25 * ATR
        trailing_progress: float = 0.40,  # Move to breakeven after 40% progress toward target
        min_vol_mult: float = 1.15,       # Require 1.15x relative volume expansion
        max_daily_picks: int = 5          # Trade up to top 5 volume-expansion stocks per day
    ) -> Dict[str, Any]:
        """
        Executes daily intraday backtest across top 100 stocks for 4 years,
        logging every day's trade and each stock's PnL into SQLite.
        """
        data_by_sym = self.fetch_historical_data()
        if not data_by_sym:
            logger.error("No historical data available for backtesting.")
            return {}

        # Precompute indicators (ATR, Rolling Mean Volume)
        processed = {}
        all_dates = set()

        for t, df in data_by_sym.items():
            df = df.copy()
            df.index = pd.to_datetime(df.index).strftime("%Y-%m-%d")

            high = df["High"].values
            low = df["Low"].values
            close = df["Close"].values

            prev_close = np.roll(close, 1)
            prev_close[0] = close[0]

            tr = np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
            df["ATR"] = pd.Series(tr, index=df.index).rolling(14, min_periods=5).mean().bfill()
            df["MeanVol"] = df["Volume"].rolling(20, min_periods=5).mean().bfill()

            processed[t] = df
            all_dates.update(df.index)

        sorted_dates = sorted(list(all_dates))
        logger.info(f"Running daily intraday simulation over {len(sorted_dates)} trading dates across {len(processed)} stocks...")

        conn = sqlite3.connect(str(self.db_path))
        cur = conn.cursor()

        # Clear existing logs for fresh run
        cur.execute("DELETE FROM top100_daily_trade_logs;")
        cur.execute("DELETE FROM top100_stock_pnl_summary;")
        cur.execute("DELETE FROM top100_daily_pnl_summary;")
        conn.commit()

        cumulative_net_pnl = 0.0
        peak_equity = self.initial_capital
        daily_summaries = []
        all_trade_logs = []

        total_trades = 0
        total_wins = 0
        total_losses = 0

        # Dictionary tracking per-stock trade results
        stock_stats: Dict[str, Dict[str, Any]] = {
            t: {
                "trades": [],
                "wins": 0,
                "losses": 0,
                "gross_pnl": 0.0,
                "net_pnl": 0.0,
                "dates": []
            }
            for t in processed.keys()
        }

        # Daily simulation loop
        for d in sorted_dates:
            day_trades = []
            day_candidates = []

            for t in processed.keys():
                df = processed[t]
                if d not in df.index:
                    continue

                row = df.loc[d]
                idx_pos = df.index.get_loc(d)
                if idx_pos < 15:  # skip initial warm-up days
                    continue

                open_p = float(row["Open"])
                high_p = float(row["High"])
                low_p = float(row["Low"])
                close_p = float(row["Close"])
                vol = float(row["Volume"])
                atr = float(row["ATR"])
                mean_vol = float(row["MeanVol"])

                if open_p <= 0 or atr <= 0:
                    continue

                rvol = vol / max(1.0, mean_vol)
                if rvol >= min_vol_mult:
                    day_candidates.append({
                        "ticker": t,
                        "open": open_p,
                        "high": high_p,
                        "low": low_p,
                        "close": close_p,
                        "atr": atr,
                        "rvol": rvol
                    })

            # Pick top relative volume expansion stocks of the day
            day_candidates.sort(key=lambda x: x["rvol"], reverse=True)
            active_picks = day_candidates[:max_daily_picks]

            for cand in active_picks:
                t = cand["ticker"]
                open_p = cand["open"]
                high_p = cand["high"]
                low_p = cand["low"]
                close_p = cand["close"]
                atr = cand["atr"]

                breakout_buy = open_p + (breakout_k * atr)

                if high_p >= breakout_buy:
                    entry_p = breakout_buy * 1.0003
                    target_p = entry_p * (1.0 + target_pct)
                    initial_stop = entry_p * (1.0 - stop_loss_pct)

                    qty = int(self.risk_per_trade / entry_p)
                    if qty <= 0:
                        continue

                    # Trailing Stop to Breakeven after 40% target progress
                    breakeven_threshold = entry_p + ((target_p - entry_p) * trailing_progress)
                    trailing_activated = (high_p >= breakeven_threshold)
                    effective_stop = (entry_p * 1.001) if trailing_activated else initial_stop

                    if high_p >= target_p:
                        exit_p = target_p
                        exit_reason = "TARGET"
                    elif low_p <= effective_stop:
                        exit_p = effective_stop
                        exit_reason = "TRAILING_STOP" if trailing_activated else "STOP_LOSS"
                    else:
                        exit_p = close_p
                        exit_reason = "EOD"

                    gross_pnl = (exit_p - entry_p) * qty
                    cost = (entry_p + exit_p) * qty * 0.0003
                    net_pnl = round(gross_pnl - cost, 2)
                    ret_pct = round((net_pnl / (entry_p * qty)) * 100.0, 2)
                    is_win = 1 if net_pnl > 0 else 0

                    record = (
                        d, t, strategy_name, "BUY",
                        round(entry_p, 2), round(exit_p, 2), exit_reason,
                        qty, round(gross_pnl, 2), net_pnl, ret_pct, is_win
                    )
                    day_trades.append(record)
                    all_trade_logs.append(record)

                    # Update stock stats
                    st = stock_stats[t]
                    st["trades"].append(net_pnl)
                    st["gross_pnl"] += gross_pnl
                    st["net_pnl"] += net_pnl
                    st["dates"].append(d)
                    if is_win:
                        st["wins"] += 1
                        total_wins += 1
                    else:
                        st["losses"] += 1
                        total_losses += 1
                    total_trades += 1

            if day_trades:
                daily_gross = sum(tr[8] for tr in day_trades)
                daily_net = sum(tr[9] for tr in day_trades)
                daily_wins = sum(tr[11] for tr in day_trades)
                daily_losses = len(day_trades) - daily_wins
                stocks_traded_str = ",".join(tr[1] for tr in day_trades)
            else:
                daily_gross = 0.0
                daily_net = 0.0
                daily_wins = 0
                daily_losses = 0
                stocks_traded_str = ""

            cumulative_net_pnl += daily_net
            curr_equity = self.initial_capital + cumulative_net_pnl
            if curr_equity > peak_equity:
                peak_equity = curr_equity
            dd_pct = round(((peak_equity - curr_equity) / peak_equity) * 100.0, 2) if peak_equity > 0 else 0.0
            daily_ret_pct = round((daily_net / self.initial_capital) * 100.0, 3)

            daily_summaries.append((
                d, len(day_trades), daily_wins, daily_losses,
                round(daily_gross, 2), round(daily_net, 2), daily_ret_pct,
                round(cumulative_net_pnl, 2), round(curr_equity, 2), dd_pct,
                stocks_traded_str
            ))

        # Save Table 1: Individual daily trade logs
        logger.info(f"Saving {len(all_trade_logs)} individual trade logs to database...")
        cur.executemany("""
            INSERT INTO top100_daily_trade_logs (
                trade_date, ticker, strategy_name, side,
                entry_price, exit_price, exit_reason, qty,
                gross_pnl, net_pnl, return_pct, is_win
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, all_trade_logs)

        # Save Table 2: Per-stock 4-year performance summary
        per_stock_records = []
        for t, st in stock_stats.items():
            cnt = len(st["trades"])
            if cnt == 0:
                continue
            wins = st["wins"]
            losses = st["losses"]
            wr = round((wins / cnt) * 100.0, 1)
            tot_net = round(st["net_pnl"], 2)
            tot_gross = round(st["gross_pnl"], 2)

            pos_pnl = sum(p for p in st["trades"] if p > 0)
            neg_pnl = abs(sum(p for p in st["trades"] if p < 0))
            pf = round(pos_pnl / max(1.0, neg_pnl), 2)
            avg_pnl = round(tot_net / cnt, 2)
            best_trade = round(max(st["trades"]), 2)
            worst_trade = round(min(st["trades"]), 2)
            first_d = st["dates"][0] if st["dates"] else ""
            last_d = st["dates"][-1] if st["dates"] else ""
            clean_name = t.replace(".NS", "")

            per_stock_records.append((
                t, clean_name, cnt, wins, losses, wr,
                tot_net, tot_gross, pf, avg_pnl,
                best_trade, worst_trade, first_d, last_d
            ))

        logger.info(f"Saving {len(per_stock_records)} per-stock 4-year performance summaries to database...")
        cur.executemany("""
            INSERT INTO top100_stock_pnl_summary (
                ticker, company_name, total_trades, win_trades, loss_trades,
                win_rate, total_net_pnl, total_gross_pnl, profit_factor,
                avg_trade_pnl, best_trade_pnl, worst_trade_pnl,
                first_trade_date, last_trade_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, per_stock_records)

        # Save Table 3: Daily portfolio summaries
        logger.info(f"Saving {len(daily_summaries)} daily portfolio summaries to database...")
        cur.executemany("""
            INSERT INTO top100_daily_pnl_summary (
                date, trades_count, win_trades, loss_trades,
                daily_gross_pnl, daily_net_pnl, daily_return_pct,
                cumulative_net_pnl, portfolio_equity, drawdown_pct,
                stocks_traded
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, daily_summaries)

        conn.commit()
        conn.close()

        # Overall analytics
        win_rate = (total_wins / total_trades * 100.0) if total_trades > 0 else 0.0
        pos_sum = sum(t[8] for t in all_trade_logs if t[8] > 0)
        neg_sum = abs(sum(t[8] for t in all_trade_logs if t[8] < 0))
        pf = round(pos_sum / max(1.0, neg_sum), 2)
        total_ret_pct = round((cumulative_net_pnl / self.initial_capital) * 100.0, 2)
        max_dd = max([s[9] for s in daily_summaries], default=0.0)

        yearly_pnl = {}
        for s in daily_summaries:
            yr = s[0][:4]
            yearly_pnl[yr] = yearly_pnl.get(yr, 0.0) + s[5]

        result = {
            "strategy_name": strategy_name,
            "period_years": self.years,
            "universe_size": len(self.tickers),
            "stocks_traded_count": len(per_stock_records),
            "total_trading_days": len(sorted_dates),
            "days_traded": len([s for s in daily_summaries if s[1] > 0]),
            "total_trades": total_trades,
            "win_trades": total_wins,
            "loss_trades": total_losses,
            "win_rate_pct": round(win_rate, 1),
            "profit_factor": pf,
            "cumulative_net_pnl": round(cumulative_net_pnl, 2),
            "net_return_pct": total_ret_pct,
            "max_drawdown_pct": max_dd,
            "initial_capital": self.initial_capital,
            "ending_equity": round(self.initial_capital + cumulative_net_pnl, 2),
            "yearly_breakdown": {yr: round(pnl, 2) for yr, pnl in sorted(yearly_pnl.items())},
            "top_stocks": sorted(per_stock_records, key=lambda x: x[6], reverse=True)[:10]
        }

        self._print_performance_report(result)
        return result

    def _print_performance_report(self, r: Dict[str, Any]):
        """Prints terminal summary."""
        print("\n" + "=" * 75)
        print(" 🎯 TOP 100 VOLUME-BASED NSE STOCKS - 4-YEAR EVERYDAY INTRADAY REPORT")
        print("=" * 75)
        print(f" Strategy Name        : {r['strategy_name']}")
        print(f" Universe Analyzed    : Top {r['universe_size']} Volume NSE Stocks")
        print(f" Distinct Stocks Traded: {r['stocks_traded_count']} Stocks")
        print(f" Backtest Horizon     : {r['period_years']} Years ({r['total_trading_days']} Trading Days)")
        print(f" Days Traded          : {r['days_traded']} Days")
        print(f" Total Trades Taken   : {r['total_trades']:,}")
        print(f" Win Trades / Losses  : {r['win_trades']:,} Wins / {r['loss_trades']:,} Losses")
        print(f" Overall Win Rate     : ⭐ {r['win_rate_pct']}%")
        print(f" Profit Factor        : 🚀 {r['profit_factor']}")
        print(f" Initial Capital      : ₹{r['initial_capital']:,.2f}")
        print(f" Total Net PnL        : +₹{r['cumulative_net_pnl']:,.2f} ({r['net_return_pct']:+,.2f}%)")
        print(f" Ending Equity        : ₹{r['ending_equity']:,.2f}")
        print(f" Maximum Drawdown     : {r['max_drawdown_pct']}%")
        print("-" * 75)
        print(" 📅 YEARLY PnL BREAKDOWN:")
        for yr, pnl in r["yearly_breakdown"].items():
            print(f"   • Year {yr} : +₹{pnl:,.2f}")
        print("-" * 75)
        print(" 🏆 TOP 10 MOST PROFITABLE STOCKS OVER 4 YEARS:")
        for st in r["top_stocks"][:10]:
            print(f"   • {st[0]:<15} : Net PnL: +₹{st[6]:>10,.2f} | WR: {st[5]}% | Trades: {st[2]:>3} | PF: {st[8]}")
        print("=" * 75)
        print(" ✅ Detailed logs and per-stock PnL saved to SQLite tables:")
        print("    1. top100_stock_pnl_summary  (4-year stats for EACH stock chosen)")
        print("    2. top100_daily_trade_logs   (every single trade on everyday basis)")
        print("    3. top100_daily_pnl_summary  (daily aggregate PnL & equity curve)")
        print("=" * 75 + "\n")


if __name__ == "__main__":
    backtester = Top100IntradayBacktester()
    backtester.run_backtest()
