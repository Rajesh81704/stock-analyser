"""
Continuous Autonomous Gemini AI Quant Research & Optimization Engine.

Continuously creates, backtests, evaluates, and iteratively tweaks intraday trading
strategies against historical 5-minute market data while the AlgoDesk server is running.
"""

import json
import logging
import os
import random
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from src.algodesk.ai.gemini_client import GeminiClient
from src.algodesk.config.settings import settings

logger = logging.getLogger(__name__)


# -------------------------------------------------------------------------
# Strategy & Backtest Data Structures
# -------------------------------------------------------------------------
@dataclass
class BacktestSummary:
    strategy_id: str
    symbol_tested: str
    bars_tested: int
    trades_count: int
    win_trades: int
    loss_trades: int
    win_rate: float
    gross_profit: float
    gross_loss: float
    net_pnl: float
    net_return_pct: float
    profit_factor: float
    max_drawdown_pct: float
    sharpe_ratio: float
    verdict: str  # "PROFITABLE", "PROMISING", "UNPROFITABLE"
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class QuantStrategy:
    strategy_id: str
    name: str
    version: int
    archetype: str  # "ORB_BREAKOUT", "EMA_MOMENTUM", "VWAP_REVERSION", "RSI_PULLBACK", "SUPERTREND_VOL"
    hypothesis: str
    parameters: Dict[str, Any]
    parent_id: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    latest_result: Optional[BacktestSummary] = None
    iteration_history: List[Dict[str, Any]] = field(default_factory=list)


# -------------------------------------------------------------------------
# High-Speed Vectorized Intraday Backtester
# -------------------------------------------------------------------------
class FastIntradayBacktester:
    """Ultra-fast intraday backtester running across cached 5m historical data."""

    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.cached_bars: Dict[str, pd.DataFrame] = {}
        self._load_data()

    def _load_data(self):
        """Pre-loads top liquid stocks into memory for instant backtesting."""
        parquets = list(self.data_dir.glob("*.parquet"))
        if not parquets:
            logger.warning(f"No parquet datasets found in {self.data_dir}")
            return

        priority_stocks = [
            "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN",
            "TATAMOTORS", "TATASTEEL", "KOTAKBANK", "LT", "ITC", "BAJFINANCE",
            "BHARTIARTL", "M&M", "MARUTI", "AXISBANK", "ADANIENT", "TITAN"
        ]

        loaded = 0
        for p in parquets:
            sym = p.stem.upper()
            if sym in priority_stocks or loaded < 15:
                try:
                    df = pd.read_parquet(p)
                    if "timestamp" in df.columns:
                        df["timestamp"] = pd.to_datetime(df["timestamp"])
                        df = df.sort_values("timestamp").reset_index(drop=True)
                    self.cached_bars[sym] = df
                    loaded += 1
                except Exception as e:
                    logger.warning(f"Error loading {p}: {e}")

        logger.info(f"FastIntradayBacktester loaded {len(self.cached_bars)} symbols for backtesting.")

    def run_backtest(self, strategy: QuantStrategy, symbols: Optional[List[str]] = None) -> BacktestSummary:
        """Executes intraday simulation for the given strategy parameters."""
        liquid_pool = ["HDFCBANK", "ICICIBANK", "INFY", "TATAMOTORS", "RELIANCE", "TCS", "KOTAKBANK"]
        test_symbols = symbols or [s for s in liquid_pool if s in self.cached_bars] or list(self.cached_bars.keys())[:7]
        if not test_symbols:
            # Fallback if cache was empty
            return BacktestSummary(
                strategy_id=strategy.strategy_id,
                symbol_tested="NONE",
                bars_tested=0,
                trades_count=0,
                win_trades=0,
                loss_trades=0,
                win_rate=0.0,
                gross_profit=0.0,
                gross_loss=0.0,
                net_pnl=0.0,
                net_return_pct=0.0,
                profit_factor=0.0,
                max_drawdown_pct=0.0,
                sharpe_ratio=0.0,
                verdict="UNPROFITABLE"
            )

        total_trades = []
        total_bars = 0
        capital = 100000.0  # ₹100,000 initial simulated capital

        for sym in test_symbols:
            df = self.cached_bars.get(sym)
            if df is None or len(df) < 100:
                continue

            total_bars += len(df)
            trades = self._simulate_symbol(strategy, df)
            total_trades.extend(trades)

        if not total_trades:
            return BacktestSummary(
                strategy_id=strategy.strategy_id,
                symbol_tested=",".join(test_symbols),
                bars_tested=total_bars,
                trades_count=0,
                win_trades=0,
                loss_trades=0,
                win_rate=0.0,
                gross_profit=0.0,
                gross_loss=0.0,
                net_pnl=0.0,
                net_return_pct=0.0,
                profit_factor=0.0,
                max_drawdown_pct=0.0,
                sharpe_ratio=0.0,
                verdict="UNPROFITABLE"
            )

        # Performance analytics
        gross_profit = sum(t["pnl"] for t in total_trades if t["pnl"] > 0)
        gross_loss = abs(sum(t["pnl"] for t in total_trades if t["pnl"] < 0))
        net_pnl = gross_profit - gross_loss

        win_trades = sum(1 for t in total_trades if t["pnl"] > 0)
        loss_trades = sum(1 for t in total_trades if t["pnl"] <= 0)
        win_rate = (win_trades / len(total_trades)) * 100.0

        profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)
        net_return_pct = round((net_pnl / capital) * 100.0, 2)

        # Drawdown calculation
        equity_curve = [capital]
        for t in total_trades:
            equity_curve.append(equity_curve[-1] + t["pnl"])
        peak = capital
        max_dd = 0.0
        for eq in equity_curve:
            if eq > peak:
                peak = eq
            dd = ((peak - eq) / peak) * 100.0 if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd

        # Sharpe approximation
        pnls = [t["pnl"] for t in total_trades]
        std_pnl = np.std(pnls) if len(pnls) > 1 else 1.0
        sharpe = round((np.mean(pnls) / (std_pnl + 1e-9)) * np.sqrt(252), 2) if len(pnls) > 1 else 0.0

        # Profitability & Win Rate Verdict Decision
        if win_rate >= 75.0 and net_return_pct >= 0.5 and profit_factor >= 1.15:
            verdict = "PROFITABLE (75%+ WINRATE)"
        elif net_return_pct >= 0.5 and profit_factor >= 1.10 and win_rate >= 35.0:
            verdict = "PROFITABLE"
        elif net_return_pct >= -1.5 and profit_factor >= 0.95:
            verdict = "PROMISING"
        else:
            verdict = "UNPROFITABLE"

        return BacktestSummary(
            strategy_id=strategy.strategy_id,
            symbol_tested=",".join(test_symbols),
            bars_tested=total_bars,
            trades_count=len(total_trades),
            win_trades=win_trades,
            loss_trades=loss_trades,
            win_rate=round(win_rate, 1),
            gross_profit=round(gross_profit, 2),
            gross_loss=round(gross_loss, 2),
            net_pnl=round(net_pnl, 2),
            net_return_pct=net_return_pct,
            profit_factor=profit_factor,
            max_drawdown_pct=round(max_dd, 2),
            sharpe_ratio=sharpe,
            verdict=verdict
        )

    def _simulate_symbol(self, strategy: QuantStrategy, df: pd.DataFrame) -> List[Dict[str, Any]]:
        """Simulates trading logic on a single stock dataframe with pure numpy arrays for sub-second backtesting."""
        params = strategy.parameters
        arch = strategy.archetype
        trades = []

        closes = df["close"].values
        highs = df["high"].values
        lows = df["low"].values
        vols = df["volume"].values
        n = len(closes)
        if n < 50:
            return trades

        ts_dt = pd.to_datetime(df["timestamp"])
        minutes = ts_dt.dt.hour.values * 60 + ts_dt.dt.minute.values
        dates = ts_dt.dt.date.values

        stop_loss_pct = float(params.get("stop_loss_pct", 0.01))
        target_pct = float(params.get("target_pct", 0.02))
        risk_capital = 50000.0

        if arch == "ORB_BREAKOUT":
            or_mins = int(params.get("or_minutes", 15))
            or_cutoff = 9 * 60 + 15 + or_mins
            vol_mult = float(params.get("vol_mult", 1.2))
            use_trailing = bool(params.get("trailing_stop", True))

            in_pos = False
            traded_today = False
            trailing_done = False
            pos_side = "BUY"
            entry_price = 0.0
            stop_price = 0.0
            target_price = 0.0
            qty = 0

            curr_date = None
            or_high = -1.0
            or_low = 9999999.0
            or_vol_sum = 0.0
            or_bar_cnt = 0

            for i in range(n):
                d = dates[i]
                m = minutes[i]
                c_price = closes[i]

                if d != curr_date:
                    curr_date = d
                    in_pos = False
                    traded_today = False
                    trailing_done = False
                    or_high = highs[i]
                    or_low = lows[i]
                    or_vol_sum = vols[i]
                    or_bar_cnt = 1
                    continue

                if m <= or_cutoff:
                    if highs[i] > or_high:
                        or_high = highs[i]
                    if lows[i] < or_low:
                        or_low = lows[i]
                    or_vol_sum += vols[i]
                    or_bar_cnt += 1
                    continue

                if m >= (15 * 60 + 10):
                    if in_pos:
                        pnl = (c_price - entry_price) * qty if pos_side == "BUY" else (entry_price - c_price) * qty
                        trades.append({"side": pos_side, "pnl": pnl, "exit": "EOD"})
                        in_pos = False
                    continue

                or_vol_avg = or_vol_sum / max(1, or_bar_cnt)

                if not in_pos:
                    if not traded_today and m <= (12 * 60):
                        if c_price > or_high and vols[i] >= (or_vol_avg * vol_mult):
                            qty = int(risk_capital / c_price)
                            if qty > 0:
                                entry_price = c_price * 1.0003
                                stop_price = entry_price * (1.0 - stop_loss_pct)
                                target_price = entry_price * (1.0 + target_pct)
                                in_pos = True
                                traded_today = True
                                trailing_done = False
                                pos_side = "BUY"
                        elif c_price < or_low and vols[i] >= (or_vol_avg * vol_mult):
                            qty = int(risk_capital / c_price)
                            if qty > 0:
                                entry_price = c_price * 0.9997
                                stop_price = entry_price * (1.0 + stop_loss_pct)
                                target_price = entry_price * (1.0 - target_pct)
                                in_pos = True
                                traded_today = True
                                trailing_done = False
                                pos_side = "SELL"
                else:
                    if pos_side == "BUY":
                        if use_trailing and not trailing_done and highs[i] >= (entry_price + (target_price - entry_price) * 0.40):
                            stop_price = entry_price * 1.001
                            trailing_done = True

                        if lows[i] <= stop_price:
                            pnl = (stop_price - entry_price) * qty
                            trades.append({"side": "BUY", "pnl": pnl, "exit": "STOP"})
                            in_pos = False
                        elif highs[i] >= target_price:
                            pnl = (target_price - entry_price) * qty
                            trades.append({"side": "BUY", "pnl": pnl, "exit": "TARGET"})
                            in_pos = False
                    elif pos_side == "SELL":
                        if use_trailing and not trailing_done and lows[i] <= (entry_price - (entry_price - target_price) * 0.40):
                            stop_price = entry_price * 0.999
                            trailing_done = True

                        if highs[i] >= stop_price:
                            pnl = (entry_price - stop_price) * qty
                            trades.append({"side": "SELL", "pnl": pnl, "exit": "STOP"})
                            in_pos = False
                        elif lows[i] <= target_price:
                            pnl = (entry_price - target_price) * qty
                            trades.append({"side": "SELL", "pnl": pnl, "exit": "TARGET"})
                            in_pos = False

        elif arch == "EMA_MOMENTUM":
            fast_p = int(params.get("fast_ema", 9))
            slow_p = int(params.get("slow_ema", 21))
            rsi_p = int(params.get("rsi_period", 14))
            use_trailing = bool(params.get("trailing_stop", True))

            ema_fast = df["close"].ewm(span=fast_p, adjust=False).mean().values
            ema_slow = df["close"].ewm(span=slow_p, adjust=False).mean().values

            delta = df["close"].diff()
            gain = delta.clip(lower=0).rolling(rsi_p).mean()
            loss = (-delta.clip(upper=0)).rolling(rsi_p).mean()
            rs = gain / loss.replace(0, 1e-9)
            rsi = (100.0 - (100.0 / (1.0 + rs))).fillna(50.0).values

            in_pos = False
            traded_today = False
            trailing_done = False
            curr_date = None
            pos_side = "BUY"
            entry_price = 0.0
            stop_price = 0.0
            target_price = 0.0
            qty = 0
            start_idx = max(slow_p, rsi_p) + 2

            for i in range(start_idx, n):
                d = dates[i]
                m = minutes[i]
                c_price = closes[i]

                if d != curr_date:
                    curr_date = d
                    in_pos = False
                    traded_today = False
                    trailing_done = False
                    continue

                if m >= (15 * 60 + 10):
                    if in_pos:
                        pnl = (c_price - entry_price) * qty if pos_side == "BUY" else (entry_price - c_price) * qty
                        trades.append({"side": pos_side, "pnl": pnl, "exit": "EOD"})
                        in_pos = False
                    continue

                if not in_pos:
                    if not traded_today and (9 * 60 + 30 <= m <= 13 * 60):
                        if ema_fast[i-1] <= ema_slow[i-1] and ema_fast[i] > ema_slow[i] and rsi[i] > 55:
                            qty = int(risk_capital / c_price)
                            if qty > 0:
                                entry_price = c_price * 1.0003
                                stop_price = entry_price * (1.0 - stop_loss_pct)
                                target_price = entry_price * (1.0 + target_pct)
                                in_pos = True
                                traded_today = True
                                trailing_done = False
                                pos_side = "BUY"
                        elif ema_fast[i-1] >= ema_slow[i-1] and ema_fast[i] < ema_slow[i] and rsi[i] < 45:
                            qty = int(risk_capital / c_price)
                            if qty > 0:
                                entry_price = c_price * 0.9997
                                stop_price = entry_price * (1.0 + stop_loss_pct)
                                target_price = entry_price * (1.0 - target_pct)
                                in_pos = True
                                traded_today = True
                                trailing_done = False
                                pos_side = "SELL"
                else:
                    if pos_side == "BUY":
                        if use_trailing and not trailing_done and highs[i] >= (entry_price + (target_price - entry_price) * 0.40):
                            stop_price = entry_price * 1.001
                            trailing_done = True
                        if lows[i] <= stop_price:
                            pnl = (stop_price - entry_price) * qty
                            trades.append({"side": "BUY", "pnl": pnl, "exit": "STOP"})
                            in_pos = False
                        elif highs[i] >= target_price:
                            pnl = (target_price - entry_price) * qty
                            trades.append({"side": "BUY", "pnl": pnl, "exit": "TARGET"})
                            in_pos = False
                    elif pos_side == "SELL":
                        if use_trailing and not trailing_done and lows[i] <= (entry_price - (entry_price - target_price) * 0.40):
                            stop_price = entry_price * 0.999
                            trailing_done = True
                        if highs[i] >= stop_price:
                            pnl = (entry_price - stop_price) * qty
                            trades.append({"side": "SELL", "pnl": pnl, "exit": "STOP"})
                            in_pos = False
                        elif lows[i] <= target_price:
                            pnl = (entry_price - target_price) * qty
                            trades.append({"side": "SELL", "pnl": pnl, "exit": "TARGET"})
                            in_pos = False

        elif arch == "RSI_PULLBACK":
            trend_p = int(params.get("trend_ema", 50))
            rsi_p = int(params.get("rsi_period", 14))
            oversold = float(params.get("oversold", 35))
            overbought = float(params.get("overbought", 65))
            use_trailing = bool(params.get("trailing_stop", True))

            ema_trend = df["close"].ewm(span=trend_p, adjust=False).mean().values

            delta = df["close"].diff()
            gain = delta.clip(lower=0).rolling(rsi_p).mean()
            loss = (-delta.clip(upper=0)).rolling(rsi_p).mean()
            rs = gain / loss.replace(0, 1e-9)
            rsi = (100.0 - (100.0 / (1.0 + rs))).fillna(50.0).values

            in_pos = False
            trailing_done = False
            pos_side = "BUY"
            entry_price = 0.0
            stop_price = 0.0
            target_price = 0.0
            qty = 0
            start_idx = max(trend_p, rsi_p) + 2

            for i in range(start_idx, n):
                m = minutes[i]
                c_price = closes[i]

                if m >= (15 * 60 + 10):
                    if in_pos:
                        pnl = (c_price - entry_price) * qty if pos_side == "BUY" else (entry_price - c_price) * qty
                        trades.append({"side": pos_side, "pnl": pnl, "exit": "EOD"})
                        in_pos = False
                    continue

                if not in_pos:
                    if 9 * 60 + 30 <= m <= 14 * 60:
                        qty = int(risk_capital / c_price)
                        if qty > 0:
                            if c_price > ema_trend[i] and rsi[i-1] <= oversold and rsi[i] > oversold:
                                entry_price = c_price * 1.0003
                                stop_price = entry_price * (1.0 - stop_loss_pct)
                                target_price = entry_price * (1.0 + target_pct)
                                in_pos = True
                                trailing_done = False
                                pos_side = "BUY"
                            elif c_price < ema_trend[i] and rsi[i-1] >= overbought and rsi[i] < overbought:
                                entry_price = c_price * 0.9997
                                stop_price = entry_price * (1.0 + stop_loss_pct)
                                target_price = entry_price * (1.0 - target_pct)
                                in_pos = True
                                trailing_done = False
                                pos_side = "SELL"
                else:
                    if pos_side == "BUY":
                        if use_trailing and not trailing_done and highs[i] >= (entry_price + (target_price - entry_price) * 0.40):
                            stop_price = entry_price * 1.001
                            trailing_done = True
                        if lows[i] <= stop_price:
                            pnl = (stop_price - entry_price) * qty
                            trades.append({"side": "BUY", "pnl": pnl, "exit": "STOP"})
                            in_pos = False
                        elif highs[i] >= target_price:
                            pnl = (target_price - entry_price) * qty
                            trades.append({"side": "BUY", "pnl": pnl, "exit": "TARGET"})
                            in_pos = False
                    elif pos_side == "SELL":
                        if use_trailing and not trailing_done and lows[i] <= (entry_price - (entry_price - target_price) * 0.40):
                            stop_price = entry_price * 0.999
                            trailing_done = True
                        if highs[i] >= stop_price:
                            pnl = (entry_price - stop_price) * qty
                            trades.append({"side": "SELL", "pnl": pnl, "exit": "STOP"})
                            in_pos = False
                        elif lows[i] <= target_price:
                            pnl = (entry_price - target_price) * qty
                            trades.append({"side": "SELL", "pnl": pnl, "exit": "TARGET"})
                            in_pos = False

        else:
            # VWAP_REVERSION (Daily Anchored Intraday VWAP)
            dev_mult = float(params.get("dev_mult", 1.8))
            use_trailing = bool(params.get("trailing_stop", True))
            tp = (highs + lows + closes) / 3.0
            intraday_vwap = np.zeros(n)
            curr_d = None
            c_tp_vol = 0.0
            c_vol = 0.0

            for idx in range(n):
                d = dates[idx]
                if d != curr_d:
                    curr_d = d
                    c_tp_vol = 0.0
                    c_vol = 0.0
                c_tp_vol += tp[idx] * vols[idx]
                c_vol += vols[idx]
                intraday_vwap[idx] = c_tp_vol / max(1.0, c_vol)

            rolling_std = df["close"].rolling(20).std().bfill().values
            upper_band = intraday_vwap + (rolling_std * dev_mult)
            lower_band = intraday_vwap - (rolling_std * dev_mult)

            # RSI filter
            delta = df["close"].diff()
            gain = delta.clip(lower=0).rolling(14).mean()
            loss = (-delta.clip(upper=0)).rolling(14).mean()
            rs = gain / loss.replace(0, 1e-9)
            rsi = (100.0 - (100.0 / (1.0 + rs))).fillna(50.0).values

            in_pos = False
            trailing_done = False
            pos_side = "BUY"
            entry_price = 0.0
            stop_price = 0.0
            target_price = 0.0
            qty = 0

            for i in range(25, n):
                m = minutes[i]
                c_price = closes[i]

                if m >= (15 * 60 + 10):
                    if in_pos:
                        pnl = (c_price - entry_price) * qty if pos_side == "BUY" else (entry_price - c_price) * qty
                        trades.append({"side": pos_side, "pnl": pnl, "exit": "EOD"})
                        in_pos = False
                    continue

                if not in_pos:
                    if 9 * 60 + 45 <= m <= 14 * 60:
                        if c_price < lower_band[i] and rsi[i] < 38:
                            qty = int(risk_capital / c_price)
                            if qty > 0:
                                entry_price = c_price * 1.0003
                                stop_price = entry_price * (1.0 - stop_loss_pct)
                                target_price = intraday_vwap[i]
                                in_pos = True
                                trailing_done = False
                                pos_side = "BUY"
                        elif c_price > upper_band[i] and rsi[i] > 62:
                            qty = int(risk_capital / c_price)
                            if qty > 0:
                                entry_price = c_price * 0.9997
                                stop_price = entry_price * (1.0 + stop_loss_pct)
                                target_price = intraday_vwap[i]
                                in_pos = True
                                trailing_done = False
                                pos_side = "SELL"
                else:
                    if pos_side == "BUY":
                        if use_trailing and not trailing_done and highs[i] >= (entry_price + (target_price - entry_price) * 0.40):
                            stop_price = entry_price * 1.001
                            trailing_done = True
                        if lows[i] <= stop_price:
                            pnl = (stop_price - entry_price) * qty
                            trades.append({"side": "BUY", "pnl": pnl, "exit": "STOP"})
                            in_pos = False
                        elif highs[i] >= target_price:
                            pnl = (target_price - entry_price) * qty
                            trades.append({"side": "BUY", "pnl": pnl, "exit": "TARGET"})
                            in_pos = False
                    elif pos_side == "SELL":
                        if use_trailing and not trailing_done and lows[i] <= (entry_price - (entry_price - target_price) * 0.40):
                            stop_price = entry_price * 0.999
                            trailing_done = True
                        if highs[i] >= stop_price:
                            pnl = (entry_price - stop_price) * qty
                            trades.append({"side": "SELL", "pnl": pnl, "exit": "STOP"})
                            in_pos = False
                        elif lows[i] <= target_price:
                            pnl = (entry_price - target_price) * qty
                            trades.append({"side": "SELL", "pnl": pnl, "exit": "TARGET"})
                            in_pos = False

        net_trades = []
        for t in trades:
            cost = risk_capital * 0.0005
            t["pnl"] = round(t["pnl"] - cost, 2)
            net_trades.append(t)

        return net_trades


# -------------------------------------------------------------------------
# Continuous Autonomous Quant Optimizer Service
# -------------------------------------------------------------------------
class ContinuousQuantOptimizer:
    """
    Background worker that continuously uses Gemini to invent new strategies,
    backtests them on historical market data, decides profitability, and tweaks
    underperforming parameters to maximize intraday alpha.
    """

    STATE_FILE = Path("data/gemini_quant_optimizer_state.json")

    def __init__(self):
        self.gemini = GeminiClient()
        self.backtester = FastIntradayBacktester(data_dir="data")

        self.is_running: bool = False
        self.cycle_count: int = 0
        self.strategies: Dict[str, QuantStrategy] = {}
        self.activity_log: List[Dict[str, Any]] = []
        self.current_activity: str = "Idle (Ready to launch continuous optimization)"
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        self._load_persisted_state()

    def _load_persisted_state(self):
        """Loads state from disk if available."""
        if self.STATE_FILE.exists():
            try:
                data = json.loads(self.STATE_FILE.read_text(encoding="utf-8"))
                self.cycle_count = data.get("cycle_count", 0)
                self.activity_log = data.get("activity_log", [])[-80:]
                raw_strats = data.get("strategies", {})
                for sid, sdata in raw_strats.items():
                    res_data = sdata.pop("latest_result", None)
                    latest_res = BacktestSummary(**res_data) if res_data else None
                    strat = QuantStrategy(latest_result=latest_res, **sdata)
                    self.strategies[sid] = strat
                logger.info(f"Loaded {len(self.strategies)} strategies from {self.STATE_FILE}")
                # Re-backtest loaded strategies to sync with current backtester engine
                for sid, strat in list(self.strategies.items()):
                    summary = self.backtester.run_backtest(strat)
                    strat.latest_result = summary
                    if summary.verdict == "PROFITABLE":
                        self._export_to_algodesk_config(strat, summary)

                # Ensure diverse high-winrate baseline strategies exist across distinct names
                diverse_baselines = [
                    ("morning_orb_alpha_v1", "Morning_ORB_Alpha", 1, "ORB_BREAKOUT", "High-conviction 15-minute opening range breakout on institutional momentum stocks with 40% trailing breakeven ratchet.", {"or_minutes": 15, "vol_mult": 1.25, "stop_loss_pct": 0.0065, "target_pct": 0.0135, "trailing_stop": True}),
                    ("institutional_breakout_75_v1", "Institutional_Breakout_75", 1, "ORB_BREAKOUT", "Institutional volume expansion above opening 15m range with rapid breakeven profit lock.", {"or_minutes": 15, "vol_mult": 1.20, "stop_loss_pct": 0.0060, "target_pct": 0.0125, "trailing_stop": True}),
                    ("dynamic_trend_pulse_75_v1", "Dynamic_Trend_Pulse_75", 1, "ORB_BREAKOUT", "Morning momentum trend continuation filtering out choppy days with asymmetric 1:2 R:R.", {"or_minutes": 15, "vol_mult": 1.18, "stop_loss_pct": 0.0065, "target_pct": 0.0130, "trailing_stop": True}),
                    ("nifty_momentum_sniper_v1", "Nifty_Momentum_Sniper", 1, "ORB_BREAKOUT", "Ultra-tight opening range expansion on NIFTY liquid leaders.", {"or_minutes": 15, "vol_mult": 1.22, "stop_loss_pct": 0.0070, "target_pct": 0.0140, "trailing_stop": True}),
                ]
                for sid, name, ver, arch, hyp, params in diverse_baselines:
                    if sid not in self.strategies:
                        strat = QuantStrategy(strategy_id=sid, name=name, version=ver, archetype=arch, hypothesis=hyp, parameters=params)
                        summary = self.backtester.run_backtest(strat)
                        strat.latest_result = summary
                        self.strategies[sid] = strat
                        if "PROFITABLE" in summary.verdict:
                            self._export_to_algodesk_config(strat, summary)
            except Exception as e:
                logger.warning(f"Error loading quant optimizer state: {e}")

    def _persist_state(self):
        """Saves state to disk."""
        try:
            self.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            export_strats = {}
            for sid, strat in self.strategies.items():
                s_dict = asdict(strat)
                export_strats[sid] = s_dict

            payload = {
                "cycle_count": self.cycle_count,
                "activity_log": self.activity_log[-80:],
                "strategies": export_strats,
                "last_updated": datetime.now().isoformat()
            }
            self.STATE_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning(f"Error persisting quant optimizer state: {e}")

    def log_event(self, event_type: str, message: str, meta: Optional[Dict[str, Any]] = None):
        """Appends an event to the activity stream."""
        entry = {
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "type": event_type,
            "message": message,
            "meta": meta or {}
        }
        self.activity_log.append(entry)
        if len(self.activity_log) > 100:
            self.activity_log = self.activity_log[-100:]
        logger.info(f"[QuantEngine] {event_type}: {message}")

    def start(self):
        """Starts the continuous background optimization loop."""
        with self._lock:
            if self.is_running:
                return
            self.is_running = True
            self.log_event("ENGINE_START", "🚀 Autonomous Gemini Quant Research Engine started in background.")
            self._thread = threading.Thread(target=self._run_loop, daemon=True, name="GeminiQuantEngine")
            self._thread.start()

    def stop(self):
        """Pauses the continuous background optimization loop."""
        with self._lock:
            self.is_running = False
            self.current_activity = "Paused by operator"
            self.log_event("ENGINE_PAUSE", "⏸️ Autonomous research engine paused.")
            self._persist_state()

    def run_one_cycle_now(self) -> Dict[str, Any]:
        """Manually triggers one complete iteration (Create -> Backtest -> Decide -> Tweak)."""
        return self._execute_cycle()

    def _run_loop(self):
        """Continuous execution loop while server is up."""
        logger.info("Autonomous Quant Engine background worker loop active.")
        while self.is_running:
            try:
                self._execute_cycle()
            except Exception as e:
                logger.error(f"Error in quant engine cycle: {e}", exc_info=True)
                self.log_event("CYCLE_ERROR", f"Cycle execution failed: {str(e)}")

            # Wait 25 seconds between cycles in autonomous mode
            for _ in range(25):
                if not self.is_running:
                    break
                time.sleep(1)

    def _execute_cycle(self) -> Dict[str, Any]:
        """Executes a single end-to-end iteration."""
        self.cycle_count += 1
        cycle_num = self.cycle_count

        # Decide whether to TWEAK an existing promising strategy or CREATE a new archetype
        promising_candidates = [
            s for s in self.strategies.values()
            if s.latest_result and s.version < 6
        ]

        # 40% chance: Innovate a brand new strategy archetype
        # 60% chance: Tweak an existing candidate across diverse archetypes
        if promising_candidates and random.random() < 0.60:
            # Group by archetype so all archetypes (EMA, VWAP, RSI, ORB) get optimized toward >= 75% win rate
            arch_groups = {}
            for s in promising_candidates:
                arch_groups.setdefault(s.archetype, []).append(s)
            
            # Rotate across archetypes so non-ORB strategies get tweaked too
            chosen_arch = random.choice(list(arch_groups.keys()))
            arch_strats = arch_groups[chosen_arch]
            arch_strats.sort(
                key=lambda s: (s.latest_result.profit_factor if s.latest_result else 0.0),
                reverse=True
            )
            target_strat = arch_strats[0] if random.random() < 0.60 else random.choice(arch_strats)
            action = "TWEAK"
            self.current_activity = f"Cycle #{cycle_num}: Tweaking strategy '{target_strat.name}' ({target_strat.archetype} v{target_strat.version}) via Gemini AI..."
            strat, summary, thought = self._tweak_strategy_with_gemini(target_strat)
        else:
            action = "INNOVATE"
            self.current_activity = f"Cycle #{cycle_num}: Conceiving new strategy archetype via Gemini AI..."
            strat, summary, thought = self._create_new_strategy_with_gemini()

        # Update and persist
        self.strategies[strat.strategy_id] = strat
        self._persist_state()

        # Auto-export profitable strategies to configs/
        if summary.verdict == "PROFITABLE":
            self._export_to_algodesk_config(strat, summary)

        self.current_activity = f"Cycle #{cycle_num} Complete: Strategy '{strat.name}' -> {summary.verdict} (Net Return: {summary.net_return_pct}%, PF: {summary.profit_factor})"
        return {
            "cycle": cycle_num,
            "action": action,
            "strategy": asdict(strat),
            "result": asdict(summary),
            "thought": thought
        }

    # -------------------------------------------------------------------------
    # Gemini AI Generation & Mutation Methods
    # -------------------------------------------------------------------------
    def _create_new_strategy_with_gemini(self) -> Tuple[QuantStrategy, BacktestSummary, str]:
        """Prompts Gemini to conceive a novel intraday trading algorithm."""
        archetypes = ["ORB_BREAKOUT", "EMA_MOMENTUM", "VWAP_REVERSION", "RSI_PULLBACK"]
        # Balanced representation across archetypes
        arch_counts = {a: 0 for a in archetypes}
        for s in self.strategies.values():
            if s.archetype in arch_counts:
                arch_counts[s.archetype] += 1
        min_count = min(arch_counts.values())
        candidates = [a for a, c in arch_counts.items() if c == min_count]
        chosen_arch = random.choice(candidates) if candidates else random.choice(archetypes)

        prompt = (
            f"You are a Senior Quantitative Portfolio Manager designing intraday strategies for the Indian equity market (NSE NIFTY 50).\n"
            f"MANDATORY REQUIREMENT: Target AT LEAST 75% WIN RATE on 5-minute historical candles.\n"
            f"Generate an optimized quantitative intraday strategy for archetype: '{chosen_arch}'.\n\n"
            f"RULES TO REACH 75%+ WIN RATE:\n"
            f"1. Target high-probability asymmetric setups: achievable targets (0.010 to 0.014, i.e. 1.0% to 1.4%) with tight stop losses (0.006 to 0.0075).\n"
            f"2. Enable trailing_stop: true to move stop-loss to breakeven after 40% target progress, securing win rate.\n"
            f"3. Strict volume confirmation: vol_mult between 1.15 and 1.25 to avoid false breakouts.\n"
            f"4. Output strictly JSON with keys:\n"
            f"   - \"name\": string (e.g. \"Alpha_ORB_75Winrate\", \"Confluence_Momentum_Elite\", \"Vwap_Pullback_Edge\")\n"
            f"   - \"hypothesis\": string (short 1-2 sentence market rationale emphasizing 75%+ win rate)\n"
            f"   - \"parameters\": dict matching the archetype:\n"
            f"       * If ORB_BREAKOUT: {{\"or_minutes\": 15, \"vol_mult\": 1.15 to 1.25, \"stop_loss_pct\": 0.0065 to 0.0075, \"target_pct\": 0.011 to 0.014, \"trailing_stop\": true}}\n"
            f"       * If EMA_MOMENTUM: {{\"fast_ema\": 9, \"slow_ema\": 21, \"rsi_period\": 14, \"stop_loss_pct\": 0.007, \"target_pct\": 0.012, \"trailing_stop\": true}}\n"
            f"       * If VWAP_REVERSION: {{\"dev_mult\": 1.8 to 2.2, \"stop_loss_pct\": 0.007, \"target_pct\": 0.012, \"trailing_stop\": true}}\n"
            f"       * If RSI_PULLBACK: {{\"trend_ema\": 50, \"rsi_period\": 14, \"oversold\": 35, \"overbought\": 65, \"stop_loss_pct\": 0.007, \"target_pct\": 0.012, \"trailing_stop\": true}}\n"
            f"Respond ONLY with valid JSON."
        )

        thought = "Generating new 75%+ win rate intraday hypothesis..."
        try:
            if self.gemini.is_available():
                resp_text = self.gemini._call_gemini(self.gemini.fast_model, prompt)
                data = json.loads(resp_text)
                name = data.get("name", f"Gemini_{chosen_arch.title()}_75")
                hypothesis = data.get("hypothesis", "High-probability 75%+ win rate setup.")
                params = data.get("parameters", {})
                thought = f"Gemini conceived '{name}': {hypothesis}"
            else:
                # Built-in deterministic generation fallback
                names_by_arch = {
                    "ORB_BREAKOUT": ["Opening_Range_Sniper", "Breakout_Surge_Alpha", "Morning_Momentum_Orb"],
                    "EMA_MOMENTUM": ["Trend_Cross_Momentum", "Dual_Ema_Rider", "Dynamic_Trend_Pulse"],
                    "VWAP_REVERSION": ["Vwap_Mean_Reversion", "Institutional_Band_Reversal", "Vwap_Bounce_Edge"],
                    "RSI_PULLBACK": ["Rsi_Deep_Pullback", "Mean_Reversion_Sniper", "Oscillator_Exhaustion_Trap"]
                }
                chosen_names = names_by_arch.get(chosen_arch, ["Quant_Edge"])
                name = random.choice(chosen_names) + f"_{int(time.time()) % 1000}"
                hypothesis = f"Rule-based {chosen_arch} optimized for liquid NSE stocks."
                params = self._default_parameters_for_archetype(chosen_arch)
                thought = f"Rule engine configured baseline '{name}'."
        except Exception as e:
            logger.warning(f"Gemini generation call failed, using heuristic baseline: {e}")
            names_by_arch = {
                "ORB_BREAKOUT": ["Opening_Range_Sniper", "Breakout_Surge_Alpha", "Morning_Momentum_Orb"],
                "EMA_MOMENTUM": ["Trend_Cross_Momentum", "Dual_Ema_Rider", "Dynamic_Trend_Pulse"],
                "VWAP_REVERSION": ["Vwap_Mean_Reversion", "Institutional_Band_Reversal", "Vwap_Bounce_Edge"],
                "RSI_PULLBACK": ["Rsi_Deep_Pullback", "Mean_Reversion_Sniper", "Oscillator_Exhaustion_Trap"]
            }
            chosen_names = names_by_arch.get(chosen_arch, ["Quant_Edge"])
            name = random.choice(chosen_names) + f"_{int(time.time()) % 1000}"
            hypothesis = "Algorithmic momentum baseline."
            params = self._default_parameters_for_archetype(chosen_arch)

        base_id = name.lower().replace(' ', '_').replace('-', '_')
        strat_id = f"{base_id}_v1"
        idx = 1
        while strat_id in self.strategies:
            idx += 1
            strat_id = f"{base_id}_{idx}_v1"
        strat = QuantStrategy(
            strategy_id=strat_id,
            name=name,
            version=1,
            archetype=chosen_arch,
            hypothesis=hypothesis,
            parameters=params
        )

        # Backtest against historical market data
        summary = self.backtester.run_backtest(strat)
        strat.latest_result = summary
        strat.iteration_history.append({
            "version": 1,
            "parameters": params,
            "summary": asdict(summary),
            "thought": thought
        })

        self.log_event(
            "STRAT_CREATED",
            f"Generated '{strat.name}' (v1) -> Backtested {summary.trades_count} trades, WinRate: {summary.win_rate}%, Net: {summary.net_return_pct}%, PF: {summary.profit_factor} [{summary.verdict}]",
            {"strategy_id": strat.strategy_id, "verdict": summary.verdict}
        )
        return strat, summary, thought

    def _tweak_strategy_with_gemini(self, parent_strat: QuantStrategy) -> Tuple[QuantStrategy, BacktestSummary, str]:
        """Feeds backtest performance to Gemini to tweak parameters for at least 75% win rate."""
        prev_res = parent_strat.latest_result
        new_version = parent_strat.version + 1

        prompt = (
            f"You are an AI Quantitative Trader optimizing an intraday strategy for Indian equities (NSE).\n"
            f"Current Strategy: '{parent_strat.name}' (Archetype: {parent_strat.archetype}, Version: {parent_strat.version})\n"
            f"Current Parameters: {json.dumps(parent_strat.parameters)}\n\n"
            f"Historical Backtest Results:\n"
            f"- Trades Count: {prev_res.trades_count if prev_res else 0}\n"
            f"- Win Rate: {prev_res.win_rate if prev_res else 0}% (MANDATORY TARGET: >= 75.0%)\n"
            f"- Profit Factor: {prev_res.profit_factor if prev_res else 0}\n"
            f"- Net Return: {prev_res.net_return_pct if prev_res else 0}%\n"
            f"- Max Drawdown: {prev_res.max_drawdown_pct if prev_res else 0}%\n"
            f"- Current Status: {prev_res.verdict if prev_res else 'UNPROFITABLE'}\n\n"
            f"TASK:\n"
            f"Tweak parameters specifically to achieve a WIN RATE OF AT LEAST 75.0% while keeping Profit Factor > 1.5 and Net Return > 1.0%.\n"
            f"Proven adjustments for 75%+ Win Rate on NSE 5-minute data:\n"
            f"1. Set \"trailing_stop\": true (locks in breakeven when price moves 40% toward target).\n"
            f"2. For ORB_BREAKOUT: set or_minutes: 15, vol_mult: 1.18 to 1.25, stop_loss_pct: 0.0065 to 0.0075, target_pct: 0.011 to 0.0135.\n"
            f"3. For pullbacks / mean-reversion: tighten target to 0.010 - 0.013 to ensure high hit rate before reversals.\n"
            f"Output strictly JSON with keys:\n"
            f"   - \"tweak_rationale\": string (why you adjusted these parameters to reach >= 75% win rate)\n"
            f"   - \"parameters\": dict with refined values\n"
            f"Respond ONLY with valid JSON."
        )

        thought = "Tweaking strategy parameters..."
        new_params = dict(parent_strat.parameters)

        try:
            if self.gemini.is_available():
                resp_text = self.gemini._call_gemini(self.gemini.fast_model, prompt)
                data = json.loads(resp_text)
                thought = data.get("tweak_rationale", "Refined parameters based on backtest risk-reward.")
                gemini_params = data.get("parameters", {})
                new_params.update(gemini_params)
            else:
                # Heuristic optimization fallback
                thought = "Heuristically optimizing stop-loss and profit targets."
                sl = new_params.get("stop_loss_pct", 0.01)
                tp = new_params.get("target_pct", 0.02)
                new_params["stop_loss_pct"] = round(sl * 1.15 if prev_res and prev_res.win_rate < 40 else sl * 0.9, 4)
                new_params["target_pct"] = round(tp * 1.2, 4)
        except Exception as e:
            logger.warning(f"Gemini tweak call failed: {e}")
            thought = "Applied parameter perturbation."
            new_params["target_pct"] = round(new_params.get("target_pct", 0.02) * 1.1, 4)

        # Mutate strategy
        base_id = parent_strat.name.lower().replace(' ', '_').replace('-', '_')
        mutated_id = f"{base_id}_v{new_version}"
        idx = 1
        while mutated_id in self.strategies:
            idx += 1
            mutated_id = f"{base_id}_{idx}_v{new_version}"

        mutated_strat = QuantStrategy(
            strategy_id=mutated_id,
            name=parent_strat.name,
            version=new_version,
            archetype=parent_strat.archetype,
            hypothesis=parent_strat.hypothesis,
            parameters=new_params,
            parent_id=parent_strat.strategy_id,
            iteration_history=list(parent_strat.iteration_history)
        )

        # Re-backtest mutated version
        new_summary = self.backtester.run_backtest(mutated_strat)
        mutated_strat.latest_result = new_summary
        mutated_strat.iteration_history.append({
            "version": new_version,
            "parameters": new_params,
            "summary": asdict(new_summary),
            "thought": thought
        })

        ret_diff = new_summary.net_return_pct - (prev_res.net_return_pct if prev_res else 0)
        sign = "+" if ret_diff >= 0 else ""

        self.log_event(
            "STRAT_TWEAKED",
            f"Tweaked '{mutated_strat.name}' (v{new_version}): Return {sign}{ret_diff:.2f}% -> Net: {new_summary.net_return_pct}%, PF: {new_summary.profit_factor} [{new_summary.verdict}]",
            {"strategy_id": mutated_strat.strategy_id, "verdict": new_summary.verdict, "thought": thought}
        )

        return mutated_strat, new_summary, thought

    def _default_parameters_for_archetype(self, archetype: str) -> Dict[str, Any]:
        """Baseline parameters for fallback generation."""
        if archetype == "ORB_BREAKOUT":
            return {"or_minutes": 15, "vol_mult": 1.20, "stop_loss_pct": 0.007, "target_pct": 0.0135, "trailing_stop": True}
        elif archetype == "EMA_MOMENTUM":
            return {"fast_ema": 9, "slow_ema": 21, "rsi_period": 14, "stop_loss_pct": 0.007, "target_pct": 0.012, "trailing_stop": True}
        elif archetype == "RSI_PULLBACK":
            return {"trend_ema": 50, "rsi_period": 14, "oversold": 35, "overbought": 65, "stop_loss_pct": 0.007, "target_pct": 0.0135, "trailing_stop": True}
        else:
            return {"dev_mult": 1.8, "stop_loss_pct": 0.008, "target_pct": 0.012, "trailing_stop": True}

    def _export_to_algodesk_config(self, strat: QuantStrategy, summary: BacktestSummary):
        """Auto-exports a profitable strategy to configs/ for 1-click execution in AlgoDesk."""
        try:
            cfg_dir = Path("configs")
            cfg_dir.mkdir(parents=True, exist_ok=True)
            cfg_file = cfg_dir / f"{strat.strategy_id}.yaml"

            yaml_content = f"""# =====================================================================
# AlgoDesk AI-Generated Strategy Configuration (Auto-Optimized by Gemini)
# Status: {summary.verdict} | Net Return: +{summary.net_return_pct}% | Profit Factor: {summary.profit_factor}
# Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
# =====================================================================
name: "{strat.strategy_id}"
description: "{strat.hypothesis}"
archetype: "{strat.archetype}"
version: "{strat.version}"
timeframe: "5m"
live_enabled: false

parameters:
{chr(10).join(f"  {k}: {v}" for k, v in strat.parameters.items())}

risk:
  risk_per_trade_pct: 0.01
  max_open_positions: 3
  stop_loss_pct: {strat.parameters.get('stop_loss_pct', 0.01)}
  target_pct: {strat.parameters.get('target_pct', 0.02)}

backtest_metrics:
  net_return_pct: {summary.net_return_pct}
  profit_factor: {summary.profit_factor}
  win_rate_pct: {summary.win_rate}
  sharpe_ratio: {summary.sharpe_ratio}
  max_drawdown_pct: {summary.max_drawdown_pct}
"""
            cfg_file.write_text(yaml_content, encoding="utf-8")
            self.log_event("CONFIG_EXPORTED", f"Exported profitable strategy to {cfg_file}")

            # Persist to SQLite Database
            self._save_strategy_to_db(strat, summary, cfg_file)
        except Exception as e:
            logger.warning(f"Error exporting config: {e}")

    def _save_strategy_to_db(self, strat: QuantStrategy, summary: BacktestSummary, cfg_path: Optional[Path] = None):
        """Persists winning and profitable strategies directly into SQLite database (data/stock_screener.db)."""
        db_path = Path("data/stock_screener.db")
        try:
            import sqlite3
            conn = sqlite3.connect(str(db_path))
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS ai_quant_strategies (
                    strategy_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    archetype TEXT NOT NULL,
                    hypothesis TEXT,
                    parameters TEXT,
                    symbol_tested TEXT,
                    win_rate REAL,
                    profit_factor REAL,
                    net_return_pct REAL,
                    max_drawdown_pct REAL,
                    sharpe_ratio REAL,
                    trades_count INTEGER,
                    win_trades INTEGER,
                    loss_trades INTEGER,
                    verdict TEXT,
                    config_yaml_path TEXT,
                    created_at TEXT,
                    updated_at TEXT
                );
            """)

            cur.execute("""
                INSERT INTO ai_quant_strategies (
                    strategy_id, name, version, archetype, hypothesis,
                    parameters, symbol_tested, win_rate, profit_factor,
                    net_return_pct, max_drawdown_pct, sharpe_ratio,
                    trades_count, win_trades, loss_trades, verdict,
                    config_yaml_path, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(strategy_id) DO UPDATE SET
                    parameters=excluded.parameters,
                    win_rate=excluded.win_rate,
                    profit_factor=excluded.profit_factor,
                    net_return_pct=excluded.net_return_pct,
                    max_drawdown_pct=excluded.max_drawdown_pct,
                    sharpe_ratio=excluded.sharpe_ratio,
                    trades_count=excluded.trades_count,
                    win_trades=excluded.win_trades,
                    loss_trades=excluded.loss_trades,
                    verdict=excluded.verdict,
                    config_yaml_path=excluded.config_yaml_path,
                    updated_at=excluded.updated_at;
            """, (
                strat.strategy_id,
                strat.name,
                strat.version,
                strat.archetype,
                strat.hypothesis,
                json.dumps(strat.parameters),
                summary.symbol_tested,
                summary.win_rate,
                summary.profit_factor,
                summary.net_return_pct,
                summary.max_drawdown_pct,
                summary.sharpe_ratio,
                summary.trades_count,
                summary.win_trades,
                summary.loss_trades,
                summary.verdict,
                str(cfg_path) if cfg_path else "",
                strat.created_at,
                datetime.now().isoformat()
            ))
            conn.commit()
            conn.close()
            self.log_event("DB_SAVED", f"Persisted winning algorithm '{strat.strategy_id}' ({summary.win_rate}% WR, PF {summary.profit_factor}) into SQLite database.")
        except Exception as e:
            logger.warning(f"Error saving strategy to DB: {e}")

    # -------------------------------------------------------------------------
    # Public Telemetry API for UI
    # -------------------------------------------------------------------------
    def get_status_payload(self) -> Dict[str, Any]:
        """Provides full real-time telemetry for the frontend dashboard."""
        all_strats = list(self.strategies.values())
        profitable_strats = [
            asdict(s) for s in all_strats
            if s.latest_result and "PROFITABLE" in s.latest_result.verdict
        ]
        # Prioritize 75%+ Win Rate, then Profit Factor, then Net Return
        profitable_strats.sort(
            key=lambda x: (
                1 if (x.get("latest_result", {}).get("win_rate", 0.0) >= 75.0) else 0,
                x.get("latest_result", {}).get("profit_factor", 0.0),
                x.get("latest_result", {}).get("net_return_pct", 0.0)
            ),
            reverse=True
        )

        high_winrate_strats = [
            s for s in profitable_strats
            if s.get("latest_result", {}).get("win_rate", 0.0) >= 75.0
        ]

        all_strats_list = [asdict(s) for s in all_strats]
        all_strats_list.sort(
            key=lambda x: (
                1 if (x.get("latest_result", {}).get("win_rate", 0.0) >= 75.0) else 0,
                x.get("latest_result", {}).get("net_return_pct", -999.0)
            ),
            reverse=True
        )

        best_pf = max((s.latest_result.profit_factor for s in all_strats if s.latest_result), default=0.0)
        best_ret = max((s.latest_result.net_return_pct for s in all_strats if s.latest_result), default=0.0)
        best_wr = max((s.latest_result.win_rate for s in all_strats if s.latest_result), default=0.0)

        db_count = len(profitable_strats)
        try:
            import sqlite3
            conn = sqlite3.connect("data/stock_screener.db")
            cur = conn.cursor()
            cur.execute("SELECT count(*) FROM ai_quant_strategies;")
            row = cur.fetchone()
            if row:
                db_count = row[0]
            conn.close()
        except Exception:
            pass

        # Diversify profitable leaderboard so at most 2 versions per root strategy name appear,
        # ensuring different archetypes (EMA, VWAP, RSI, ORB) are visible simultaneously!
        diverse_profitable = []
        name_counts = {}
        for s in profitable_strats:
            name = s.get("name", "")
            if name_counts.get(name, 0) < 2:
                diverse_profitable.append(s)
                name_counts[name] = name_counts.get(name, 0) + 1

        # Diversify high winrate leaderboard (>= 75%) across distinct strategy names
        high_wr_list = [
            s for s in profitable_strats
            if s.get("latest_result", {}).get("win_rate", 0.0) >= 75.0
        ]
        diverse_high_wr = []
        hwr_counts = {}
        for s in high_wr_list:
            name = s.get("name", "")
            if hwr_counts.get(name, 0) < 2:
                diverse_high_wr.append(s)
                hwr_counts[name] = hwr_counts.get(name, 0) + 1

        return {
            "is_running": self.is_running,
            "cycle_count": self.cycle_count,
            "current_activity": self.current_activity,
            "gemini_available": self.gemini.is_available(),
            "gemini_model": self.gemini.fast_model,
            "total_strategies": len(all_strats),
            "profitable_count": len(profitable_strats),
            "high_winrate_count": len(high_winrate_strats),
            "db_saved_count": db_count,
            "best_win_rate": best_wr,
            "best_profit_factor": best_pf,
            "best_net_return": best_ret,
            "high_winrate_leaderboard": diverse_high_wr[:15],
            "profitable_leaderboard": diverse_profitable[:15],
            "all_strategies": all_strats_list[:30],
            "recent_activity": list(reversed(self.activity_log[-20:])),
        }


# Global singleton instance
quant_optimizer = ContinuousQuantOptimizer()
