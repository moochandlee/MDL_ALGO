"""
Risk-adjusted return metrics for strategy evaluation.

Each function takes a pd.Series of daily returns and returns a scalar.
Composite computation runs all metrics at once via ``compute_all``.

Usage::

    from quant.metrics import compute_all
    metrics = compute_all(daily_returns)
    print(metrics["sharpe_ratio"], metrics["max_drawdown_pct"])
"""

import numpy as np
import pandas as pd

ANNUAL_FACTOR = 252  # trading days


# ── Individual metrics ────────────────────────────────────────────────────────

def annualized_return(returns: pd.Series) -> float:
    """Compound annual growth rate (CAGR) from daily returns."""
    total = (1 + returns).prod()
    years = len(returns) / ANNUAL_FACTOR
    return float(total ** (1 / years) - 1) if years > 0 else 0.0


def annualized_volatility(returns: pd.Series) -> float:
    """Annualized standard deviation of returns."""
    return float(np.std(returns, ddof=1) * np.sqrt(ANNUAL_FACTOR))


def sharpe_ratio(returns: pd.Series, risk_free: float = 0.0) -> float:
    """Annualized Sharpe ratio = (excess return) / volatility."""
    vol = annualized_volatility(returns)
    if vol == 0:
        return 0.0
    return (annualized_return(returns) - risk_free) / vol


def sortino_ratio(returns: pd.Series, risk_free: float = 0.0, target: float = 0.0) -> float:
    """
    Sortino ratio — uses downside deviation instead of total volatility.

    Downside deviation only penalizes returns below ``target``.
    """
    downside = returns[returns < target]
    if len(downside) == 0:
        return float("inf") if annualized_return(returns) > risk_free else 0.0

    downside_std = np.std(downside, ddof=1) * np.sqrt(ANNUAL_FACTOR)
    if downside_std == 0:
        return 0.0
    return (annualized_return(returns) - risk_free) / downside_std


def max_drawdown(returns: pd.Series):
    """
    Maximum drawdown from daily returns.

    Returns
    -------
    (drawdown_pct, duration_days)
        drawdown_pct: float between 0 and 1 (e.g., 0.25 = 25% drawdown)
        duration_days: int, days from peak to trough
    """
    cumulative = (1 + returns).cumprod()
    running_max = cumulative.cummax()
    drawdown = (cumulative - running_max) / running_max

    dd_pct = float(drawdown.min())
    dd_idx = drawdown.idxmin()
    peak_idx = running_max[:dd_idx].idxmax() if dd_idx in cumulative.index else cumulative.index[0]

    duration = (dd_idx - peak_idx).days if hasattr(dd_idx - peak_idx, "days") else 0
    return abs(dd_pct), max(duration, 0)


def max_drawdown_pct(returns: pd.Series) -> float:
    """Maximum drawdown as a positive percentage (e.g., 25.5 = 25.5%)."""
    dd, _ = max_drawdown(returns)
    return dd * 100


def calmar_ratio(returns: pd.Series) -> float:
    """Calmar ratio = CAGR / |max drawdown|."""
    dd, _ = max_drawdown(returns)
    if dd == 0:
        return 0.0
    return annualized_return(returns) / dd


def win_rate(returns: pd.Series) -> float:
    """Proportion of days with positive returns."""
    if len(returns) == 0:
        return 0.0
    return float((returns > 0).sum() / len(returns))


def profit_factor(returns: pd.Series) -> float:
    """Gross profit / gross loss (absolute values)."""
    gross_profit = returns[returns > 0].sum()
    gross_loss = abs(returns[returns < 0].sum())
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return float(gross_profit / gross_loss)


def var_historic(returns: pd.Series, confidence: float = 0.95) -> float:
    """
    Value at Risk at the given confidence level (historical method).

    Returns a positive number representing the loss magnitude.
    E.g., var(0.95) = 0.025 means the 95% daily VaR is 2.5%.
    """
    return float(-np.percentile(returns, (1 - confidence) * 100))


def cvar_historic(returns: pd.Series, confidence: float = 0.95) -> float:
    """
    Conditional VaR (expected shortfall) — average loss beyond VaR.
    """
    var = var_historic(returns, confidence)
    tail = returns[returns <= -var]
    if len(tail) == 0:
        return var
    return float(-tail.mean())


def omega_ratio(returns: pd.Series, threshold: float = 0.0) -> float:
    """
    Omega ratio = E[max(R - threshold, 0)] / E[max(threshold - R, 0)].
    Higher is better. Ratio of gains above threshold to losses below.
    """
    gains = (returns[returns > threshold] - threshold).sum()
    losses = (threshold - returns[returns < threshold]).sum()
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return float(gains / losses)


def total_return_pct(returns: pd.Series) -> float:
    """Total return as a percentage (e.g., 34.5 = 34.5%)."""
    return float(((1 + returns).prod() - 1) * 100)


# ── Composite ─────────────────────────────────────────────────────────────────

def compute_all(returns: pd.Series) -> dict:
    """
    Compute all risk-adjusted metrics for a daily returns series.

    Returns a dict with all metric values as plain floats.
    """
    if len(returns) < 10:
        return {k: 0.0 for k in METRIC_NAMES}

    dd_pct, dd_days = max_drawdown(returns)

    return {
        "total_return_pct": total_return_pct(returns),
        "cagr_pct": annualized_return(returns) * 100,
        "annualized_volatility_pct": annualized_volatility(returns) * 100,
        "sharpe_ratio": sharpe_ratio(returns),
        "sortino_ratio": sortino_ratio(returns),
        "calmar_ratio": calmar_ratio(returns),
        "max_drawdown_pct": dd_pct * 100,
        "max_drawdown_days": dd_days,
        "win_rate": win_rate(returns),
        "profit_factor": profit_factor(returns),
        "var_95_pct": var_historic(returns, 0.95) * 100,
        "var_99_pct": var_historic(returns, 0.99) * 100,
        "cvar_95_pct": cvar_historic(returns, 0.95) * 100,
        "omega_ratio": omega_ratio(returns),
    }


METRIC_NAMES = [
    "total_return_pct", "cagr_pct", "annualized_volatility_pct",
    "sharpe_ratio", "sortino_ratio", "calmar_ratio",
    "max_drawdown_pct", "max_drawdown_days",
    "win_rate", "profit_factor",
    "var_95_pct", "var_99_pct", "cvar_95_pct",
    "omega_ratio",
]

# Higher is better for all of these
HIGHER_IS_BETTER = {
    "total_return_pct", "cagr_pct", "sharpe_ratio", "sortino_ratio",
    "calmar_ratio", "win_rate", "profit_factor", "omega_ratio",
}

# Lower is better for all of these
LOWER_IS_BETTER = {
    "annualized_volatility_pct", "max_drawdown_pct", "max_drawdown_days",
    "var_95_pct", "var_99_pct", "cvar_95_pct",
}
