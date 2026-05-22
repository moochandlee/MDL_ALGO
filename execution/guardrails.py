import json
from pathlib import Path

# Ensure this matches your Settings.risk_state_path
RISK_PATH = Path("data/risk_state.json")

def initialize_risk_engine():
    """Create the risk file if it doesn't exist."""
    if not RISK_PATH.parent.exists():
        RISK_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    if not RISK_PATH.exists():
        with open(RISK_PATH, "w") as f:
            json.dump({"kill_switch": True, "approved_strategies": {}}, f)

def get_risk_status() -> dict:
    """Reads the current risk state for the UI."""
    try:
        with open(RISK_PATH, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"kill_switch": True, "approved_strategies": {}}

def set_kill_switch(status: bool):
    """Updates the global kill switch."""
    state = get_risk_status()
    state["kill_switch"] = status
    with open(RISK_PATH, "w") as f:
        json.dump(state, f, indent=4)

def validate_trade(symbol: str) -> bool:
    """Final check before execution engine calls Schwab."""
    state = get_risk_status()
    if state.get("kill_switch", True):
        return False
    return True

def validate_strategy_trade(symbol: str, cost: float, allocation_usd: float) -> bool:
    """Final check for strategy trades before execution."""
    state = get_risk_status()
    if state.get("kill_switch", True):
        return False
    if cost > allocation_usd:
        return False
    return True