#!/usr/bin/env python3
"""
CLI Script: Run Backtest on Opening Range Breakout (ORB) Strategy.

Executes backtest over historical or synthetic intraday 5-minute candles,
applies realistic Zerodha equity intraday costs and slippage,
evaluates In-Sample vs Out-of-Sample metrics, and produces reports.
"""

import argparse
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.costs.calculator import CostCalculator, ZerodhaIntradayCostsConfig
from src.data.loader import load_dataset
from src.data.synthetic import generate_synthetic_universe
from src.engine.backtester import BacktestEngine
from src.metrics.performance import calculate_metrics_for_slice
from src.report.generator import ReportGenerator
from src.strategy.config import StrategyConfig


def main():
    parser = argparse.ArgumentParser(description="Run research-grade backtest of ORB strategy.")
    parser.add_argument("--synthetic", action="store_true", help="Run on synthetic random-walk data for smoke-testing")
    parser.add_argument("--stop-atr", type=float, default=0.10, help="Stop distance as fraction of ATR14 (default: 0.10)")
    parser.add_argument("--top-n", type=int, default=5, help="Number of top RVOL candidates to trade per day (default: 5)")
    parser.add_argument("--or-minutes", type=int, choices=[5, 15, 30], default=5, help="Opening range duration in minutes (5, 15, 30)")
    parser.add_argument("--min-turnover-cr", type=float, default=20.0, help="Min trailing 20d turnover in Rs Crore (default: 20)")
    parser.add_argument("--min-rvol", type=float, default=1.0, help="Min RVOL threshold (default: 1.0)")
    parser.add_argument("--direction", choices=["both", "long_only", "short_only"], default="both", help="Directional switch")
    parser.add_argument("--capital", type=float, default=100000.0, help="Starting portfolio capital in INR (default: 100,000)")
    parser.add_argument("--risk-pct", type=float, default=0.01, help="Risk percentage per trade of SOD equity (default: 0.01 = 1%)")
    parser.add_argument("--cost-multiplier", type=float, default=1.0, help="Multiplier on statutory charges & brokerage (stress testing)")
    parser.add_argument("--slippage-multiplier", type=float, default=1.0, help="Multiplier on slippage bps (stress testing)")
    parser.add_argument("--data-dir", type=str, default="data", help="Directory containing candle CSV files")
    parser.add_argument("--results-dir", type=str, default="results", help="Directory for output reports and plots")
    args = parser.parse_args()

    # 1. Config Setup
    config = StrategyConfig(
        or_minutes=args.or_minutes,
        stop_atr=args.stop_atr,
        top_n=args.top_n,
        min_turnover_cr=args.min_turnover_cr,
        min_rvol=args.min_rvol,
        direction_mode=args.direction,
        initial_capital=args.capital,
        risk_pct=args.risk_pct,
    )

    data_path = Path(args.data_dir)

    # 2. Synthetic Data Generation if needed
    if args.synthetic:
        csv_files = list(data_path.glob("*.csv"))
        # Filter out index list
        stock_files = [f for f in csv_files if not f.name.startswith("ind_") and f.name != "nifty500.csv"]
        if len(stock_files) < 10:
            print("[SMOKE TEST] Generating synthetic data for 30 symbols...")
            generate_synthetic_universe(output_dir=str(data_path), trading_days=70)

    # 3. Load Dataset
    print(f"\n[BACKTEST INIT] Loading dataset from '{args.data_dir}'...")
    data_stores, hygiene_reports = load_dataset(data_dir=args.data_dir, config=config)

    if not data_stores:
        print(f"[ERROR] No valid data found in '{args.data_dir}'.", file=sys.stderr)
        if not args.synthetic:
            print("Tip: Run with --synthetic to generate smoke-test data or fetch data using scripts/fetch_data.py.", file=sys.stderr)
        sys.exit(1)

    print(f"[DATA LOADED] Loaded {len(data_stores)} valid symbol series.")

    # 4. Check for data hygiene warnings
    flagged_corps = [r for r in hygiene_reports if r.corporate_action_flags]
    if flagged_corps:
        print(f"\n[DATA HYGIENE] Flagged {len(flagged_corps)} symbols with large single-day returns (|return| > 40%):")
        for fc in flagged_corps[:5]:
            for flag in fc.corporate_action_flags:
                print(f"  - {flag}")

    # 5. Run Engine
    print("\n[BACKTEST RUNNING] Simulating intraday execution with daily compounding and Zerodha MIS costs...")
    engine = BacktestEngine(config=config)
    result = engine.run(
        data_stores=data_stores,
        cost_multiplier=args.cost_multiplier,
        slippage_multiplier=args.slippage_multiplier,
    )

    # 6. Generate Reports and Plots
    rep_gen = ReportGenerator(output_dir=args.results_dir)
    paths = rep_gen.generate_all(
        result=result,
        cost_multiplier=args.cost_multiplier,
        slippage_multiplier=args.slippage_multiplier,
        is_synthetic=args.synthetic,
    )

    # 7. Print Terminal Summary
    trades_df = result.trades_df
    daily_df = result.daily_df

    is_daily = daily_df[daily_df["is_in_sample"]]
    oos_daily = daily_df[~daily_df["is_in_sample"]]
    is_trades = trades_df[trades_df["date"] < result.split_date] if not trades_df.empty else pd.DataFrame()
    oos_trades = trades_df[trades_df["date"] >= result.split_date] if not trades_df.empty else pd.DataFrame()

    full_m = calculate_metrics_for_slice("Full", daily_df, trades_df, result.start_equity)
    is_m = calculate_metrics_for_slice("In-Sample", is_daily, is_trades, result.start_equity)
    oos_start_eq = float(is_daily["eod_equity"].iloc[-1]) if not is_daily.empty else result.start_equity
    oos_m = calculate_metrics_for_slice("Out-of-Sample", oos_daily, oos_trades, oos_start_eq)

    print("\n" + "=" * 78)
    if args.synthetic:
        print(">>> SYNTHETIC DATA MODE ACTIVE - CODE PIPELINE SMOKE TEST ONLY <<<")
        print(">>> Synthetic random-walk data DOES NOT represent real market performance! <<<")
        print("=" * 78)

    print(f"EVALUATION SUMMARY: Opening Range Breakout (ORB)")
    print(f"Trading Days: {result.total_trading_days} (IS: {result.is_trading_days}, OOS: {result.oos_trading_days}) | Split Date: {result.split_date}")
    print(f"Universe Loaded: {len(data_stores)} stocks | Capital: Rs {config.initial_capital:,.0f} | Risk/Trade: {config.risk_pct*100:.1f}%\n")

    print(f"{'METRIC':<32} {'FULL HORIZON':<15} {'IN-SAMPLE (70%)':<17} {'OUT-OF-SAMPLE (30%)':<18}")
    print("-" * 84)
    print(f"{'Total Trades':<32} {full_m.trades_count:<15} {is_m.trades_count:<17} {oos_m.trades_count:<18}")
    print(f"{'Total Net Return %':<32} {full_m.total_return_pct:>10.2f}% {is_m.total_return_pct:>12.2f}% {oos_m.total_return_pct:>13.2f}%")
    print(f"{'Annualized CAGR %':<32} {full_m.cagr_pct:>10.2f}% {is_m.cagr_pct:>12.2f}% {oos_m.cagr_pct:>13.2f}%")
    print(f"{'Annualized Sharpe (250d)':<32} {full_m.sharpe_ratio:>11.3f} {is_m.sharpe_ratio:>13.3f} {oos_m.sharpe_ratio:>14.3f}")
    print(f"{'Max Drawdown %':<32} {full_m.max_drawdown_pct:>10.2f}% {is_m.max_drawdown_pct:>12.2f}% {oos_m.max_drawdown_pct:>13.2f}%")
    print(f"{'Win Rate %':<32} {full_m.win_rate_pct:>10.2f}% {is_m.win_rate_pct:>12.2f}% {oos_m.win_rate_pct:>13.2f}%")
    print(f"{'Profit Factor':<32} {full_m.profit_factor:>11.2f} {is_m.profit_factor:>13.2f} {oos_m.profit_factor:>14.2f}")
    print(f"{'Stopped Out %':<32} {full_m.stopped_out_pct:>10.1f}% {is_m.stopped_out_pct:>12.1f}% {oos_m.stopped_out_pct:>13.1f}%")
    print(f"{'Gross P&L (INR)':<32} Rs {full_m.gross_pnl:>11,.0f} Rs {is_m.gross_pnl:>13,.0f} Rs {oos_m.gross_pnl:>14,.0f}")
    print(f"{'Total Costs & Slippage (INR)':<32} -Rs {full_m.total_costs:>10,.0f} -Rs {is_m.total_costs:>12,.0f} -Rs {oos_m.total_costs:>13,.0f}")
    print(f"{'Net P&L (INR)':<32} Rs {full_m.net_pnl:>11,.0f} Rs {is_m.net_pnl:>13,.0f} Rs {oos_m.net_pnl:>14,.0f}")
    print(f"{'Benchmark (Cash / 0%)':<32} {'0.00%':>11} {'0.00%':>13} {'0.00%':>14}")
    print("-" * 84)

    print("\nHONEST VERDICT & RESEARCH ASSESSMENT:")
    if oos_m.net_pnl > 0 and oos_m.sharpe_ratio > 0.5:
        print(f"  [POSITIVE] The strategy generated positive net return ({oos_m.total_return_pct:.2f}%) and Sharpe ({oos_m.sharpe_ratio:.2f})")
        print(f"  in the Out-of-Sample period after realistic Zerodha intraday transaction costs.")
    elif oos_m.net_pnl > 0:
        print(f"  [MARGINAL] The strategy was barely positive out-of-sample ({oos_m.total_return_pct:.2f}%, Sharpe {oos_m.sharpe_ratio:.2f}),")
        print(f"  indicating weak alpha that may easily evaporate with slight execution drag.")
    else:
        print(f"  [UNPROFITABLE] The strategy LOST money in the Out-of-Sample period ({oos_m.total_return_pct:.2f}% net return).")
        print(f"  Gross gains (Rs {oos_m.gross_pnl:,.0f}) were completely wiped out by statutory taxes & slippage (Rs {oos_m.total_costs:,.0f}).")
        print(f"  Conclusion: The strategy DOES NOT demonstrate robust out-of-sample edge under realistic Indian market friction.")

    if oos_m.few_trades_warning:
        print(f"\n  [WARNING] Only {oos_m.trades_count} trades occurred Out-of-Sample (< 100 threshold).")
        print("  Statistical significance is limited; do not draw definitive conclusions without more sample trades.")

    print(f"\nArtifacts generated successfully in '{args.results_dir}':")
    for k, v in paths.items():
        print(f"  - {k}: {v}")
    print("=" * 78 + "\n")


if __name__ == "__main__":
    main()
