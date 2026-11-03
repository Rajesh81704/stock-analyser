"""
algodesk: Swing Trading Quantitative Platform for Indian Equities (NSE Nifty 500)
"""
import os
from pathlib import Path

# Unify namespace across root algodesk and src/algodesk
_root = Path(__file__).resolve().parent.parent
for _p in [str(_root / "algodesk"), str(_root / "src" / "algodesk")]:
    if os.path.isdir(_p) and _p not in __path__:
        __path__.append(_p)

__version__ = "1.0.0"
