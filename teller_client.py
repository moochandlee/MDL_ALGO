"""
teller_client.py — async-friendly Teller API wrapper
"""

import requests
from datetime import date, datetime, timedelta
from pathlib import Path
import json
import pandas as pd
from config import settings

BASE_URL       = "https://api.teller.io"
TELLER_VERSION = "2020-10-12"
LOOKBACK_DAYS  = 10

BALANCE_COLS = [
    "snapshot_date","account_id","institution","account_name",
    "account_type","subtype","available","ledger",
]
TXN_COLS = [
    "transaction_id","account_id","institution","account_name",
    "date","description","amount","type","status",
    "category","counterparty","running_balance","fetched_date",
]

STATE_FILE = settings.data_dir / "sync_state.json"
BALANCES_CSV     = settings.data_dir / "balances.csv"
TRANSACTIONS_CSV = settings.data_dir / "transactions.csv"


def _headers():
    return {"Teller-Version": TELLER_VERSION}


def _get(path: str, params=None):
    cert  = settings.teller_cert_tuple()
    token = settings.teller_token
    r = requests.get(
        f"{BASE_URL}{path}",
        auth=(token, ""),
        headers=_headers(),
        cert=cert,
        params=params,
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


def fetch_accounts() -> list[dict]:
    return _get("/accounts")


def fetch_balance(account_id: str) -> dict:
    return _get(f"/accounts/{account_id}/balances")


def fetch_transactions(account_id: str, start_date=None, end_date=None) -> list[dict]:
    params = {}
    if start_date: params["start_date"] = start_date
    if end_date:   params["end_date"]   = end_date
    return _get(f"/accounts/{account_id}/transactions", params)


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def load_csv(path: Path, cols: list) -> pd.DataFrame:
    if path.exists() and path.stat().st_size > 0:
        try:
            return pd.read_csv(path, dtype=str)
        except Exception:
            pass
    return pd.DataFrame(columns=cols)


def sync_teller() -> dict:
    """
    Full incremental sync. Returns summary dict with keys:
      accounts, balances, new_transactions, total_transactions
    """
    today  = date.today().isoformat()
    state  = load_state()

    try:
        accounts = fetch_accounts()
    except Exception as e:
        return {"error": str(e), "accounts": [], "new_transactions": 0}

    # ── Balances ─────────────────────────────────────────────────────────
    bal_rows       = []
    balances_by_id = {}

    for acct in accounts:
        aid  = acct["id"]
        inst = acct.get("institution", {}).get("name", "Unknown")
        name = acct.get("name", "")
        try:
            b = fetch_balance(aid)
            balances_by_id[aid] = b
            bal_rows.append({
                "snapshot_date": today,
                "account_id":    aid,
                "institution":   inst,
                "account_name":  name,
                "account_type":  acct.get("type", ""),
                "subtype":       acct.get("subtype", ""),
                "available":     b.get("available"),
                "ledger":        b.get("ledger"),
            })
        except Exception:
            pass

    bal_df     = load_csv(BALANCES_CSV, BALANCE_COLS)
    new_bal_df = pd.DataFrame(bal_rows, columns=BALANCE_COLS)
    bal_df     = pd.concat([bal_df, new_bal_df], ignore_index=True)
    bal_df.to_csv(BALANCES_CSV, index=False)

    # ── Transactions ─────────────────────────────────────────────────────
    txn_df       = load_csv(TRANSACTIONS_CSV, TXN_COLS)
    new_txn_rows = []

    for acct in accounts:
        aid  = acct["id"]
        inst = acct.get("institution", {}).get("name", "Unknown")
        name = acct.get("name", "")

        last_sync = state.get(aid)
        if last_sync:
            start = (datetime.fromisoformat(last_sync) - timedelta(days=LOOKBACK_DAYS)).date().isoformat()
        else:
            start = (date.today() - timedelta(days=90)).isoformat()

        try:
            txns = fetch_transactions(aid, start_date=start, end_date=today)
        except Exception:
            continue

        for t in txns:
            details      = t.get("details") or {}
            counterparty = details.get("counterparty") or {}
            new_txn_rows.append({
                "transaction_id":  t["id"],
                "account_id":      aid,
                "institution":     inst,
                "account_name":    name,
                "date":            t.get("date"),
                "description":     t.get("description"),
                "amount":          t.get("amount"),
                "type":            t.get("type"),
                "status":          t.get("status"),
                "category":        details.get("category"),
                "counterparty":    counterparty.get("name"),
                "running_balance": t.get("running_balance"),
                "fetched_date":    today,
            })

        state[aid] = today

    if new_txn_rows:
        incoming = pd.DataFrame(new_txn_rows, columns=TXN_COLS)
        if not txn_df.empty:
            txn_df = txn_df[~txn_df["transaction_id"].isin(incoming["transaction_id"])]
        txn_df = pd.concat([txn_df, incoming], ignore_index=True)
        txn_df = txn_df.sort_values(["account_id","date"], ascending=[True, False])

    txn_df.to_csv(TRANSACTIONS_CSV, index=False)
    save_state(state)

    return {
        "accounts":          accounts,
        "balances_by_id":    balances_by_id,
        "new_transactions":  len(new_txn_rows),
        "total_transactions": len(txn_df),
        "synced_at":         today,
    }


def get_latest_balances() -> list[dict]:
    """Return most recent balance snapshot per account."""
    df = load_csv(BALANCES_CSV, BALANCE_COLS)
    if df.empty:
        return []
    latest = df.sort_values("snapshot_date").groupby("account_id").last().reset_index()
    return latest.to_dict("records")


def get_recent_transactions(days: int = 30) -> pd.DataFrame:
    df = load_csv(TRANSACTIONS_CSV, TXN_COLS)
    if df.empty:
        return df
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    df = df[df["date"] >= cutoff].copy()
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    return df.sort_values("date", ascending=False)
