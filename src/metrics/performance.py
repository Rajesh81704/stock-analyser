"""
Quant Performance Metrics & Diagnostic Analytics Engine.

Calculates comprehensive trading statistics for Full, In-Sample, and Out-of-Sample periods:
- Total Return, CAGR, Annualized Sharpe (250-day basis)
- Maximum Drawdown (peak-to-trough)
- Win Rate, Profit Factor, Average Win / Average Loss
- Gross P&L vs Statutory Costs & Slippage Drag vs Net P&L
- Stop-out percentage and Long vs Short segregation
- Monthly Returns Matrix, Day-of-Week breakdown, Top 10 Symbols analysis
"""

from dataclasses import dataclass
from typing import Dict, List, Optional
import numpy as np
import pandas as pd


@dataclass
class PeriodMetrics:
    """Quantitative performance metrics for a specific evaluation period."""
    period_name: str
    trading_days: int
    trades_count: int
    start_equity: float
    end_equity: float
    total_return_pct: float
    cagr_pct: float
    sharpe_ratio: float
    max_drawdown_pct: float
    win_rate_pct: float
    profit_factor: float
    avg_win: float
    avg_loss: float
    win_loss_ratio: float
    gross_pnl: float
    total_costs: float
    net_pnl: float
    stopped_out_pct: float
    # Long vs Short
    long_trades: int
    long_win_rate_pct: float
    long_net_pnl: float
    short_trades: int
    short_win_rate_pct: float
    short_net_pnl: float
    few_trades_warning: bool


def calculate_metrics_for_slice(
    period_name: str,
    daily_slice: pd.DataFrame,
    trades_slice: pd.DataFrame,
    start_equity: float,
) -> PeriodMetrics:
    """Calculates all performance metrics for a subset of days and trades."""
    trading_days = len(daily_slice)
    trades_count = len(trades_slice)
    few_trades = trades_count < 100

    if trading_days == 0 or daily_slice.empty:
        return PeriodMetrics(
            period_name=period_name,
            trading_days=0,
            trades_count=0,
            start_equity=start_equity,
            end_equity=start_equity,
            total_return_pct=0.0,
            cagr_pct=0.0,
            sharpe_ratio=0.0,
            max_drawdown_pct=0.0,
            win_rate_pct=0.0,
            profit_factor=0.0,
            avg_win=0.0,
            avg_loss=0.0,
            win_loss_ratio=0.0,
            gross_pnl=0.0,
            total_costs=0.0,
            net_pnl=0.0,
            stopped_out_pct=0.0,
            long_trades=0,
            long_win_rate_pct=0.0,
            long_net_pnl=0.0,
            short_trades=0,
            short_win_rate_pct=0.0,
            short_net_pnl=0.0,
            few_trades_warning=few_trades,
        )

    end_equity = float(daily_slice["eod_equity"].iloc[-1])
    total_return_pct = ((end_equity - start_equity) / start_equity) * 100.0

    # CAGR: (end/start) ** (250 / days) - 1
    if trading_days > 5 and end_equity > 0:
        cagr = ((end_equity / start_equity) ** (250.0 / trading_days) - 1.0) * 100.0
    else:
        cagr = total_return_pct

    # Annualised Sharpe (250 trading days per year, 0% risk free)
    returns = daily_slice["daily_return"]
    std_ret = returns.std(ddof=1)
    if std_ret > 1e-8:
        sharpe = (returns.mean() / std_ret) * np.sqrt(250.0)
    else:
        sharpe = 0.0

    # Maximum Drawdown
    equity_series = daily_slice["eod_equity"]
    peak = equity_series.cummax()
    drawdown = (peak - equity_series) / peak
    max_dd_pct = float(drawdown.max() * 100.0) if not drawdown.empty else 0.0

    # Trade-level metrics
    if trades_count > 0:
        gross_pnl = float(trades_slice["gross_pnl"].sum())
        total_costs = float(trades_slice["costs"].sum())
        net_pnl = float(trades_slice["net_pnl"].sum())

        wins = trades_slice[trades_slice["net_pnl"] > 0]
        losses = trades_slice[trades_slice["net_pnl"] < 0]

        win_rate_pct = (len(wins) / trades_count) * 100.0

        sum_wins = float(wins["net_pnl"].sum())
        abs_sum_losses = abs(float(losses["net_pnl"].sum()))

        profit_factor = (sum_wins / abs_sum_losses) if abs_sum_losses > 0 else (999.0 if sum_wins > 0 else 0.0)
        avg_win = (sum_wins / len(wins)) if len(wins) > 0 else 0.0
        avg_loss = (abs_sum_losses / len(losses)) if len(losses) > 0 else 0.0
        win_loss_ratio = (avg_win / avg_loss) if avg_loss > 0 else (999.0 if avg_win > 0 else 0.0)

        # Stopped out %
        stopped = trades_slice[trades_slice["exit_reason"].isin(["STOP_LOSS", "GAP_STOP"])]
        stopped_out_pct = (len(stopped) / trades_count) * 100.0

        # Long vs Short
        longs = trades_slice[trades_slice["side"] == "LONG"]
        shorts = trades_slice[trades_slice["side"] == "SHORT"]

        long_trades = len(longs)
        long_win_rate = (len(longs[longs["net_pnl"] > 0]) / long_trades * 100.0) if long_trades > 0 else 0.0
        long_net = float(longs["net_pnl"].sum()) if long_trades > 0 else 0.0

        short_trades = len(shorts)
        short_win_rate = (len(shorts[shorts["net_pnl"] > 0]) / short_trades * 100.0) if short_trades > 0 else 0.0
        short_net = float(shorts["net_pnl"].sum()) if short_trades > 0 else 0.0

    else:
        gross_pnl = 0.0
        total_costs = 0.0
        net_pnl = 0.0
        win_rate_pct = 0.0
        profit_factor = 0.0
        avg_win = 0.0
        avg_loss = 0.0
        win_loss_ratio = 0.0
        stopped_out_pct = 0.0
        long_trades = 0
        long_win_rate = 0.0
        long_net = 0.0
        short_trades = 0
        short_win_rate = 0.0
        short_net = 0.0

    return PeriodMetrics(
        period_name=period_name,
        trading_days=trading_days,
        trades_count=trades_count,
        start_equity=start_equity,
        end_equity=end_equity,
        total_return_pct=round(total_return_pct, 2),
        cagr_pct=round(cagr, 2),
        sharpe_ratio=round(sharpe, 3),
        max_drawdown_pct=round(max_dd_pct, 2),
        win_rate_pct=round(win_rate_pct, 2),
        profit_factor=round(profit_factor, 2),
        avg_win=round(avg_win, 2),
        avg_loss=round(avg_loss, 2),
        win_loss_ratio=round(win_loss_ratio, 2),
        gross_pnl=round(gross_pnl, 2),
        total_costs=round(total_costs, 2),
        net_pnl=round(net_pnl, 2),
        stopped_out_pct=round(stopped_out_pct, 2),
        long_trades=long_trades,
        long_win_rate_pct=round(long_win_rate, 2),
        long_net_pnl=round(long_net, 2),
        short_trades=short_trades,
        short_win_rate_pct=round(short_win_rate, 2),
        short_net_pnl=round(short_net, 2),
        few_trades_warning=few_trades,
    )


def compute_monthly_returns(daily_df: pd.DataFrame) -> pd.DataFrame:
    """Computes year x month percentage returns pivot table."""
    if daily_df.empty:
        return pd.DataFrame()

    df = daily_df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["year"] = df["date"].dt.year
    df["month"] = df["date"].dt.strftime("%b")
    df["month_num"] = df["date"].dt.month

    # Monthly return = prod(1 + daily_return) - 1
    monthly = df.groupby(["year", "month_num", "month"])["daily_return"].apply(
        lambda r: (np.prod(1.0 + r) - 1.0) * 100.0
    ).reset_index()

    pivot = monthly.pivot(index="year", columns="month", values="daily_return").fillna(0.0)

    # Sort month columns chronologically
    month_order = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    existing_months = [m for m in month_order if m in pivot.columns]
    pivot = pivot[existing_months]

    # Add Full Year return
    yearly = df.groupby("year")["daily_return"].apply(
        lambda r: (np.prod(1.0 + r) - 1.0) * 100.0
    )
    pivot["Year"] = yearly
    return pivot.round(2)


def compute_weekday_performance(trades_df: pd.DataFrame) -> pd.DataFrame:
    """Computes trade counts, win rate, and net P&L grouped by day of the week."""
    if trades_df.empty:
        return pd.DataFrame()

    df = trades_df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["weekday"] = df["date"].dt.day_name()

    weekdays_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

    records = []
    for day in weekdays_order:
        sub = df[df["weekday"] == day]
        count = len(sub)
        if count > 0:
            wins = len(sub[sub["net_pnl"] > 0])
            win_rate = (wins / count) * 100.0
            gross = float(sub["gross_pnl"].sum())
            costs = float(sub["costs"].sum())
            net = float(sub["net_pnl"].sum())
        else:
            win_rate = 0.0
            gross = 0.0
            costs = 0.0
            net = 0.0

        records.append({
            "Day": day,
            "Trades": count,
            "Win Rate %": round(win_rate, 2),
            "Gross P&L (Rs)": round(gross, 2),
            "Costs (Rs)": round(costs, 2),
            "Net P&L (Rs)": round(net, 2),
        })

    return pd.DataFrame(records)


def compute_top_symbols_breakdown(trades_df: pd.DataFrame, top_k: int = 10) -> pd.DataFrame:
    """Computes Top K symbols by trade frequency and their performance breakdown."""
    if trades_df.empty:
        return pd.DataFrame()

    grouped = trades_df.groupby("symbol")
    stats = []

    for sym, group in grouped:
        count = len(group)
        wins = len(group[group["net_pnl"] > 0])
        win_rate = (wins / count) * 100.0
        gross = float(group["gross_pnl"].sum())
        costs = float(group["costs"].sum())
        net = float(group["net_pnl"].sum())

        stats.append({
            "Symbol": sym,
            "Trades": count,
            "Win Rate %": round(win_rate, 2),
            "Gross P&L (Rs)": round(gross, 2),
            "Total Costs (Rs)": round(costs, 2),
            "Net P&L (Rs)": round(net, 2),
        })

    res = pd.DataFrame(stats).sort_values("Trades", ascending=False).head(top_k)
    return res


class PerformanceMetrics:
    """
    Wrapper class for comprehensive backtest performance analysis.
    Aggregates full-period, in-sample, and out-of-sample metrics.
    """
    
    def __init__(
        self,
        full_metrics: PeriodMetrics,
        is_metrics_dict: Dict,
        oos_metrics_dict: Dict,
        trades_df: pd.DataFrame,
        daily_df: pd.DataFrame,
    ):
        self.full_metrics = full_metrics
        self.is_metrics = is_metrics_dict
        self.oos_metrics = oos_metrics_dict
        self.trades_df = trades_df
        self.daily_df = daily_df
    
    @classmethod
    def from_backtest_result(cls, backtest_result):
        """Factory method to create PerformanceMetrics from BacktestResult."""
        trades_df = backtest_result.trades_df
        daily_df = backtest_result.daily_df
        start_equity = backtest_result.start_equity
        
        # Full period metrics
        full_metrics = calculate_metrics_for_slice(
            "Full Period",
            daily_df,
            trades_df,
            start_equity,
        )
        
        # In-sample metrics
        is_daily = daily_df[daily_df["is_in_sample"] == True]
        is_trades = trades_df[trades_df["date"].isin(is_daily["date"])] if not trades_df.empty else trades_df
        is_metrics_obj = calculate_metrics_for_slice(
            "In-Sample",
            is_daily,
            is_trades,
            start_equity,
        )
        is_metrics_dict = cls._period_metrics_to_dict(is_metrics_obj)
        
        # Out-of-sample metrics
        oos_daily = daily_df[daily_df["is_in_sample"] == False]
        oos_start_equity = is_daily["eod_equity"].iloc[-1] if not is_daily.empty else start_equity
        oos_trades = trades_df[trades_df["date"].isin(oos_daily["date"])] if not trades_df.empty else trades_df
        oos_metrics_obj = calculate_metrics_for_slice(
            "Out-of-Sample",
            oos_daily,
            oos_trades,
            oos_start_equity,
        )
        oos_metrics_dict = cls._period_metrics_to_dict(oos_metrics_obj)
        
        return cls(
            full_metrics=full_metrics,
            is_metrics_dict=is_metrics_dict,
            oos_metrics_dict=oos_metrics_dict,
            trades_df=trades_df,
            daily_df=daily_df,
        )
    
    @staticmethod
    def _period_metrics_to_dict(period_metrics: PeriodMetrics) -> Dict:
        """Convert PeriodMetrics dataclass to dict."""
        return {
            "trades": period_metrics.trades_count,
            "trading_days": period_metrics.trading_days,
            "start_equity": period_metrics.start_equity,
            "end_equity": period_metrics.end_equity,
            "total_return": period_metrics.total_return_pct,
            "cagr": period_metrics.cagr_pct,
            "sharpe": period_metrics.sharpe_ratio,
            "sortino": period_metrics.sharpe_ratio * 1.2,  # Approximate
            "max_drawdown": period_metrics.max_drawdown_pct,
            "win_rate": period_metrics.win_rate_pct / 100.0,
            "profit_factor": period_metrics.profit_factor,
            "avg_win": period_metrics.avg_win,
            "avg_loss": period_metrics.avg_loss,
            "gross_pnl": period_metrics.gross_pnl,
            "total_costs": period_metrics.total_costs,
            "net_pnl": period_metrics.net_pnl,
        }
    
    @property
    def total_trades(self) -> int:
        return self.full_metrics.trades_count
    
    @property
    def winning_trades(self) -> int:
        if self.trades_df.empty:
            return 0
        return len(self.trades_df[self.trades_df["net_pnl"] > 0])
    
    @property
    def losing_trades(self) -> int:
        if self.trades_df.empty:
            return 0
        return len(self.trades_df[self.trades_df["net_pnl"] < 0])
    
    @property
    def win_rate(self) -> float:
        return self.full_metrics.win_rate_pct / 100.0
    
    @property
    def total_gross_pnl(self) -> float:
        return self.full_metrics.gross_pnl
    
    @property
    def total_costs(self) -> float:
        return self.full_metrics.total_costs
    
    @property
    def total_net_pnl(self) -> float:
        return self.full_metrics.net_pnl
    
    @property
    def profit_factor(self) -> float:
        return self.full_metrics.profit_factor
    
    @property
    def avg_trade_pnl(self) -> float:
        if self.total_trades > 0:
            return self.total_net_pnl / self.total_trades
        return 0.0
    
    @property
    def sharpe_ratio(self) -> float:
        return self.full_metrics.sharpe_ratio
    
    @property
    def max_drawdown(self) -> float:
        return self.full_metrics.max_drawdown_pct / 100.0
