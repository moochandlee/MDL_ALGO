"""
Cross-asset and multi-asset strategies.

- Multi-Asset Trend Following (ETF 4.6)
- Sector Momentum Rotation with MA Filter (4.1.1)
- Index Volatility Targeting (6.5)
- Global Macro Momentum (19.2)
- Commodity Trend Following (9.1, 10.4)
"""

import numpy as np
import pandas as pd

from quant.strategies.base import Strategy, registry


class MultiAssetTrendFollowing(Strategy):
    """
    Section 4.6 — Multi-asset trend following.

    Apply trend-following across multiple asset classes.
    For a single ticker: multi-timeframe trend confirmation.
    """

    name = "Multi-Asset Trend Following"
    category = "trend"
    asset_classes = ["equity", "etf", "fx", "crypto"]
    paper_section = "4.6"
    description = "Multi-timeframe trend confirmation across fast/medium/slow"
    parameters = {"fast": 21, "medium": 63, "slow": 126}

    def generate_signals(self, data, **params):
        fast = params.get("fast", 21)
        medium = params.get("medium", 63)
        slow = params.get("slow", 126)
        close = data["close"]

        # Multi-timeframe trend
        sma_fast = close.rolling(fast).mean()
        sma_med = close.rolling(medium).mean()
        sma_slow = close.rolling(slow).mean()

        trend_up = (close > sma_fast) & (sma_fast > sma_med) & (sma_med > sma_slow)
        entries = trend_up & (~trend_up.shift(1).fillna(False))
        exits = ~trend_up & (trend_up.shift(1).fillna(False))
        return entries, exits

    def default_params(self):
        return {"fast": 21, "medium": 63, "slow": 126}


class SectorRotationMAFilter(Strategy):
    """
    Section 4.1.1 — Sector momentum rotation with MA filter.

    Momentum rotation with an absolute trend filter (must be above long MA).
    """

    name = "Sector Rotation with MA Filter"
    category = "momentum"
    asset_classes = ["equity", "etf"]
    paper_section = "4.1.1"
    description = "Momentum rotation with absolute trend filter (above MA = trade)"
    parameters = {"mom_period": 63, "ma_period": 200}

    def generate_signals(self, data, **params):
        mom_period = params.get("mom_period", 63)
        ma_period = params.get("ma_period", 200)
        close = data["close"]

        momentum = close.pct_change(mom_period)
        sma = close.rolling(ma_period).mean()
        above_ma = close > sma

        long_signal = (momentum > 0) & above_ma
        entries = long_signal & (~long_signal.shift(1).fillna(False))
        exits = ~long_signal & (long_signal.shift(1).fillna(False))
        return entries, exits

    def default_params(self):
        return {"mom_period": 63, "ma_period": 200}


class GlobalMacroMomentum(Strategy):
    """
    Section 19.2 — Fundamental macro momentum.

    Trades based on macroeconomic trends. Without actual macro data,
    uses long-horizon price trends as a macro proxy (currencies, bonds, equities
    all reflect macro conditions in their long-term trends).
    """

    name = "Global Macro Momentum"
    category = "trend"
    asset_classes = ["equity", "etf", "fx", "crypto"]
    paper_section = "19.2"
    description = "Long-horizon trend following (macro trend proxy)"
    parameters = {"macro_trend": 252, "signal_ma": 50}

    def generate_signals(self, data, **params):
        macro_trend = params.get("macro_trend", 252)
        signal_ma = params.get("signal_ma", 50)
        close = data["close"]

        # Long-term trend direction via slope of 252-day MA
        long_ma = close.rolling(macro_trend).mean()
        ma_slope = long_ma.diff(signal_ma)

        long_signal = (close > long_ma) & (ma_slope > 0)
        entries = long_signal & (~long_signal.shift(1).fillna(False))
        exits = ~long_signal & (long_signal.shift(1).fillna(False))
        return entries, exits

    def default_params(self):
        return {"macro_trend": 252, "signal_ma": 50}


class CommodityRollYield(Strategy):
    """
    Section 9.1 — Roll yield strategy.

    In commodity futures, roll yield is the return from rolling contracts.
    For equity/ETF proxy: use the spread between short-term and long-term
    price trends to approximate a term-structure signal.

    When short-term price > long-term price = backwardation proxy (positive roll).
    """

    name = "Commodity Roll Yield Proxy"
    category = "carry"
    asset_classes = ["equity", "etf", "fx"]
    paper_section = "9.1"
    description = "Roll yield proxy: trade the term structure of price trends"
    parameters = {"near_term": 20, "long_term": 120}

    def generate_signals(self, data, **params):
        near = params.get("near_term", 20)
        far = params.get("long_term", 120)
        close = data["close"]

        near_ma = close.rolling(near).mean()
        far_ma = close.rolling(far).mean()

        # Backwardation proxy: near-term > long-term price
        backwardation = near_ma > far_ma
        entries = backwardation & (~backwardation.shift(1).fillna(False))
        exits = ~backwardation & (backwardation.shift(1).fillna(False))
        return entries, exits

    def default_params(self):
        return {"near_term": 20, "long_term": 120}


class FuturesTrendFollowing(Strategy):
    """
    Section 10.4 — Futures trend following (momentum).

    Classic managed futures trend strategy: long when price > N-day high,
    short when price < N-day low. Uses a multi-timeframe filter.
    """

    name = "Futures Trend Following"
    category = "trend"
    asset_classes = ["equity", "etf", "fx", "crypto"]
    paper_section = "10.4"
    description = "Multi-timeframe breakout (managed futures style)"
    parameters = {"short_window": 20, "long_window": 50}

    def generate_signals(self, data, **params):
        short_w = params.get("short_window", 20)
        long_w = params.get("long_window", 50)
        close = data["close"]
        high = data.get("high", close)
        low = data.get("low", close)

        # Short-term channel
        upper_s = high.rolling(short_w).max().shift(1)
        lower_s = low.rolling(short_w).min().shift(1)

        # Long-term trend filter
        sma_long = close.rolling(long_w).mean()

        entries = (close > upper_s) & (close > sma_long)
        exits = (close < lower_s) | (close < sma_long)

        return entries, exits

    def default_params(self):
        return {"short_window": 20, "long_window": 50}


class DispersionTrading(Strategy):
    """
    Section 6.3 — Dispersion trading in equity indexes.

    Trade the spread between index volatility and constituent volatility.
    For single-ticker proxy: trade deviations of stock vol from index vol.
    Approximated as vol mean-reversion.
    """

    name = "Dispersion Trading"
    category = "volatility"
    asset_classes = ["equity", "etf"]
    paper_section = "6.3"
    description = "Vol dispersion proxy: trade when stock vol deviates from trend"
    parameters = {"vol_window": 21, "lookback": 252}

    def generate_signals(self, data, **params):
        vol_w = params.get("vol_window", 21)
        lookback = params.get("lookback", 252)
        close = data["close"]

        returns = np.log(close / close.shift(1))
        realized_vol = returns.rolling(vol_w).std() * np.sqrt(252)
        median_vol = realized_vol.rolling(lookback).median()
        vol_spread = realized_vol - median_vol

        # Enter when vol is elevated (dispersion wide) and reverting
        entries = (vol_spread > vol_spread.rolling(100).std().fillna(0)) & (
            vol_spread.diff(5) < 0
        )
        # Exit when vol normalizes
        exits = vol_spread < 0

        return entries, exits

    def default_params(self):
        return {"vol_window": 21, "lookback": 252}


# Register
for _cls in [MultiAssetTrendFollowing, SectorRotationMAFilter, GlobalMacroMomentum,
             CommodityRollYield, FuturesTrendFollowing, DispersionTrading]:
    registry.register(_cls)
