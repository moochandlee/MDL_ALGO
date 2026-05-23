"""
Daily strategy execution loop.

Fetches prices → runs active strategies → validates via guardrails →
executes via real (Schwab) or paper trading.

Usage::

    from execution.strategy_runner import StrategyRunner
    runner = StrategyRunner(mode="paper")
    runner.run_daily()
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from execution.guardrails import validate_strategy_trade, get_risk_status
from execution.paper_trader import PaperTrader

STRATEGIES_PATH = Path("data/strategies.json")
ACTIVE_STRATEGIES_PATH = Path("data/active_strategies.json")
RUN_LOG_PATH = Path("data/run_log.json")


class StrategyRunner:
    """
    Orchestrates daily strategy execution.

    Parameters
    ----------
    mode : "paper" or "live"
        Paper mode uses PaperTrader. Live mode uses schwab_client.
    """

    def __init__(self, mode: str = "paper"):
        self.mode = mode
        if mode == "paper":
            self.trader = PaperTrader()
        else:
            self.trader = None  # uses schwab_client directly

    # ── Active strategy management ────────────────────────────────────────

    def load_active(self) -> list[dict]:
        """Load the list of active strategies with their ticker assignments."""
        if not ACTIVE_STRATEGIES_PATH.exists():
            return []
        return json.loads(ACTIVE_STRATEGIES_PATH.read_text())

    def save_active(self, strategies: list[dict]) -> None:
        ACTIVE_STRATEGIES_PATH.parent.mkdir(parents=True, exist_ok=True)
        ACTIVE_STRATEGIES_PATH.write_text(json.dumps(strategies, indent=2))

    def activate(self, strategy_name: str, ticker: str,
                 allocation_usd: float = 5000,
                 params: dict = None) -> dict:
        """Add a strategy+ticker combo to the active set."""
        active = self.load_active()
        # Remove existing entry for this strategy+ticker if present
        active = [a for a in active
                  if not (a["strategy"] == strategy_name and a["ticker"] == ticker)]
        active.append({
            "strategy": strategy_name,
            "ticker": ticker,
            "allocation_usd": allocation_usd,
            "params": params or {},
            "active": True,
            "added_at": datetime.now().isoformat(),
        })
        self.save_active(active)
        return {"status": "activated", "strategy": strategy_name, "ticker": ticker}

    def deactivate(self, strategy_name: str, ticker: str) -> dict:
        """Remove a strategy+ticker combo."""
        active = self.load_active()
        active = [a for a in active
                  if not (a["strategy"] == strategy_name and a["ticker"] == ticker)]
        self.save_active(active)
        return {"status": "deactivated", "strategy": strategy_name, "ticker": ticker}

    # ── Daily run ─────────────────────────────────────────────────────────

    def run_daily(self) -> dict:
        """
        Execute all active strategies for the day.

        Returns a dict with results for each strategy+ticker combo.
        """
        risk_state = get_risk_status()
        if risk_state.get("kill_switch", True):
            return {"error": "Kill switch is ON — no trades executed"}

        active = self.load_active()
        if not active:
            return {"message": "No active strategies", "results": []}

        results = []
        prices_cache = {}

        for cfg in active:
            if not cfg.get("active"):
                continue

            strategy_name = cfg["strategy"]
            ticker = cfg["ticker"]
            allocation = cfg.get("allocation_usd", 5000)
            params = cfg.get("params", {})

            # Fetch price data if not cached
            if ticker not in prices_cache:
                try:
                    from quant.data import fetch_ohlcv
                    df = fetch_ohlcv(ticker, days=365)
                    prices_cache[ticker] = df
                except Exception as e:
                    results.append({
                        "strategy": strategy_name, "ticker": ticker,
                        "error": f"Data fetch failed: {e}",
                    })
                    continue
            else:
                df = prices_cache[ticker]

            # Get the strategy class and generate signals
            try:
                from quant.strategies import registry
                registry.discover()
                strat_cls = registry.get(strategy_name)
                if strat_cls is None:
                    results.append({
                        "strategy": strategy_name, "ticker": ticker,
                        "error": f"Strategy not found: {strategy_name}",
                    })
                    continue

                strat = strat_cls()
                entries, exits = strat.generate_signals(df, **params)
            except Exception as e:
                results.append({
                    "strategy": strategy_name, "ticker": ticker,
                    "error": f"Signal generation failed: {e}",
                })
                continue

            # Get latest signals
            latest_entry = entries.iloc[-1] if len(entries) > 0 else False
            latest_exit = exits.iloc[-1] if len(exits) > 0 else False

            if not latest_entry and not latest_exit:
                results.append({
                    "strategy": strategy_name, "ticker": ticker,
                    "action": "hold", "reason": "no signal",
                })
                continue

            current_price = float(df["close"].iloc[-1])
            result = self._execute_signal(
                strategy_name, ticker, latest_entry, latest_exit,
                current_price, allocation, params,
            )
            results.append(result)

        # Log the run
        self._log_run(results)

        return {"results": results, "timestamp": datetime.now().isoformat()}

    def _execute_signal(
        self, strategy_name: str, ticker: str,
        entry: bool, exit_signal: bool,
        price: float, allocation: float, params: dict,
    ) -> dict:
        """Execute a single signal through paper or live trading."""
        result = {
            "strategy": strategy_name, "ticker": ticker,
            "price": round(price, 4), "allocation": allocation,
        }

        if exit_signal:
            # Exit any existing position
            if self.mode == "paper":
                pos = self.trader.positions.get(ticker)
                if pos and pos.quantity > 0:
                    trade = self.trader.place_order(
                        "SELL", ticker, pos.quantity, price,
                        reason=f"{strategy_name} exit signal",
                    )
                    result["action"] = "sell"
                    result["trade"] = trade
                else:
                    result["action"] = "hold"
                    result["reason"] = "exit signal but no position"
            else:
                # Live mode: use Schwab
                from schwab_client import build_market_order, place_order
                # First check current position size
                balances = __import__("schwab_client", fromlist=["get_balances_and_positions"])
                pos_data = balances.get_balances_and_positions()
                current_qty = 0
                for p in pos_data.get("positions", []):
                    if p["symbol"] == ticker:
                        current_qty = int(float(p["quantity"]))
                        break
                if current_qty > 0:
                    order = build_market_order(ticker, current_qty, "SELL")
                    resp = place_order(order)
                    result["action"] = "sell"
                    result["trade"] = resp
                else:
                    result["action"] = "hold"
                    result["reason"] = "exit signal but no live position"

        elif entry:
            # Calculate position size
            quantity = max(int(allocation // price), 1)
            notional = quantity * price

            if self.mode == "paper":
                trade = self.trader.place_order(
                    "BUY", ticker, quantity, price,
                    reason=f"{strategy_name} entry signal",
                )
                result["action"] = "buy"
                result["trade"] = trade
            else:
                if not validate_strategy_trade(ticker, notional, allocation):
                    result["action"] = "blocked"
                    result["reason"] = "guardrails prevented trade"
                    return result

                from schwab_client import build_market_order, place_order
                order = build_market_order(ticker, quantity, "BUY")
                resp = place_order(order)
                result["action"] = "buy"
                result["trade"] = resp

        else:
            result["action"] = "hold"
            result["reason"] = "no actionable signal"

        return result

    def _log_run(self, results: list[dict]) -> None:
        """Append run results to the log file."""
        RUN_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        log = []
        if RUN_LOG_PATH.exists():
            try:
                log = json.loads(RUN_LOG_PATH.read_text())
            except (json.JSONDecodeError, Exception):
                log = []
        log.append({
            "timestamp": datetime.now().isoformat(),
            "mode": self.mode,
            "results": results,
        })
        # Keep last 1000 runs
        if len(log) > 1000:
            log = log[-1000:]
        RUN_LOG_PATH.write_text(json.dumps(log, indent=2))

    def paper_summary(self) -> dict:
        """Get the paper portfolio summary."""
        if self.mode != "paper":
            return {"error": "Not in paper mode"}
        return self.trader.summary()

    def recent_runs(self, limit: int = 10) -> list[dict]:
        """Get recent run logs."""
        if not RUN_LOG_PATH.exists():
            return []
        log = json.loads(RUN_LOG_PATH.read_text())
        return log[-limit:]
