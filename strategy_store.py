"""Strategy persistence — shared by orders and quant agent pages."""
import json
from pathlib import Path

STRATEGIES_PATH = Path('data/strategies.json')


def load_strategies():
    if not STRATEGIES_PATH.exists():
        return []
    with open(STRATEGIES_PATH, 'r') as f:
        return json.load(f)


def save_strategies(strategies):
    with open(STRATEGIES_PATH, 'w') as f:
        json.dump(strategies, f, indent=4)
