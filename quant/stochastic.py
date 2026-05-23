"""
Stochastic simulation engine for trading strategy evaluation.

Generates synthetic price paths so strategies can be stress-tested across
thousands of possible futures, not just the one historical path observed.

Methods (ordered by complexity):
  - Bootstrap:   resample historical returns (preserves actual distribution)
  - GBM:          geometric Brownian motion (log-normal random walk)
  - Merton:       GBM + Poisson-driven jumps (captures crash risk)
  - Heston:       stochastic volatility model
  - RegimeSwitch: hidden Markov bull/bear/sideways states

Usage::

    from quant.stochastic import simulate
    from quant.data import fetch_close

    prices = fetch_close("AAPL", days=365)
    paths = simulate(prices, method="gbm", n_paths=1000, horizon=252)
    # paths.shape == (1000, 252)
"""

import numpy as np


def _calibrate_gbm(log_returns: np.ndarray) -> tuple[float, float]:
    """Estimate annualized drift (mu) and volatility (sigma) from log returns."""
    mu = np.mean(log_returns) * 252
    sigma = np.std(log_returns, ddof=1) * np.sqrt(252)
    return mu, sigma


def simulate_gbm(
    prices: np.ndarray,
    n_paths: int = 1000,
    horizon_days: int = 252,
    dt: float = 1 / 252,
    seed: int = None,
) -> np.ndarray:
    """
    Geometric Brownian Motion.

    S_t = S_0 * exp((mu - sigma^2/2)*t + sigma * W_t)

    Calibrates mu and sigma from historical daily log returns.
    """
    rng = np.random.default_rng(seed)
    log_returns = np.diff(np.log(prices))
    mu, sigma = _calibrate_gbm(log_returns)

    # Drift with Ito correction
    drift = (mu - 0.5 * sigma ** 2) * dt
    diffusion = sigma * np.sqrt(dt)

    # Generate random walks: (n_paths, horizon_days)
    shocks = rng.normal(loc=drift, scale=diffusion, size=(n_paths, horizon_days))

    # Cumulative product starting from last price
    S0 = prices[-1]
    paths = S0 * np.exp(np.cumsum(shocks, axis=1))
    return paths


def simulate_bootstrap(
    prices: np.ndarray,
    n_paths: int = 1000,
    horizon_days: int = 252,
    block_size: int = 1,
    seed: int = None,
) -> np.ndarray:
    """
    Bootstrap simulation: resample historical daily returns with replacement.

    When block_size > 1, uses block bootstrap to preserve serial correlation.
    """
    rng = np.random.default_rng(seed)
    log_returns = np.diff(np.log(prices))
    n = len(log_returns)

    if block_size <= 1:
        # Standard bootstrap — independent draws
        idx = rng.integers(0, n, size=(n_paths, horizon_days))
        sampled_returns = log_returns[idx]
    else:
        # Block bootstrap — preserve short-term dependencies
        n_blocks_total = n // block_size
        blocks = np.array([log_returns[i * block_size:(i + 1) * block_size].sum()
                          for i in range(n_blocks_total)])
        blocks_needed = int(np.ceil(horizon_days / block_size))
        sampled = []
        for _ in range(n_paths):
            block_idx = rng.integers(0, n_blocks_total, size=blocks_needed)
            path_returns = []
            for bi in block_idx:
                start = bi * block_size
                end = min(start + block_size, n)
                path_returns.extend(log_returns[start:end])
            sampled.append(path_returns[:horizon_days])
        sampled_returns = np.array(sampled)
        # Edge case: array may be ragged if n < horizon_days
        if sampled_returns.ndim == 1:
            sampled_returns = sampled_returns.reshape(n_paths, -1)
        sampled_returns = sampled_returns[:, :horizon_days]

    S0 = prices[-1]
    paths = S0 * np.exp(np.cumsum(sampled_returns, axis=1))
    return paths


def simulate_jump_diffusion(
    prices: np.ndarray,
    n_paths: int = 1000,
    horizon_days: int = 252,
    dt: float = 1 / 252,
    jump_intensity: float = None,
    jump_mean: float = None,
    jump_std: float = 0.02,
    seed: int = None,
) -> np.ndarray:
    """
    Merton jump-diffusion model.

    dS/S = (mu - lambda*k) * dt + sigma * dW + J * dN

    where dN ~ Poisson(lambda*dt) and J ~ Normal(jump_mean, jump_std^2).
    Jumps are log-normal in price space: log(1+J).

    If jump_intensity/jump_mean are None, they are calibrated from returns
    exceeding 3 standard deviations (tail events).
    """
    rng = np.random.default_rng(seed)
    log_returns = np.diff(np.log(prices))
    mu, sigma = _calibrate_gbm(log_returns)

    # Calibrate jumps from tail events if not provided
    if jump_intensity is None or jump_mean is None:
        threshold = 3 * np.std(log_returns)
        tails = log_returns[np.abs(log_returns) > threshold]
        if len(tails) < 3:
            # Not enough tail events — fall back to sensible defaults
            jump_intensity = jump_intensity or 1.0  # ~1 jump per year
            jump_mean = jump_mean or -0.01
        else:
            jump_intensity = jump_intensity or len(tails) / (len(log_returns) * dt)
            jump_mean = jump_mean or np.mean(tails)

    k = np.exp(jump_mean + 0.5 * jump_std ** 2) - 1  # expected jump size
    drift = (mu - jump_intensity * k - 0.5 * sigma ** 2) * dt
    diffusion = sigma * np.sqrt(dt)

    paths = np.zeros((n_paths, horizon_days))
    S = np.full(n_paths, prices[-1])

    for t in range(horizon_days):
        dW = rng.normal(0, 1, n_paths)
        dN = rng.poisson(jump_intensity * dt, n_paths)
        J = rng.normal(jump_mean, jump_std, n_paths) * dN

        S = S * np.exp(drift + diffusion * dW + J)
        paths[:, t] = S

    return paths


def simulate_heston(
    prices: np.ndarray,
    n_paths: int = 1000,
    horizon_days: int = 252,
    dt: float = 1 / 252,
    kappa: float = 3.0,      # mean reversion speed of volatility
    theta: float = 0.04,      # long-run variance
    xi: float = 0.3,          # vol-of-vol
    rho: float = -0.7,        # correlation between price and vol shocks
    seed: int = None,
) -> np.ndarray:
    """
    Heston stochastic volatility model.

    dS = mu * S * dt + sqrt(v) * S * dW1
    dv = kappa * (theta - v) * dt + xi * sqrt(v) * dW2
    corr(dW1, dW2) = rho

    Uses Euler-Maruyama discretization with full truncation (v = max(v, 0)).
    """
    rng = np.random.default_rng(seed)
    log_returns = np.diff(np.log(prices))
    mu_annual, _ = _calibrate_gbm(log_returns)
    mu = mu_annual  # annual drift

    paths = np.zeros((n_paths, horizon_days))
    S = np.full(n_paths, prices[-1])
    v = np.full(n_paths, theta)  # start vol at long-run mean

    for t in range(horizon_days):
        # Correlated shocks
        Z1 = rng.normal(0, 1, n_paths)
        Z2 = rho * Z1 + np.sqrt(1 - rho ** 2) * rng.normal(0, 1, n_paths)

        # Full truncation: ensure variance non-negative
        v = np.maximum(v, 0)
        sqrt_v = np.sqrt(v)

        S = S * np.exp((mu - 0.5 * v) * dt + sqrt_v * np.sqrt(dt) * Z1)
        v = v + kappa * (theta - v) * dt + xi * sqrt_v * np.sqrt(dt) * Z2

        paths[:, t] = S

    return paths


def simulate_regime_switching(
    prices: np.ndarray,
    n_paths: int = 1000,
    horizon_days: int = 252,
    dt: float = 1 / 252,
    seed: int = None,
) -> np.ndarray:
    """
    2-state regime-switching model (bull/bear markets).

    Each regime has its own mu and sigma. Transitions follow a Markov chain.
    Default transition probabilities calibrated from historical data.
    """
    rng = np.random.default_rng(seed)
    log_returns = np.diff(np.log(prices))

    # Simple calibration: split returns into positive/negative regimes
    pos_mask = log_returns > 0
    mu_bull = np.mean(log_returns[pos_mask]) * 252 if pos_mask.any() else 0.15
    sigma_bull = np.std(log_returns[pos_mask]) * np.sqrt(252) if pos_mask.any() else 0.15
    mu_bear = np.mean(log_returns[~pos_mask]) * 252 if (~pos_mask).any() else -0.10
    sigma_bear = np.std(log_returns[~pos_mask]) * np.sqrt(252) if (~pos_mask).any() else 0.25

    # Transition probabilities (daily)
    p_bb = 0.95   # P(stay bull | bull)
    p_ss = 0.95   # P(stay bear | bear)
    P = np.array([[p_bb, 1 - p_bb],
                  [1 - p_ss, p_ss]])  # transition matrix

    mus = np.array([mu_bull, mu_bear])
    sigmas = np.array([sigma_bull, sigma_bear])

    paths = np.zeros((n_paths, horizon_days))
    S = np.full(n_paths, prices[-1])
    regime = rng.integers(0, 2, n_paths)  # start states

    for t in range(horizon_days):
        # Transition
        for i in range(n_paths):
            regime[i] = rng.choice([0, 1], p=P[regime[i]])

        mu_t = mus[regime]
        sigma_t = sigmas[regime]

        drift = (mu_t - 0.5 * sigma_t ** 2) * dt
        diffusion = sigma_t * np.sqrt(dt)
        shocks = rng.normal(0, 1, n_paths)

        S = S * np.exp(drift + diffusion * shocks)
        paths[:, t] = S

    return paths


# ── Unified API ────────────────────────────────────────────────────────────────

METHODS = {
    "gbm": simulate_gbm,
    "bootstrap": simulate_bootstrap,
    "jump_diffusion": simulate_jump_diffusion,
    "heston": simulate_heston,
    "regime_switching": simulate_regime_switching,
}


def simulate(
    prices: np.ndarray,
    method: str = "gbm",
    n_paths: int = 1000,
    horizon_days: int = 252,
    seed: int = None,
    **kwargs,
) -> np.ndarray:
    """
    Generate synthetic price paths.

    Parameters
    ----------
    prices : np.ndarray
        1-D array of historical close prices (used to calibrate parameters).
    method : {"gbm", "bootstrap", "jump_diffusion", "heston", "regime_switching"}
    n_paths : int
        Number of synthetic paths to generate.
    horizon_days : int
        Number of trading days forward (e.g., 252 = 1 year).
    seed : int or None
        Random seed for reproducibility.

    Returns
    -------
    np.ndarray of shape (n_paths, horizon_days)
    """
    simulator = METHODS.get(method)
    if simulator is None:
        raise ValueError(f"Unknown method: {method}. Choose from: {list(METHODS)}")
    return simulator(prices, n_paths=n_paths, horizon_days=horizon_days, seed=seed, **kwargs)


def simulate_multi(
    prices: np.ndarray,
    methods: list[str] = ("gbm", "bootstrap"),
    n_paths: int = 1000,
    horizon_days: int = 252,
    seed: int = None,
) -> dict[str, np.ndarray]:
    """Run multiple simulation methods and return {method: paths}."""
    results = {}
    for method in methods:
        results[method] = simulate(
            prices, method=method, n_paths=n_paths,
            horizon_days=horizon_days, seed=seed,
        )
    return results
