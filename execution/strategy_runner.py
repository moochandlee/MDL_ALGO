import json
from pathlib import Path
import yfinance as yf
from typing import List, Dict

# Paths
STRATEGIES_PATH = Path('data/strategies.json')
RISK_PATH = Path('data/risk_state.json')

# Helper functions
def load_strategies() -> List[Dict]:
    if not STRATEGIES_PATH.exists():
        return []
    with open(STRATEGIES_PATH, 'r') as f:
        return json.load(f)

def save_strategies(strategies: List[Dict]):
    with open(STRATEGIES_PATH, 'w') as f:
        json.dump(strategies, f, indent=4)

def get_price_history(ticker: str, period: str = '1y', interval: str = '1d'):
    data = yf.download(ticker, period=period, interval=interval, progress=False)
    return data['Close'] if 'Close' in data else []

def ma_crossover_signal(prices, short_window=20, long_window=50):
    if len(prices) < long_window:
        return None
    short_ma = prices.rolling(window=short_window).mean()
    long_ma = prices.rolling(window=long_window).mean()
    # Simple logic: generate BUY when short crosses above long, SELL when crosses below
    if short_ma.iloc[-2] < long_ma.iloc[-2] and short_ma.iloc[-1] > long_ma.iloc[-1]:
        return 'BUY'
    if short_ma.iloc[-2] > long_ma.iloc[-2] and short_ma.iloc[-1] < long_ma.iloc[-1]:
        return 'SELL'
    return None

# Guardrails import (assumes execution.guardrails module is in PYTHONPATH)
from execution.guardrails import validate_strategy_trade, get_risk_status

# Placeholder Schwab client – replace with real implementation
class SchwabClient:
    def place_order(self, ticker: str, qty: int, side: str):
        # In production, call the real Schwab API.
        print(f"Placing {side} order for {qty} shares of {ticker}")
        return {"status": "submitted"}

schwab_client = SchwabClient()

def check_strategies():
    strategies = load_strategies()
    risk_state = get_risk_status()
    kill_switch = risk_state.get('kill_switch', True)
    if kill_switch:
        print('Kill switch is ON – no automated trades will be executed.')
        return
    for strat in strategies:
        if not strat.get('active'):
            continue
        ticker = strat.get('ticker')
        allocation = strat.get('allocation_usd', 0)
        reinvest = strat.get('reinvest_profits', False)
        stop_loss_pct = strat.get('stop_loss_pct')
        # Fetch price history
        prices = get_price_history(ticker)
        if prices.empty:
            continue
        signal = ma_crossover_signal(prices)
        if not signal:
            continue
        # Determine trade size – simple: allocate full amount / current price
        current_price = prices.iloc[-1]
        qty = int(allocation / current_price)
        cost = qty * current_price
        if not validate_strategy_trade(ticker, cost, allocation):
            continue
        # Execute trade
        side = 'BUY' if signal == 'BUY' else 'SELL'
        result = schwab_client.place_order(ticker, qty, side)
        print(f"Executed {side} for {ticker}: {result}")
        # Update allocation if reinvest is enabled
        if reinvest and side == 'SELL':
            # add proceeds to allocation (simple approximation)
            strat['allocation_usd'] += cost
        elif side == 'BUY':
            strat['allocation_usd'] -= cost
        # TODO: stop‑loss handling would require storing entry price; omitted for brevity
    save_strategies(strategies)
