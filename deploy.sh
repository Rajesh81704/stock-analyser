#!/usr/bin/env bash
# =======================================================================
# AlgoDesk MarketX - Deploy Shell Wrapper
# Usage:
#   ./deploy.sh
#   ./deploy.sh -m "commit message"
# =======================================================================
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# Ensure deploy.py is executable
chmod +x deploy.py 2>/dev/null || true

# Run python deployer
if [ -f ".venv/bin/python" ]; then
    .venv/bin/python deploy.py "$@"
elif command -v python3 &>/dev/null; then
    python3 deploy.py "$@"
else
    python deploy.py "$@"
fi
