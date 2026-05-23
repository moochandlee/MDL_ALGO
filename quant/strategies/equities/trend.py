"""
Equity trend-following strategies (Section 3.11-3.15).

- Single Moving Average (3.11)
- Two Moving Averages (3.12)
- Three Moving Averages (3.13)
- Support and Resistance (3.14)
- Channel / Donchian breakout (3.15)
"""

import numpy as np
import pandas as pd

from quant.strategies.base import Strategy, registry


class SingleMovingAverage(Strategy):
    """Section 3.11 — Buy when close crosses above MA, sell when below."""

    name = "Single Moving Average"
    category = "trend"
    asset_classes = ["equity", "etf", "fx", "crypto"]
    paper_section = "3.11"
    description = "Long when close > SMA(period), flat otherwise"
    parameters = {"period": 50}

    def generate_signals(self, data, **params):
        period = params.get("period", 50)
        close = data["close"]
        sma = close.rolling(period).mean()
        entries = (close > sma) & (close.shift(1) <= sma.shift(1))
        exits = (close < sma) & (close.shift(1) >= sma.shift(1))
        return entries, exits

    def default_params(self):
        return {"period": 50}

    def param_grid(self):
        return {"period": [10, 20, 50, 100, 200]}


class TwoMovingAverages(Strategy):
    """Section 3.12 — Buy when fast MA crosses above slow MA."""

    name = "Two Moving Averages"
    category = "trend"
    asset_classes = ["equity", "etf", "fx", "crypto"]
    paper_section = "3.12"
    description = "Long when fast SMA > slow SMA (golden cross)"
    parameters = {"fast": 20, "slow": 50}

    def generate_signals(self, data, **params):
        fast = params.get("fast", 20)
        slow = params.get("slow", 50)
        close = data["close"]
        fast_ma = close.rolling(fast).mean()
        slow_ma = close.rolling(slow).mean()
        entries = (fast_ma > slow_ma) & (fast_ma.shift(1) <= slow_ma.shift(1))
        exits = (fast_ma < slow_ma) & (fast_ma.shift(1) >= slow_ma.shift(1))
        return entries, exits

    def default_params(self):
        return {"fast": 20, "slow": 50}

    def param_grid(self):
        return {
            "fast": [5, 10, 20, 50],
            "slow": [20, 50, 100, 200],
        }


class ThreeMovingAverages(Strategy):
    """Section 3.13 — Triple MA system: fast > mid > slow = long."""

    name = "Three Moving Averages"
    category = "trend"
    asset_classes = ["equity", "etf", "fx", "crypto"]
    paper_section = "3.13"
    description = "Long when short > mid > long SMA, exit when short < long"
    parameters = {"short": 10, "mid": 20, "long": 50}

    def generate_signals(self, data, **params):
        s = params.get("short", 10)
        m = params.get("mid", 20)
        l = params.get("long", 50)
        close = data["close"]
        sma_s = close.rolling(s).mean()
        sma_m = close.rolling(m).mean()
        sma_l = close.rolling(l).mean()

        aligned = (sma_s > sma_m) & (sma_m > sma_l)
        entries = aligned & (~aligned.shift(1).fillna(False))
        exits = ~aligned & (aligned.shift(1).fillna(False))
        return entries, exits

    def default_params(self):
        return {"short": 10, "mid": 20, "long": 50}


class SupportResistance(Strategy):
    """Section 3.14 — Use rolling highs/lows as support/resistance levels."""

    name = "Support and Resistance"
    category = "trend"
    asset_classes = ["equity", "etf", "fx", "crypto"]
    paper_section = "3.14"
    description = "Buy near support (rolling low), sell near resistance (rolling high)"
    parameters = {"lookback": 20, "threshold": 0.02}

    def generate_signals(self, data, **params):
        lookback = params.get("lookback", 20)
        threshold = params.get("threshold", 0.02)
        close = data["close"]
        high = data.get("high", close)
        low = data.get("low", close)

        resistance = high.rolling(lookback).max()
        support = low.rolling(lookback).min()

        near_support = (close - support) / support < threshold
        near_resistance = (resistance - close) / close < threshold

        entries = near_support & (~near_support.shift(1).fillna(False))
        exits = near_resistance & (~near_resistance.shift(1).fillna(False))
        return entries, exits

    def default_params(self):
        return {"lookback": 20, "threshold": 0.02}


class ChannelBreakout(Strategy):
    """Section 3.15 — Donchian channel: buy at new high, sell at new low."""

    name = "Channel Breakout"
    category = "trend"
    asset_classes = ["equity", "etf", "fx", "crypto"]
    paper_section = "3.15"
    description = "Buy on n-day high breakout, exit on n-day low breakdown"
    parameters = {"period": 20}

    def generate_signals(self, data, **params):
        period = params.get("period", 20)
        close = data["close"]
        high = data.get("high", close)
        low = data.get("low", close)

        upper = high.rolling(period).max().shift(1)
        lower = low.rolling(period).min().shift(1)

        entries = close > upper
        exits = close < lower
        return entries, exits

    def default_params(self):
        return {"period": 20}

    def param_grid(self):
        return {"period": [10, 20, 50, 100]}


# Register all
for _cls in [SingleMovingAverage, TwoMovingAverages, ThreeMovingAverages,
             SupportResistance, ChannelBreakout]:
    registry.register(_cls)
