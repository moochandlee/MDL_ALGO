"""
Equity mean-reversion strategies (Sections 3.8-3.10).

- Pairs Trading (3.8)
- Mean-Reversion – Single Cluster (3.9)
- Mean-Reversion – Weighted Regression (3.10)
- ETF Mean-Reversion (4.4)
"""

import numpy as np
import pandas as pd

from quant.strategies.base import Strategy, registry


class BollingerBands(Strategy):
    """
    Classic Bollinger Band mean-reversion.

    Buy when price touches/crosses below lower band.
    Sell when price touches/crosses above upper band.
    Uses 2-sigma bands by default.
    """

    name = "Bollinger Bands"
    category = "mean_reversion"
    asset_classes = ["equity", "etf", "fx", "crypto"]
    paper_section = "3.9"
    description = "Buy at lower band (oversold), sell at upper band (overbought)"
    parameters = {"period": 20, "num_std": 2.0}

    def generate_signals(self, data, **params):
        period = params.get("period", 20)
        num_std = params.get("num_std", 2.0)
        close = data["close"]

        sma = close.rolling(period).mean()
        std = close.rolling(period).std(ddof=1)
        upper = sma + num_std * std
        lower = sma - num_std * std

        entries = close < lower
        exits = close > upper
        return entries, exits

    def default_params(self):
        return {"period": 20, "num_std": 2.0}

    def param_grid(self):
        return {"period": [10, 20, 50], "num_std": [1.5, 2.0, 2.5]}


class RSIMeanReversion(Strategy):
    """
    RSI-based mean-reversion.

    Buy when RSI crosses above oversold threshold (30).
    Sell when RSI crosses below overbought threshold (70).
    """

    name = "RSI Mean Reversion"
    category = "mean_reversion"
    asset_classes = ["equity", "etf", "fx", "crypto"]
    paper_section = "3.9"
    description = "Buy when RSI < oversold, sell when RSI > overbought"
    parameters = {"period": 14, "oversold": 30, "overbought": 70}

    def generate_signals(self, data, **params):
        period = params.get("period", 14)
        oversold = params.get("oversold", 30)
        overbought = params.get("overbought", 70)
        close = data["close"]

        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)
        avg_gain = gain.ewm(span=period, adjust=False).mean()
        avg_loss = loss.ewm(span=period, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, 1e-10)
        rsi = 100 - (100 / (1 + rs))

        entries = (rsi < oversold) & (rsi.shift(1) >= oversold)
        exits = (rsi > overbought) & (rsi.shift(1) <= overbought)
        return entries, exits

    def default_params(self):
        return {"period": 14, "oversold": 30, "overbought": 70}


class PairsTrading(Strategy):
    """
    Section 3.8 — Pairs trading.

    Requires two price series in data: "close" (primary) and "pair" (secondary).
    Trades the spread z-score mean-reversion.

    When run on a single ticker without a pair column, uses the close series
    against its own rolling mean as a proxy.
    """

    name = "Pairs Trading"
    category = "mean_reversion"
    asset_classes = ["equity", "etf"]
    paper_section = "3.8"
    description = "Trade spread reversion between two correlated assets"
    parameters = {"lookback": 60, "entry_z": 2.0, "exit_z": 0.0}

    def generate_signals(self, data, **params):
        lookback = params.get("lookback", 60)
        entry_z = params.get("entry_z", 2.0)
        exit_z = params.get("exit_z", 0.0)
        close = data["close"]

        if "pair" in data.columns:
            # True pairs: compute spread
            ratio = close / data["pair"]
        else:
            # Proxy: deviation from rolling mean
            ratio = close / close.rolling(lookback * 2).mean()

        spread_mean = ratio.rolling(lookback).mean()
        spread_std = ratio.rolling(lookback).std(ddof=1)
        z_score = (ratio - spread_mean) / spread_std.replace(0, 1e-10)

        entries = z_score < -entry_z
        exits = z_score > exit_z
        return entries, exits

    def default_params(self):
        return {"lookback": 60, "entry_z": 2.0, "exit_z": 0.0}


class MeanReversionSingleCluster(Strategy):
    """
    Section 3.9 — Mean-reversion in a single cluster.

    Assets are grouped into clusters (e.g., by sector). Within each cluster,
    buy underperformers and sell outperformers, expecting reversion.

    For a single ticker: reversion relative to its own smoothed trend.
    """

    name = "Mean Reversion Single Cluster"
    category = "mean_reversion"
    asset_classes = ["equity", "etf"]
    paper_section = "3.9"
    description = "Buy when significantly below smoothed trend, sell when above"
    parameters = {"smooth_period": 50, "threshold_std": 2.0}

    def generate_signals(self, data, **params):
        smooth = params.get("smooth_period", 50)
        threshold = params.get("threshold_std", 2.0)
        close = data["close"]

        # Smoothed trend (exponential)
        trend = close.ewm(span=smooth, adjust=False).mean()
        deviation = (close - trend) / trend.replace(0, 1e-10)
        dev_std = deviation.rolling(smooth * 5).std().fillna(deviation.std())

        z_dev = deviation / dev_std.replace(0, 1e-10)

        entries = z_dev < -threshold
        exits = z_dev > threshold
        return entries, exits

    def default_params(self):
        return {"smooth_period": 50, "threshold_std": 2.0}


class WeightedRegressionReversion(Strategy):
    """
    Section 3.10 — Mean-reversion with weighted regression.

    Uses exponentially weighted regression to estimate the fair value trend
    and trades deviations from it. More emphasis on recent observations.
    """

    name = "Weighted Regression Reversion"
    category = "mean_reversion"
    asset_classes = ["equity", "etf", "fx"]
    paper_section = "3.10"
    description = "Trade reversion to exponentially-weighted fair value trend"
    parameters = {"half_life": 21, "entry_z": 2.0}

    def generate_signals(self, data, **params):
        half_life = params.get("half_life", 21)
        entry_z = params.get("entry_z", 2.0)
        close = data["close"]

        # EWMA as a simple exponentially-weighted fair value
        fair_value = close.ewm(halflife=half_life, adjust=False).mean()
        residual = close - fair_value
        resid_std = residual.rolling(half_life * 5).std().fillna(residual.std())
        z_score = residual / resid_std.replace(0, 1e-10)

        entries = z_score < -entry_z
        exits = z_score > 0
        return entries, exits

    def default_params(self):
        return {"half_life": 21, "entry_z": 2.0}


class MeanReversionETF(Strategy):
    """
    Section 4.4 — ETF mean-reversion.

    ETFs tend to mean-revert faster than individual stocks. Uses short-term
    RSI plus a persistence filter.
    """

    name = "ETF Mean Reversion"
    category = "mean_reversion"
    asset_classes = ["etf"]
    paper_section = "4.4"
    description = "Short-term mean-reversion, optimized for ETFs"
    parameters = {"rsi_period": 5, "oversold": 25, "overbought": 75}

    def generate_signals(self, data, **params):
        rsi_period = params.get("rsi_period", 5)
        oversold = params.get("oversold", 25)
        overbought = params.get("overbought", 75)
        close = data["close"]

        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)
        avg_gain = gain.ewm(span=rsi_period, adjust=False).mean()
        avg_loss = loss.ewm(span=rsi_period, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, 1e-10)
        rsi = 100 - (100 / (1 + rs))

        entries = (rsi < oversold) & (rsi.shift(1) >= oversold)
        exits = (rsi > overbought) & (rsi.shift(1) <= overbought)
        return entries, exits

    def default_params(self):
        return {"rsi_period": 5, "oversold": 25, "overbought": 75}


# Register all
for _cls in [BollingerBands, RSIMeanReversion, PairsTrading,
             MeanReversionSingleCluster, WeightedRegressionReversion,
             MeanReversionETF]:
    registry.register(_cls)
