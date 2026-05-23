"""
Strategy base class and registry for the 151 Trading Strategies framework.

Each strategy from the Kakushadze & Serur paper is a small subclass of Strategy.
The StrategyRegistry auto-discovers them and provides lookup by category,
asset class, and name.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd


@dataclass
class StrategyMeta:
    """Lightweight metadata for a strategy — can live without instantiating the class."""

    name: str
    category: str  # trend, momentum, mean_reversion, volatility, carry, etc.
    asset_classes: list[str]  # ["equity", "etf", "fx", "crypto"]
    paper_section: str = ""
    description: str = ""
    param_count: int = 0


class Strategy(ABC):
    """
    Abstract base for every trading strategy.

    Subclasses override ``generate_signals`` and set class-level metadata.
    """

    # Override these in subclasses
    name: str = ""
    category: str = ""
    asset_classes: list[str] = []
    paper_section: str = ""
    description: str = ""
    parameters: dict = {}

    @abstractmethod
    def generate_signals(
        self, data: pd.DataFrame, **params
    ) -> tuple[pd.Series, pd.Series]:
        """
        Return (entries, exits) boolean Series from OHLCV data.

        ``data`` must have columns: open, high, low, close, volume.
        Both returned Series share the same index as ``data``.
        True = enter/exit, False = no action.
        """
        ...

    def default_params(self) -> dict:
        """Return the default parameter values. Override to add parameter grids."""
        return {}

    def param_grid(self) -> dict:
        """
        Return parameter ranges for optimization.
        Default is empty — override to enable grid search.
        Example: {"short_window": [10, 20, 50], "long_window": [50, 100, 200]}
        """
        return {}

    @classmethod
    def to_meta(cls) -> StrategyMeta:
        return StrategyMeta(
            name=cls.name,
            category=cls.category,
            asset_classes=cls.asset_classes,
            paper_section=cls.paper_section,
            description=cls.description,
            param_count=len(cls.parameters),
        )


class StrategyRegistry:
    """
    Auto-discoverable registry for all Strategy subclasses.

    Usage::

        registry = StrategyRegistry()
        registry.discover()               # scans quant.strategies subpackages
        for s in registry.by_category("trend"):
            print(s.name)
    """

    def __init__(self):
        self._strategies: dict[str, type[Strategy]] = {}
        self._metas: dict[str, StrategyMeta] = {}

    def register(self, cls: type[Strategy]) -> None:
        key = cls.name
        self._strategies[key] = cls
        self._metas[key] = cls.to_meta()

    def discover(self) -> None:
        """Import all strategy subpackages so subclasses self-register."""
        import importlib

        for pkg in ("quant.strategies.equities", "quant.strategies.fx",
                     "quant.strategies.crypto", "quant.strategies.cross_asset"):
            try:
                importlib.import_module(pkg)
            except ImportError:
                pass

    def get(self, name: str) -> Optional[type[Strategy]]:
        return self._strategies.get(name)

    def list_all(self) -> list[StrategyMeta]:
        return sorted(self._metas.values(), key=lambda m: m.name)

    def by_category(self, category: str) -> list[StrategyMeta]:
        return [m for m in self._metas.values() if m.category == category]

    def by_asset_class(self, asset_class: str) -> list[StrategyMeta]:
        return [m for m in self._metas.values() if asset_class in m.asset_classes]

    @property
    def categories(self) -> list[str]:
        return sorted({m.category for m in self._metas.values()})

    @property
    def count(self) -> int:
        return len(self._strategies)

    def summary(self) -> str:
        lines = [f"{self.count} strategies registered"]
        for cat in self.categories:
            metas = self.by_category(cat)
            lines.append(f"  {cat}: {len(metas)}")
        return "\n".join(lines)


# Singleton
registry = StrategyRegistry()
