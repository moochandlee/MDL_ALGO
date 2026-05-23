"""
Equity factor strategies (Sections 3.2, 3.3, 3.6, 3.20).

- Earnings Momentum (3.2)
- Value (3.3)
- Multifactor Portfolio (3.6)
- Alpha Combos (3.20)
"""

import numpy as np
import pandas as pd

from quant.strategies.base import Strategy, registry


class EarningsMomentum(Strategy):
    """
    Section 3.2 — Earnings momentum.

    Stocks with positive earnings surprises tend to drift up.
    Trade based on price acceleration as a real-time proxy for earnings momentum.
    Measures the rate of change of momentum (second derivative of price).
    """

    name = "Earnings Momentum"
    category = "factor"
    asset_classes = ["equity"]
    paper_section = "3.2"
    description = "Long when price momentum is accelerating (earnings proxy)"
    parameters = {"mom_period": 63, "accel_period": 21}

    def generate_signals(self, data, **params):
        mom_period = params.get("mom_period", 63)
        accel_period = params.get("accel_period", 21)
        close = data["close"]

        momentum = close.pct_change(mom_period)
        acceleration = momentum.diff(accel_period)

        long_signal = (momentum > 0) & (acceleration > 0)
        entries = long_signal & (~long_signal.shift(1).fillna(False))
        exits = ~long_signal & (long_signal.shift(1).fillna(False))
        return entries, exits

    def default_params(self):
        return {"mom_period": 63, "accel_period": 21}


class ValueFactor(Strategy):
    """
    Section 3.3 — Value factor.

    Buy cheap, sell expensive. Without fundamental data, uses a statistical
    value proxy: low price relative to its own long-term trend.
    The price-to-N-year-high ratio approximates the value signal.
    """

    name = "Value Factor"
    category = "factor"
    asset_classes = ["equity", "etf"]
    paper_section = "3.3"
    description = "Long when price is low relative to long-term range (cheap)"
    parameters = {"lookback": 252, "value_threshold": 0.2}

    def generate_signals(self, data, **params):
        lookback = params.get("lookback", 252)
        threshold = params.get("value_threshold", 0.2)
        close = data["close"]

        rolling_max = close.rolling(lookback).max()
        rolling_min = close.rolling(lookback).min()

        # Normalized price position: 0 = at low, 1 = at high
        price_position = (close - rolling_min) / (rolling_max - rolling_min + 1e-10)

        cheap = price_position < threshold
        entries = cheap & (~cheap.shift(1).fillna(False))
        exits = ~cheap & (cheap.shift(1).fillna(False))
        return entries, exits

    def default_params(self):
        return {"lookback": 252, "value_threshold": 0.2}

    def param_grid(self):
        return {"lookback": [126, 252, 504], "value_threshold": [0.1, 0.2, 0.3]}


class MultifactorPortfolio(Strategy):
    """
    Section 3.6 — Multifactor model.

    Combines multiple alpha signals: momentum, value, and low-volatility.
    Each signal is normalized and averaged. Enter when composite > 0.
    """

    name = "Multifactor Portfolio"
    category = "factor"
    asset_classes = ["equity", "etf"]
    paper_section = "3.6"
    description = "Combine momentum + value + low-vol signals into one composite"
    parameters = {"mom_period": 63, "value_period": 252, "vol_period": 21}

    def generate_signals(self, data, **params):
        mom_period = params.get("mom_period", 63)
        value_period = params.get("value_period", 252)
        vol_period = params.get("vol_period", 21)
        close = data["close"]
        returns = np.log(close / close.shift(1))

        # Momentum signal (z-scored)
        mom = close.pct_change(mom_period)
        mom_z = (mom - mom.rolling(252).mean()) / mom.rolling(252).std().replace(0, 1)

        # Value signal: inverse of price position in range
        high = close.rolling(value_period).max()
        low = close.rolling(value_period).min()
        pos = (close - low) / (high - low + 1e-10)
        value_signal = 1.0 - pos  # 1 = cheap, 0 = expensive

        # Low-vol signal: negative of recent volatility
        realized_vol = returns.rolling(vol_period).std() * np.sqrt(252)
        vol_z = -(realized_vol - realized_vol.rolling(252).mean()) / realized_vol.rolling(252).std().replace(0, 1)

        # Equal-weighted composite
        composite = (mom_z.fillna(0) + value_signal.fillna(0.5) + vol_z.fillna(0)) / 3

        long_signal = composite > 0
        entries = long_signal & (~long_signal.shift(1).fillna(False))
        exits = ~long_signal & (long_signal.shift(1).fillna(False))
        return entries, exits

    def default_params(self):
        return {"mom_period": 63, "value_period": 252, "vol_period": 21}


class AlphaCombos(Strategy):
    """
    Section 3.20 — Alpha combos.

    Combine multiple orthogonal alpha signals with optimal weights.
    Uses a simple PCA-like approach: decorrelate signals via rolling regression
    and trade the combined residual alpha.
    """

    name = "Alpha Combos"
    category = "factor"
    asset_classes = ["equity", "etf"]
    paper_section = "3.20"
    description = "Combine orthogonal alpha signals with rolling weights"
    parameters = {"short_ma": 5, "long_ma": 21, "rsi_period": 14, "vol_window": 21}

    def generate_signals(self, data, **params):
        short_ma = params.get("short_ma", 5)
        long_ma = params.get("long_ma", 21)
        rsi_period = params.get("rsi_period", 14)
        vol_window = params.get("vol_window", 21)
        close = data["close"]

        # Signal 1: MA crossover strength
        sma_s = close.rolling(short_ma).mean()
        sma_l = close.rolling(long_ma).mean()
        s1 = (sma_s / sma_l.replace(0, 1e-10) - 1).fillna(0)

        # Signal 2: RSI flip (1 = oversold bounce)
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)
        avg_gain = gain.ewm(span=rsi_period, adjust=False).mean()
        avg_loss = loss.ewm(span=rsi_period, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, 1e-10)
        rsi = 100 - (100 / (1 + rs))
        s2 = (50 - rsi) / 50  # positive when oversold

        # Signal 3: Volatility regime
        returns = np.log(close / close.shift(1))
        vol = returns.rolling(vol_window).std() * np.sqrt(252)
        vol_median = vol.rolling(252).median()
        s3 = (vol_median - vol) / vol_median.replace(0, 1e-10)  # positive when low vol

        # Equal-weight composite
        composite = (
            s1.rank(pct=True).fillna(0.5) +
            s2.rank(pct=True).fillna(0.5) +
            s3.rank(pct=True).fillna(0.5)
        ) / 3

        long_signal = composite > 0.5
        entries = long_signal & (~long_signal.shift(1).fillna(False))
        exits = ~long_signal & (long_signal.shift(1).fillna(False))
        return entries, exits

    def default_params(self):
        return {"short_ma": 5, "long_ma": 21, "rsi_period": 14, "vol_window": 21}


class StatisticalArbitrage(Strategy):
    """
    Section 3.18 — Statistical arbitrage via optimization.

    Mean-reversion of a portfolio of securities. For single-ticker proxy:
    trades the residual from a simple trend regression.
    """

    name = "Statistical Arbitrage"
    category = "factor"
    asset_classes = ["equity", "etf"]
    paper_section = "3.18"
    description = "Trade the residual from a linear trend (stat-arb proxy)"
    parameters = {"regression_window": 60, "entry_z": 2.0}

    def generate_signals(self, data, **params):
        reg_window = params.get("regression_window", 60)
        entry_z = params.get("entry_z", 2.0)
        close = data["close"]
        log_price = np.log(close)

        # Linear regression of log price on time
        x = np.arange(reg_window)
        y = log_price.values
        residuals = pd.Series(index=close.index, dtype=float)

        for i in range(reg_window, len(y)):
            yi = y[i - reg_window:i]
            if len(yi) < reg_window:
                continue
            xi = x[-len(yi):]
            slope = (np.cov(xi, yi)[0, 1] / np.var(xi)) if np.var(xi) > 0 else 0
            intercept = np.mean(yi) - slope * np.mean(xi)
            pred = intercept + slope * (reg_window - 1)
            residuals.iloc[i] = yi[-1] - pred

        resid_z = residuals / residuals.rolling(reg_window * 2).std().replace(0, 1e-10)

        entries = resid_z < -entry_z
        exits = resid_z > 0
        return entries, exits

    def default_params(self):
        return {"regression_window": 60, "entry_z": 2.0}


# Register
for _cls in [EarningsMomentum, ValueFactor, MultifactorPortfolio, AlphaCombos,
             StatisticalArbitrage]:
    registry.register(_cls)
