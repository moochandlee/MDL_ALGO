# Finance Autopilot

A NiceGUI web app that unifies your Charles Schwab brokerage and Teller.io bank accounts into one dashboard — with daily sync, email + iOS push alerts, and semi-automatic sweep recommendations.

---

## Architecture

```
finance_app/
├── main.py              # NiceGUI app, routes, nav shell
├── config.py            # Settings loaded from .env
├── teller_client.py     # Teller API: sync balances + transactions → CSV
├── schwab_client.py     # Schwab API: positions, quotes, orders, sweep logic
├── notifications.py     # Email (SMTP) + iOS push (ntfy.sh)
├── scheduler.py         # APScheduler: daily sync job
├── pages/
│   ├── dashboard.py     # Overview: balances, positions, sweep approvals
│   ├── ledger.py        # Transaction history with search/filter/export
│   ├── orders.py        # Order builder with preview → confirm flow
│   ├── alerts.py        # Notification test + history
│   └── settings_page.py # Config status, thresholds, .env guide
├── static/              # PWA icons (run generate_icons.py)
├── data/                # Auto-created: balances.csv, transactions.csv
├── generate_icons.py    # One-time icon generation
└── requirements.txt
```

---

## Quick Start

### 1. Install dependencies

```bash
cd finance_app
pip install -r requirements.txt
python generate_icons.py   # creates PWA icons
```

### 2. Create your `.env`

Copy the template from the Settings page, or run the app once and click **Create .env Template**.

```bash
# Key values needed:
SCHWAB_APP_KEY=...
SCHWAB_APP_SECRET=...
TELLER_TOKEN=...
TELLER_CERT=~/.teller/cert.pem
TELLER_KEY=~/.teller/key.pem
SMTP_USER=you@gmail.com
SMTP_PASSWORD=your_gmail_app_password   # NOT your real password — use App Password
ALERT_EMAIL_TO=you@gmail.com
NTFY_TOPIC=finance-autopilot-yourprivatetopic
```

### 3. Run

```bash
python main.py
```

Visit **http://localhost:8080**

---

## iOS Setup (PWA + Push)

### Install as PWA (home screen app)

1. Open **http://your-server-ip:8080** in Safari on iPhone
2. Tap the **Share** button → **Add to Home Screen**
3. Name it "Finance Autopilot" → Add
4. It opens full-screen like a native app, no browser chrome

> For this to work from iPhone, the app must be reachable on your local network.
> Run on your Mac/PC and connect both to the same Wi-Fi, or use a VPS (see below).

### iOS Push Notifications (ntfy.sh)

The app uses **[ntfy.sh](https://ntfy.sh)** — a free, open-source push notification service.
No Apple developer account needed.

1. Install **ntfy** from the App Store (free)
2. Tap **+** → subscribe to your private topic, e.g. `finance-autopilot-x7k2m9`
3. Set `NTFY_TOPIC=finance-autopilot-x7k2m9` in `.env`
4. Test from the **Alerts** page

> **Privacy note**: ntfy.sh topics are public URLs. Use a long random string as your topic
> name, or self-host ntfy on your own server for full privacy.

### Running on a VPS (access from anywhere)

```bash
# On your VPS (e.g. Digital Ocean $6/mo droplet):
pip install -r requirements.txt
python main.py

# Expose via nginx + SSL (recommended) or Tailscale (easier, private)
```

With **Tailscale** (easiest):
1. Install Tailscale on your Mac/server and iPhone
2. Run the app, access it at `http://your-tailscale-ip:8080` from your phone
3. No port forwarding, no SSL headaches, fully private

---

## How the Sweep Logic Works

Each daily sync:
1. Fetches all bank balances via Teller
2. Sums total available cash across all accounts
3. If `total_cash - MIN_CASH_BUFFER > $500`, calculates how many shares
   of `SWEEP_SYMBOL` (default: SNSXX money market) that buys
4. Queues a **pending recommendation** on the Dashboard
5. Sends email + iOS push notification
6. **You** tap Approve or Dismiss — nothing executes automatically

To change the sweep target, set `SWEEP_SYMBOL` in `.env`:
- `SNSXX` — Schwab Government Money Market (recommended, 0 transaction fees at Schwab)
- `SGOV` — iShares 0-3mo Treasury ETF (slightly higher yield)
- `SPY`  — S&P 500 (for longer-term idle cash)

---

## Gmail App Password Setup

Gmail requires an **App Password** (not your real password) for SMTP:

1. Go to Google Account → Security → 2-Step Verification (must be enabled)
2. Search "App passwords" → Create one for "Mail"
3. Use the 16-character code as `SMTP_PASSWORD` in `.env`

---

## Scheduled Sync

The app runs a full sync every day at `SYNC_TIME` (default `07:00`).

What it does:
- Incremental Teller transaction sync (10-day lookback to catch pending→posted shifts)
- Schwab balance + position refresh
- Low-balance alerts for any account below `LOW_BALANCE_THRESHOLD`
- Large-debit alerts for transactions above `LARGE_DEBIT_THRESHOLD`
- Sweep recommendation if idle cash exceeds buffer
- Daily summary push notification

Use **Sync Now** on the Dashboard for an immediate manual sync.

---

## Monthly Transfer Rules

On the **Orders** page, document your recurring transfers (paycheck → checking,
checking → brokerage, etc.). These are stored in-session and help you reason
about expected cash flow when reviewing sweep recommendations.

> Note: Schwab's API does not support automated ACH transfers — those must be
> set up in Schwab's web interface under "Transfers & Payments → Automatic".
> The app reminds you when to act if automation isn't possible.

---

## Data Storage

All data is stored locally as CSV files in `./data/`:
- `balances.csv` — daily balance snapshots per account
- `transactions.csv` — full transaction history (upserted by transaction ID)
- `sync_state.json` — last sync date per account for incremental fetching

No cloud storage, no third-party database.
