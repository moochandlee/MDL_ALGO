"""
Strategy ranking engine.

Pipeline:
  1. Historical backtest against real data via vectorbt
  2. Pre-filter: skip strategies with terrible historical results
  3. Stochastic simulation (GBM + bootstrap) for metric distributions
  4. Composite scoring with configurable weights
  5. Hardware-aware filtering and final ranking

Usage::

    from quant.ranking import rank_strategies
    results = rank_strategies(strategies, tickers=["AAPL", "SPY"])
    for r in results[:5]:
        print(r["strategy"], r["composite_score"])
"""

import json
import multiprocessing
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import vectorbt as vbt

from quant.data import fetch_ohlcv
from quant.metrics import (
    ANNUAL_FACTOR, METRIC_NAMES, HIGHER_IS_BETTER, LOWER_IS_BETTER,
    compute_all, annualized_return, max_drawdown_pct, calmar_ratio,
    sharpe_ratio, sortino_ratio,
)
from quant.stochastic import simulate_multi

RANKINGS_DIR = Path("data/rankings")
RANKINGS_DIR.mkdir(parents=True, exist_ok=True)

# Default composite score weights — tunable per user preference
DEFAULT_WEIGHTS = {
    "sharpe_ratio": 0.25,
    "sortino_ratio": 0.20,
    "calmar_ratio": 0.20,
    "max_drawdown_pct": 0.15,  # inverted: lower drawdown = higher sub-score
    "win_rate": 0.10,
    "profit_factor": 0.10,
}

# Strategies that score below this on historical data skip stochastic simulation
PRE_FILTER_MIN_SHARPE = -0.5
PRE_FILTER_MIN_CALMAR = -1.0


@dataclass
class RankingConfig:
    metric_weights: dict = field(default_factory=lambda: DEFAULT_WEIGHTS.copy())
    n_stochastic_paths: int = 1000
    stochastic_horizon: int = 252  # 1 year of trading days
    stochastic_methods: tuple = ("gbm", "bootstrap")
    min_history_days: int = 60
    pre_filter_sharpe: float = PRE_FILTER_MIN_SHARPE
    pre_filter_calmar: float = PRE_FILTER_MIN_CALMAR
    n_jobs: int = 1  # parallel workers (1 = no multiprocessing)
    max_strategies: int = 40  # return top N after ranking


def _backtest_signals(
    prices: pd.Series,
    entries: pd.Series,
    exits: pd.Series,
) -> dict:
    """
    Run a vectorbt portfolio backtest from entry/exit signals.
    Returns computed metrics and daily returns.
    """
    # Align all series to the same index
    common_idx = prices.index.intersection(entries.index).intersection(exits.index)
    if len(common_idx) < 10:
        return None

    prices = prices[common_idx]
    entries = entries[common_idx].fillna(False).astype(bool)
    exits = exits[common_idx].fillna(False).astype(bool)

    # Ensure exits don't fire before entries
    pf = vbt.Portfolio.from_signals(
        prices, entries, exits,
        init_cash=10000,
        freq="1D",
    )

    daily_returns = pf.daily_returns().fillna(0.0)
    metrics = compute_all(daily_returns)

    # Add trade-level stats
    try:
        trades_df = pf.trades.records_readable
        metrics["n_trades"] = len(trades_df)
        metrics["avg_trade_return_pct"] = (
            float(trades_df["Return"].mean() * 100) if len(trades_df) > 0 else 0.0
        )
    except Exception:
        metrics["n_trades"] = 0
        metrics["avg_trade_return_pct"] = 0.0

    metrics["total_return_pct"] = float(pf.total_return() * 100)
    metrics["daily_returns"] = daily_returns
    metrics["equity_curve"] = pf.value()

    return metrics


def _evaluate_on_paths(
    strategy,
    synthetic_paths: np.ndarray,
    params: dict,
) -> dict:
    """
    Run a strategy across synthetic price paths and aggregate metrics.
    Returns {metric_name: {"mean": float, "std": float, "p5": float, "p50": float, "p95": float}}.
    """
    n_paths, horizon = synthetic_paths.shape
    all_metrics = {k: [] for k in METRIC_NAMES}

    success_count = 0
    for i in range(n_paths):
        path_prices = synthetic_paths[i]
        # Build a minimal DataFrame for the strategy
        df = pd.DataFrame({
            "close": path_prices,
        }, index=pd.RangeIndex(horizon))

        try:
            entries, exits = strategy.generate_signals(df, **params)
        except Exception:
            continue

        # Simple portfolio simulation without vectorbt (faster for synthetic)
        returns = _portfolio_returns_from_signals(path_prices, entries, exits)
        if returns is None or len(returns) < 5:
            continue

        m = compute_all(returns)
        for k in METRIC_NAMES:
            all_metrics[k].append(m.get(k, 0.0))
        success_count += 1

    if success_count < 10:
        return {k: {"mean": 0.0, "std": 0.0, "p5": 0.0, "p50": 0.0, "p95": 0.0}
                for k in METRIC_NAMES}

    result = {}
    for k in METRIC_NAMES:
        vals = np.array(all_metrics[k])
        result[k] = {
            "mean": float(np.mean(vals)),
            "std": float(np.std(vals, ddof=1)),
            "p5": float(np.percentile(vals, 5)),
            "p50": float(np.percentile(vals, 50)),
            "p95": float(np.percentile(vals, 95)),
        }
    result["success_paths"] = success_count
    result["total_paths"] = n_paths
    return result


def _portfolio_returns_from_signals(
    prices: np.ndarray,
    entries: pd.Series,
    exits: pd.Series,
    init_cash: float = 10000,
) -> pd.Series:
    """Lightweight portfolio simulation — faster than vectorbt for synthetic data."""
    n = len(prices)
    entries = entries.values if hasattr(entries, "values") else entries
    exits = exits.values if hasattr(exits, "values") else exits

    in_position = False
    holdings = 0.0
    cash = init_cash
    daily_values = []

    for i in range(n):
        if entries[i] and not in_position and cash > 0:
            holdings = cash / prices[i]
            cash = 0.0
            in_position = True
        elif exits[i] and in_position:
            cash = holdings * prices[i]
            holdings = 0.0
            in_position = False

        value = cash + holdings * prices[i]
        daily_values.append(value)

    if len(daily_values) < 2:
        return None

    equity = pd.Series(daily_values)
    returns = equity.pct_change().fillna(0.0)
    return returns


def _compute_composite(
    metrics: dict,
    cohort_max: dict,
    cohort_min: dict,
    weights: dict,
) -> float:
    """
    Compute a weighted composite score from individual metrics.

    Each metric is min-max normalized across the cohort (0 = worst, 1 = best),
    then combined with the configured weights.
    """
    score = 0.0
    total_weight = 0.0

    for metric, weight in weights.items():
        if metric not in metrics or metric not in cohort_max or metric not in cohort_min:
            continue

        val = metrics[metric]
        mx = cohort_max[metric]
        mn = cohort_min[metric]

        if mx == mn:
            norm = 0.5  # everyone ties
        else:
            norm = (val - mn) / (mx - mn)

        # Invert metrics where lower is better
        if metric in LOWER_IS_BETTER:
            norm = 1.0 - norm

        score += norm * weight
        total_weight += weight

    return score / total_weight if total_weight > 0 else 0.0


def _evaluate_strategy(
    strategy,
    ticker: str,
    config: RankingConfig,
) -> dict:
    """Evaluate a single strategy on a single ticker. Returns result dict or None."""
    start = datetime.now()

    # Fetch data
    try:
        df = fetch_ohlcv(ticker, days=365 * 3)  # 3 years history
    except Exception:
        return None

    if len(df) < config.min_history_days:
        return None

    close = df["close"].astype("float64")

    # Historical backtest
    params = strategy.default_params()
    try:
        entries, exits = strategy.generate_signals(df, **params)
    except Exception:
        return None

    hist = _backtest_signals(close, entries, exits)
    if hist is None:
        return None

    # Pre-filter: skip stochastic if historical results are terrible
    hist_sharpe = hist.get("sharpe_ratio", 0)
    hist_calmar = hist.get("calmar_ratio", 0)
    skip_stochastic = (
        hist_sharpe < config.pre_filter_sharpe or
        hist_calmar < config.pre_filter_calmar
    )

    # Build result
    result = {
        "strategy": strategy.name,
        "category": strategy.category,
        "ticker": ticker,
        "paper_section": strategy.paper_section,
        "params": params,
        "historical": {
            k: v for k, v in hist.items()
            if k not in ("daily_returns", "equity_curve")
        },
        "stochastic": {},
        "elapsed_seconds": 0,
    }

    if not skip_stochastic:
        try:
            price_arr = close.values.astype("float64")
            synth = simulate_multi(
                price_arr,
                methods=list(config.stochastic_methods),
                n_paths=config.n_stochastic_paths,
                horizon_days=config.stochastic_horizon,
                seed=42,
            )
            for method, paths in synth.items():
                method_metrics = _evaluate_on_paths(strategy, paths, params)
                result["stochastic"][method] = method_metrics
        except Exception:
            pass

    result["elapsed_seconds"] = round((datetime.now() - start).total_seconds(), 1)
    return result


def rank_strategies(
    strategies: list,
    tickers: list[str],
    config: RankingConfig = None,
    progress_callback=None,
) -> list[dict]:
    """
    Evaluate and rank strategies across all tickers.

    Parameters
    ----------
    strategies : list[Strategy]
        Instantiated strategy objects.
    tickers : list[str]
        Tickers to test on (e.g., ["AAPL", "SPY", "EURUSD=X"]).
    config : RankingConfig
        Ranking configuration.
    progress_callback : callable(str, float) or None
        Called with (status_message, fraction_done) for UI progress bars.

    Returns
    -------
    list[dict]
        Sorted by composite_score descending.
    """
    if config is None:
        config = RankingConfig()

    results = []
    total_combos = len(strategies) * len(tickers)
    completed = 0

    for strategy in strategies:
        for ticker in tickers:
            # Check asset class compatibility
            asset_class = "equity"
            if "-USD" in ticker or "USD" in ticker.upper()[:3].replace("-", "").replace("=", ""):
                if any(c in ticker.upper() for c in ["=X", "JPY", "GBP", "EUR", "AUD", "CAD", "CHF", "NZD"]):
                    asset_class = "fx"
                elif "-USD" in ticker:
                    asset_class = "crypto"
            if "ETF" in strategy.asset_classes or "equity" in strategy.asset_classes:
                if "etf" not in strategy.asset_classes and ticker in ["SPY", "QQQ", "IWM", "DIA", "VTI"]:
                    if "etf" not in strategy.asset_classes and "equity" not in strategy.asset_classes:
                        continue

            if asset_class not in strategy.asset_classes and "all" not in strategy.asset_classes:
                continue

            result = _evaluate_strategy(strategy, ticker, config)
            if result is not None:
                results.append(result)

            completed += 1
            if progress_callback:
                progress_callback(
                    f"{strategy.name} on {ticker}",
                    completed / total_combos if total_combos > 0 else 0,
                )

    if not results:
        return []

    # Compute composite scores
    # First, gather cohort stats for normalization
    cohort_stable = {}
    for metric in DEFAULT_WEIGHTS:
        vals = [r["historical"].get(metric, 0) for r in results
                if r["historical"].get(metric) is not None]
        if vals:
            # Trim outliers at 1st/99th percentile for stable normalization
            lo = np.percentile(vals, 1)
            hi = np.percentile(vals, 99)
            cohort_stable[metric] = {"min": lo, "max": hi}
        else:
            cohort_stable[metric] = {"min": 0, "max": 1}

    cohort_max = {k: v["max"] for k, v in cohort_stable.items()}
    cohort_min = {k: v["min"] for k, v in cohort_stable.items()}

    for r in results:
        r["composite_score"] = round(
            _compute_composite(
                r["historical"], cohort_max, cohort_min, config.metric_weights
            ) * 100, 1
        )

    # Sort best first
    results.sort(key=lambda r: r["composite_score"], reverse=True)

    # Trim to top N
    results = results[:config.max_strategies]

    return results


def run_batch_ranking(
    strategy_classes: list,
    tickers_by_asset: dict[str, list[str]],
    output_file: str = None,
    config: RankingConfig = None,
    progress_callback=None,
) -> list[dict]:
    """
    Run a full batch ranking across multiple asset classes.

    Parameters
    ----------
    strategy_classes : list[type[Strategy]]
    tickers_by_asset : dict, e.g. {"equity": ["AAPL", ...], "fx": ["EURUSD=X", ...]}
    output_file : str or None
        Path to save JSON results.
    """
    if config is None:
        config = RankingConfig()

    all_results = []

    for asset_class, tickers in tickers_by_asset.items():
        # Filter strategies that support this asset class
        applicable = [
            s() for s in strategy_classes
            if asset_class in s.asset_classes or "all" in s.asset_classes
        ]
        if not applicable:
            continue

        if progress_callback:
            progress_callback(f"Running {asset_class} strategies...", 0)

        results = rank_strategies(applicable, tickers, config=config,
                                  progress_callback=progress_callback)
        for r in results:
            r["asset_class"] = asset_class
        all_results.extend(results)

    # Re-sort combined results
    all_results.sort(key=lambda r: r.get("composite_score", 0), reverse=True)

    # Save
    if output_file:
        output_path = Path(output_file) if output_file else RANKINGS_DIR / "latest.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        # Strip non-serializable fields
        serializable = []
        for r in all_results:
            s = {k: v for k, v in r.items()}
            if "historical" in s and "daily_returns" in s["historical"]:
                del s["historical"]["daily_returns"]
            if "historical" in s and "equity_curve" in s["historical"]:
                s["historical"]["equity_curve"] = None
            serializable.append(s)
        output_path.write_text(json.dumps(serializable, indent=2, default=str))

    return all_results
