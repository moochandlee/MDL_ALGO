"""
teller_client.py — async-friendly Teller API wrapper
"""

import asyncio
import json
import re
import threading
import webbrowser
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd
import requests

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
TOKENS_FILE      = settings.data_dir / "teller_tokens.json"

def load_teller_tokens() -> dict:
    if TOKENS_FILE.exists():
        try:
            return json.loads(TOKENS_FILE.read_text())
        except Exception:
            pass
    # Auto-migrate existing token from .env
    t = getattr(settings, 'teller_token', None)
    if t:
        tokens = {"capital_one": t}
        TOKENS_FILE.write_text(json.dumps(tokens, indent=2))
        return tokens
    return {}


def _headers():
    return {"Teller-Version": TELLER_VERSION}


def _get(path: str, params=None, token=None):
    cert  = settings.teller_cert_tuple()
    if not token:
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


def fetch_accounts(token=None) -> list[dict]:
    return _get("/accounts", token=token)


def fetch_balance(account_id: str, token=None) -> dict:
    return _get(f"/accounts/{account_id}/balances", token=token)


def fetch_transactions(account_id: str, start_date=None, end_date=None, token=None) -> list[dict]:
    params = {}
    if start_date: params["start_date"] = start_date
    if end_date:   params["end_date"]   = end_date
    return _get(f"/accounts/{account_id}/transactions", params, token=token)


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
    Full incremental sync across all tokens. Returns summary dict with keys:
      accounts, balances, new_transactions, total_transactions
    """
    today  = date.today().isoformat()
    state  = load_state()
    tokens = load_teller_tokens()

    all_accounts = []
    bal_rows       = []
    balances_by_id = {}
    new_txn_rows = []

    for label, token in tokens.items():
        try:
            accts = fetch_accounts(token=token)
            all_accounts.extend(accts)
        except Exception as e:
            print(f"Error fetching accounts for {label}: {e}")
            continue

        for acct in accts:
            aid  = acct["id"]
            inst = acct.get("institution", {}).get("name", "Unknown")
            name = acct.get("name", "")
            try:
                b = fetch_balance(aid, token=token)
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

            last_sync = state.get(aid)
            if last_sync:
                start = (datetime.fromisoformat(last_sync) - timedelta(days=LOOKBACK_DAYS)).date().isoformat()
            else:
                start = (date.today() - timedelta(days=90)).isoformat()

            try:
                txns = fetch_transactions(aid, start_date=start, end_date=today, token=token)
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

    # Sync account registry with newly fetched accounts
    from accounts import sync_from_teller
    sync_from_teller(all_accounts)

    bal_df     = load_csv(BALANCES_CSV, BALANCE_COLS)
    if bal_rows:
        new_bal_df = pd.DataFrame(bal_rows, columns=BALANCE_COLS)
        bal_df     = pd.concat([bal_df, new_bal_df], ignore_index=True)
        bal_df.to_csv(BALANCES_CSV, index=False)

    txn_df       = load_csv(TRANSACTIONS_CSV, TXN_COLS)

    if new_txn_rows:
        incoming = pd.DataFrame(new_txn_rows, columns=TXN_COLS)
        if not txn_df.empty:
            txn_df = txn_df[~txn_df["transaction_id"].isin(incoming["transaction_id"])]
        txn_df = pd.concat([txn_df, incoming], ignore_index=True)
        txn_df = txn_df.sort_values(["account_id","date"], ascending=[True, False])

    txn_df.to_csv(TRANSACTIONS_CSV, index=False)
    save_state(state)

    return {
        "accounts":          all_accounts,
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


# ── Teller Connect Enrollment Flow ─────────────────────────────────────

_connect_server: HTTPServer | None = None
_connect_event = threading.Event()
_connect_token: str | None = None
_connect_html: str = ""


class _ConnectHandler(BaseHTTPRequestHandler):
    """Minimal HTTP server that serves the Teller Connect widget and
    captures the access token from the /callback redirect."""

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        global _connect_token
        p = urlparse(self.path)
        if p.path in ("/", ""):
            self._send(200, _connect_html)
        elif p.path == "/callback":
            token = (parse_qs(p.query).get("token") or [None])[0]
            if token:
                _connect_token = token
                self._send(200, "<h2>Token captured! You can close this tab.</h2>")
                _connect_event.set()
            else:
                self._send(400, "<h2>No token received.</h2>")
        elif p.path == "/favicon.ico":
            self._send(204, "")
        else:
            self._send(404, "Not found")

    def _send(self, status, body):
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)


def _build_connect_page(app_id: str, port: int) -> str:
    cb = f"http://127.0.0.1:{port}/callback"
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"/>
<title>Teller Connect — Link Bank Account</title>
<style>
  body{{font-family:-apple-system,sans-serif;background:#f0f4f8;display:flex;
       align-items:center;justify-content:center;min-height:100vh;margin:0}}
  .card{{background:#fff;border-radius:16px;box-shadow:0 4px 24px rgba(0,0,0,.1);
         padding:48px 40px;max-width:440px;width:100%;text-align:center}}
  h1{{font-size:20px;font-weight:600;color:#1a1a2e;margin-bottom:8px}}
  p{{font-size:14px;color:#6b7280;margin-bottom:28px;line-height:1.5}}
  .badge{{display:inline-block;background:#dbeafe;color:#1e40af;border:1px solid #93c5fd;
          border-radius:6px;font-size:11px;font-weight:600;text-transform:uppercase;
          padding:3px 10px;margin-bottom:20px;letter-spacing:.5px}}
  button{{width:100%;padding:14px;font-size:15px;font-weight:600;color:#fff;
          background:#1a1a2e;border:none;border-radius:10px;cursor:pointer;margin-bottom:16px}}
  button:hover{{background:#2d2d4e}}
  button:disabled{{background:#9ca3af;cursor:not-allowed}}
  .hint{{font-size:12px;color:#9ca3af;line-height:1.7}}
  code{{background:#f3f4f6;padding:1px 5px;border-radius:4px;font-family:monospace;color:#374151}}
  #status{{margin-top:20px;font-size:14px;color:#6b7280;word-break:break-all}}
  #status.ok{{color:#059669;font-weight:600}} #status.err{{color:#dc2626}}
</style></head><body>
<div class="card">
  <span class="badge">Development Mode — Real Bank Data</span>
  <h1>Connect your bank account</h1>
  <p>Sign in with your real bank credentials. Teller connects to your actual institution.</p>
  <button id="btn">Connect to your bank</button>
  <p class="hint">App ID: <code>{app_id}</code></p>
  <div id="status"></div>
</div>
<script src="https://cdn.teller.io/connect/connect.js"></script>
<script>
document.addEventListener("DOMContentLoaded", function() {{
  var btn = document.getElementById("btn");
  var st  = document.getElementById("status");
  var tc  = TellerConnect.setup({{
    applicationId: "{app_id}",
    environment:   "development",
    products:      ["balance","transactions","identity"],
    onSuccess: function(e) {{
      st.textContent = "⏳ Sending token…"; btn.disabled = true;
      fetch("{cb}?token=" + encodeURIComponent(e.accessToken))
        .then(function() {{ st.textContent = "Done! Check your app."; st.className = "ok"; }})
        .catch(function() {{
          st.innerHTML = "Copy token manually:<br><code>" + e.accessToken + "</code>";
          st.className = "err";
        }});
    }},
    onExit:    function() {{ if (!btn.disabled) st.textContent = "Closed without enrolling."; }},
    onFailure: function(f) {{ st.textContent = "❌" + (f.message||"Failed"); st.className="err"; btn.disabled=false; }},
  }});
  btn.addEventListener("click", function() {{ tc.open(); }});
}});
</script></body></html>"""


def _migrate_token_labels() -> dict:
    """Rename any ``bank_N`` labels in the token file to real institution names.
    Returns the updated tokens dict (or the current one if nothing changed)."""
    try:
        tokens = load_teller_tokens()
    except Exception:
        return load_teller_tokens()

    changed = False
    for label, token in list(tokens.items()):
        if re.match(r'^bank_\d+$', label):
            try:
                accounts = fetch_accounts(token=token)
                if accounts:
                    inst = accounts[0].get("institution", {}).get("name", "")
                    if inst:
                        new_label = inst.lower().replace(" ", "_")
                        final = new_label
                        counter = 1
                        while final in tokens and tokens[final] != token:
                            counter += 1
                            final = f"{new_label}_{counter}"
                        if final != label:
                            del tokens[label]
                            tokens[final] = token
                            changed = True
            except Exception:
                continue

    if changed:
        TOKENS_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKENS_FILE.write_text(json.dumps(tokens, indent=2))

    return tokens


async def connect_bank(app_id: str, port: int = 8765, label: str | None = None) -> str:
    """
    Run the Teller Connect enrollment flow from within the app.

    Starts a local HTTP server, opens the browser with the Teller Connect
    widget, waits for the user to complete enrollment, saves the new token
    to ``data/teller_tokens.json``, and returns the captured token.

    Parameters
    ----------
    app_id : str
        Your Teller Application ID (``app_...``).
    port : int
        Local port for the OAuth callback server (default 8765).
    label : str, optional
        A friendly label for this bank connection (e.g. ``"chase"``).
        Auto-generated from an incrementing counter if omitted.

    Returns
    -------
    str
        The captured access token.
    """
    global _connect_html, _connect_event, _connect_token, _connect_server

    _connect_html = _build_connect_page(app_id, port)
    _connect_event.clear()
    _connect_token = None

    # Start local HTTP server on a background thread
    try:
        server = HTTPServer(("127.0.0.1", port), _ConnectHandler)
    except OSError:
        # Port in use — let the OS pick a free one
        server = HTTPServer(("127.0.0.1", 0), _ConnectHandler)
        port = server.server_address[1]

    _connect_server = server
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    # Open the browser to the Teller Connect page
    webbrowser.open(f"http://127.0.0.1:{port}/")

    # Wait for callback (non-blocking via executor)
    loop = asyncio.get_event_loop()
    ok = await loop.run_in_executor(None, lambda: _connect_event.wait(timeout=300))

    server.shutdown()
    _connect_server = None

    if not ok or not _connect_token:
        raise TimeoutError(
            "Teller Connect timed out (5 minutes). "
            "Close any lingering browser tabs at http://127.0.0.1:8765 and try again."
        )

    # Auto-generate label if not provided
    if not label:
        tokens = load_teller_tokens()
        label = f"bank_{len(tokens) + 1}"

    # Save token to multi-token store, merging any .env token
    TOKENS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tokens = load_teller_tokens()

    # Pull in any token from .env so everything stays consolidated
    env_token = getattr(settings, 'teller_token', None)
    if env_token and env_token not in tokens.values():
        tokens.setdefault("capital_one", env_token)

    tokens[label] = _connect_token
    TOKENS_FILE.write_text(json.dumps(tokens, indent=2))

    # Identify the institution from the first account and rename label
    try:
        accounts = fetch_accounts(token=_connect_token)
        if accounts:
            inst_name = accounts[0].get("institution", {}).get("name", "")
            if inst_name:
                inst_label = inst_name.lower().replace(" ", "_")
                # Deduplicate: append _2, _3 etc if label already taken
                final_label = inst_label
                counter = 1
                while final_label in tokens and tokens[final_label] != _connect_token:
                    counter += 1
                    final_label = f"{inst_label}_{counter}"
                # Rename the key
                if final_label != label:
                    del tokens[label]
                    tokens[final_label] = _connect_token
                    TOKENS_FILE.write_text(json.dumps(tokens, indent=2))
    except Exception:
        pass  # Keep auto-generated label as fallback

    # Trigger a sync so data appears on dashboard/ledger immediately
    try:
        sync_teller()
    except Exception as e:
        print(f"Post-link sync warning: {e}")

    # Migrate any existing bank_N labels from previous enrollments
    try:
        _migrate_token_labels()
    except Exception:
        pass

    return _connect_token
