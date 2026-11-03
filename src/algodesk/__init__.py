"""
AlgoDesk: Personal Self-Hosted Intraday & Swing Algo Trading Platform for Indian Equities.
"""
import os
from pathlib import Path

# Unify namespace across root algodesk and src/algodesk
_root = Path(__file__).resolve().parent.parent.parent
for _p in [str(_root / "algodesk"), str(_root / "src" / "algodesk")]:
    if os.path.isdir(_p) and _p not in __path__:
        __path__.append(_p)

__version__ = "0.1.0"
