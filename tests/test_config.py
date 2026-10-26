"""
Unit tests for AlgoDesk Configuration and Live Execution Safety Gates.
"""

from pathlib import Path
import pytest
from src.algodesk.config.settings import Settings, ExecutionMode
from src.algodesk.config.strategy_config import load_strategy_yaml, StrategyFileConfig


def test_settings_default_values():
    """Validates default settings safety parameters."""
    s = Settings(ALGODESK_ALLOW_LIVE=False)
    assert s.algodesk_allow_live is False
    assert s.default_mode == ExecutionMode.PAPER


def test_safety_gates_strictly_block_live_mode():
    """
    NON-NEGOTIABLE SAFETY RULE:
    LIVE requires ALL of:
      1. env var ALGODESK_ALLOW_LIVE=true
      2. per-strategy 'live_enabled: true' in its config
      3. explicit confirmation action in dashboard each trading day.
    """
    # Case 1: ALGODESK_ALLOW_LIVE is False
    s1 = Settings(ALGODESK_ALLOW_LIVE=False)
    permitted, reason = s1.is_live_execution_permitted(strategy_live_enabled=True, daily_confirmed=True)
    assert permitted is False
    assert "ALGODESK_ALLOW_LIVE" in reason

    # Case 2: strategy_live_enabled is False
    s2 = Settings(ALGODESK_ALLOW_LIVE=True)
    permitted, reason = s2.is_live_execution_permitted(strategy_live_enabled=False, daily_confirmed=True)
    assert permitted is False
    assert "live_enabled" in reason

    # Case 3: daily_confirmed is False
    s3 = Settings(ALGODESK_ALLOW_LIVE=True)
    permitted, reason = s3.is_live_execution_permitted(strategy_live_enabled=True, daily_confirmed=False)
    assert permitted is False
    assert "daily confirmation" in reason

    # Case 4: ALL 3 ARE TRUE -> Permitted
    permitted, reason = s3.is_live_execution_permitted(strategy_live_enabled=True, daily_confirmed=True)
    assert permitted is True
    assert "PERMITTED" in reason


def test_load_strategy_yaml():
    """Validates loading and schema validation of configs/orb_stocks_in_play.yaml."""
    cfg_path = Path("configs/orb_stocks_in_play.yaml")
    assert cfg_path.exists()

    config = load_strategy_yaml(cfg_path)
    assert config.name == "orb_stocks_in_play"
    assert config.mode == ExecutionMode.PAPER
    assert config.live_enabled is False
    assert config.universe.min_turnover_cr == 20.0
    assert config.parameters["or_minutes"] == 5
    assert config.risk.risk_pct_per_trade == 0.01
    assert config.risk.max_leverage == 5.0
