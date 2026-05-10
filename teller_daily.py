#!/usr/bin/env python3
"""
Teller.io Daily Financial Ledger
---------------------------------
Run every morning to get a full picture of your finances:

  • Fetches real balances from all linked accounts (development environment)
  • Incrementally syncs transactions (only pulls what's new + a 10-day
    lookback window to catch pending→posted date shifts)
  • Appends new rows to transactions.csv and upserts on transaction ID
  • Writes a fresh balances.csv snapshot with today's date
  • Prints a morning summary: balances, new transactions, and dates of
    importance (upcoming bills, large debits, low balance warnings)

FIRST-TIME SETUP
----------------
1. pip install requests pandas
2. Complete one Teller Connect enrollment in development mode to get your
   access token (run with --connect).  Save the printed token.
3. Add your cert/key paths and token to a .env file or pass as flags.

Daily use (after setup):
    python teller_daily.py --token TOKEN --cert cert.pem --key key.pem

Or store in a .env:
    TELLER_TOKEN=token_xxx
    TELLER_CERT=~/.teller/cert.pem
    TELLER_KEY=~/.teller/key.pem

Then just:
    python teller_daily.py

Schedule with cron (runs at 7 AM every day):
    0 7 * * * cd /path/to/script && python teller_daily.py >> teller.log 2>&1
"""

import argparse
import csv
import json
import os
import sys
import threading
import webbrowser
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# ---------------------------------------------------------------------------
# Optional .env loading (no python-dotenv required)
# ---------------------------------------------------------------------------
def load_dotenv():
    """Search for .env in script dir, then cwd. Expand ~ in values."""
    candidates = [
        Path(__file__).parent / ".env",   # same folder as the script
        Path.cwd() / ".env",              # current working directory
    ]
    for env_path in candidates:
        if env_path.exists():
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip('"').strip("'")
                        # Expand ~ so paths like ~/teller/cert.pem work
                        if v.startswith("~"):
                            v = str(Path(v).expanduser())
                        os.environ.setdefault(k, v)
            break   # stop after first found

load_dotenv()

try:
    import requests
except ImportError:
    sys.exit("Missing: pip install requests")
try:
    import pandas as pd
except ImportError:
    sys.exit("Missing: pip install pandas")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_URL        = "https://api.teller.io"
TELLER_VERSION  = "2020-10-12"
DEFAULT_PORT    = 8765
DATA_DIR        = Path(os.environ.get("TELLER_DATA_DIR", "./teller_data"))
BALANCES_CSV    = DATA_DIR / "balances.csv"
TRANSACTIONS_CSV= DATA_DIR / "transactions.csv"
STATE_FILE      = DATA_DIR / "sync_state.json"

# Thresholds for "dates of importance" alerts
LOW_BALANCE_THRESHOLD   = float(os.environ.get("LOW_BALANCE_THRESHOLD", "500"))
LARGE_DEBIT_THRESHOLD   = float(os.environ.get("LARGE_DEBIT_THRESHOLD", "200"))
LOOKBACK_DAYS           = 10   # catch pending→posted date shifts


# ---------------------------------------------------------------------------
# Teller Connect one-time enrollment flow (re-used from teller_balances.py)
# ---------------------------------------------------------------------------
_html_page:      str        = ""
_captured_token: str | None = None
_server_done:    threading.Event = threading.Event()


class ConnectHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass

    def do_GET(self):
        global _captured_token
        p = urlparse(self.path)
        if p.path in ("/", ""):
            self._send(200, _html_page)
        elif p.path == "/callback":
            token = (parse_qs(p.query).get("token") or [None])[0]
            if token:
                _captured_token = token
                self._send(200, "<h2 style='font-family:sans-serif;padding:2rem'>"
                                "Token captured! Switch back to your terminal.</h2>")
                _server_done.set()
            else:
                self._send(400, "<h2>❌ No token.</h2>")
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


def build_connect_page(app_id: str, port: int) -> str:
    cb = f"http://127.0.0.1:{port}/callback"
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"/>
<title>Teller Connect — Development</title>
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
  <p>Sign in with your real bank credentials. This is the development environment —
     Teller connects to your actual institution.</p>
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
        .then(function() {{ st.textContent = "Done! Check your terminal."; st.className = "ok"; }})
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


def run_connect_flow(app_id: str, port: int) -> str:
    """Open Teller Connect in the browser and return the captured token."""
    global _html_page
    _html_page = build_connect_page(app_id, port)
    srv = HTTPServer(("127.0.0.1", port), ConnectHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    url = f"http://127.0.0.1:{port}/"
    print(f"\n✅  Local server → {url}")
    webbrowser.open(url)
    print("Opening Teller Connect in your browser (development / real bank)…\n")

    print("Waiting for enrollment…  (Ctrl-C to abort)\n")
    if not _server_done.wait(timeout=300) or not _captured_token:
        srv.shutdown()
        sys.exit("Timed out. Please try again.")

    token = _captured_token
    print(f"\nToken captured: {token[:14]}…")
    print(f"\nSave this token — you won't need to log in again:\n\n    {token}\n")
    print("    Add it to .env:  TELLER_TOKEN=" + token)
    return token


# ---------------------------------------------------------------------------
# Teller API
# ---------------------------------------------------------------------------
def _headers():
    return {"Teller-Version": TELLER_VERSION}


def _get(url: str, token: str, cert, params: dict | None = None):
    r = requests.get(url, auth=(token, ""), headers=_headers(),
                     cert=cert, params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def fetch_accounts(token, cert):
    return _get(f"{BASE_URL}/accounts", token, cert)


def fetch_balance(token, cert, account_id: str):
    return _get(f"{BASE_URL}/accounts/{account_id}/balances", token, cert)


def fetch_transactions(token, cert, account_id: str,
                       start_date: str | None = None,
                       end_date:   str | None = None) -> list[dict]:
    params = {}
    if start_date: params["start_date"] = start_date
    if end_date:   params["end_date"]   = end_date
    return _get(f"{BASE_URL}/accounts/{account_id}/transactions", token, cert, params)


# ---------------------------------------------------------------------------
# State management (tracks last sync date per account)
# ---------------------------------------------------------------------------
def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2))


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------
BALANCE_COLS = [
    "snapshot_date", "account_id", "institution", "account_name",
    "account_type", "subtype", "available", "ledger",
]

TXN_COLS = [
    "transaction_id", "account_id", "institution", "account_name",
    "date", "description", "amount", "type", "status",
    "category", "counterparty", "running_balance", "fetched_date",
]


def load_csv(path: Path, cols: list[str]) -> pd.DataFrame:
    if path.exists():
        return pd.read_csv(path, dtype=str)
    return pd.DataFrame(columns=cols)


def save_csv(df: pd.DataFrame, path: Path):
    df.to_csv(path, index=False)


# ---------------------------------------------------------------------------
# Core daily sync
# ---------------------------------------------------------------------------
def sync(token: str, cert, verbose: bool = False):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    today     = date.today().isoformat()
    state     = load_state()
    accounts  = fetch_accounts(token, cert)

    if not accounts:
        print("No accounts found.")
        return

    # ---- Balances snapshot ------------------------------------------------
    bal_rows = []
    balances_by_id = {}

    for acct in accounts:
        aid  = acct["id"]
        inst = acct.get("institution", {}).get("name", "Unknown")
        name = acct.get("name", "")
        try:
            b = fetch_balance(token, cert, aid)
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
        except Exception as e:
            print(f"  ⚠ Balance fetch failed for {aid}: {e}")

    bal_df = load_csv(BALANCES_CSV, BALANCE_COLS)
    new_bal_df = pd.DataFrame(bal_rows, columns=BALANCE_COLS)
    bal_df = pd.concat([bal_df, new_bal_df], ignore_index=True)
    save_csv(bal_df, BALANCES_CSV)

    # ---- Transactions sync ------------------------------------------------
    txn_df      = load_csv(TRANSACTIONS_CSV, TXN_COLS)
    new_txn_rows = []

    for acct in accounts:
        aid  = acct["id"]
        inst = acct.get("institution", {}).get("name", "Unknown")
        name = acct.get("name", "")

        # Determine sync window: go back LOOKBACK_DAYS from last sync
        # (catches pending→posted date shifts), or 90 days on first run
        last_sync = state.get(aid)
        if last_sync:
            start = (datetime.fromisoformat(last_sync) - timedelta(days=LOOKBACK_DAYS)).date().isoformat()
        else:
            start = (date.today() - timedelta(days=90)).isoformat()

        try:
            txns = fetch_transactions(token, cert, aid, start_date=start, end_date=today)
        except Exception as e:
            print(f"  ⚠ Transaction fetch failed for {aid}: {e}")
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

    # Upsert: keep existing rows, overwrite on matching transaction_id
    if new_txn_rows:
        incoming = pd.DataFrame(new_txn_rows, columns=TXN_COLS)
        if not txn_df.empty:
            txn_df = txn_df[~txn_df["transaction_id"].isin(incoming["transaction_id"])]
        txn_df = pd.concat([txn_df, incoming], ignore_index=True)
        txn_df = txn_df.sort_values(["account_id", "date"], ascending=[True, False])

    save_csv(txn_df, TRANSACTIONS_CSV)
    save_state(state)

    return accounts, balances_by_id, txn_df, new_txn_rows


# ---------------------------------------------------------------------------
# Morning summary printer
# ---------------------------------------------------------------------------
def morning_summary(accounts, balances_by_id, txn_df, new_txn_rows):
    today     = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    week_ago  = (date.today() - timedelta(days=7)).isoformat()

    print()
    print("╔" + "═" * 62 + "╗")
    print(f"║{'Good morning — Teller Daily Ledger':^62}║")
    print(f"║{today:^62}║")
    print("╠" + "═" * 62 + "╣")

    # ── Balances ──────────────────────────────────────────────────────────
    print(f"║{'  ACCOUNT BALANCES':<62}║")
    print("╠" + "─" * 62 + "╣")

    alerts = []

    for acct in accounts:
        aid    = acct["id"]
        inst   = acct.get("institution", {}).get("name", "")
        name   = acct.get("name", "")
        b      = balances_by_id.get(aid, {})
        avail  = b.get("available")
        ledger = b.get("ledger")

        def fmt(v):
            try: return f"${float(v):>10,.2f}"
            except: return f"{'N/A':>11}"

        label = f"  {inst} · {name}"[:40]
        print(f"║  {label:<38}  Available: {fmt(avail)}  ║")
        print(f"║  {'':38}  Ledger:    {fmt(ledger)}  ║")

        # Low balance check
        try:
            if float(avail) < LOW_BALANCE_THRESHOLD:
                alerts.append(f"⚠️  LOW BALANCE: {inst} · {name} available ${float(avail):,.2f}")
        except (TypeError, ValueError):
            pass

    # ── New transactions (since yesterday) ────────────────────────────────
    recent = [r for r in new_txn_rows if r["date"] and r["date"] >= yesterday]

    print("╠" + "─" * 62 + "╣")
    print(f"║{'  NEW TRANSACTIONS (last 24 hrs)':<62}║")
    print("╠" + "─" * 62 + "╣")

    if recent:
        for r in sorted(recent, key=lambda x: x["date"], reverse=True):
            try:
                amt = float(r["amount"])
                amt_str = f"${abs(amt):>8,.2f} {'OUT' if amt > 0 else ' IN'}"
            except (TypeError, ValueError):
                amt_str = f"{'N/A':>12}"

            desc = (r["description"] or "")[:30]
            acct_label = (r["account_name"] or "")[:12]
            cat  = (r["category"] or "")[:10]
            print(f"║  {r['date']}  {desc:<30}  {amt_str}  ║")
            print(f"║  {'':10}  {acct_label:<12}  {cat:<10}{'':16}  ║")

            # Large debit check
            try:
                if float(r["amount"]) > LARGE_DEBIT_THRESHOLD:
                    alerts.append(f"🔔 LARGE DEBIT: ${float(r['amount']):,.2f} — {r['description']}")
            except (TypeError, ValueError):
                pass
    else:
        print(f"║  {'No new transactions since yesterday.':<60}║")

    # ── This week's spending summary ──────────────────────────────────────
    print("╠" + "─" * 62 + "╣")
    print(f"║{'  THIS WEEK':<62}║")
    print("╠" + "─" * 62 + "╣")

    if not txn_df.empty:
        week_df = txn_df[
            (txn_df["date"] >= week_ago) &
            (txn_df["date"] <= today) &
            (txn_df["status"] == "posted")
        ].copy()

        if not week_df.empty:
            week_df["amount"] = pd.to_numeric(week_df["amount"], errors="coerce")
            # Positive amounts = debits in Teller's convention
            spent   = week_df[week_df["amount"] > 0]["amount"].sum()
            income  = week_df[week_df["amount"] < 0]["amount"].abs().sum()
            net     = income - spent

            print(f"║  {'Spending (posted):':<30}  ${spent:>10,.2f}           ║")
            print(f"║  {'Income / credits:':<30}  ${income:>10,.2f}           ║")
            print(f"║  {'Net:':<30}  ${net:>+10,.2f}           ║")

            # Top categories
            cats = (
                week_df[week_df["amount"] > 0]
                .groupby("category")["amount"]
                .sum()
                .sort_values(ascending=False)
                .head(4)
            )
            if not cats.empty:
                print("╠" + "─" * 62 + "╣")
                print(f"║  {'Top spending categories (this week)':<60}║")
                for cat, amt in cats.items():
                    cat_label = (cat or "uncategorized")[:24]
                    print(f"║    {cat_label:<24}  ${amt:>8,.2f}                    ║")
        else:
            print(f"║  {'No posted transactions this week.':<60}║")
    else:
        print(f"║  {'No transaction history yet.':<60}║")

    # ── File locations ────────────────────────────────────────────────────
    print("╠" + "─" * 62 + "╣")
    print(f"║  📁 Data saved to:                                           ║")
    print(f"║     {str(BALANCES_CSV):<58}║")
    print(f"║     {str(TRANSACTIONS_CSV):<58}║")
    print("╚" + "═" * 62 + "╝")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Teller.io daily financial ledger — balances + transactions → CSV"
    )
    parser.add_argument("--connect",  action="store_true",
                        help="Run Teller Connect enrollment flow to get a token")
    parser.add_argument("--app-id",   default=os.environ.get("TELLER_APP_ID"),
                        help="Teller Application ID (required with --connect)")
    parser.add_argument("--token",    default=None,
                        help="Access token, or name of env var holding it (e.g. TELLER_COF_TOKEN)")
    parser.add_argument("--cert",     default=os.environ.get("TELLER_CERT"),
                        help="Path to client certificate (.pem) — required in development")
    parser.add_argument("--key",      default=os.environ.get("TELLER_KEY"),
                        help="Path to private key (.pem)         — required in development")
    parser.add_argument("--port",     type=int, default=DEFAULT_PORT,
                        help=f"Local server port for Connect flow (default {DEFAULT_PORT})")
    parser.add_argument("--data-dir", default=None,
                        help="Directory to store CSV files (default: ./teller_data)")
    parser.add_argument("--verbose",  action="store_true")
    args = parser.parse_args()

    # Override data dir if passed
    if args.data_dir:
        global DATA_DIR, BALANCES_CSV, TRANSACTIONS_CSV, STATE_FILE
        DATA_DIR         = Path(args.data_dir)
        BALANCES_CSV     = DATA_DIR / "balances.csv"
        TRANSACTIONS_CSV = DATA_DIR / "transactions.csv"
        STATE_FILE       = DATA_DIR / "sync_state.json"

    # ── Cert / key ──────────────────────────────────────────────────────
    cert_path = args.cert or os.environ.get("TELLER_CERT")
    key_path  = args.key  or os.environ.get("TELLER_KEY")

    if cert_path: cert_path = str(Path(cert_path).expanduser())
    if key_path:  key_path  = str(Path(key_path).expanduser())

    if not cert_path or not key_path:
        print("⚠️  No certificate/key provided. Development environment requires mTLS.")
        print("   Pass --cert and --key, or set TELLER_CERT / TELLER_KEY in .env\n")
        cert = None
    else:
        # Verify files actually exist before attempting the request
        missing = [p for p in [cert_path, key_path] if not Path(p).exists()]
        if missing:
            for m in missing:
                print(f"File not found: {m}")
            sys.exit("Fix the cert/key paths in your .env and try again.")
        print(f"  cert : {cert_path}")
        print(f"  key  : {key_path}")
        cert = (cert_path, key_path)

    # ── One-time enrollment ─────────────────────────────────────────────
    if args.connect:
        app_id = args.app_id
        if not app_id:
            app_id = input("Teller Application ID (app_xxxxxxxx): ").strip()
        if not app_id:
            sys.exit("Application ID required for --connect.")
        token = run_connect_flow(app_id, args.port)
    else:
        # Resolve token: --token can be a literal token or an env var name
        # Falls back to TELLER_TOKEN if nothing else is provided
        raw = args.token
        if raw:
            # If it looks like an env var name (all caps, underscores), resolve it
            token = os.environ.get(raw, raw)
        else:
            # Auto-detect: look for any TELLER_*_TOKEN or TELLER_TOKEN in env
            token = None
            for key, val in os.environ.items():
                if key == "TELLER_TOKEN" or (key.startswith("TELLER_") and key.endswith("_TOKEN")):
                    token = val
                    print(f"  Using token from env: {key}")
                    break
        if not token:
            sys.exit(
                "No token found.\n"
                "  First-time: run with --connect to enroll your bank account.\n"
                "  Daily use:  pass --token TELLER_COF_TOKEN (env var name) or the token directly,\n"
                "              or set TELLER_TOKEN / TELLER_COF_TOKEN in .env"
            )

    # ── Daily sync ──────────────────────────────────────────────────────
    print(f"\nSyncing with Teller API…  ({date.today().isoformat()})")
    result = sync(token, cert, verbose=args.verbose)

    if result:
        accounts, balances_by_id, txn_df, new_txn_rows = result
        morning_summary(accounts, balances_by_id, txn_df, new_txn_rows)


if __name__ == "__main__":
    main()