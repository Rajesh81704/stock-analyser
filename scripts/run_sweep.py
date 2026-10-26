#!/usr/bin/env python3
"""
CLI Script: Robustness Grid Sweep & Overfitting Diagnostic.

Sweeps parameter grid:
- stop_atr in {0.05, 0.10, 0.20, 0.50}
- top_n in {3, 5, 10}
- or_minutes in {5, 15, 30}
- min_turnover_cr in {20, 50, 100}

Ranks parameter sets strictly by IN-SAMPLE Sharpe ratio to expose overfitting,
then checks corresponding Out-of-Sample performance.
Includes cost-stress test (2x slippage, 1.5x costs) and benchmark comparison (vs 0%).
"""

import argparse
import itertools
import sys
from pathlib import Path
from typing import Dict, List
import pandas as pd

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.costs.calculator import CostCalculator
from src.data.loader import load_dataset, SymbolDataStore
from src.data.synthetic import generate_synthetic_universe
from src.engine.backtester import BacktestEngine
from src.metrics.performance import calculate_metrics_for_slice
from src.strategy.config import StrategyConfig


def main():
    parser = argparse.ArgumentParser(description="Run parameter grid sweep and robustness evaluation.")
    parser.add_argument("--synthetic", action="store_true", help="Run sweep on synthetic data")
    parser.add_argument("--data-dir", type=str, default="data", help="Data directory")
    parser.add_argument("--results-dir", type=str, default="results", help="Results directory")
    parser.add_argument("--quick", action="store_true", help="Run a compact 16-point sweep for fast smoke-testing")
    args = parser.parse_args()

    data_path = Path(args.data_dir)
    results_path = Path(args.results_dir)
    results_path.mkdir(parents=True, exist_ok=True)

    if args.synthetic:
        csv_files = list(data_path.glob("*.csv"))
        stock_files = [f for f in csv_files if not f.name.startswith("ind_") and f.name != "nifty500.csv"]
        if len(stock_files) < 10:
            print("[SWEEP INIT] Generating synthetic dataset for smoke-test...")
            generate_synthetic_universe(output_dir=str(data_path), trading_days=70)

    # Define Parameter Grid
    if args.quick:
        stop_atr_vals = [0.10, 0.20]
        top_n_vals = [3, 5]
        or_minutes_vals = [5, 15]
        min_turnover_vals = [20.0, 50.0]
    else:
        stop_atr_vals = [0.05, 0.10, 0.20, 0.50]
        top_n_vals = [3, 5, 10]
        or_minutes_vals = [5, 15, 30]
        min_turnover_vals = [20.0, 50.0, 100.0]

    grid_combos = list(itertools.product(stop_atr_vals, top_n_vals, or_minutes_vals, min_turnover_vals))
    total_runs = len(grid_combos)
    print(f"\n[SWEEP GRID] Total parameter configurations to evaluate: {total_runs}")
    print(f"  - stop_atr: {stop_atr_vals}")
    print(f"  - top_n: {top_n_vals}")
    print(f"  - or_minutes: {or_minutes_vals}")
    print(f"  - min_turnover_cr: {min_turnover_vals}\n")

    # Group combinations by or_minutes to cache dataset loads
    combos_by_or: Dict[int, list] = {}
    for c in grid_combos:
        combos_by_or.setdefault(c[2], []).append(c)

    sweep_results: List[dict] = []
    engine_cost_calc = CostCalculator()

    run_count = 0
    for or_m, sub_combos in combos_by_or.items():
        base_cfg = StrategyConfig(or_minutes=or_m)
        print(f"[CACHE] Loading/precomputing data for or_minutes = {or_m}...")
        data_stores, _ = load_dataset(data_dir=args.data_dir, config=base_cfg)
        if not data_stores:
            print(f"[ERROR] Failed to load data from {args.data_dir}", file=sys.stderr)
            sys.exit(1)

        for (stop_atr, top_n, _, min_turnover) in sub_combos:
            run_count += 1
            cfg = StrategyConfig(
                or_minutes=or_m,
                stop_atr=stop_atr,
                top_n=top_n,
                min_turnover_cr=min_turnover,
            )

            engine = BacktestEngine(config=cfg, cost_calculator=engine_cost_calc)
            res = engine.run(data_stores=data_stores)

            daily_df = res.daily_df
            trades_df = res.trades_df

            is_daily = daily_df[daily_df["is_in_sample"]]
            oos_daily = daily_df[~daily_df["is_in_sample"]]
            is_trades = trades_df[trades_df["date"] < res.split_date] if not trades_df.empty else pd.DataFrame()
            oos_trades = trades_df[trades_df["date"] >= res.split_date] if not trades_df.empty else pd.DataFrame()

            is_m = calculate_metrics_for_slice("IS", is_daily, is_trades, res.start_equity)
            oos_start_eq = float(is_daily["eod_equity"].iloc[-1]) if not is_daily.empty else res.start_equity
            oos_m = calculate_metrics_for_slice("OOS", oos_daily, oos_trades, oos_start_eq)

            sharpe_decay = oos_m.sharpe_ratio - is_m.sharpe_ratio

            sweep_results.append({
                "stop_atr": stop_atr,
                "top_n": top_n,
                "or_minutes": or_m,
                "min_turnover_cr": min_turnover,
                "is_trades": is_m.trades_count,
                "is_return_pct": is_m.total_return_pct,
                "is_sharpe": is_m.sharpe_ratio,
                "is_max_dd_pct": is_m.max_drawdown_pct,
                "is_win_rate_pct": is_m.win_rate_pct,
                "oos_trades": oos_m.trades_count,
                "oos_return_pct": oos_m.total_return_pct,
                "oos_sharpe": oos_m.sharpe_ratio,
                "oos_max_dd_pct": oos_m.max_drawdown_pct,
                "oos_win_rate_pct": oos_m.win_rate_pct,
                "sharpe_decay": round(sharpe_decay, 3),
            })

            if run_count % 10 == 0 or run_count == total_runs:
                print(f"  Progress: [{run_count}/{total_runs}] evaluated...")

    results_df = pd.DataFrame(sweep_results)

    # MANDATORY: Rank strictly by IN-SAMPLE Sharpe only to expose overfitting!
    results_df = results_df.sort_values("is_sharpe", ascending=False).reset_index(drop=True)
    results_df.index = results_df.index + 1
    results_df.index.name = "Rank (IS Sharpe)"

    sweep_csv_path = results_path / "sweep_results.csv"
    results_df.to_csv(sweep_csv_path)

    # Display Top 10 Configurations
    print("\n" + "=" * 100)
    print("PARAMETRIC SWEEP RESULTS (Ranked STRICTLY by In-Sample Sharpe to Expose Overfitting)")
    print("=" * 100)
    header = (
        f"{'Rank':<5} {'stop_atr':<9} {'top_n':<6} {'or_min':<7} {'turnover':<9} "
        f"{'IS Trd':<7} {'IS Ret%':<9} {'IS Sharpe':<10} "
        f"{'OOS Trd':<8} {'OOS Ret%':<9} {'OOS Sharpe':<11} {'Decay':<7}"
    )
    print(header)
    print("-" * 100)

    for rank, row in results_df.head(15).iterrows():
        print(
            f"{rank:<5} {row['stop_atr']:<9.2f} {int(row['top_n']):<6} {int(row['or_minutes']):<7} {row['min_turnover_cr']:<9.0f} "
            f"{int(row['is_trades']):<7} {row['is_return_pct']:>7.2f}% {row['is_sharpe']:>9.3f} "
            f"{int(row['oos_trades']):<8} {row['oos_return_pct']:>7.2f}% {row['oos_sharpe']:>10.3f} {row['sharpe_decay']:>7.3f}"
        )
    print("-" * 100)

    # Cost-Stress Test on Best In-Sample Configuration
    best_is_row = results_df.iloc[0]
    best_cfg = StrategyConfig(
        stop_atr=float(best_is_row["stop_atr"]),
        top_n=int(best_is_row["top_n"]),
        or_minutes=int(best_is_row["or_minutes"]),
        min_turnover_cr=float(best_is_row["min_turnover_cr"]),
    )

    print(f"\n[COST-STRESS TEST] Re-running #1 In-Sample Configuration under Adverse Market Friction:")
    print(f"  Configuration: stop_atr={best_cfg.stop_atr}, top_n={best_cfg.top_n}, or_minutes={best_cfg.or_minutes}, min_turnover={best_cfg.min_turnover_cr} Cr")
    print("  Stress parameters: 2.0x Slippage Multiplier, 1.5x Statutory & Brokerage Costs Multiplier\n")

    # Load cache for best_cfg or_minutes
    best_stores, _ = load_dataset(data_dir=args.data_dir, config=best_cfg)
    stress_engine = BacktestEngine(config=best_cfg)
    stress_res = stress_engine.run(
        data_stores=best_stores,
        cost_multiplier=1.5,
        slippage_multiplier=2.0,
    )

    s_daily = stress_res.daily_df
    s_trades = stress_res.trades_df
    s_is_daily = s_daily[s_daily["is_in_sample"]]
    s_oos_daily = s_daily[~s_daily["is_in_sample"]]
    s_is_trades = s_trades[s_trades["date"] < stress_res.split_date] if not s_trades.empty else pd.DataFrame()
    s_oos_trades = s_trades[s_trades["date"] >= stress_res.split_date] if not s_trades.empty else pd.DataFrame()

    stress_is_m = calculate_metrics_for_slice("Stress IS", s_is_daily, s_is_trades, stress_res.start_equity)
    stress_oos_start_eq = float(s_is_daily["eod_equity"].iloc[-1]) if not s_is_daily.empty else stress_res.start_equity
    stress_oos_m = calculate_metrics_for_slice("Stress OOS", s_oos_daily, s_oos_trades, stress_oos_start_eq)

    print(f"{'Condition':<25} {'IS Return %':<14} {'IS Sharpe':<12} {'OOS Return %':<14} {'OOS Sharpe':<12}")
    print("-" * 77)
    print(
        f"{'Baseline Costs (1.0x)':<25} {best_is_row['is_return_pct']:>11.2f}% {best_is_row['is_sharpe']:>10.3f} "
        f"{best_is_row['oos_return_pct']:>12.2f}% {best_is_row['oos_sharpe']:>11.3f}"
    )
    print(
        f"{'Stressed (2x slip, 1.5x fee)':<25} {stress_is_m.total_return_pct:>11.2f}% {stress_is_m.sharpe_ratio:>10.3f} "
        f"{stress_oos_m.total_return_pct:>12.2f}% {stress_oos_m.sharpe_ratio:>11.3f}"
    )
    print(
        f"{'Benchmark (Doing Nothing / 0%)':<25} {'0.00%':>11} {'0.000':>10} {'0.00%':>12} {'0.000':>11}"
    )
    print("-" * 77)

    # Diagnostic Summary
    avg_decay = results_df["sharpe_decay"].mean()
    print(f"\nOVERFITTING & DECAY DIAGNOSTIC:")
    print(f"  Average Sharpe decay across all configurations (OOS - IS): {avg_decay:+.3f}")
    if avg_decay < -0.3:
        print("  ⚠️ Severe performance degradation from In-Sample to Out-of-Sample observed across parameter space.")
        print("     High probability that in-sample optima represent curve-fitting to historical noise rather than genuine edge.")
    else:
        print("  Performance decay between In-Sample and Out-of-Sample is moderate.")

    print(f"\nSweep results saved to '{sweep_csv_path}'.\n")


if __name__ == "__main__":
    main()
