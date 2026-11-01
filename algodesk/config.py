"""
algodesk configuration loader and validation.
Loads YAML configuration and overrides secrets from environment variables.
"""

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Any, Dict, Optional
import yaml


@dataclass
class StrategyConfig:
    name: str = "ema_pullback_adx"
    ema_fast: int = 20
    ema_slow: int = 50
    adx_len: int = 14
    adx_min: float = 20.0
    atr_len: int = 14
    vol_mult: float = 1.5
    vol_avg_len: int = 30
    swing_lookback: int = 20
    setup_valid_days: int = 2
    min_rr: float = 1.5
    max_stop_atr: float = 2.5
    min_turnover_20d: float = 50000000.0
    gap_max_atr: float = 0.5
    time_stop_days: int = 20


@dataclass
class RiskConfig:
    risk_pct: float = 0.01
    max_position_pct: float = 0.20
    max_positions: int = 5
    max_per_sector: int = 2
    max_open_risk: float = 0.05
    month_dd_halt: float = -0.06


@dataclass
class ExecutionConfig:
    initial_capital: float = 1000000.0
    slippage_pct: float = 0.001
    product: str = "CNC"
    exchange: str = "NSE"
    live_mode: bool = False
    api_key: str = field(default_factory=lambda: os.getenv("KITE_API_KEY", os.getenv("ZERODHA_API_KEY", "")))
    access_token: str = field(default_factory=lambda: os.getenv("KITE_ACCESS_TOKEN", os.getenv("ZERODHA_ACCESS_TOKEN", "")))


@dataclass
class CostConfig:
    stt_delivery_buy_pct: float = 0.001
    stt_delivery_sell_pct: float = 0.001
    exchange_txn_pct: float = 0.0000297
    stamp_duty_buy_pct: float = 0.00015
    sebi_turnover_pct: float = 0.000001
    gst_pct: float = 0.18
    dp_charge_per_sell: float = 15.93


@dataclass
class StorageConfig:
    db_path: str = "data/algodesk.db"
    schema_path: str = "algodesk/store/schema.sql"


@dataclass
class DataConfig:
    cache_dir: str = "data/nifty500_10y_cache"
    universe_csv: str = "ind_nifty500list.csv"
    benchmark_symbol: str = "^NSEI"


@dataclass
class AppConfig:
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    costs: CostConfig = field(default_factory=CostConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    data: DataConfig = field(default_factory=DataConfig)

    @classmethod
    def load(cls, config_path: Optional[str] = None) -> "AppConfig":
        if config_path is None:
            config_path = str(Path(__file__).parent / "config.yaml")

        raw_cfg: Dict[str, Any] = {}
        if os.path.exists(config_path):
            with open(config_path, "r") as f:
                raw_cfg = yaml.safe_load(f) or {}

        strat = StrategyConfig(**raw_cfg.get("strategy", {}))
        rsk = RiskConfig(**raw_cfg.get("risk", {}))
        cst = CostConfig(**raw_cfg.get("costs", {}))
        stg = StorageConfig(**raw_cfg.get("storage", {}))
        dt = DataConfig(**raw_cfg.get("data", {}))

        # Execution with env secret overrides
        exec_dict = raw_cfg.get("execution", {})
        live_flag = os.getenv("LIVE", "").lower() in ("true", "1", "yes")
        if live_flag:
            exec_dict["live_mode"] = True
        exc = ExecutionConfig(**exec_dict)

        return cls(
            strategy=strat,
            risk=rsk,
            execution=exc,
            costs=cst,
            storage=stg,
            data=dt
        )
