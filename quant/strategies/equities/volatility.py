"""
Equity volatility strategies (Sections 3.4-3.5, 6.5, 7.4).

- Low-Volatility Anomaly (3.4)
- Implied Volatility Signal (3.5)
- Volatility Targeting (6.5)
- Volatility Risk Premium (7.4)
"""

import numpy as np
import pandas as pd

from quant.strategies.base import Strategy, registry


class LowVolatilityAnomaly(Strategy):
    """
    Section 3.4 — Low-volatility anomaly.

    Low-volatility stocks outperform on a risk-adjusted basis.
    Trade the signal: allocate more when realized vol is low,
    reduce when vol spikes.

    For a single ticker: go long when trailing vol < historical median,
    exit when vol spikes above median.
    """

    name = "Low Volatility Anomaly"
    category = "volatility"
    asset_classes = ["equity", "etf"]
    paper_section = "3.4"
    description = "Long when trailing volatility is below historical median"
    parameters = {"vol_window": 21, "median_window": 252}

    def generate_signals(self, data, **params):
        vol_window = params.get("vol_window", 21)
        median_window = params.get("median_window", 252)
        close = data["close"]

        returns = np.log(close / close.shift(1))
        realized_vol = returns.rolling(vol_window).std() * np.sqrt(252)
        median_vol = realized_vol.rolling(median_window).median()

        low_vol = realized_vol < median_vol
        entries = low_vol & (~low_vol.shift(1).fillna(False))
        exits = ~low_vol & (low_vol.shift(1).fillna(False))
        return entries, exits

    def default_params(self):
        return {"vol_window": 21, "median_window": 252}


class VolatilityTargeting(Strategy):
    """
    Section 6.5 — Volatility targeting.

    Size positions inversely to trailing volatility to maintain a target vol.
    Signal: entry when the scaled position is above a minimum, exit when below.

    This generates entry/exit signals from the allocation ratio.
    """

    name = "Volatility Targeting"
    category = "volatility"
    asset_classes = ["equity", "etf", "fx", "crypto"]
    paper_section = "6.5"
    description = "Scale positions to maintain constant portfolio volatility"
    parameters = {"target_vol": 0.15, "vol_window": 21, "min_allocation": 0.1}

    def generate_signals(self, data, **params):
        target_vol = params.get("target_vol", 0.15)
        vol_window = params.get("vol_window", 21)
        min_alloc = params.get("min_allocation", 0.1)
        close = data["close"]

        returns = np.log(close / close.shift(1))
        realized_vol = returns.rolling(vol_window).std() * np.sqrt(252)
        allocation = target_vol / realized_vol.replace(0, 1e-10)
        allocation = allocation.clip(upper=2.0)

        long_signal = allocation > min_alloc
        entries = long_signal & (~long_signal.shift(1).fillna(False))
        exits = ~long_signal & (long_signal.shift(1).fillna(False))
        return entries, exits

    def default_params(self):
        return {"target_vol": 0.15, "vol_window": 21, "min_allocation": 0.1}


class VolatilityRiskPremium(Strategy):
    """
    Section 7.4 — Volatility risk premium.

    Implied volatility tends to exceed realized volatility (the vol risk premium).
    When the spread between implied and realized vol is wide, collect the premium
    by being short volatility / long the underlying.

    For a single ticker using only price data: trades based on the spread between
    short-term and long-term realized volatility as a proxy.
    """

    name = "Volatility Risk Premium"
    category = "volatility"
    asset_classes = ["equity", "etf"]
    paper_section = "7.4"
    description = "Long when short-term vol << long-term vol (vol premium exists)"
    parameters = {"short_vol_window": 10, "long_vol_window": 63}

    def generate_signals(self, data, **params):
        short_w = params.get("short_vol_window", 10)
        long_w = params.get("long_vol_window", 63)
        close = data["close"]

        returns = np.log(close / close.shift(1))
        short_vol = returns.rolling(short_w).std() * np.sqrt(252)
        long_vol = returns.rolling(long_w).std() * np.sqrt(252)

        # Vol premium proxy: short-term vol is low relative to long-term
        vol_ratio = short_vol / long_vol.replace(0, 1e-10)
        premium_exists = vol_ratio < 0.7

        entries = premium_exists & (~premium_exists.shift(1).fillna(False))
        exits = ~premium_exists & (premium_exists.shift(1).fillna(False))
        return entries, exits

    def default_params(self):
        return {"short_vol_window": 10, "long_vol_window": 63}


class GARCHVolatilityStrategy(Strategy):
    """
    GARCH(1,1) volatility forecast for regime detection.

    Uses a simple exponential GARCH proxy: if forecasted vol is rising,
    reduce risk. If falling, increase. Entry when vol regime is declining.
    """

    name = "GARCH Volatility Strategy"
    category = "volatility"
    asset_classes = ["equity", "etf", "fx", "crypto"]
    paper_section = "3.5"
    description = "Use GARCH-like vol forecast: enter when vol is declining"
    parameters = {"vol_window": 21, "trend_window": 10}

    def generate_signals(self, data, **params):
        vol_window = params.get("vol_window", 21)
        trend_window = params.get("trend_window", 10)
        close = data["close"]

        returns = np.log(close / close.shift(1))
        # Simple GARCH(1,1) proxy using EWMA volatility
        ewma_vol = returns.pow(2).ewm(span=vol_window).mean().pow(0.5) * np.sqrt(252)

        # Vol trend: is vol declining?
        vol_trend = ewma_vol.diff(trend_window)

        long_signal = vol_trend < 0
        entries = long_signal & (~long_signal.shift(1).fillna(False))
        exits = ~long_signal & (long_signal.shift(1).fillna(False))
        return entries, exits

    def default_params(self):
        return {"vol_window": 21, "trend_window": 10}


# Register
for _cls in [LowVolatilityAnomaly, VolatilityTargeting, VolatilityRiskPremium,
             GARCHVolatilityStrategy]:
    registry.register(_cls)
