"""
Continuous Swing Paper Trading Runner (₹250,000 Capital)
Strategy: EMA Pullback + ADX (Long-Only CNC Delivery)
Automates universe scanning, signal generation, trade execution, trailing stops, and real-time equity tracking.
"""

from datetime import datetime, date, timedelta
import json
import logging
import math
import os
from pathlib import Path
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from algodesk.strategies.ema_pullback_adx import EMAPullbackADXStrategy
from algodesk.execution.paper_trading import PaperTradingEngine, PaperPosition, PaperTrade
from algodesk.indicators.ema import calc_ema_trend
from algodesk.indicators.atr import calc_atr
from algodesk.indicators.adx import calc_adx
from algodesk.backtest.costs import CostModel

IST = ZoneInfo("Asia/Kolkata")
logger = logging.getLogger("SwingContinuousRunner")


class SwingContinuousRunner:
    """Production-grade continuous paper trading runner for EMA Pullback + ADX strategy."""

    def __init__(self, initial_capital: float = 250000.0, config_path: str = "algodesk/config.yaml"):
        self.initial_capital = initial_capital
        self.config_path = config_path
        self.log_dir = Path("algodesk/paper_trading_logs")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        self.engine = PaperTradingEngine(
            initial_capital=initial_capital,
            name="Swing_EMA_ADX_250K"
        )
        self.cost_model = CostModel()
        
        # Strategy config
        self.strategy_config = {
            'indicators': {
                'ema_fast': 20,
                'ema_slow': 50,
                'adx_len': 14,
                'adx_min': 20.0,
                'atr_len': 14,
                'vol_mult': 1.5
            },
            'risk': {
                'min_rr': 1.5,
                'max_stop_atr': 2.5,
                'risk_pct': 0.01,
                'max_position_pct': 0.20,
                'max_positions': 5,
                'max_per_sector': 2,
                'max_open_risk': 0.05
            },
            'setup': {
                'gap_max_atr': 0.5,
                'time_stop_days': 20,
                'setup_valid_days': 2
            },
            'filters': {
                'min_traded_value_20d': 5000000.0,  # 50 Lakhs INR
                'skip_circuit_limit': 0.95
            }
        }
        self.strategy = EMAPullbackADXStrategy(self.strategy_config)
        
        # State
        self.active_signals: List[Dict[str, Any]] = []
        self.scanned_candidates: List[Dict[str, Any]] = []
        self.market_filter_status: Dict[str, Any] = {
            "passed": True,
            "nifty_close": 0.0,
            "nifty_ema50": 0.0,
            "checked_at": None
        }
        self.is_running = False
        self._worker_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        
        # Attempt to restore previous state
        self._load_state()

    def _state_file(self) -> Path:
        return self.log_dir / "swing_state_250k.json"

    def _trades_csv(self) -> Path:
        return self.log_dir / "swing_trades_250k.csv"

    def _save_state(self):
        """Persists current state to JSON and CSV."""
        with self._lock:
            try:
                state_data = {
                    "initial_capital": self.initial_capital,
                    "current_capital": self.engine.current_capital,
                    "equity": self.engine.equity,
                    "peak_equity": self.engine.peak_equity,
                    "max_drawdown": self.engine.max_drawdown,
                    "max_drawdown_pct": self.engine.max_drawdown_pct,
                    "positions": {
                        sym: {
                            "symbol": p.symbol,
                            "qty": p.qty,
                            "entry_price": p.entry_price,
                            "entry_date": p.entry_date,
                            "stop_loss": p.stop_loss,
                            "target": p.target,
                            "current_price": p.current_price,
                            "unrealized_pnl": p.unrealized_pnl,
                            "unrealized_pnl_pct": p.unrealized_pnl_pct,
                            "setup_type": p.setup_type,
                            "days_held": p.days_held
                        }
                        for sym, p in self.engine.positions.items()
                    },
                    "market_filter": self.market_filter_status,
                    "active_signals": self.active_signals,
                    "last_updated": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
                }
                with open(self._state_file(), "w") as f:
                    json.dump(state_data, f, indent=2)

                # Save trades CSV
                if self.engine.trades:
                    rows = []
                    for t in self.engine.trades:
                        rows.append({
                            "symbol": t.symbol,
                            "entry_date": t.entry_date,
                            "exit_date": t.exit_date,
                            "entry_price": t.entry_price,
                            "exit_price": t.exit_price,
                            "qty": t.qty,
                            "setup_type": t.setup_type,
                            "exit_reason": t.exit_reason,
                            "gross_pnl": t.gross_pnl,
                            "costs": t.costs,
                            "net_pnl": t.net_pnl,
                            "net_pnl_pct": t.net_pnl_pct
                        })
                    pd.DataFrame(rows).to_csv(self._trades_csv(), index=False)
            except Exception as e:
                logger.error(f"Error saving swing runner state: {e}")

    def _load_state(self):
        """Restores state if previous session exists."""
        if not self._state_file().exists():
            return
        try:
            with open(self._state_file(), "r") as f:
                data = json.load(f)
            self.engine.current_capital = float(data.get("current_capital", self.initial_capital))
            self.engine.equity = float(data.get("equity", self.initial_capital))
            self.engine.peak_equity = float(data.get("peak_equity", self.initial_capital))
            self.engine.max_drawdown = float(data.get("max_drawdown", 0.0))
            self.engine.max_drawdown_pct = float(data.get("max_drawdown_pct", 0.0))
            
            # Restore positions
            positions = data.get("positions", {})
            for sym, pdata in positions.items():
                pos = PaperPosition(
                    symbol=pdata["symbol"],
                    qty=int(pdata["qty"]),
                    entry_price=float(pdata["entry_price"]),
                    entry_date=pdata["entry_date"],
                    stop_loss=float(pdata["stop_loss"]),
                    target=float(pdata["target"]),
                    current_price=float(pdata.get("current_price", pdata["entry_price"])),
                    unrealized_pnl=float(pdata.get("unrealized_pnl", 0.0)),
                    unrealized_pnl_pct=float(pdata.get("unrealized_pnl_pct", 0.0)),
                    setup_type=pdata.get("setup_type", "A_pullback"),
                    days_held=int(pdata.get("days_held", 0))
                )
                self.engine.positions[sym] = pos

            self.active_signals = data.get("active_signals", [])
            self.market_filter_status = data.get("market_filter", self.market_filter_status)
            logger.info(f"Loaded existing swing state: Equity ₹{self.engine.equity:,.2f}, {len(self.engine.positions)} open positions")
        except Exception as e:
            logger.error(f"Failed to load swing state: {e}")

    def get_latest_quote(self, symbol: str) -> Optional[float]:
        """Fetches fast real-time or cached quote."""
        clean_sym = symbol.replace(".NS", "").upper()
        # 1. Try Yahoo Finance / data loader
        try:
            from src.data_loader import fetch_stock_data
            df = fetch_stock_data(clean_sym, period="5d")
            if df is not None and not df.empty:
                return float(df.iloc[-1]['Close'])
        except Exception:
            pass

        # 2. Try parquet cache fallback
        for cache_dir in ["data/nifty500_10y_cache", "data/top100_cache"]:
            pfile = Path(f"{cache_dir}/{clean_sym}.NS.parquet")
            if pfile.exists():
                try:
                    df = pd.read_parquet(pfile)
                    col = 'Close' if 'Close' in df.columns else 'close'
                    return float(df.iloc[-1][col])
                except Exception:
                    pass
        return None

    def check_market_filter(self) -> Tuple[bool, float, float]:
        """Checks if Nifty 50 close is above its 50-day EMA."""
        try:
            from src.data_loader import fetch_stock_data
            nifty_df = fetch_stock_data("^NSEI", period="6mo")
            if nifty_df is not None and len(nifty_df) >= 50:
                nifty_df['ema_50'] = nifty_df['Close'].ewm(span=50, adjust=False).mean()
                latest_close = float(nifty_df.iloc[-1]['Close'])
                latest_ema50 = float(nifty_df.iloc[-1]['ema_50'])
                passed = latest_close > latest_ema50
                self.market_filter_status = {
                    "passed": passed,
                    "nifty_close": round(latest_close, 2),
                    "nifty_ema50": round(latest_ema50, 2),
                    "checked_at": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
                }
                return passed, latest_close, latest_ema50
        except Exception as e:
            logger.warning(f"Error checking Nifty market filter: {e}")

        # Fallback to permissive
        self.market_filter_status["checked_at"] = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
        return True, 0.0, 0.0

    def scan_universe(self, max_stocks: int = 50) -> List[Dict[str, Any]]:
        """
        Runs EOD/Continuous scan across liquid Nifty universe.
        Returns list of valid Setup A (Pullback) and Setup B (Breakout) signals.
        Evaluates signals valid within SETUP_VALID_DAYS (2 days).
        """
        logger.info(f"Initiating Swing Scan across liquid universe (max {max_stocks})...")
        market_pass, n_close, n_ema = self.check_market_filter()
        if not market_pass:
            logger.warning(f"Nifty filter failed (Close {n_close} <= EMA50 {n_ema}). Skipping setups.")
            self.scanned_candidates = []
            return []

        import glob
        from concurrent.futures import ThreadPoolExecutor, as_completed

        cache_files = sorted(glob.glob("data/nifty500_10y_cache/*.parquet"))
        if cache_files:
            target_files = cache_files[:max_stocks]
        else:
            target_files = []

        setups_found = []
        today_str = datetime.now(IST).date().isoformat()
        seen_symbols = set()
        seen_lock = threading.Lock()

        def _scan_single_stock(pfile_path: str) -> Optional[Dict[str, Any]]:
            sym = Path(pfile_path).stem.replace(".NS", "")
            try:
                df = pd.read_parquet(pfile_path).tail(80).copy()
                if len(df) < 50:
                    return None
                df.columns = [str(c).lower() for c in df.columns]

                for lookback_offset in range(min(3, len(df) - 45)):
                    sub_idx = len(df) - lookback_offset
                    sub_df = df.iloc[:sub_idx]
                    bar_date_str = sub_df.index[-1].strftime("%Y-%m-%d") if hasattr(sub_df.index[-1], "strftime") else today_str

                    ctx = {
                        'symbol': sym,
                        'current_date': bar_date_str,
                        'nifty_ema50': n_ema if n_ema > 0 else None
                    }

                    setup = self.strategy.scan(sub_df, ctx)
                    if setup:
                        with seen_lock:
                            if sym in seen_symbols:
                                return None
                            seen_symbols.add(sym)
                        return {
                            "symbol": setup.symbol,
                            "date": bar_date_str,
                            "kind": setup.kind,
                            "trigger": round(float(setup.trigger), 2),
                            "stop": round(float(setup.stop), 2),
                            "target1": round(float(setup.target1), 2),
                            "risk": round(float(setup.risk), 2),
                            "rr": round(float(setup.rr), 2),
                            "ema20": round(float(setup.ema20), 2),
                            "ema50": round(float(setup.ema50), 2),
                            "adx": round(float(setup.adx or 0.0), 2),
                            "atr": round(float(setup.atr), 2),
                            "volume_ratio": round(float(setup.volume_ratio or 1.0), 2),
                            "pattern": setup.meta.get("pattern", "setup"),
                            "valid_until": (datetime.now(IST).date() + timedelta(days=2)).isoformat(),
                            "status": "OPEN"
                        }
            except Exception as e:
                logger.debug(f"Error scanning {sym}: {e}")
            return None

        with ThreadPoolExecutor(max_workers=8) as executor:
            future_to_file = {executor.submit(_scan_single_stock, f): f for f in target_files}
            for fut in as_completed(future_to_file):
                res = fut.result()
                if res:
                    setups_found.append(res)

        # Sort by R:R descending
        setups_found.sort(key=lambda s: s["rr"], reverse=True)
        self.scanned_candidates = setups_found
        self.active_signals = setups_found[:10]
        self._save_state()
        logger.info(f"Scan complete: Found {len(setups_found)} swing setups.")
        return setups_found

    def execute_setups(self, max_new_positions: int = 2) -> List[Dict[str, Any]]:
        """
        Executes top qualified setups using strict position sizing & portfolio limits.
        1% equity risk per trade, max 20% single position, max 5 positions.
        """
        executed_trades = []
        with self._lock:
            current_positions_count = len(self.engine.positions)
            max_allowed_positions = self.strategy_config['risk']['max_positions']  # 5
            available_slots = max(0, max_allowed_positions - current_positions_count)
            slots_to_fill = min(available_slots, max_new_positions)

            if slots_to_fill <= 0:
                logger.info(f"Max positions ({max_allowed_positions}) reached or 0 slots available.")
                return []

            for sig in list(self.active_signals):
                if slots_to_fill <= 0:
                    break

                sym = sig["symbol"]
                if sym in self.engine.positions:
                    continue  # already open

                entry_price = sig["trigger"]
                stop_loss = sig["stop"]
                target = sig["target1"]

                risk_per_share = entry_price - stop_loss
                if risk_per_share <= 0:
                    continue

                # 1% risk rule
                equity = self.engine.equity
                risk_amount = equity * self.strategy_config['risk']['risk_pct']
                qty = int(risk_amount / risk_per_share)

                # Cap single position at 20% of equity
                max_position_cost = equity * self.strategy_config['risk']['max_position_pct']
                max_qty = int(max_position_cost / entry_price)
                qty = min(qty, max_qty)

                if qty <= 0:
                    continue

                trade_cost = qty * entry_price
                if trade_cost > self.engine.current_capital:
                    # Scale down if capital insufficient
                    qty = int(self.engine.current_capital / entry_price)
                    if qty <= 0:
                        continue

                # Place order in PaperTradingEngine
                success, msg = self.engine.place_order(
                    symbol=sym,
                    qty=qty,
                    side="BUY",
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    target=target,
                    setup_type=sig["kind"]
                )

                if success:
                    slots_to_fill -= 1
                    sig["status"] = "FILLED"
                    executed_trades.append({
                        "symbol": sym,
                        "qty": qty,
                        "entry_price": entry_price,
                        "stop_loss": stop_loss,
                        "target": target,
                        "setup": sig["kind"],
                        "cost": qty * entry_price
                    })
                    logger.info(f"✅ EXECUTED SWING TRADE: {sym} x {qty} @ ₹{entry_price:.2f} ({sig['kind']})")

        self._save_state()
        return executed_trades

    def update_ticks_and_manage(self, custom_prices: Optional[Dict[str, float]] = None) -> List[Dict[str, Any]]:
        """
        Evaluates open positions against latest market prices.
        Executes stop-loss, target partial exits, and trailing remainder exits.
        """
        closed_actions = []
        today_str = datetime.now(IST).date().isoformat()

        with self._lock:
            for sym, pos in list(self.engine.positions.items()):
                # Get current price
                curr_price = None
                if custom_prices and sym in custom_prices:
                    curr_price = float(custom_prices[sym])
                else:
                    curr_price = self.get_latest_quote(sym)

                if curr_price is None or curr_price <= 0:
                    continue

                # Update position tracking
                pos.current_price = curr_price
                pos.unrealized_pnl = (curr_price - pos.entry_price) * pos.qty
                pos.unrealized_pnl_pct = (curr_price - pos.entry_price) / pos.entry_price * 100.0
                try:
                    pos.days_held = (datetime.now(IST).date() - pd.to_datetime(pos.entry_date).date()).days
                except Exception:
                    pos.days_held = 1

                # Check Exit Rules:
                exit_reason = None
                exit_price = curr_price

                # 1. Stop Loss Hit
                if curr_price <= pos.stop_loss:
                    exit_reason = "STOP_LOSS"
                    exit_price = pos.stop_loss

                # 2. Target Hit
                elif curr_price >= pos.target:
                    exit_reason = "TARGET_HIT"
                    exit_price = pos.target

                # 3. Time Stop (20 days)
                elif pos.days_held >= self.strategy_config['setup']['time_stop_days']:
                    exit_reason = "TIME_STOP"
                    exit_price = curr_price

                if exit_reason:
                    success, msg = self.engine.close_position(
                        symbol=sym,
                        exit_price=exit_price,
                        exit_reason=exit_reason
                    )
                    if success:
                        trade = self.engine.trades[-1]
                        closed_actions.append({
                            "symbol": sym,
                            "exit_reason": exit_reason,
                            "exit_price": exit_price,
                            "net_pnl": trade.net_pnl,
                            "return_pct": trade.net_pnl_pct
                        })
                        logger.info(f"🚨 CLOSED SWING POSITION: {sym} @ ₹{exit_price:.2f} ({exit_reason}) Net PnL: ₹{trade.net_pnl:+,.2f}")

        self._save_state()
        return closed_actions

    def get_telemetry(self) -> Dict[str, Any]:
        """Provides full real-time telemetry for the frontend dashboard."""
        with self._lock:
            open_positions_list = []
            total_unrealized = 0.0
            total_exposure = 0.0

            for sym, p in self.engine.positions.items():
                p_dict = {
                    "symbol": p.symbol,
                    "qty": p.qty,
                    "entry_price": round(p.entry_price, 2),
                    "current_price": round(p.current_price or p.entry_price, 2),
                    "stop_loss": round(p.stop_loss, 2),
                    "target": round(p.target, 2),
                    "unrealized_pnl": round(p.unrealized_pnl, 2),
                    "unrealized_pnl_pct": round(p.unrealized_pnl_pct, 2),
                    "setup_type": p.setup_type,
                    "days_held": p.days_held,
                    "entry_date": p.entry_date,
                    "notional_value": round(p.qty * (p.current_price or p.entry_price), 2)
                }
                open_positions_list.append(p_dict)
                total_unrealized += p.unrealized_pnl
                total_exposure += p_dict["notional_value"]

            # Realized trades summary
            trades_list = []
            total_realized = 0.0
            winners = 0
            losers = 0

            for t in reversed(self.engine.trades):
                total_realized += t.net_pnl
                if t.net_pnl > 0:
                    winners += 1
                elif t.net_pnl < 0:
                    losers += 1
                trades_list.append({
                    "symbol": t.symbol,
                    "entry_date": t.entry_date,
                    "exit_date": t.exit_date,
                    "entry_price": round(t.entry_price, 2),
                    "exit_price": round(t.exit_price, 2),
                    "qty": t.qty,
                    "setup_type": t.setup_type,
                    "exit_reason": t.exit_reason,
                    "gross_pnl": round(t.gross_pnl, 2),
                    "costs": round(t.costs, 2),
                    "net_pnl": round(t.net_pnl, 2),
                    "net_pnl_pct": round(t.net_pnl_pct, 2)
                })

            total_closed = len(self.engine.trades)
            win_rate = (winners / total_closed * 100.0) if total_closed > 0 else 0.0
            current_equity = self.engine.current_capital + total_exposure + total_unrealized
            net_return_pct = ((current_equity - self.initial_capital) / self.initial_capital) * 100.0

            return {
                "status": "success",
                "strategy_name": "EMA Pullback + ADX (Long-Only CNC Delivery)",
                "initial_capital": self.initial_capital,
                "current_capital": round(self.engine.current_capital, 2),
                "current_equity": round(current_equity, 2),
                "total_exposure": round(total_exposure, 2),
                "total_unrealized_pnl": round(total_unrealized, 2),
                "total_realized_pnl": round(total_realized, 2),
                "total_pnl": round(total_realized + total_unrealized, 2),
                "net_return_pct": round(net_return_pct, 2),
                "max_drawdown_pct": round(self.engine.max_drawdown_pct, 2),
                "open_positions_count": len(open_positions_list),
                "open_positions": open_positions_list,
                "active_signals": self.active_signals,
                "scanned_count": len(self.scanned_candidates),
                "closed_trades_count": total_closed,
                "win_rate": round(win_rate, 1),
                "closed_trades": trades_list[:20],
                "market_filter": self.market_filter_status,
                "is_running": self.is_running,
                "last_updated": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
            }

    def start_continuous(self, interval_seconds: int = 60):
        """Starts background thread to continuously monitor swing positions and market."""
        if self.is_running:
            return
        self.is_running = True

        def _loop():
            logger.info("Swing Continuous Worker started.")
            # Initial scan if signals empty
            if not self.active_signals:
                try:
                    self.scan_universe()
                    self.execute_setups()
                except Exception as e:
                    logger.error(f"Error in initial swing scan: {e}")

            while self.is_running:
                try:
                    # Update live prices & manage exits
                    self.update_ticks_and_manage()
                except Exception as e:
                    logger.error(f"Error in swing continuous loop: {e}")
                time.sleep(interval_seconds)

        self._worker_thread = threading.Thread(target=_loop, daemon=True)
        self._worker_thread.start()

    def stop(self):
        self.is_running = False


# Singleton instance initialized with user's ₹250,000 capital
swing_runner = SwingContinuousRunner(initial_capital=250000.0)
