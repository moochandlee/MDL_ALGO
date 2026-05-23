"""
Equity momentum strategies (Sections 3.1, 3.7).

- Price Momentum / Time-Series Momentum (3.1)
- Residual Momentum (3.7)
- Dual Momentum (ETF 4.1.2)
"""

import numpy as np
import pandas as pd

from quant.strategies.base import Strategy, registry


class PriceMomentum(Strategy):
    """
    Section 3.1 — Time-series momentum.

    Buy when past N-period return is positive, sell when negative.
    Standard formulation: long the top momentum decile, short the bottom.
    For single-stock: go long when momentum > 0, exit when < 0.
    """

    name = "Price Momentum"
    category = "momentum"
    asset_classes = ["equity", "etf", "fx", "crypto"]
    paper_section = "3.1"
    description = "Buy when past N-day return is positive, sell when negative"
    parameters = {"lookback": 63, "skip_recent": 1}

    def generate_signals(self, data, **params):
        lookback = params.get("lookback", 63)
        skip = params.get("skip_recent", 1)
        close = data["close"]

        # Momentum = return over lookback period, excluding most recent skip days
        momentum = close.pct_change(lookback).shift(skip)
        entries = (momentum > 0) & (momentum.shift(1) <= 0)
        exits = (momentum < 0) & (momentum.shift(1) >= 0)
        return entries, exits

    def default_params(self):
        return {"lookback": 63, "skip_recent": 1}

    def param_grid(self):
        return {"lookback": [21, 63, 126, 252]}


class ResidualMomentum(Strategy):
    """
    Section 3.7 — Residual momentum.

    Regress stock returns on market returns; trade the residual (alpha) momentum.
    This removes the market beta component and trades only the idiosyncratic momentum.
    """

    name = "Residual Momentum"
    category = "momentum"
    asset_classes = ["equity", "etf"]
    paper_section = "3.7"
    description = "Momentum of residuals from market-beta regression"
    parameters = {"lookback": 63, "regression_window": 252}

    def generate_signals(self, data, **params):
        lookback = params.get("lookback", 63)
        reg_window = params.get("regression_window", 252)
        close = data["close"]

        # Keep full index; first value will be NaN
        returns = np.log(close / close.shift(1))

        # Market proxy: either provided market column or rolling mean as fallback
        if "market" in data.columns:
            market_returns = np.log(data["market"] / data["market"].shift(1))
        else:
            market_returns = returns.rolling(reg_window).mean()

        # Rolling beta: Cov(R, Rm) / Var(Rm), use raw returns (not dropna)
        cov = returns.rolling(reg_window).cov(market_returns)
        var_mkt = market_returns.rolling(reg_window).var()
        beta = cov / var_mkt.replace(0, 1e-10)

        # Residual return = actual - beta * market
        residual = returns - beta * market_returns

        # Momentum of residuals
        res_mom = residual.rolling(lookback).sum()
        entries = (res_mom > 0) & (res_mom.shift(1) <= 0)
        exits = (res_mom < 0) & (res_mom.shift(1) >= 0)
        return entries, exits

    def default_params(self):
        return {"lookback": 63, "regression_window": 252}


class DualMomentum(Strategy):
    """
    ETF Section 4.1.2 — Dual momentum.

    Compares absolute momentum (vs T-bills) and relative momentum (vs other assets).
    For a single asset: if the asset's return > risk-free and its return > average,
    be long. Otherwise flat.
    """

    name = "Dual Momentum"
    category = "momentum"
    asset_classes = ["equity", "etf"]
    paper_section = "4.1.2"
    description = "Absolute + relative momentum: long only when both positive"
    parameters = {"lookback": 63, "risk_free_annual": 0.03}

    def generate_signals(self, data, **params):
        lookback = params.get("lookback", 63)
        rf_annual = params.get("risk_free_annual", 0.03)
        rf_daily = rf_annual / 252
        close = data["close"]

        mom = close.pct_change(lookback)
        abs_mom = mom - rf_daily * lookback  # absolute momentum vs risk-free

        # Relative momentum: compare to own longer average
        rel_mom = mom - mom.rolling(lookback * 2).mean()

        long_signal = (abs_mom > 0) & (rel_mom > 0)
        entries = long_signal & (~long_signal.shift(1).fillna(False))
        exits = ~long_signal & (long_signal.shift(1).fillna(False))
        return entries, exits

    def default_params(self):
        return {"lookback": 63, "risk_free_annual": 0.03}


class SectorMomentumRotation(Strategy):
    """
    ETF Section 4.1 — Sector momentum rotation.

    For single-ticker implementation: go long when this ticker's momentum
    exceeds a threshold relative to its own history. In multi-asset form, this
    would pick the top-N sector ETFs each month.
    """

    name = "Sector Momentum Rotation"
    category = "momentum"
    asset_classes = ["equity", "etf"]
    paper_section = "4.1"
    description = "Long when momentum exceeds historical median momentum"
    parameters = {"lookback": 63, "percentile": 50}

    def generate_signals(self, data, **params):
        lookback = params.get("lookback", 63)
        pct = params.get("percentile", 50)
        close = data["close"]

        mom = close.pct_change(lookback)
        # Rolling median of momentum values
        median_mom = mom.rolling(252).median()

        long_signal = mom > (median_mom * pct / 50.0)
        entries = long_signal & (~long_signal.shift(1).fillna(False))
        exits = ~long_signal & (long_signal.shift(1).fillna(False))
        return entries, exits

    def default_params(self):
        return {"lookback": 63, "percentile": 50}


# Register
for _cls in [PriceMomentum, ResidualMomentum, DualMomentum, SectorMomentumRotation]:
    registry.register(_cls)
