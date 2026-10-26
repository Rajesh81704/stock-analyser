# Research-Grade Intraday Equity Backtesting System (NSE / Zerodha MIS)

> **RESEARCH & BACKTEST ONLY**: This software is strictly for quantitative research, historical simulation, and academic verification. It contains **NO code that connects to live order endpoints or executes live market orders**.

---

## 1. System Overview

A high-performance quantitative intraday backtesting platform designed specifically for Indian equities (NSE, Zerodha MIS product). It simulates the **Opening Range Breakout (ORB) on Stocks in Play** strategy across the Nifty 500 universe with realistic statutory transaction taxes, broker charges, and liquidity-tiered slippage.

The system prioritizes **uncompromising research honesty**:
- **Strict In-Sample (70%) vs Out-of-Sample (30%) chronological segregation**.
- **Zero lookahead bias**: all trailing baselines (ATR, turnover, RVOL) are strictly shifted to exclude same-day information.
- **Conservative execution mechanics**: intrabar stop-out assumption on entry bars and adverse gap fills.
- **Comprehensive friction modeling**: statutory STT, GST, SEBI turnover fees, exchange transaction charges, stamp duty, and slippage.

---

## 2. Project Architecture

```
stock-analyser/
├── README.md                      # Architecture documentation & research guidelines
├── requirements.txt               # Pinned dependencies
├── pytest.ini                     # Pytest configuration
├── ind_nifty500list.csv           # NSE Nifty 500 constituents file
├── src/
│   ├── costs/                     # Zerodha intraday fee calculator & cost breakdown
│   │   ├── __init__.py
│   │   └── calculator.py
│   ├── data/                      # Data hygiene, synthetic generator, Kite API client
│   │   ├── __init__.py
│   │   ├── hygiene.py
│   │   ├── synthetic.py
│   │   ├── loader.py
│   │   └── kite_client.py
│   ├── strategy/                  # Strategy configuration & RVOL ranking engine
│   │   ├── __init__.py
│   │   ├── config.py
│   │   └── ranking.py
│   ├── engine/                    # Bar-by-bar intraday simulator & compounding backtester
│   │   ├── __init__.py
│   │   ├── simulator.py
│   │   └── backtester.py
│   ├── metrics/                   # Quant statistics, drawdowns, Sharpe, and period analytics
│   │   ├── __init__.py
│   │   └── performance.py
│   └── report/                    # Markdown report generator & Matplotlib equity plots
│       ├── __init__.py
│       └── generator.py
├── scripts/
│   ├── fetch_data.py              # Historical 5m candle downloader & session manager
│   │   --login-url, --request-token, --resume, --days, --synthetic
│   ├── run_backtest.py            # Primary backtest runner & reporting CLI
│   └── run_sweep.py               # Robustness parameter sweep & overfitting analysis
├── tests/
│   ├── test_costs.py              # Hand-computed cost verification against Zerodha
│   ├── test_lookahead.py          # Verifies future data shifts have zero impact on today
│   ├── test_breakout_synthetic.py # Deterministic breakout trigger & exit verification
│   └── test_stop_intrabar.py      # Conservative intrabar stop & gap exit rules
├── data/                          # 5-minute candle CSV files (git-ignored)
└── results/                       # Backtest ledger, metrics, and plots (git-ignored)
    ├── trades.csv                 # Granular trade-by-trade audit ledger
    ├── daily.csv                  # Daily compounded equity series
    ├── equity_curve.png           # Equity curve with IS/OOS split
    ├── sweep_results.csv          # Grid sweep parameter results
    └── report.md                  # Comprehensive quant research markdown report
```

---

## 3. Installation & Environment Setup

### Prerequisites
- Python 3.11+
- Linux / macOS / Windows

```bash
# Clone the repository
cd /path/to/stock-analyser

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

---

## 4. Authentication: Daily Zerodha Kite Connect Workflow

Zerodha Kite Connect sessions expire daily at 06:00 AM IST. Because Indian regulatory guidelines mandate Two-Factor Authentication (2FA TOTP), access token generation cannot be fully automated into an unattended cron without violating terms or security best practices.

**Credentials must ONLY be passed via environment variables. Never hardcode API keys or secrets in source code.**

```bash
# 1. Set your Kite Connect App credentials in your environment
export KITE_API_KEY="your_api_key_here"
export KITE_API_SECRET="your_api_secret_here"

# 2. Generate the Kite web authorization URL
python scripts/fetch_data.py --login-url
```

Sample output:
```text
=== Zerodha Kite Connect Login ===
1. Open the following URL in your browser:
   https://kite.zerodha.com/connect/login?v=3&api_key=your_api_key_here

2. Log in with your Zerodha credentials and 2FA TOTP.
3. After login, your browser redirects to your redirect URL. Copy the 'request_token' parameter from the address bar.
4. Run: python scripts/fetch_data.py --request-token <COPIED_REQUEST_TOKEN>
```

```bash
# 3. Exchange request token for the daily access token
python scripts/fetch_data.py --request-token "abc123xyz..."

# Sample output:
# export KITE_ACCESS_TOKEN="your_daily_access_token..."

# 4. Export the generated access token
export KITE_ACCESS_TOKEN="your_daily_access_token..."
```

---

## 5. End-to-End Workflow

### Step 1: Download Historical 5-Minute Candles

Downloads 5-minute candles for all Nifty 500 constituents chunked into 90-day intervals (respecting Kite's limit of ~100 days for 5-minute candles) with rate limiting ($\ge 0.5$s sleep, ~2 req/s) and backoff retry.

```bash
# Download 500 days of history for Nifty 500 universe with resume support
python scripts/fetch_data.py --days 500 --resume

# Or run in smoke-test mode without Kite API credentials (generates synthetic random-walk data):
python scripts/fetch_data.py --synthetic
```

### Step 2: Run Single Backtest

Executes the baseline ORB strategy with daily compounding, logs progress, produces reports in `results/`, and prints an honest quant summary.

```bash
# Run with synthetic data smoke-test
python scripts/run_backtest.py --synthetic

# Run with full dataset
python scripts/run_backtest.py \
  --stop-atr 0.10 \
  --top-n 5 \
  --or-minutes 5 \
  --min-turnover-cr 20 \
  --capital 100000 \
  --risk-pct 0.01
```

### Step 3: Run Robustness Grid Sweep & Overfitting Diagnostics

Sweeps a 108-point parameter grid:
- `stop_atr` $\in \{0.05, 0.10, 0.20, 0.50\}$
- `top_n` $\in \{3, 5, 10\}$
- `or_minutes` $\in \{5, 15, 30\}$
- `min_turnover_cr` $\in \{20, 50, 100\}$

**Critical Quant Requirement**: Parameters are ranked **strictly by In-Sample Sharpe**, and the corresponding Out-of-Sample metrics are printed side-by-side to expose curve-fitting decay.

```bash
# Run quick 16-point smoke sweep
python scripts/run_sweep.py --synthetic --quick

# Run full 108-point sweep
python scripts/run_sweep.py --synthetic
```

---

## 6. Strategy Rules & Exact Mathematical Definitions

The "Opening Range Breakout on Stocks in Play" strategy operates on strict, lookahead-free rules:

### A. Opening Range (OR)
- Defined by the first $M$ minutes of the trading session starting at 09:15:00 IST ($M \in \{5, 15, 30\}$).
- $OR_{High} = \max(\text{High}_{09:15 \dots 09:15+M})$, $OR_{Low} = \min(\text{Low}_{09:15 \dots 09:15+M})$.
- Directional filter:
  - $OR_{Close} > OR_{Open} \implies$ **LONG ONLY**
  - $OR_{Close} < OR_{Open} \implies$ **SHORT ONLY**
  - $OR_{Close} == OR_{Open} \implies$ **DOJI (SKIP)**
  - Optional CLI switches: `--direction both`, `long_only`, `short_only`.

### B. Relative Volume (RVOL) — "Stocks in Play"
- Relative Volume measures institutional participation:
  $$\text{RVOL}_t = \frac{\text{OR\_Volume}_t}{\frac{1}{14} \sum_{k=1}^{14} \text{OR\_Volume}_{t-k}}$$
- **Strict No-Lookahead Shift**: Today's volume is excluded from the baseline. Only prior 14 completed trading days are used.

### C. Daily ATR(14)
- Daily True Range calculated on daily candles:
  $$TR_t = \max(H_t - L_t, |H_t - C_{t-1}|, |L_t - C_{t-1}|)$$
  $$ATR(14)_t = \text{WilderEMA}(TR, 14)$$
- **Strict No-Lookahead Shift**: Today's trading decisions use $ATR(14)_{t-1}$ (the ATR known at market open).

### D. Universe Eligibility & Daily Ranking
Every day $t$, filter stocks satisfying:
1. Trailing 20-day average daily turnover (close $\times$ volume in Rs Crore) $\ge \text{min\_turnover\_cr}$ (default Rs 20 Cr, shifted 1 day).
2. Previous day close $\ge \text{Rs } 50$.
3. $\text{RVOL}_t \ge 1.0$.
4. Valid directional signal (not Doji).
- Eligible stocks are ranked descending by $\text{RVOL}_t$; the top $N$ stocks (default 5) are selected for execution.

### E. Execution & Intrabar Stop Mechanics
- **Scanning**: Bars are scanned starting immediately after the OR window ($t \ge 09:15 + M$).
- **Trigger**:
  - Long: Bar High $\ge OR_{High}$.
  - Short: Bar Low $\le OR_{Low}$.
- **Gap Entry Fill**: If a bar opens beyond the trigger ($Open > OR_{High}$ for long, or $Open < OR_{Low}$ for short), order is filled at the **bar Open price**, not the trigger.
- **Stop-Loss Level**:
  $$\text{Stop Loss} = \text{Fill Price} \mp (\text{stop\_atr} \times ATR(14)_{t-1})$$
- **Conservative Intrabar Rule**: If the bar that triggers the entry also touches the stop-loss level ($Low \le \text{Stop}$ for long), the trade is **assumed stopped out on that same bar**.
- **Gap Exit Fill**: If a bar opens beyond the stop level, execution fills at the **bar Open price**, not the stop price.
- **Time Exit**: If neither stop nor profit target is hit, positions are squared off at the close of the last bar before 15:15 IST (the 15:10 candle close) to prevent broker MIS auto-squareoff penalties.
- **Single Trade Rule**: Maximum of 1 trade per stock per day.

### F. Position Sizing & Compounding
- Sizing based on risk fraction $f_{risk} = 1\%$ of start-of-day equity $E_t$:
  $$Qty_{risk} = \left\lfloor \frac{E_t \times f_{risk}}{\text{Stop Distance}} \right\rfloor$$
- Leverage constraint: Gross exposure capped at max leverage (5x Zerodha MIS) divided equally across $N$ slots:
  $$Qty_{cap} = \left\lfloor \frac{E_t \times \text{max\_leverage} / N}{\text{Entry Price}} \right\rfloor$$
  $$Qty = \min(Qty_{risk}, Qty_{cap})$$
- Integer share quantities only; if $Qty < 1$, the trade is skipped. Daily compounded equity: $E_{t+1} = E_t + \sum \text{Net PnL}_i$.

---

## 7. Indian Equity Intraday Transaction Costs & Slippage

Rates are defined in `src/costs/calculator.py` (`ZerodhaIntradayCostsConfig`). 
> **Important**: Always verify these statutory rates against Zerodha's live brokerage calculator: https://zerodha.com/brokerage-calculator/#tab-equities

| Fee Item | Statutory / Broker Tariff | Applied Side |
| :--- | :--- | :--- |
| **Brokerage** | $\min(\text{Rs } 20, 0.03\% \text{ turnover})$ | Both Buy & Sell legs |
| **STT / CTT** | $0.025\%$ of sell turnover | Sell leg only |
| **Exchange Txn (NSE)** | $0.00297\%$ of turnover | Both Buy & Sell legs |
| **SEBI Turnover Fee** | Rs 10 / Crore ($0.0001\%$) | Both Buy & Sell legs |
| **Stamp Duty** | $0.003\%$ of buy turnover | Buy leg only |
| **GST** | $18\%$ on $(\text{Brokerage} + \text{Exchange Fee} + \text{SEBI Fee})$ | Both legs combined |
| **Slippage Drag** | **5 bps** ($0.05\%$) default; **10 bps** ($0.10\%$) for turnover < Rs 100 Cr | Both Buy & Sell fills |

---

## 8. Automated Test Suite

Run unit and integration tests via `pytest`:

```bash
pytest tests/ -v
```

Test coverage includes:
1. `tests/test_costs.py`: Verifies brokerage cap (Rs 20), uncapped small turnover, STT, exchange charges, stamp duty, GST, and turnover-based slippage doubling against hand-calculated benchmarks.
2. `tests/test_lookahead.py`: Mutates future bars (days $> T$) and asserts that Day $T$'s features, indicators, and candidate ranking are bit-for-bit invariant.
3. `tests/test_breakout_synthetic.py`: Validates entry price, stop-loss calculation, gap open fill, and 15:10 time exit on deterministic candles.
4. `tests/test_stop_intrabar.py`: Proves that entry bars touching the stop trigger an immediate stop-out and that gaps past the stop fill at the open price.

---

## 9. Known Limitations & Structural Caveats

Every quantitative trading system must acknowledge the gap between simulation and real-world market microstructure:

1. **Survivorship Bias**: Testing on the current Nifty 500 constituents file introduces survivorship bias. Companies that entered insolvency, merged, or lost market cap over the 500-day window are absent from today's list, inflating historical returns.
2. **Assumed Stop Order Fills**: Stop orders are assumed filled at the trigger price or bar open. In fast-moving breakouts or market selloffs, market stop orders can suffer substantial slippage beyond 5-10 bps.
3. **Zero Market Impact**: The backtester assumes our simulated orders do not move the book or exhaust available depth at the best quote.
4. **Price Circuits**: Does not simulate upper/lower circuit halts (5%, 10%, 20%) where exchange trading halts and orders cannot be filled or squared off.
5. **Broker MIS Shorting Bans**: Assumes all Nifty 500 stocks are eligible for MIS intraday shorting on Zerodha every day. In practice, Zerodha restricts MIS shorting on scrips undergoing surveillance (GSM/ASM) or high-volatility events.
6. **Corporate Actions**: Splits, reverse splits, and bonus issues can produce false gap breakouts. The data loader flags single-day $|return| > 40\%$ for manual review.
7. **Past Performance Disclaimer**: Past simulated performance is **NOT indicative of future live market returns**. Market dynamics, volatility regimes, and execution liquidity constantly evolve.

---

## 10. CI/CD Pipeline (GitHub Actions)

This repository features automated Continuous Integration and Continuous Deployment pipelines via GitHub Actions:

### 1. Continuous Integration (`.github/workflows/ci.yml`)
- **Triggers**: On push and pull requests targeting `main`.
- **Matrix**: Tests across Python `3.11` and `3.12`.
- **Stages**:
  - Python compilation and syntax check across all source files.
  - Verification of YAML strategy configurations in `configs/`.
  - Comprehensive unit and integration test suite execution (`pytest tests/ -v`).

### 2. Continuous Deployment (`.github/workflows/deploy.yml`)
- **Triggers**: Automatically on push to `main` after CI checks pass, or manually via `workflow_dispatch`.
- **Target**: Production VPS (`stock@72.61.255.43`) with Caddy reverse proxy & Let's Encrypt SSL.
- **Workflow**:
  - Fetches and resets repository to latest `origin/main`.
  - Updates pip dependencies from `requirements.txt`.
  - Zero-downtime reloads PM2 service (`stock-analyser`).
  - Probes live API endpoints (`/api/automation/top10/status`) to confirm operational health.

### 3. GitHub Secrets Configuration (Optional Override)
Configure these in **GitHub Repository Settings > Secrets and variables > Actions**:
- `VPS_HOST`: `72.61.255.43`
- `VPS_USER`: `stock`
- `VPS_PASSWORD`: `stock` (or provide `VPS_SSH_KEY`)
- `VPS_PORT`: `22`

