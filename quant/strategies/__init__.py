"""
quant.strategies — 151 Trading Strategies from Kakushadze & Serur (SSRN 3247865).

Usage::

    from quant.strategies import registry
    registry.discover()
    print(registry.summary())
"""

from quant.strategies.base import Strategy, StrategyMeta, StrategyRegistry, registry

__all__ = ["Strategy", "StrategyMeta", "StrategyRegistry", "registry"]
