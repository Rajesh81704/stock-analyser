"""
Strategy Configuration Loader & Schema Validation.

Loads and validates YAML configuration files from configs/ for each strategy.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml
from pydantic import BaseModel, Field

from src.algodesk.config.settings import ExecutionMode


class UniverseConfig(BaseModel):
    """Universe definition and screening filters for a strategy."""
    source: str = "nifty500"                  # "nifty500", "custom", or comma-separated list
    symbols: Optional[List[str]] = None      # Specific symbols if custom
    min_turnover_cr: float = 20.0            # Trailing 20d turnover filter in Rs Crore
    min_price: float = 50.0                  # Minimum share price (prev close)
    max_symbols_per_day: int = 5             # Maximum candidates to trade per day


class RiskOverrides(BaseModel):
    """Strategy-specific risk overrides."""
    max_daily_loss: Optional[float] = None    # Max cumulative daily loss for this strategy
    max_open_positions: int = 5               # Max concurrent positions
    max_notional_per_order: Optional[float] = None # Max order value in INR
    risk_pct_per_trade: float = 0.01          # 1% risk per trade of SOD equity
    max_leverage: float = 5.0                 # Max gross leverage across positions
    entry_cutoff_time: str = "14:45:00"       # No new entries after 14:45 IST
    square_off_time: str = "15:10:00"         # Mandatory intraday square off


class StrategyFileConfig(BaseModel):
    """Schema for strategy configuration files in configs/<name>.yaml."""
    name: str
    version: str = "1.0.0"
    strategy_class: str                       # Registered strategy class name
    timeframe: str = "5m"                     # 1m, 5m, 15m, etc.
    mode: ExecutionMode = ExecutionMode.PAPER # Default is PAPER
    live_enabled: bool = False                # Must be explicitly true for LIVE mode
    universe: UniverseConfig = Field(default_factory=UniverseConfig)
    parameters: Dict[str, Any] = Field(default_factory=dict)
    risk: RiskOverrides = Field(default_factory=RiskOverrides)


def load_strategy_yaml(file_path: Path) -> StrategyFileConfig:
    """Loads and validates a single strategy configuration YAML file."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Strategy config file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ValueError(f"Invalid YAML content in {path}: expected dictionary mapping.")

    return StrategyFileConfig(**data)


def load_all_strategy_configs(configs_dir: Path) -> List[StrategyFileConfig]:
    """Scans and loads all strategy YAML configuration files in the specified directory."""
    path = Path(configs_dir)
    if not path.exists():
        return []

    configs = []
    for yaml_file in sorted(path.glob("*.yaml")) + sorted(path.glob("*.yml")):
        try:
            cfg = load_strategy_yaml(yaml_file)
            configs.append(cfg)
        except Exception as e:
            # Skip invalid or log
            pass
    return configs
