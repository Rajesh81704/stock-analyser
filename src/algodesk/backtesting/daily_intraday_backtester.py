"""
4-Year Daily Intraday Backtesting Engine for Liquid NSE Equities.

Simulates daily intraday opening range breakouts, momentum pulses, and trailing
breakeven stops across the Top 20 liquid NSE stocks over the last 4 years (980+ trading days).
Logs every single daily trade and aggregate PnL directly into SQLite database (data/stock_screener.db).
"""

import sys
import os
import json
import sqlite3
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any

import numpy as np
import pandas as pd
import yfinance as yf

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
logger = logging.getLogger("DailyIntradayBacktester")

# Top 20 high-liquidity, high-beta NSE stocks suitable for intraday trading
TOP_20_INTRADAY_STOCKS = [
    "RELIANCE.NS", "HDFCBANK.NS", "ICICIBANK.NS", "INFY.NS", "TCS.NS",
    "AXISBANK.NS", "SBIN.NS", "KOTAKBANK.NS", "BAJFINANCE.NS", "BHARTIARTL.NS",
    "LT.NS", "MARUTI.NS", "TITAN.NS", "SUNPHARMA.NS", "ASIANPAINT.NS",
    "M&M.NS", "JSWSTEEL.NS", "TATASTEEL.NS", "ADANIENT.NS", "NTPC.NS"
]


class DailyIntradayBacktester:
    """
    Backtests intraday strategies over 4 years of daily data for top 20 stocks
    and logs every day's trade and PnL into SQLite.
    """

    def __init__(
        self,
        db_path: str = "data/stock_screener.db",
        initial_capital: float = 100000.0,
        risk_per_trade: float = 50000.0,
        years: int = 4
    ):
        self.db_path = Path(db_path)
        self.initial_capital = initial_capital
        self.risk_per_trade = risk_per_trade
        self.years = years
        self.tickers = TOP_20_INTRADAY_STOCKS

        self._init_db_tables()

    def _init_db_tables(self):
        """Initializes tables for logging trade-by-trade outcomes and daily PnL summaries."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        cur = conn.cursor()

        # Detailed individual trade log table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS intraday_daily_pnl_logs (
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

        # Daily aggregate PnL and portfolio equity curve table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS intraday_daily_pnl_summary (
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
                active_symbols TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        cur.execute("CREATE INDEX IF NOT EXISTS idx_trade_date ON intraday_daily_pnl_logs (trade_date);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_trade_ticker ON intraday_daily_pnl_logs (ticker);")
        conn.commit()
        conn.close()

    def fetch_historical_data(self) -> Dict[str, pd.DataFrame]:
        """Downloads or loads 4 years of daily OHLCV data for the top 20 stocks."""
        logger.info(f"Fetching {self.years} years of historical data for {len(self.tickers)} top intraday stocks...")
        cached_data = {}

        try:
            raw = yf.download(self.tickers, period=f"{self.years}y", group_by="ticker", progress=False)
            for t in self.tickers:
                try:
                    df = raw[t].copy() if len(self.tickers) > 1 else raw.copy()
                    df.dropna(subset=["Open", "High", "Low", "Close"], inplace=True)
                    if len(df) > 100:
                        cached_data[t] = df
                except Exception as e:
                    logger.warning(f"Could not extract dataframe for {t}: {e}")
        except Exception as e:
            logger.error(f"Error downloading batch data: {e}")

        logger.info(f"Successfully loaded data for {len(cached_data)} symbols (average {np.mean([len(d) for d in cached_data.values()]):.0f} trading days each).")
        return cached_data

    def run_backtest(
        self,
        strategy_name: str = "Alpha_ORB_TrailingBreakeven_75",
        target_pct: float = 0.0135,       # 1.35% intraday profit target
        stop_loss_pct: float = 0.0065,    # 0.65% initial stop loss
        breakout_k: float = 0.25,         # Breakout above Open by 0.25 * ATR
        trailing_progress: float = 0.40,  # Move to breakeven after 40% progress toward target
        min_vol_mult: float = 1.10        # Minimum relative volume
    ) -> Dict[str, Any]:
        """
        Executes daily intraday backtest across all 20 stocks for 4 years,
        logging every day's trade into SQLite.
        """
        data_by_sym = self.fetch_historical_data()
        if not data_by_sym:
            logger.error("No data available for backtesting.")
            return {}

        # Precompute indicators for each stock
        processed = {}
        all_dates = set()

        for t, df in data_by_sym.items():
            df = df.copy()
            # Standardize index
            df.index = pd.to_datetime(df.index).strftime("%Y-%m-%d")

            # True Range & 14-day ATR
            high = df["High"].values
            low = df["Low"].values
            close = df["Close"].values
            n = len(df)

            prev_close = np.roll(close, 1)
            prev_close[0] = close[0]

            tr = np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
            df["ATR"] = pd.Series(tr, index=df.index).rolling(14, min_periods=5).mean().bfill()
            df["MeanVol"] = df["Volume"].rolling(20, min_periods=5).mean().bfill()

            processed[t] = df
            all_dates.update(df.index)

        sorted_dates = sorted(list(all_dates))
        logger.info(f"Running daily intraday simulation over {len(sorted_dates)} trading dates ({sorted_dates[0]} to {sorted_dates[-1]})...")

        # Connect to SQLite for logging
        conn = sqlite3.connect(str(self.db_path))
        cur = conn.cursor()

        # Clear existing logs for fresh run
        cur.execute("DELETE FROM intraday_daily_pnl_logs WHERE strategy_name = ?;", (strategy_name,))
        cur.execute("DELETE FROM intraday_daily_pnl_summary;")
        conn.commit()

        cumulative_net_pnl = 0.0
        peak_equity = self.initial_capital
        daily_summaries = []
        all_trade_logs = []

        total_trades = 0
        total_wins = 0
        total_losses = 0

        # Simulate day-by-day
        for d in sorted_dates:
            day_trades = []
            day_candidates = []

            for t in self.tickers:
                if t not in processed:
                    continue
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

                # Relative volume score
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

            # Pick top 3 stocks with highest relative volume expansion each day
            day_candidates.sort(key=lambda x: x["rvol"], reverse=True)
            active_picks = day_candidates[:3]

            for cand in active_picks:
                t = cand["ticker"]
                open_p = cand["open"]
                high_p = cand["high"]
                low_p = cand["low"]
                close_p = cand["close"]
                atr = cand["atr"]

                # Intraday Opening Breakout Level
                breakout_buy = open_p + (breakout_k * atr)
                breakout_sell = open_p - (breakout_k * atr)

                # Check if upper breakout occurred
                if high_p >= breakout_buy:
                    entry_p = breakout_buy * 1.0003  # slippage on entry
                    target_p = entry_p * (1.0 + target_pct)
                    initial_stop = entry_p * (1.0 - stop_loss_pct)

                    qty = int(self.risk_per_trade / entry_p)
                    if qty <= 0:
                        continue

                    # Trailing Stop Ratchet:
                    # If high reached 40% progress toward target, stop moves to breakeven + buffer
                    breakeven_threshold = entry_p + ((target_p - entry_p) * trailing_progress)
                    trailing_activated = (high_p >= breakeven_threshold)
                    effective_stop = (entry_p * 1.001) if trailing_activated else initial_stop

                    # Determine exit
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
                    # Zerodha statutory fees & brokerage (~0.05% of turnover)
                    cost = (entry_p + exit_p) * qty * 0.0003
                    net_pnl = round(gross_pnl - cost, 2)
                    ret_pct = round((net_pnl / (entry_p * qty)) * 100.0, 2)
                    is_win = 1 if net_pnl > 0 else 0

                    trade_record = (
                        d, t, strategy_name, "BUY",
                        round(entry_p, 2), round(exit_p, 2), exit_reason,
                        qty, round(gross_pnl, 2), net_pnl, ret_pct, is_win
                    )
                    day_trades.append(trade_record)
                    all_trade_logs.append(trade_record)

                    total_trades += 1
                    if is_win:
                        total_wins += 1
                    else:
                        total_losses += 1

            # Compute daily summary
            if day_trades:
                daily_gross = sum(tr[8] for tr in day_trades)
                daily_net = sum(tr[9] for tr in day_trades)
                daily_wins = sum(tr[11] for tr in day_trades)
                daily_losses = len(day_trades) - daily_wins
                active_syms = ",".join(tr[1] for tr in day_trades)
            else:
                daily_gross = 0.0
                daily_net = 0.0
                daily_wins = 0
                daily_losses = 0
                active_syms = ""

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
                active_syms
            ))

        # Batch insert into database
        logger.info(f"Saving {len(all_trade_logs)} individual trade logs to database...")
        cur.executemany("""
            INSERT INTO intraday_daily_pnl_logs (
                trade_date, ticker, strategy_name, side,
                entry_price, exit_price, exit_reason, qty,
                gross_pnl, net_pnl, return_pct, is_win
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, all_trade_logs)

        logger.info(f"Saving {len(daily_summaries)} daily PnL summaries to database...")
        cur.executemany("""
            INSERT INTO intraday_daily_pnl_summary (
                date, trades_count, win_trades, loss_trades,
                daily_gross_pnl, daily_net_pnl, daily_return_pct,
                cumulative_net_pnl, portfolio_equity, drawdown_pct,
                active_symbols
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, daily_summaries)

        conn.commit()
        conn.close()

        # Compute overall portfolio performance analytics
        win_rate = (total_wins / total_trades * 100.0) if total_trades > 0 else 0.0
        gross_profit = sum(t[8] for t in all_trade_logs if t[8] > 0)
        gross_loss = abs(sum(t[8] for t in all_trade_logs if t[8] < 0))
        pf = round(gross_profit / max(1.0, gross_loss), 2)
        total_return_pct = round((cumulative_net_pnl / self.initial_capital) * 100.0, 2)
        max_drawdown = max([s[9] for s in daily_summaries], default=0.0)

        # Yearly breakdown
        yearly_pnl = {}
        for s in daily_summaries:
            yr = s[0][:4]
            yearly_pnl[yr] = yearly_pnl.get(yr, 0.0) + s[5]

        result = {
            "strategy_name": strategy_name,
            "period_years": self.years,
            "total_trading_days": len(sorted_dates),
            "days_traded": len([s for s in daily_summaries if s[1] > 0]),
            "total_trades": total_trades,
            "win_trades": total_wins,
            "loss_trades": total_losses,
            "win_rate_pct": round(win_rate, 1),
            "profit_factor": pf,
            "cumulative_net_pnl": round(cumulative_net_pnl, 2),
            "net_return_pct": total_return_pct,
            "max_drawdown_pct": max_drawdown,
            "initial_capital": self.initial_capital,
            "ending_equity": round(self.initial_capital + cumulative_net_pnl, 2),
            "yearly_breakdown": {yr: round(pnl, 2) for yr, pnl in sorted(yearly_pnl.items())}
        }

        self._print_performance_report(result)
        return result

    def _print_performance_report(self, r: Dict[str, Any]):
        """Prints a clean tabular terminal performance report."""
        print("\n" + "=" * 70)
        print(" 🎯 4-YEAR DAILY INTRADAY BACKTEST PERFORMANCE REPORT (TOP 20 STOCKS)")
        print("=" * 70)
        print(f" Strategy Name        : {r['strategy_name']}")
        print(f" Backtest Horizon     : {r['period_years']} Years ({r['total_trading_days']} Total Trading Days)")
        print(f" Days Traded          : {r['days_traded']} Days")
        print(f" Total Trades Taken   : {r['total_trades']}")
        print(f" Win Trades / Losses  : {r['win_trades']} Wins / {r['loss_trades']} Losses")
        print(f" Win Rate             : ⭐ {r['win_rate_pct']}%")
        print(f" Profit Factor        : 🚀 {r['profit_factor']}")
        print(f" Initial Capital      : ₹{r['initial_capital']:,.2f}")
        print(f" Total Net PnL        : +₹{r['cumulative_net_pnl']:,.2f} ({r['net_return_pct']:+,.2f}%)")
        print(f" Ending Equity        : ₹{r['ending_equity']:,.2f}")
        print(f" Maximum Drawdown     : {r['max_drawdown_pct']}%")
        print("-" * 70)
        print(" 📅 YEARLY PnL BREAKDOWN:")
        for yr, pnl in r["yearly_breakdown"].items():
            print(f"   • Year {yr} : +₹{pnl:,.2f}")
        print("=" * 70)
        print(" ✅ Detailed day-by-day logs saved to SQLite:")
        print("    - Table: intraday_daily_pnl_logs (every single trade entry/exit/PnL)")
        print("    - Table: intraday_daily_pnl_summary (every trading day aggregate PnL & equity)")
        print("=" * 70 + "\n")


if __name__ == "__main__":
    backtester = DailyIntradayBacktester()
    backtester.run_backtest()
