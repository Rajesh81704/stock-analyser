#!/bin/bash
# Start the hourly NIFTY 500 scanner with auto-entry system

set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

echo "═══════════════════════════════════════════════════════════════════════════════════════════════════"
echo "HOURLY NIFTY 500 SCANNER WITH AUTO-ENTRY"
echo "═══════════════════════════════════════════════════════════════════════════════════════════════════"
echo ""

# Check if Python is available
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found. Please install Python 3."
    exit 1
fi

echo "✅ Python 3 found: $(python3 --version)"
echo ""

# Check if required packages are installed
echo "Checking dependencies..."
python3 -c "import apscheduler; print('✅ APScheduler available')" 2>/dev/null || {
    echo "❌ APScheduler not installed. Installing..."
    pip install APScheduler>=3.10.0
}

python3 -c "import pandas; print('✅ Pandas available')" 2>/dev/null || {
    echo "❌ Pandas not installed. Installing..."
    pip install pandas>=2.2.0
}

python3 -c "import pytz; print('✅ Pytz available')" 2>/dev/null || {
    echo "❌ Pytz not installed. Installing..."
    pip install pytz
}

echo ""

# Run tests
echo "Running pre-flight checks..."
echo ""

if python3 test_hourly_scanner.py 2>&1 | tail -20; then
    echo ""
    echo "✅ All checks passed!"
else
    echo ""
    echo "⚠️  Some checks failed. Continuing anyway..."
fi

echo ""
echo "═══════════════════════════════════════════════════════════════════════════════════════════════════"
echo "STARTING HOURLY SCANNER"
echo "═══════════════════════════════════════════════════════════════════════════════════════════════════"
echo ""
echo "Scheduler Details:"
echo "  - Scans run at: 9:30 AM, 10:30 AM, 11:30 AM, 12:30 PM, 1:30 PM, 2:30 PM, 3:15 PM IST"
echo "  - Market hours: Mon-Fri 9:15 AM - 3:30 PM IST"
echo "  - Total scans/day: 7 scans × 500 stocks = 3,500 stock checks/day"
echo ""
echo "Capital:"
echo "  - EMA Pullback: ₹125,000"
echo "  - 52WH Breakout: ₹125,000"
echo "  - Total: ₹250,000"
echo ""
echo "Logs:"
echo "  - Scanner: algodesk/paper_trading_logs/nifty500_scan.log"
echo "  - Scheduler: algodesk/paper_trading_logs/scheduler.log"
echo "  - Results: algodesk/paper_trading_logs/hourly_scan_results.json"
echo ""
echo "To stop: Press Ctrl+C"
echo ""
echo "═══════════════════════════════════════════════════════════════════════════════════════════════════"
echo ""

# Start the scheduler
exec python3 scheduler_hourly_scan.py
