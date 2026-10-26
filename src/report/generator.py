"""
Report Generator & Visualization Engine.

Generates:
- results/trades.csv: Itemized trade ledger with exact execution details
- results/daily.csv: Daily equity progression, returns, and cost drag
- results/equity_curve.png: High-resolution plot marking In-Sample vs Out-of-Sample boundary
- results/report.md: Comprehensive markdown quant research report with honest conclusions
"""

import os
from pathlib import Path
from typing import Dict, List, Optional
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np

from src.engine.backtester import BacktestResult
from src.metrics.performance import (
    PeriodMetrics,
    calculate_metrics_for_slice,
    compute_monthly_returns,
    compute_weekday_performance,
    compute_top_symbols_breakdown,
)


def df_to_markdown_table(df: pd.DataFrame, include_index: bool = True) -> str:
    """Converts a pandas DataFrame to a GitHub markdown table without requiring tabulate."""
    if df.empty:
        return ""
    data = df.copy()
    if include_index:
        idx_name = data.index.name if data.index.name else ""
        data = data.reset_index()
        if not idx_name and data.columns[0] == "index":
            data.rename(columns={"index": "Year"}, inplace=True)
    
    headers = [str(c) for c in data.columns]
    lines = []
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join([":---:" for _ in headers]) + " |")
    for _, row in data.iterrows():
        row_strs = []
        for val in row:
            if isinstance(val, (float, np.floating)):
                row_strs.append(f"{val:.2f}")
            else:
                row_strs.append(str(val))
        lines.append("| " + " | ".join(row_strs) + " |")
    return "\n".join(lines)


class ReportGenerator:
    """Generates reporting artifacts, plots, and markdown evaluations."""

    def __init__(self, output_dir: str = "results"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_all(
        self,
        result: BacktestResult,
        cost_multiplier: float = 1.0,
        slippage_multiplier: float = 1.0,
        is_synthetic: bool = False,
    ) -> Dict[str, str]:
        """
        Executes complete report generation workflow.
        Returns paths to created artifacts.
        """
        trades_df = result.trades_df
        daily_df = result.daily_df

        # 1. Save CSVs
        trades_path = self.output_dir / "trades.csv"
        daily_path = self.output_dir / "daily.csv"
        trades_df.to_csv(trades_path, index=False)
        daily_df.to_csv(daily_path, index=False)

        # 2. Compute Segmented Metrics
        is_daily = daily_df[daily_df["is_in_sample"]]
        oos_daily = daily_df[~daily_df["is_in_sample"]]

        if not trades_df.empty:
            is_trades = trades_df[trades_df["date"] < result.split_date]
            oos_trades = trades_df[trades_df["date"] >= result.split_date]
        else:
            is_trades = pd.DataFrame()
            oos_trades = pd.DataFrame()

        full_metrics = calculate_metrics_for_slice("Full Period", daily_df, trades_df, result.start_equity)
        
        is_start_eq = result.start_equity
        is_metrics = calculate_metrics_for_slice("In-Sample (70%)", is_daily, is_trades, is_start_eq)

        oos_start_eq = float(is_daily["eod_equity"].iloc[-1]) if not is_daily.empty else result.start_equity
        oos_metrics = calculate_metrics_for_slice("Out-of-Sample (30%)", oos_daily, oos_trades, oos_start_eq)

        # 3. Generate Equity Curve Plot
        plot_path = self.output_dir / "equity_curve.png"
        self._plot_equity_curve(daily_df, result.split_date, plot_path, is_synthetic)

        # 4. Generate Additional Analytics
        monthly_df = compute_monthly_returns(daily_df)
        weekday_df = compute_weekday_performance(trades_df)
        top_symbols_df = compute_top_symbols_breakdown(trades_df, top_k=10)

        # 5. Generate Markdown Report
        report_path = self.output_dir / "report.md"
        self._generate_markdown_report(
            report_path=report_path,
            result=result,
            full_metrics=full_metrics,
            is_metrics=is_metrics,
            oos_metrics=oos_metrics,
            monthly_df=monthly_df,
            weekday_df=weekday_df,
            top_symbols_df=top_symbols_df,
            cost_multiplier=cost_multiplier,
            slippage_multiplier=slippage_multiplier,
            is_synthetic=is_synthetic,
        )

        return {
            "trades_csv": str(trades_path),
            "daily_csv": str(daily_path),
            "equity_curve": str(plot_path),
            "report_md": str(report_path),
        }

    def _plot_equity_curve(
        self,
        daily_df: pd.DataFrame,
        split_date: str,
        output_path: Path,
        is_synthetic: bool = False,
    ):
        """Plots equity curve with In-Sample / Out-of-Sample boundary and drawdown pane."""
        if daily_df.empty:
            return

        fig, (ax1, ax2) = plt.subplots(
            2, 1, figsize=(12, 8), sharex=True, gridspec_kw={"height_ratios": [3, 1]}
        )

        dates = pd.to_datetime(daily_df["date"])
        equity = daily_df["eod_equity"]
        peak = equity.cummax()
        drawdown_pct = (equity - peak) / peak * 100.0

        # Title
        title_prefix = "[SYNTHETIC DATA - SMOKE TEST ONLY] " if is_synthetic else ""
        ax1.set_title(f"{title_prefix}Equity Curve: Opening Range Breakout (ORB) on Nifty 500", fontsize=14, fontweight="bold")

        # Top Pane: Equity
        ax1.plot(dates, equity, label="Strategy Equity (compounded)", color="#1f77b4", linewidth=2.0)
        ax1.plot(dates, peak, label="High Water Mark", color="#2ca02c", linestyle="--", alpha=0.6)
        ax1.axhline(daily_df["sod_equity"].iloc[0], color="grey", linestyle=":", alpha=0.8, label="Initial Capital")

        # Mark IS / OOS split
        split_dt = pd.to_datetime(split_date)
        ax1.axvline(split_dt, color="#d62728", linestyle="--", linewidth=1.8, label=f"OOS Boundary ({split_date})")

        # Shading
        ax1.axvspan(dates.iloc[0], split_dt, color="#1f77b4", alpha=0.04, label="In-Sample Period (70%)")
        ax1.axvspan(split_dt, dates.iloc[-1], color="#ff7f0e", alpha=0.06, label="Out-of-Sample Period (30%)")

        ax1.set_ylabel("Portfolio Value (INR)", fontsize=11)
        ax1.grid(True, linestyle="--", alpha=0.5)
        ax1.legend(loc="upper left", framealpha=0.9)

        # Bottom Pane: Drawdown
        ax2.fill_between(dates, drawdown_pct, 0, color="#d62728", alpha=0.4, label="Underwater Drawdown %")
        ax2.plot(dates, drawdown_pct, color="#d62728", linewidth=1.0)
        ax2.axvline(split_dt, color="#d62728", linestyle="--", linewidth=1.5)
        ax2.set_ylabel("Drawdown %", fontsize=11)
        ax2.set_xlabel("Date", fontsize=11)
        ax2.grid(True, linestyle="--", alpha=0.5)
        ax2.legend(loc="lower left", framealpha=0.9)

        plt.tight_layout()
        plt.savefig(output_path, dpi=200)
        plt.close(fig)

    def _generate_markdown_report(
        self,
        report_path: Path,
        result: BacktestResult,
        full_metrics: PeriodMetrics,
        is_metrics: PeriodMetrics,
        oos_metrics: PeriodMetrics,
        monthly_df: pd.DataFrame,
        weekday_df: pd.DataFrame,
        top_symbols_df: pd.DataFrame,
        cost_multiplier: float,
        slippage_multiplier: float,
        is_synthetic: bool,
    ):
        """Generates comprehensive markdown report with honest verdicts."""
        cfg = result.config
        oos_profitable = oos_metrics.net_pnl > 0 and oos_metrics.sharpe_ratio > 0

        verdict_str = (
            "✅ **STRATEGY IS PROFITABLE OUT-OF-SAMPLE AFTER COSTS**"
            if oos_profitable
            else "❌ **STRATEGY IS UNPROFITABLE OUT-OF-SAMPLE AFTER COSTS**"
        )

        md = []
        md.append("# Quantitative Research Report: Opening Range Breakout (ORB)")
        md.append(f"**Generated:** {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S IST')}\n")

        if is_synthetic:
            md.append("> ⚠️ **CRITICAL NOTICE: SYNTHETIC DATA MODE ACTIVE**\n"
                      "> This backtest was executed on synthetically generated random-walk data for pipeline smoke-testing.\n"
                      "> **These results only prove code mechanics and data flow. They have ZERO predictive alpha value.**\n")

        md.append("## Executive Summary\n")
        md.append(f"### Verdict: {verdict_str}\n")
        md.append(
            "> ⚠️ **Methodological Mandate**: Only **Out-of-Sample (OOS)** results reflect realistic forward expectations. "
            "In-Sample (IS) results suffer from selection bias and curve-fitting risk.\n"
        )

        if oos_metrics.few_trades_warning:
            md.append(
                f"> ⚠️ **STATISTICAL SIGNIFICANCE WARNING**: The Out-of-Sample evaluation recorded only **{oos_metrics.trades_count} trades** "
                "(< 100 trades threshold). Conclusions are subject to high sampling variance and small-sample noise.\n"
            )

        md.append("### Key Quant Performance Breakdown\n")
        md.append("| Metric | Full Horizon | In-Sample (70%) | Out-of-Sample (30%) |")
        md.append("| :--- | :---: | :---: | :---: |")
        md.append(f"| **Evaluation Period** | Full | First 70% | Last 30% (from {result.split_date}) |")
        md.append(f"| **Trading Days** | {full_metrics.trading_days} | {is_metrics.trading_days} | {oos_metrics.trading_days} |")
        md.append(f"| **Total Trades** | {full_metrics.trades_count} | {is_metrics.trades_count} | {oos_metrics.trades_count} |")
        md.append(f"| **Net Return %** | **{full_metrics.total_return_pct:.2f}%** | **{is_metrics.total_return_pct:.2f}%** | **{oos_metrics.total_return_pct:.2f}%** |")
        md.append(f"| **Annualized CAGR %** | {full_metrics.cagr_pct:.2f}% | {is_metrics.cagr_pct:.2f}% | {oos_metrics.cagr_pct:.2f}% |")
        md.append(f"| **Annualized Sharpe (250d)** | **{full_metrics.sharpe_ratio:.3f}** | **{is_metrics.sharpe_ratio:.3f}** | **{oos_metrics.sharpe_ratio:.3f}** |")
        md.append(f"| **Max Drawdown %** | {full_metrics.max_drawdown_pct:.2f}% | {is_metrics.max_drawdown_pct:.2f}% | {oos_metrics.max_drawdown_pct:.2f}% |")
        md.append(f"| **Win Rate %** | {full_metrics.win_rate_pct:.2f}% | {is_metrics.win_rate_pct:.2f}% | {oos_metrics.win_rate_pct:.2f}% |")
        md.append(f"| **Profit Factor** | {full_metrics.profit_factor:.2f} | {is_metrics.profit_factor:.2f} | {oos_metrics.profit_factor:.2f} |")
        md.append(f"| **Avg Win / Avg Loss** | Rs {full_metrics.avg_win:.1f} / Rs {full_metrics.avg_loss:.1f} ({full_metrics.win_loss_ratio:.2f}x) | Rs {is_metrics.avg_win:.1f} / Rs {is_metrics.avg_loss:.1f} ({is_metrics.win_loss_ratio:.2f}x) | Rs {oos_metrics.avg_win:.1f} / Rs {oos_metrics.avg_loss:.1f} ({oos_metrics.win_loss_ratio:.2f}x) |")
        md.append(f"| **Stopped Out %** | {full_metrics.stopped_out_pct:.1f}% | {is_metrics.stopped_out_pct:.1f}% | {oos_metrics.stopped_out_pct:.1f}% |")
        md.append(f"| **Gross P&L (Rs)** | Rs {full_metrics.gross_pnl:,.2f} | Rs {is_metrics.gross_pnl:,.2f} | Rs {oos_metrics.gross_pnl:,.2f} |")
        md.append(f"| **Total Costs & Slippage (Rs)** | -Rs {full_metrics.total_costs:,.2f} | -Rs {is_metrics.total_costs:,.2f} | -Rs {oos_metrics.total_costs:,.2f} |")
        md.append(f"| **Net P&L (Rs)** | **Rs {full_metrics.net_pnl:,.2f}** | **Rs {is_metrics.net_pnl:,.2f}** | **Rs {oos_metrics.net_pnl:,.2f}** |")

        md.append("\n### Directional Segregation (Long vs Short)\n")
        md.append("| Period | Direction | Trades | Win Rate % | Net P&L (Rs) |")
        md.append("| :--- | :---: | :---: | :---: | :---: |")
        md.append(f"| **Full Horizon** | Long | {full_metrics.long_trades} | {full_metrics.long_win_rate_pct:.1f}% | Rs {full_metrics.long_net_pnl:,.2f} |")
        md.append(f"| **Full Horizon** | Short | {full_metrics.short_trades} | {full_metrics.short_win_rate_pct:.1f}% | Rs {full_metrics.short_net_pnl:,.2f} |")
        md.append(f"| **In-Sample** | Long | {is_metrics.long_trades} | {is_metrics.long_win_rate_pct:.1f}% | Rs {is_metrics.long_net_pnl:,.2f} |")
        md.append(f"| **In-Sample** | Short | {is_metrics.short_trades} | {is_metrics.short_win_rate_pct:.1f}% | Rs {is_metrics.short_net_pnl:,.2f} |")
        md.append(f"| **Out-of-Sample** | Long | {oos_metrics.long_trades} | {oos_metrics.long_win_rate_pct:.1f}% | Rs {oos_metrics.long_net_pnl:,.2f} |")
        md.append(f"| **Out-of-Sample** | Short | {oos_metrics.short_trades} | {oos_metrics.short_win_rate_pct:.1f}% | Rs {oos_metrics.short_net_pnl:,.2f} |\n")

        md.append("## Cost Drag & Friction Analysis\n")
        if full_metrics.gross_pnl != 0:
            friction_ratio = (full_metrics.total_costs / abs(full_metrics.gross_pnl)) * 100.0
            md.append(
                f"- **Total Gross P&L**: Rs {full_metrics.gross_pnl:,.2f}\n"
                f"- **Total Friction (Statutory Fees + Slippage)**: Rs {full_metrics.total_costs:,.2f}\n"
                f"- **Friction as % of Gross P&L**: **{friction_ratio:.1f}%**\n"
                f"- **Net Edge Extracted**: Rs {full_metrics.net_pnl:,.2f}\n"
            )
        md.append(
            "> In high-frequency intraday momentum, statutory taxes (STT on sells, stamp duty on buys, exchange fees, SEBI charges, GST) "
            "and execution slippage represent an enormous hurdle. Many apparent gross edges are entirely consumed by realistic market friction.\n"
        )

        md.append("## Monthly Returns Matrix (%)\n")
        if not monthly_df.empty:
            md.append(df_to_markdown_table(monthly_df, include_index=True))
        else:
            md.append("_No monthly data available._")

        md.append("\n\n## Day-of-Week Performance\n")
        if not weekday_df.empty:
            md.append(df_to_markdown_table(weekday_df, include_index=False))
        else:
            md.append("_No weekday data available._")

        md.append("\n\n## Top 10 Traded Symbols\n")
        if not top_symbols_df.empty:
            md.append(df_to_markdown_table(top_symbols_df, include_index=False))
        else:
            md.append("_No trade breakdown available._")

        md.append("\n\n## Core Strategy Parameters\n")
        md.append(f"- **Opening Range Duration**: {cfg.or_minutes} minutes\n"
                  f"- **RVOL Baseline**: {cfg.rvol_window} trading days (strictly shifted)\n"
                  f"- **Minimum RVOL**: {cfg.min_rvol}x\n"
                  f"- **ATR Filter Window**: {cfg.atr_window} days (shifted 1 day)\n"
                  f"- **Stop Distance**: {cfg.stop_atr} x ATR14\n"
                  f"- **Liquidity Filter**: 20-day average turnover >= Rs {cfg.min_turnover_cr} Cr, Price >= Rs {cfg.min_price}\n"
                  f"- **Universe Candidates Selected per Day**: Top {cfg.top_n}\n"
                  f"- **Risk per Trade**: {cfg.risk_pct * 100:.1f}% of start-of-day equity\n"
                  f"- **Max Gross Leverage**: {cfg.max_leverage}x\n"
                  f"- **Intrabar Conservative Rule**: {cfg.conservative_intrabar}\n"
                  f"- **Square-Off Time Exit**: {cfg.square_off_time} IST\n")

        md.append("## Known Limitations & Structural Caveats\n")
        md.append("1. **Survivorship Bias**: Testing on current Nifty 500 constituents misses stocks that went bankrupt, merged, or were removed due to deteriorating liquidity.\n"
                  "2. **Stop Order Fill Assumptions**: Assumes stop orders are immediately filled at stop or open gap. In volatile breakouts, stop orders can suffer severe slippage.\n"
                  "3. **Zero Market Impact Assumption**: Assumes our orders do not move the order book or consume depth.\n"
                  "4. **Price Circuits**: Does not filter for 5%/10%/20% circuit freezes where trading halts or execution becomes impossible.\n"
                  "5. **Broker MIS Shorting Bans**: Assumes all constituents can be shorted intraday via MIS without broker surveillance or scrip-level short restrictions.\n"
                  "6. **Past Performance Disclaimer**: Past backtested performance is NOT indicative of future live market returns.\n")

        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(md))
