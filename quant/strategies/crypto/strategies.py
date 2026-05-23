"""
Crypto strategies (Section 18).

- Artificial Neural Network (18.2)
- Sentiment Analysis – Naive Bayes Bernoulli (18.3)
- Plus additional crypto-native strategies.
"""

import numpy as np
import pandas as pd

from quant.strategies.base import Strategy, registry


class CryptoANN(Strategy):
    """
    Section 18.2 — Artificial neural network for crypto.

    A simple perceptron-like signal: combine multiple normalized features
    (momentum, volatility, volume trend, RSI) with learned-like weights.
    """

    name = "Crypto ANN"
    category = "momentum"
    asset_classes = ["crypto"]
    paper_section = "18.2"
    description = "Combine multiple features with ANN-like weights for crypto"
    parameters = {
        "mom_fast": 7, "mom_slow": 30,
        "vol_window": 14, "rsi_period": 14,
    }

    def generate_signals(self, data, **params):
        fast = params.get("mom_fast", 7)
        slow = params.get("mom_slow", 30)
        vol_w = params.get("vol_window", 14)
        rsi_p = params.get("rsi_period", 14)
        close = data["close"]
        volume = data.get("volume", pd.Series(1, index=close.index))

        # Feature 1: Fast momentum
        f1 = close.pct_change(fast).rank(pct=True).fillna(0.5)

        # Feature 2: Slow momentum
        f2 = close.pct_change(slow).rank(pct=True).fillna(0.5)

        # Feature 3: Volatility regime (low vol = bullish for crypto)
        returns = np.log(close / close.shift(1))
        vol = returns.rolling(vol_w).std() * np.sqrt(365)
        f3 = (1 - vol.rank(pct=True)).fillna(0.5)

        # Feature 4: RSI
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)
        avg_gain = gain.ewm(span=rsi_p, adjust=False).mean()
        avg_loss = loss.ewm(span=rsi_p, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, 1e-10)
        rsi = 100 - (100 / (1 + rs))
        f4 = ((50 - rsi) / 50 + 1) / 2  # normalize to ~[0,1]

        # Feature 5: Volume trend (rising volume confirms trend)
        vol_ma = volume.rolling(vol_w).mean()
        vol_ratio = volume / vol_ma.replace(0, 1)
        vol_trend = vol_ratio.rolling(slow).mean().rank(pct=True).fillna(0.5)
        f5 = vol_trend

        # Combine with "learned" weights (approximation of ANN output)
        weights = np.array([0.30, 0.20, 0.15, 0.15, 0.20])
        composite = (
            weights[0] * f1 + weights[1] * f2 + weights[2] * f3 +
            weights[3] * f4 + weights[4] * f5
        )

        long_signal = composite > composite.rolling(100).median().fillna(0.5)
        entries = long_signal & (~long_signal.shift(1).fillna(False))
        exits = ~long_signal & (long_signal.shift(1).fillna(False))
        return entries, exits

    def default_params(self):
        return {"mom_fast": 7, "mom_slow": 30, "vol_window": 14, "rsi_period": 14}


class CryptoSentiment(Strategy):
    """
    Section 18.3 — Sentiment analysis with naive Bayes.

    Proxies sentiment via price-based indicators that correlate with
    retail sentiment in crypto markets.
    """

    name = "Crypto Sentiment"
    category = "momentum"
    asset_classes = ["crypto"]
    paper_section = "18.3"
    description = "Trade based on price-action sentiment proxies"
    parameters = {"sentiment_period": 14, "extreme_threshold": 0.7}

    def generate_signals(self, data, **params):
        period = params.get("sentiment_period", 14)
        threshold = params.get("extreme_threshold", 0.7)
        close = data["close"]
        high = data.get("high", close)
        low = data.get("low", close)

        # Sentiment proxies:
        # 1. Close relative to range (where in the day's range did we close?)
        day_range = high - low
        close_pos = (close - low) / day_range.replace(0, 1e-10)
        avg_close_pos = close_pos.rolling(period).mean()

        # 2. Price relative to recent high (how far from peak?)
        recent_high = high.rolling(period).max()
        drawdown_from_high = (close - recent_high) / recent_high.replace(0, 1e-10)

        # 3. Up-day ratio
        up_days = (close.diff() > 0).astype(float)
        up_ratio = up_days.rolling(period).sum() / period

        # Composite sentiment
        sentiment = (
            0.4 * avg_close_pos.fillna(0.5) +
            0.3 * up_ratio.fillna(0.5) +
            0.3 * (1 + drawdown_from_high).clip(0, 1).fillna(0.5)
        )

        entries = sentiment < (1 - threshold)
        exits = sentiment > threshold
        return entries, exits

    def default_params(self):
        return {"sentiment_period": 14, "extreme_threshold": 0.7}


class CryptoMomentumReversal(Strategy):
    """
    Crypto-specific: short-term momentum combined with overbought/oversold reversal.

    Crypto markets show both momentum (trending) and sharp reversals.
    This strategy uses fast momentum for direction but flips when RSI is extreme.
    """

    name = "Crypto Momentum-Reversal"
    category = "momentum"
    asset_classes = ["crypto"]
    paper_section = "18.2"
    description = "Momentum with RSI reversal filter (crypto-optimized)"
    parameters = {"mom_period": 14, "rsi_period": 7, "rsi_low": 20, "rsi_high": 80}

    def generate_signals(self, data, **params):
        mom_p = params.get("mom_period", 14)
        rsi_p = params.get("rsi_period", 7)
        rsi_low = params.get("rsi_low", 20)
        rsi_high = params.get("rsi_high", 80)
        close = data["close"]

        momentum = close.pct_change(mom_p)
        trend_up = momentum > 0

        # RSI
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)
        avg_gain = gain.ewm(span=rsi_p, adjust=False).mean()
        avg_loss = loss.ewm(span=rsi_p, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, 1e-10)
        rsi = 100 - (100 / (1 + rs))

        # Entry: trend is up AND RSI not overbought
        entries = trend_up & (rsi < rsi_high)
        entries = entries & (~entries.shift(1).fillna(False))

        # Exit: trend turns down OR RSI overbought
        exits = (~trend_up) | (rsi > rsi_high)
        exits = exits & (~exits.shift(1).fillna(False))

        return entries, exits

    def default_params(self):
        return {"mom_period": 14, "rsi_period": 7, "rsi_low": 20, "rsi_high": 80}


class CryptoVolatilityBreakout(Strategy):
    """
    Crypto-specific volatility breakout.

    Cryptocurrencies exhibit strong volatility clustering and breakout behavior.
    Enter when price breaks out of a tight consolidation range on expanding volume.
    """

    name = "Crypto Volatility Breakout"
    category = "trend"
    asset_classes = ["crypto"]
    paper_section = "18.2"
    description = "Enter on volatility breakout from consolidation"
    parameters = {"consolidation_period": 20, "breakout_mult": 1.5}

    def generate_signals(self, data, **params):
        period = params.get("consolidation_period", 20)
        mult = params.get("breakout_mult", 1.5)
        close = data["close"]
        high = data.get("high", close)
        low = data.get("low", close)
        volume = data.get("volume", pd.Series(1, index=close.index))

        # Consolidation: range is tight
        atr = (high - low).rolling(period).mean()
        atr_ratio = atr / atr.rolling(period * 3).mean()

        # Breakout: price exceeds recent range with volume
        recent_high = high.rolling(period).max().shift(1)
        vol_ratio = volume / volume.rolling(period * 3).mean()

        breakout_up = (close > recent_high) & (vol_ratio > mult) & (atr_ratio < 1)
        entries = breakout_up & (~breakout_up.shift(1).fillna(False))

        # Exit: reversion back below the breakout level or tight range ends
        recent_low = low.rolling(period // 2).min().shift(1)
        exits = close < recent_low

        return entries, exits

    def default_params(self):
        return {"consolidation_period": 20, "breakout_mult": 1.5}


# Register
for _cls in [CryptoANN, CryptoSentiment, CryptoMomentumReversal,
             CryptoVolatilityBreakout]:
    registry.register(_cls)
