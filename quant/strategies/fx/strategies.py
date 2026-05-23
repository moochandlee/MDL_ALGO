"""
FX strategies (Section 8).

- Moving Averages with HP Filter (8.1)
- Carry Trade (8.2)
- Dollar Carry Trade (8.3)
- Momentum & Carry Combo (8.4)
- Triangular Arbitrage (8.5)
"""

import numpy as np
import pandas as pd

from quant.strategies.base import Strategy, registry


class HPFilterMA(Strategy):
    """
    Section 8.1 — Moving averages with Hodrick-Prescott filter.

    The HP filter extracts the trend component from the price series.
    Trade crossovers of the HP trend.

    For simplicity, uses an exponential smoothing approximation to the HP filter.
    """

    name = "FX HP Filter MA"
    category = "trend"
    asset_classes = ["fx", "crypto"]
    paper_section = "8.1"
    description = "Trade crossovers of the HP-filtered trend (FX optimized)"
    parameters = {"smooth": 100, "ma_period": 20}

    def generate_signals(self, data, **params):
        smooth = params.get("smooth", 100)
        ma_period = params.get("ma_period", 20)
        close = data["close"]

        # HP filter approximation: double exponential smoothing
        trend = close.ewm(span=smooth, adjust=False).mean()

        # Trade when price crosses the smoothed trend
        entries = (close > trend) & (close.shift(1) <= trend.shift(1))
        exits = (close < trend) & (close.shift(1) >= trend.shift(1))
        return entries, exits

    def default_params(self):
        return {"smooth": 100, "ma_period": 20}


class CarryTrade(Strategy):
    """
    Section 8.2 — FX Carry trade.

    Buy high-yield currencies, sell low-yield currencies.
    Without actual interest rate data, this uses price momentum as a proxy
    (currencies with positive carry tend to appreciate gradually).

    A better proxy: the ratio of the FX pair to its long-term mean.
    Currencies trading above long-term average are "carry-positive".
    """

    name = "FX Carry Trade"
    category = "carry"
    asset_classes = ["fx"]
    paper_section = "8.2"
    description = "Long carry proxy: enter when price trend is positive (carry proxy)"
    parameters = {"trend_period": 63, "entry_threshold": 0.005}

    def generate_signals(self, data, **params):
        trend_period = params.get("trend_period", 63)
        threshold = params.get("entry_threshold", 0.005)
        close = data["close"]

        # Carry proxy: rolling return (positive = positive carry expectation)
        carry_proxy = close.pct_change(trend_period)

        entries = carry_proxy > threshold
        exits = carry_proxy < -threshold
        return entries, exits

    def default_params(self):
        return {"trend_period": 63, "entry_threshold": 0.005}


class DollarCarryTrade(Strategy):
    """
    Section 8.3 — Dollar carry trade.

    The USD leg of the carry trade. When USD rates are high relative to other
    currencies, go long USD. Uses the trend of the pair as a carry direction proxy.
    """

    name = "Dollar Carry Trade"
    category = "carry"
    asset_classes = ["fx"]
    paper_section = "8.3"
    description = "Trade based on USD carry advantage (trend + vol filter)"
    parameters = {"trend_period": 126, "vol_filter": True}

    def generate_signals(self, data, **params):
        trend_period = params.get("trend_period", 126)
        vol_filter = params.get("vol_filter", True)
        close = data["close"]

        returns = np.log(close / close.shift(1))
        carry_signal = close.pct_change(trend_period)

        if vol_filter:
            vol = returns.rolling(21).std() * np.sqrt(252)
            vol_ok = vol < vol.rolling(252).median()
        else:
            vol_ok = pd.Series(True, index=close.index)

        long_signal = (carry_signal > 0) & vol_ok
        entries = long_signal & (~long_signal.shift(1).fillna(False))
        exits = ~long_signal & (long_signal.shift(1).fillna(False))
        return entries, exits

    def default_params(self):
        return {"trend_period": 126, "vol_filter": True}


class MomentumCarryCombo(Strategy):
    """
    Section 8.4 — Momentum & carry combo.

    Combines momentum and carry signals. Enter when both agree.
    This is a classic FX strategy that avoids the crashes of pure carry.
    """

    name = "FX Momentum & Carry Combo"
    category = "carry"
    asset_classes = ["fx"]
    paper_section = "8.4"
    description = "Long only when both momentum AND carry signals are positive"
    parameters = {"mom_period": 21, "carry_period": 63}

    def generate_signals(self, data, **params):
        mom_period = params.get("mom_period", 21)
        carry_period = params.get("carry_period", 63)
        close = data["close"]

        momentum = close.pct_change(mom_period)
        carry = close.pct_change(carry_period)

        both_positive = (momentum > 0) & (carry > 0)
        entries = both_positive & (~both_positive.shift(1).fillna(False))
        # Exit when either momentum or carry turns negative
        either_negative = (momentum <= 0) | (carry <= 0)
        exits = either_negative & (~either_negative.shift(1).fillna(False))
        return entries, exits

    def default_params(self):
        return {"mom_period": 21, "carry_period": 63}


class TriangularArbitrage(Strategy):
    """
    Section 8.5 — FX triangular arbitrage.

    Exploits pricing inconsistencies across three currency pairs.
    For a single pair proxy: detects price dislocations from fair value
    using rolling regression against two related pairs.

    As a single-pair approximation: trade reversion of the pair to its
    implied cross rate based on rolling correlations.
    """

    name = "FX Triangular Arbitrage"
    category = "mean_reversion"
    asset_classes = ["fx"]
    paper_section = "8.5"
    description = "Trade reversion to implied fair value (triangular arb proxy)"
    parameters = {"lookback": 30, "z_entry": 2.5}

    def generate_signals(self, data, **params):
        lookback = params.get("lookback", 30)
        z_entry = params.get("z_entry", 2.5)
        close = data["close"]
        log_price = np.log(close)

        # Fair value: exponentially weighted moving average
        fair = log_price.ewm(span=lookback * 3, adjust=False).mean()
        deviation = log_price - fair
        dev_vol = deviation.rolling(lookback).std().replace(0, 1e-10)
        z_score = deviation / dev_vol

        entries = z_score < -z_entry
        exits = z_score > 0
        return entries, exits

    def default_params(self):
        return {"lookback": 30, "z_entry": 2.5}


# Register
for _cls in [HPFilterMA, CarryTrade, DollarCarryTrade, MomentumCarryCombo,
             TriangularArbitrage]:
    registry.register(_cls)
