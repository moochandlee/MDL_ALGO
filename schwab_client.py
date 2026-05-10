"""
schwab_client.py — Schwab brokerage wrapper around schwabdev
"""

import schwabdev
from config import settings
from typing import Optional

_client: Optional[schwabdev.Client] = None


def get_client() -> schwabdev.Client:
    global _client
    if _client is None:
        _client = schwabdev.Client(
            settings.schwab_app_key,
            settings.schwab_app_secret,
            settings.schwab_callback,
        )
    return _client


# ── Account ──────────────────────────────────────────────────────────────────

def get_account_hash() -> Optional[str]:
    client = get_client()
    r = client.linked_accounts()
    if not r.ok:
        return None
    accounts = r.json()
    return accounts[0]["hashValue"] if accounts else None


def get_balances_and_positions() -> dict:
    client = get_client()
    acct_hash = get_account_hash()
    if not acct_hash:
        return {"error": "No linked account found"}

    r = client.account_details(acct_hash, fields="positions")
    if not r.ok:
        return {"error": r.text}

    data     = r.json()
    sec_acct = data.get("securitiesAccount", {})
    balances = sec_acct.get("currentBalances", {})
    positions = sec_acct.get("positions", [])

    pos_list = []
    for pos in positions:
        instr = pos.get("instrument", {})
        pos_list.append({
            "symbol":       instr.get("symbol", ""),
            "asset_type":   instr.get("assetType", ""),
            "quantity":     pos.get("longQuantity", 0),
            "market_value": pos.get("marketValue", 0),
            "avg_price":    pos.get("averagePrice", 0),
            "unrealized_pl": pos.get("currentDayProfitLoss", 0),
        })

    return {
        "cash_balance":       balances.get("cashBalance", 0),
        "buying_power":       balances.get("buyingPower", 0),
        "liquidation_value":  balances.get("liquidationValue", 0),
        "positions":          pos_list,
        "account_hash":       acct_hash,
    }


# ── Quotes ───────────────────────────────────────────────────────────────────

def get_quotes(symbols: list[str]) -> dict:
    client = get_client()
    r = client.quotes(symbols)
    if not r.ok:
        return {}
    raw = r.json()
    result = {}
    for sym, data in raw.items():
        q = data.get("quote", {})
        result[sym] = {
            "last":   q.get("lastPrice"),
            "bid":    q.get("bidPrice"),
            "ask":    q.get("askPrice"),
            "change": q.get("netChange"),
            "pct":    q.get("netPercentChangeInDouble"),
        }
    return result


# ── Orders ───────────────────────────────────────────────────────────────────

def preview_order(order: dict) -> dict:
    client    = get_client()
    acct_hash = get_account_hash()
    if not acct_hash:
        return {"error": "No account"}
    r = client.preview_order(acct_hash, order)
    try:
        return {"status": r.status_code, "body": r.json()}
    except Exception:
        return {"status": r.status_code, "body": r.text}


def place_order(order: dict) -> dict:
    client    = get_client()
    acct_hash = get_account_hash()
    if not acct_hash:
        return {"error": "No account"}
    r = client.place_order(acct_hash, order)
    order_id = r.headers.get("location", "/").split("/")[-1]
    return {"status": r.status_code, "order_id": order_id}


def cancel_order(order_id: str) -> dict:
    client    = get_client()
    acct_hash = get_account_hash()
    if not acct_hash:
        return {"error": "No account"}
    r = client.cancel_order(acct_hash, order_id)
    return {"status": r.status_code}


def build_limit_order(symbol: str, quantity: int, price: float, side: str = "BUY") -> dict:
    return {
        "orderType":          "LIMIT",
        "session":            "NORMAL",
        "duration":           "DAY",
        "orderStrategyType":  "SINGLE",
        "price":              str(round(price, 2)),
        "orderLegCollection": [{
            "instruction": side.upper(),
            "quantity":    quantity,
            "instrument":  {"symbol": symbol, "assetType": "EQUITY"},
        }],
    }


def build_market_order(symbol: str, quantity: int, side: str = "BUY") -> dict:
    return {
        "orderType":          "MARKET",
        "session":            "NORMAL",
        "duration":           "DAY",
        "orderStrategyType":  "SINGLE",
        "orderLegCollection": [{
            "instruction": side.upper(),
            "quantity":    quantity,
            "instrument":  {"symbol": symbol, "assetType": "EQUITY"},
        }],
    }


# ── Sweep recommendation ─────────────────────────────────────────────────────

def recommend_sweep(bank_balances: list[dict], brokerage: dict) -> Optional[dict]:
    """
    If total bank cash exceeds MIN_CASH_BUFFER by more than $500,
    recommend sweeping the excess into the configured sweep symbol.
    Returns a pending order dict or None.
    """
    from config import settings

    total_bank_cash = 0.0
    for b in bank_balances:
        try:
            total_bank_cash += float(b.get("available") or 0)
        except (ValueError, TypeError):
            pass

    excess = total_bank_cash - settings.min_cash_buffer
    if excess < 500:
        return None

    symbol = settings.sweep_symbol
    quotes = get_quotes([symbol])
    price  = quotes.get(symbol, {}).get("last") or quotes.get(symbol, {}).get("ask")
    if not price:
        return None

    shares = int(excess // price)
    if shares < 1:
        return None

    return {
        "type":        "sweep_recommendation",
        "symbol":      symbol,
        "shares":      shares,
        "approx_cost": round(shares * price, 2),
        "price":       price,
        "reason":      f"Bank cash ${total_bank_cash:,.0f} exceeds buffer ${settings.min_cash_buffer:,.0f} by ${excess:,.0f}",
        "order":       build_market_order(symbol, shares, "BUY"),
    }
