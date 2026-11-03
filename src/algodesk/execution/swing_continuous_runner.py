"""Bridge module ensuring swing_continuous_runner is resolvable under src.algodesk.execution."""
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent.parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from algodesk.execution.swing_continuous_runner import *
from algodesk.execution.swing_continuous_runner import swing_runner
