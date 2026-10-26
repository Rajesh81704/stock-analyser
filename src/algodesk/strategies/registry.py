"""
Dynamic Strategy Discovery and Registry for AlgoDesk.

Automatically discovers and registers strategy plugins from:
- src/algodesk/strategies/
- strategies_user/ (hot-reloaded user strategies)
"""

import importlib.util
import inspect
import logging
from pathlib import Path
from typing import Dict, List, Type

from src.algodesk.config.settings import settings
from src.algodesk.strategies.base import BaseStrategy

logger = logging.getLogger(__name__)


class StrategyRegistry:
    """Registry holding all discovered strategy classes."""

    _registry: Dict[str, Type[BaseStrategy]] = {}

    @classmethod
    def register(cls, strategy_class: Type[BaseStrategy]):
        """Explicitly registers a strategy class."""
        if not inspect.isclass(strategy_class) or not issubclass(strategy_class, BaseStrategy):
            raise ValueError(f"{strategy_class} must be a subclass of BaseStrategy.")
        cls._registry[strategy_class.name] = strategy_class
        logger.info(f"Registered strategy: {strategy_class.name} (v{strategy_class.version})")

    @classmethod
    def get_strategy_class(cls, name: str) -> Type[BaseStrategy]:
        """Retrieves a registered strategy class by name."""
        if not cls._registry:
            cls.discover_all()

        if name not in cls._registry:
            raise KeyError(f"Strategy '{name}' not found in registry. Discovered: {list(cls._registry.keys())}")
        return cls._registry[name]

    @classmethod
    def list_strategies(cls) -> List[Dict[str, str]]:
        """Returns metadata summary of all registered strategies."""
        if not cls._registry:
            cls.discover_all()

        result = []
        for name, cls_obj in cls._registry.items():
            result.append({
                "name": name,
                "version": getattr(cls_obj, "version", "1.0.0"),
                "timeframe": getattr(cls_obj, "timeframe", "5m"),
                "description": getattr(cls_obj, "description", ""),
            })
        return result

    @classmethod
    def discover_from_directory(cls, dir_path: Path):
        """Scans a directory for python modules defining BaseStrategy subclasses."""
        path = Path(dir_path)
        if not path.exists():
            return

        for py_file in path.glob("*.py"):
            if py_file.name.startswith("__") or py_file.name in ("base.py", "context.py", "registry.py"):
                continue

            module_name = f"dynamic_strat_{py_file.stem}"
            try:
                spec = importlib.util.spec_from_file_location(module_name, py_file)
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)

                    for attr_name in dir(mod):
                        attr = getattr(mod, attr_name)
                        if (
                            inspect.isclass(attr)
                            and issubclass(attr, BaseStrategy)
                            and attr is not BaseStrategy
                        ):
                            cls.register(attr)
            except Exception as e:
                logger.warning(f"Error loading strategy from {py_file}: {e}")

    @classmethod
    def discover_all(cls):
        """Discovers built-in and user-defined strategies."""
        # 1. Built-in strategies
        builtin_dir = Path(__file__).resolve().parent
        cls.discover_from_directory(builtin_dir)

        # 2. User strategies
        user_dir = settings.strategies_user_dir
        cls.discover_from_directory(user_dir)


# Auto-discover at module import
StrategyRegistry.discover_all()
