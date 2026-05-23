"""
Equity & ETF strategies from the 151 Trading Strategies paper.

Categories:
  - trend.py:       MA crossovers, channel breakouts, support/resistance
  - momentum.py:    Price momentum, residual momentum, dual momentum
  - mean_revert.py: Bollinger Bands, RSI, pairs trading, cluster reversion
  - volatility.py:  Low-vol anomaly, vol targeting, vol risk premium
  - factors.py:     Earnings momentum, value, multifactor, stat-arb
"""

from quant.strategies.equities import trend, momentum, mean_revert, volatility, factors

__all__ = ["trend", "momentum", "mean_revert", "volatility", "factors"]
