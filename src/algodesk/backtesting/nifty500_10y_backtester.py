"""
NIFTY 500 10-Year Intraday Backtester Engine
============================================
Evaluates all 501 NIFTY 500 stocks over a 10-year period (2016-2026, or from listing date).
Implements institutional morning relative volume screening, bi-directional (BUY & SHORT)
breakout execution, and dynamic trailing stop-to-breakeven risk management.

Stores all individual trade logs, per-stock 10Y PnL summaries, and daily portfolio equity in SQLite.
"""

import os
import sys
import time
import logging
import sqlite3
from pathlib import Path
from typing import Dict, List, Any, Optional
import pandas as pd
import numpy as np
import yfinance as yf

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Nifty500_10Y_Backtester")


def get_nifty_500_tickers(csv_path: Optional[Path] = None) -> List[str]:
    """Loads all 500 NIFTY constituent symbols from ind_nifty500list.csv or fallback."""
    if csv_path is None:
        csv_path = Path(__file__).resolve().parent.parent.parent.parent / "data" / "ind_nifty500list.csv"

    if csv_path.exists():
        try:
            df = pd.read_csv(csv_path)
            col = "Symbol" if "Symbol" in df.columns else df.columns[0]
            raw_syms = df[col].dropna().astype(str).str.strip().tolist()
            tickers = []
            for s in raw_syms:
                if not s.endswith(".NS") and not s.endswith(".BO") and not s.startswith("^"):
                    s = f"{s}.NS"
                tickers.append(s)
            return list(dict.fromkeys(tickers))
        except Exception as e:
            logger.warning(f"Could not load Nifty 500 from {csv_path}: {e}")

    # Fallback to Top 100 liquid stocks if CSV missing
    from algodesk.backtesting.top100_intraday_backtester import TOP_100_VOLUME_STOCKS
    return TOP_100_VOLUME_STOCKS


class Nifty500TenYearBacktester:
    """
    Simulates everyday morning screening and intraday trading across all 500 Nifty stocks
    for 10 years (or from listing date).
    """

    def __init__(
        self,
        db_path: Optional[Path] = None,
        cache_dir: Optional[Path] = None,
        initial_capital: float = 100000.0,
        risk_per_trade: float = 50000.0
    ):
        base_dir = Path(__file__).resolve().parent.parent.parent.parent
        self.db_path = db_path or (base_dir / "data" / "stock_screener.db")
        self.cache_dir = cache_dir or (base_dir / "data" / "nifty500_10y_cache")
        self.initial_capital = initial_capital
        self.risk_per_trade = risk_per_trade
        self.tickers = get_nifty_500_tickers()

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._init_db_tables()

    def _init_db_tables(self):
        """Initializes tables for 10-year trade logs, per-stock summaries, and daily equity summaries."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        cur = conn.cursor()

        # Table 1: Individual daily trade logs (all trades taken)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS nifty500_10y_trade_logs (
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

        # Table 2: Per-stock 10-year performance summary
        cur.execute("""
            CREATE TABLE IF NOT EXISTS nifty500_10y_stock_pnl_summary (
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
            CREATE TABLE IF NOT EXISTS nifty500_10y_daily_pnl_summary (
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

        cur.execute("CREATE INDEX IF NOT EXISTS idx_nifty500_10y_logs_date ON nifty500_10y_trade_logs (trade_date);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_nifty500_10y_logs_ticker ON nifty500_10y_trade_logs (ticker);")
        conn.commit()
        conn.close()

    @staticmethod
    def calculate_trade_friction(side: str, qty: int, entry_price: float, exit_price: float) -> float:
        """
        Calculates exact Indian equity intraday transaction costs according to Zerodha / NSE schedule:
        - Brokerage: Rs 20 (entry) + Rs 20 (exit) = Rs 40.00 flat per roundtrip
        - STT: 0.025% on sell side only
        - Exchange transaction fee (NSE): 0.00297% on turnover (buy + sell)
        - SEBI turnover fee: Rs 10 per crore (0.0001% on turnover)
        - Stamp duty: 0.003% on buy side
        - GST: 18% on (Brokerage + Exchange + SEBI)
        """
        turnover_buy = qty * (entry_price if side == "BUY" else exit_price)
        turnover_sell = qty * (exit_price if side == "BUY" else entry_price)
        turnover_total = turnover_buy + turnover_sell

        brokerage = 40.0  # Rs 20 buy leg + Rs 20 sell leg
        stt = turnover_sell * 0.00025
        exchange_charges = turnover_total * 0.0000297
        sebi_charges = turnover_total * 0.000001
        stamp_duty = turnover_buy * 0.00003
        gst = (brokerage + exchange_charges + sebi_charges) * 0.18

        total_friction = brokerage + stt + exchange_charges + sebi_charges + stamp_duty + gst
        return round(total_friction, 2)

    def fetch_historical_data(self, chunk_size: int = 50, force_refresh: bool = False) -> Dict[str, pd.DataFrame]:
        """
        Fetches 10 years (or from listing date) of daily data for all 501 Nifty 500 stocks.
        Uses local Parquet cache to avoid redundant API downloads.
        """
        cached_data = {}
        missing_tickers = []

        for t in self.tickers:
            cache_file = self.cache_dir / f"{t}.parquet"
            if not force_refresh and cache_file.exists():
                try:
                    df = pd.read_parquet(cache_file)
                    if len(df) > 50:
                        cached_data[t] = df
                        continue
                except Exception:
                    pass
            missing_tickers.append(t)

        logger.info(f"Loaded {len(cached_data)} cached 10-year datasets. {len(missing_tickers)} to download.")

        if missing_tickers:
            chunks = [missing_tickers[i:i + chunk_size] for i in range(0, len(missing_tickers), chunk_size)]
            for idx, chunk in enumerate(chunks, 1):
                logger.info(f"Downloading 10-year data batch {idx}/{len(chunks)} ({len(chunk)} tickers)...")
                try:
                    raw = yf.download(chunk, period="10y", group_by="ticker", progress=False)
                    for t in chunk:
                        try:
                            df = raw[t].copy() if len(chunk) > 1 else raw.copy()
                            df.dropna(subset=["Open", "High", "Low", "Close"], inplace=True)
                            if len(df) > 50:
                                cache_file = self.cache_dir / f"{t}.parquet"
                                df.to_parquet(cache_file)
                                cached_data[t] = df
                        except Exception as e:
                            logger.debug(f"Could not parse data for {t}: {e}")
                except Exception as e:
                    logger.error(f"Error downloading batch {idx}: {e}")

        logger.info(f"Successfully loaded 10-year historical dataset for {len(cached_data)} / {len(self.tickers)} stocks.")
        return cached_data

    def run_backtest(
        self,
        strategy_name: str = "Nifty500_10Y_Intraday_Alpha",
        target_pct: float = 0.0135,       # 1.35% intraday profit target
        stop_loss_pct: float = 0.0065,    # 0.65% initial stop loss
        breakout_k: float = 0.25,         # Breakout above/below Open by 0.25 * ATR
        trailing_progress: float = 0.40,  # Move to breakeven after 40% target progress
        min_vol_mult: float = 1.15,       # Require 1.15x relative volume expansion
        max_daily_picks: int = 6,         # Up to top 6 volume-surge stocks per day
        enable_short: bool = True         # Bi-directional trading (BUY & SHORT)
    ) -> Dict[str, Any]:
        """
        Runs 10-year daily intraday simulation across all 500 stocks, logging every day's trade
        and each stock's PnL into SQLite.
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
            open_p = df["Open"].values

            prev_close = np.roll(close, 1)
            prev_close[0] = close[0]

            tr = np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
            df["ATR"] = pd.Series(tr, index=df.index).rolling(14, min_periods=5).mean().bfill()
            df["MeanVol"] = df["Volume"].rolling(20, min_periods=5).mean().bfill()
            df["PrevClose"] = prev_close

            processed[t] = df
            all_dates.update(df.index)

        sorted_dates = sorted(list(all_dates))
        logger.info(f"Running 10-Year simulation over {len(sorted_dates)} trading dates across {len(processed)} stocks...")

        conn = sqlite3.connect(str(self.db_path))
        cur = conn.cursor()

        # Clear existing logs for fresh run
        cur.execute("DELETE FROM nifty500_10y_trade_logs;")
        cur.execute("DELETE FROM nifty500_10y_stock_pnl_summary;")
        cur.execute("DELETE FROM nifty500_10y_daily_pnl_summary;")
        conn.commit()

        cumulative_net_pnl = 0.0
        peak_equity = self.initial_capital
        daily_summaries = []
        all_trade_logs = []

        total_trades = 0
        total_wins = 0
        total_losses = 0

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

        # Daily simulation loop across all 10 years
        for d in sorted_dates:
            day_trades = []
            day_candidates = []

            for t, df in processed.items():
                if d not in df.index:
                    continue

                row = df.loc[d]
                idx_pos = df.index.get_loc(d)
                if idx_pos < 15:  # warm-up period
                    continue

                open_p = float(row["Open"])
                high_p = float(row["High"])
                low_p = float(row["Low"])
                close_p = float(row["Close"])
                vol = float(row["Volume"])
                atr = float(row["ATR"])
                mean_vol = float(row["MeanVol"])
                prev_close_p = float(row["PrevClose"])

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
                        "rvol": rvol,
                        "prev_close": prev_close_p
                    })

            # Rank by relative volume surge
            day_candidates.sort(key=lambda x: x["rvol"], reverse=True)
            active_picks = day_candidates[:max_daily_picks]

            for cand in active_picks:
                t = cand["ticker"]
                open_p = cand["open"]
                high_p = cand["high"]
                low_p = cand["low"]
                close_p = cand["close"]
                atr = cand["atr"]
                prev_close_p = cand["prev_close"]

                buy_trigger = open_p + (breakout_k * atr)
                sell_trigger = open_p - (breakout_k * atr)

                is_buy = (high_p >= buy_trigger)
                is_short = enable_short and (low_p <= sell_trigger) and (open_p < prev_close_p)

                # Prioritize based on morning open gap/direction
                side = None
                if is_buy and (open_p >= prev_close_p or not is_short):
                    side = "BUY"
                elif is_short:
                    side = "SELL"
                elif is_buy:
                    side = "BUY"

                if side == "BUY":
                    entry_p = buy_trigger * 1.0003
                    target_p = entry_p * (1.0 + target_pct)
                    initial_stop = entry_p * (1.0 - stop_loss_pct)

                    qty = int(self.risk_per_trade / entry_p)
                    if qty <= 0:
                        continue

                    be_threshold = entry_p + ((target_p - entry_p) * trailing_progress)
                    trailing_activated = (high_p >= be_threshold)
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
                    cost = self.calculate_trade_friction("BUY", qty, entry_p, exit_p)
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

                elif side == "SELL":
                    entry_p = sell_trigger * 0.9997
                    target_p = entry_p * (1.0 - target_pct)
                    initial_stop = entry_p * (1.0 + stop_loss_pct)

                    qty = int(self.risk_per_trade / entry_p)
                    if qty <= 0:
                        continue

                    be_threshold = entry_p - ((entry_p - target_p) * trailing_progress)
                    trailing_activated = (low_p <= be_threshold)
                    effective_stop = (entry_p * 0.999) if trailing_activated else initial_stop

                    if low_p <= target_p:
                        exit_p = target_p
                        exit_reason = "TARGET"
                    elif high_p >= effective_stop:
                        exit_p = effective_stop
                        exit_reason = "TRAILING_STOP" if trailing_activated else "STOP_LOSS"
                    else:
                        exit_p = close_p
                        exit_reason = "EOD"

                    gross_pnl = (entry_p - exit_p) * qty
                    cost = self.calculate_trade_friction("SELL", qty, entry_p, exit_p)
                    net_pnl = round(gross_pnl - cost, 2)
                    ret_pct = round((net_pnl / (entry_p * qty)) * 100.0, 2)
                    is_win = 1 if net_pnl > 0 else 0

                    record = (
                        d, t, strategy_name, "SELL",
                        round(entry_p, 2), round(exit_p, 2), exit_reason,
                        qty, round(gross_pnl, 2), net_pnl, ret_pct, is_win
                    )
                    day_trades.append(record)
                    all_trade_logs.append(record)

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
                stocks_traded = ",".join(set(tr[1].replace(".NS", "") for tr in day_trades))
            else:
                daily_gross = 0.0
                daily_net = 0.0
                daily_wins = 0
                daily_losses = 0
                stocks_traded = ""

            cumulative_net_pnl += daily_net
            current_equity = self.initial_capital + cumulative_net_pnl
            if current_equity > peak_equity:
                peak_equity = current_equity
            drawdown = ((peak_equity - current_equity) / peak_equity) * 100.0 if peak_equity > 0 else 0.0

            daily_summaries.append((
                d, len(day_trades), daily_wins, daily_losses,
                round(daily_gross, 2), round(daily_net, 2),
                round((daily_net / self.initial_capital) * 100.0, 2),
                round(cumulative_net_pnl, 2), round(current_equity, 2),
                round(drawdown, 2), stocks_traded
            ))

        # Batch insert into SQLite
        logger.info(f"Saving {len(all_trade_logs)} trade records to nifty500_10y_trade_logs...")
        cur.executemany("""
            INSERT INTO nifty500_10y_trade_logs (
                trade_date, ticker, strategy_name, side, entry_price, exit_price,
                exit_reason, qty, gross_pnl, net_pnl, return_pct, is_win
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, all_trade_logs)

        logger.info(f"Saving {len(daily_summaries)} daily summary records to nifty500_10y_daily_pnl_summary...")
        cur.executemany("""
            INSERT INTO nifty500_10y_daily_pnl_summary (
                date, trades_count, win_trades, loss_trades, daily_gross_pnl, daily_net_pnl,
                daily_return_pct, cumulative_net_pnl, portfolio_equity, drawdown_pct, stocks_traded
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, daily_summaries)

        # Build Per-Stock 10-Year Summary
        stock_summary_rows = []
        for t, st in stock_stats.items():
            trade_pnls = st["trades"]
            n_trades = len(trade_pnls)
            w_trades = st["wins"]
            l_trades = st["losses"]
            win_r = round((w_trades / n_trades * 100.0), 1) if n_trades > 0 else 0.0
            tot_net = round(st["net_pnl"], 2)
            tot_gross = round(st["gross_pnl"], 2)

            win_sum = sum(p for p in trade_pnls if p > 0)
            loss_sum = abs(sum(p for p in trade_pnls if p < 0))
            pf = round(win_sum / loss_sum, 2) if loss_sum > 0 else (99.0 if win_sum > 0 else 0.0)

            avg_pnl = round(tot_net / n_trades, 2) if n_trades > 0 else 0.0
            best_pnl = round(max(trade_pnls), 2) if trade_pnls else 0.0
            worst_pnl = round(min(trade_pnls), 2) if trade_pnls else 0.0
            first_d = st["dates"][0] if st["dates"] else ""
            last_d = st["dates"][-1] if st["dates"] else ""

            stock_summary_rows.append((
                t, t.replace(".NS", ""), n_trades, w_trades, l_trades, win_r,
                tot_net, tot_gross, pf, avg_pnl, best_pnl, worst_pnl, first_d, last_d
            ))

        logger.info(f"Saving {len(stock_summary_rows)} stock summary rows to nifty500_10y_stock_pnl_summary...")
        cur.executemany("""
            INSERT INTO nifty500_10y_stock_pnl_summary (
                ticker, company_name, total_trades, win_trades, loss_trades, win_rate,
                total_net_pnl, total_gross_pnl, profit_factor, avg_trade_pnl,
                best_trade_pnl, worst_trade_pnl, first_trade_date, last_trade_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, stock_summary_rows)

        conn.commit()
        conn.close()

        # Compute Overall 10-Year KPIs
        win_rate = (total_wins / total_trades * 100.0) if total_trades > 0 else 0.0
        gross_wins = sum(tr[8] for tr in all_trade_logs if tr[8] > 0)
        gross_losses = abs(sum(tr[8] for tr in all_trade_logs if tr[8] < 0))
        profit_factor = (gross_wins / gross_losses) if gross_losses > 0 else 99.0

        all_dd = [r[9] for r in daily_summaries]
        max_drawdown = max(all_dd) if all_dd else 0.0

        # Yearly breakdown
        df_daily = pd.DataFrame(daily_summaries, columns=[
            "date", "trades", "wins", "losses", "gross_pnl", "net_pnl", "ret_pct",
            "cum_pnl", "equity", "drawdown", "stocks"
        ])
        df_daily["year"] = df_daily["date"].str[:4]
        yearly_grp = df_daily.groupby("year")
        yearly_stats = []
        for yr, group in yearly_grp:
            y_trades = int(group["trades"].sum())
            y_wins = int(group["wins"].sum())
            y_net = float(group["net_pnl"].sum())
            y_wr = round((y_wins / y_trades * 100.0), 1) if y_trades > 0 else 0.0
            yearly_stats.append({
                "year": yr,
                "trades": y_trades,
                "win_rate": y_wr,
                "net_pnl": round(y_net, 2),
                "return_on_capital": round((y_net / self.initial_capital) * 100.0, 1)
            })

        results = {
            "strategy_name": strategy_name,
            "period_years": 10,
            "universe_size": len(self.tickers),
            "stocks_traded": sum(1 for s in stock_summary_rows if s[2] > 0),
            "start_date": sorted_dates[0] if sorted_dates else "",
            "end_date": sorted_dates[-1] if sorted_dates else "",
            "total_trading_days": len(sorted_dates),
            "initial_capital": self.initial_capital,
            "ending_equity": round(self.initial_capital + cumulative_net_pnl, 2),
            "total_net_pnl": round(cumulative_net_pnl, 2),
            "total_return_pct": round((cumulative_net_pnl / self.initial_capital) * 100.0, 2),
            "total_trades": total_trades,
            "win_trades": total_wins,
            "loss_trades": total_losses,
            "win_rate": round(win_rate, 2),
            "profit_factor": round(profit_factor, 2),
            "max_drawdown_pct": round(max_drawdown, 2),
            "yearly_breakdown": yearly_stats
        }

        logger.info(
            f"10-Year Backtest Complete: {total_trades} trades across {len(sorted_dates)} days | "
            f"Win Rate: {win_rate:.1f}% | Profit Factor: {profit_factor:.2f} | Net PnL: Rs {cumulative_net_pnl:,.2f}"
        )
        return results
