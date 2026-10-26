"""
Chronological Backtest Engine with Daily Compounding.

Orchestrates day-by-day simulation, candidate selection, trade execution,
daily P&L compounding, and In-Sample / Out-of-Sample segregation.
"""

from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np

from src.costs.calculator import CostCalculator
from src.data.loader import SymbolDataStore
from src.engine.simulator import IntradaySimulator, TradeRecord
from src.strategy.config import StrategyConfig
from src.strategy.ranking import filter_and_rank_candidates


@dataclass
class BacktestResult:
    """Holds complete artifacts and outputs of a backtest run."""
    config: StrategyConfig
    trades_df: pd.DataFrame
    daily_df: pd.DataFrame
    split_date: str
    total_trading_days: int
    is_trading_days: int
    oos_trading_days: int
    start_equity: float
    end_equity: float


class BacktestEngine:
    """Simulates the ORB strategy over a historical time horizon."""

    def __init__(
        self,
        config: StrategyConfig,
        cost_calculator: Optional[CostCalculator] = None,
    ):
        self.config = config
        self.cost_calculator = cost_calculator or CostCalculator()
        self.simulator = IntradaySimulator(config, self.cost_calculator)

    def run(
        self,
        data_stores: Dict[str, SymbolDataStore],
        cost_multiplier: float = 1.0,
        slippage_multiplier: float = 1.0,
    ) -> BacktestResult:
        """
        Executes chronological backtest with daily compounding.
        """
        if not data_stores:
            raise ValueError("No valid data stores provided for backtest.")

        # Identify all unique trading days across all stores
        all_dates_set = set()
        for store in data_stores.values():
            all_dates_set.update(store.daily_df.index)

        sorted_dates = sorted(list(all_dates_set))
        if not sorted_dates:
            raise ValueError("No common trading dates found across data stores.")

        # Determine In-Sample vs Out-of-Sample cutoff date
        total_days = len(sorted_dates)
        split_idx = int(total_days * self.config.in_sample_ratio)
        split_date = sorted_dates[split_idx].strftime("%Y-%m-%d") if split_idx < total_days else sorted_dates[-1].strftime("%Y-%m-%d")

        current_equity = float(self.config.initial_capital)
        all_trades: List[TradeRecord] = []
        daily_records: List[dict] = []

        for current_date in sorted_dates:
            date_str = current_date.strftime("%Y-%m-%d")
            sod_equity = current_equity

            # 1. Filter and rank top N candidates for current day
            candidates = filter_and_rank_candidates(current_date, data_stores, self.config)

            day_trades: List[TradeRecord] = []
            day_gross = 0.0
            day_costs = 0.0
            day_net = 0.0

            # 2. Simulate trades for candidates
            for cand in candidates:
                store = data_stores[cand.symbol]
                trade = self.simulator.simulate_candidate(
                    candidate=cand,
                    bars_df=store.bars_5m,
                    sod_equity=sod_equity,
                    cost_multiplier=cost_multiplier,
                    slippage_multiplier=slippage_multiplier,
                )
                if trade is not None:
                    day_trades.append(trade)
                    day_gross += trade.gross_pnl
                    day_costs += trade.costs
                    day_net += trade.net_pnl

            # 3. Daily compounding
            eod_equity = sod_equity + day_net
            # Guard against bankruptcy / negative equity
            eod_equity = max(100.0, eod_equity)
            current_equity = eod_equity

            all_trades.extend(day_trades)

            daily_return = (day_net / sod_equity) if sod_equity > 0 else 0.0
            is_sample_flag = date_str < split_date

            daily_records.append({
                "date": date_str,
                "sod_equity": round(sod_equity, 2),
                "eod_equity": round(eod_equity, 2),
                "trades_count": len(day_trades),
                "gross_pnl": round(day_gross, 2),
                "costs": round(day_costs, 2),
                "net_pnl": round(day_net, 2),
                "daily_return": round(daily_return, 6),
                "is_in_sample": is_sample_flag,
            })

        trades_df = pd.DataFrame([t.__dict__ for t in all_trades]) if all_trades else pd.DataFrame(columns=[
            "date", "symbol", "side", "entry_time", "entry_price", "exit_time", "exit_price",
            "qty", "stop_loss", "gross_pnl", "costs", "net_pnl", "exit_reason", "rvol"
        ])

        daily_df = pd.DataFrame(daily_records)
        daily_df["cumulative_return"] = (daily_df["eod_equity"] / self.config.initial_capital) - 1.0

        is_days = int(daily_df["is_in_sample"].sum())
        oos_days = len(daily_df) - is_days

        return BacktestResult(
            config=self.config,
            trades_df=trades_df,
            daily_df=daily_df,
            split_date=split_date,
            total_trading_days=len(daily_df),
            is_trading_days=is_days,
            oos_trading_days=oos_days,
            start_equity=self.config.initial_capital,
            end_equity=current_equity,
        )
