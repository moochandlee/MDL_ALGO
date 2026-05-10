"""
pages/settings_page.py — Configure credentials, thresholds, sync schedule
"""

import asyncio
from nicegui import ui
from pathlib import Path


async def render():
    with ui.column().classes('w-full min-h-screen bg-[#0a0f1e] p-6 gap-6'):

        with ui.row().classes('w-full items-center justify-between'):
            with ui.column().classes('gap-1'):
                ui.label('Settings').classes('text-2xl font-bold text-white')
                ui.label('Credentials, thresholds, and automation rules').classes('text-[#8899aa] text-sm')

        from config import settings, Settings
        cfg = settings

        # ── Integration status ────────────────────────────────────────
        with ui.card().classes('w-full bg-[#0d1526] border border-[#1e2d4a] rounded-xl p-6'):
            ui.label('Integration Status').classes('text-white font-semibold mb-4')
            status = cfg.is_configured()
            integrations = [
                ("schwab",  "Charles Schwab",  "candlestick_chart"),
                ("teller",  "Teller.io Banks", "account_balance"),
                ("email",   "Email (SMTP)",    "email"),
                ("push",    "iOS Push (ntfy)", "phone_iphone"),
            ]
            with ui.row().classes('gap-4 flex-wrap'):
                for key, label, icon in integrations:
                    ok = status.get(key, False)
                    with ui.card().classes(
                        f'bg-[#0a0f1e] border {"border-[#34d39955]" if ok else "border-[#ef444455]"} rounded-xl p-4'
                    ):
                        with ui.row().classes('items-center gap-2 mb-1'):
                            ui.icon(icon, size='1rem').style(f'color: {"#34d399" if ok else "#ef4444"}')
                            ui.label(label).classes('text-white text-sm font-medium')
                        ui.label('✓ Connected' if ok else '✗ Not configured').style(
                            f'color: {"#34d399" if ok else "#8899aa"}'
                        ).classes('text-xs')

        # ── .env file editor hint ─────────────────────────────────────
        with ui.card().classes('w-full bg-[#0d1526] border border-[#1e2d4a] rounded-xl p-6'):
            ui.label('Environment Configuration').classes('text-white font-semibold mb-2')
            ui.label(
                'All credentials are stored in a .env file in your app directory. '
                'Never commit this file to git.'
            ).classes('text-[#8899aa] text-sm mb-4')

            env_template = """\
# ── Schwab ──────────────────────────────
SCHWAB_APP_KEY=your_app_key
SCHWAB_APP_SECRET=your_app_secret
SCHWAB_CALLBACK_URL=https://127.0.0.1

# ── Teller ──────────────────────────────
TELLER_TOKEN=token_xxxxxxxx
TELLER_CERT=~/.teller/cert.pem
TELLER_KEY=~/.teller/key.pem
TELLER_APP_ID=app_xxxxxxxx

# ── Email ────────────────────────────────
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASSWORD=your_app_password
ALERT_EMAIL_TO=you@gmail.com

# ── iOS Push (ntfy.sh) ───────────────────
NTFY_TOPIC=finance-autopilot-yourprivatetopic

# ── Automation ───────────────────────────
MIN_CASH_BUFFER=2000
LOW_BALANCE_THRESHOLD=500
LARGE_DEBIT_THRESHOLD=200
SYNC_TIME=07:00
SWEEP_SYMBOL=SNSXX
DATA_DIR=./data"""

            with ui.card().classes('w-full bg-[#060c1a] border border-[#1e2d4a] rounded-lg p-4'):
                ui.label(env_template).classes('font-mono text-xs text-[#8899aa] whitespace-pre')

            def save_env():
                # Write template if no .env exists
                env_path = Path('.env')
                if not env_path.exists():
                    env_path.write_text(env_template)
                    ui.notify('.env template created — fill in your credentials', type='positive')
                else:
                    ui.notify('.env already exists — edit it directly', type='info')

            ui.button('Create .env Template', icon='create', on_click=save_env).props('flat').classes(
                'text-[#4fc3f7] mt-2'
            )

        # ── Threshold sliders ─────────────────────────────────────────
        with ui.card().classes('w-full bg-[#0d1526] border border-[#1e2d4a] rounded-xl p-6'):
            ui.label('Automation Thresholds').classes('text-white font-semibold mb-4')
            ui.label(
                'These read from your .env. To change them, edit .env and restart the app.'
            ).classes('text-[#8899aa] text-xs mb-4')

            thresholds = [
                ("Minimum cash buffer per account",   cfg.min_cash_buffer,   "#4fc3f7",
                 "Excess above this triggers a sweep recommendation"),
                ("Low balance alert threshold",       cfg.low_balance_alert, "#f59e0b",
                 "Sends email + push when account falls below this"),
                ("Large debit alert threshold",       cfg.large_debit_alert, "#ef4444",
                 "Sends email + push when a single debit exceeds this"),
            ]

            for label, val, color, desc in thresholds:
                with ui.card().classes('w-full bg-[#0a0f1e] border border-[#1e2d4a] rounded-lg p-4'):
                    with ui.row().classes('items-center justify-between mb-1'):
                        ui.label(label).classes('text-white text-sm font-medium')
                        ui.label(f"${val:,.0f}").style(f'color:{color}').classes('font-mono font-bold')
                    ui.label(desc).classes('text-[#8899aa] text-xs')

        # ── Sweep symbol info ─────────────────────────────────────────
        with ui.card().classes('w-full bg-[#0d1526] border border-[#1e2d4a] rounded-xl p-6'):
            ui.label('Sweep Target').classes('text-white font-semibold mb-3')

            with ui.row().classes('items-center gap-3 mb-3'):
                with ui.element('div').classes(
                    'w-12 h-12 rounded-xl bg-[#a78bfa22] border border-[#a78bfa55] '
                    'flex items-center justify-center'
                ):
                    ui.icon('savings', size='1.3rem').classes('text-[#a78bfa]')
                with ui.column().classes('gap-0'):
                    ui.label(cfg.sweep_symbol).classes('text-white font-bold text-lg')
                    ui.label('Current sweep target (set SWEEP_SYMBOL in .env)').classes('text-[#8899aa] text-xs')

            suggestions = [
                ("SNSXX", "Schwab Gov Money Market Fund", "Lowest risk, competitive yield, no transaction fees within Schwab"),
                ("SGOV",  "iShares 0-3 Month Treasury ETF", "T-bill ETF, slightly higher yield, tiny bid-ask spread"),
                ("BIL",   "SPDR 1-3 Month T-Bill ETF",     "Alternative T-bill ETF with high liquidity"),
                ("SPY",   "S&P 500 ETF",                   "Higher growth potential, higher volatility — for long-term idle cash"),
            ]

            for sym, name, desc in suggestions:
                current = "← current" if sym == cfg.sweep_symbol else ""
                with ui.row().classes('items-start gap-3 py-2 border-b border-[#1e2d4a]'):
                    ui.label(sym).classes('text-[#4fc3f7] font-mono font-bold text-sm w-14 shrink-0')
                    with ui.column().classes('gap-0'):
                        with ui.row().classes('items-center gap-2'):
                            ui.label(name).classes('text-white text-sm')
                            if current:
                                ui.badge('current', color='purple').classes('text-xs')
                        ui.label(desc).classes('text-[#8899aa] text-xs')

        # ── Daily sync schedule ───────────────────────────────────────
        with ui.card().classes('w-full bg-[#0d1526] border border-[#1e2d4a] rounded-xl p-6'):
            with ui.row().classes('items-center justify-between mb-3'):
                ui.label('Sync Schedule').classes('text-white font-semibold')
                ui.badge(f'Daily at {cfg.sync_time}', color='teal').classes('text-sm')

            ui.label(
                f'The app runs a full sync every day at {cfg.sync_time} local time. '
                'It fetches all Teller bank data, Schwab balances, checks thresholds, '
                'and sends any required notifications. Use "Sync Now" on the Dashboard '
                'to trigger an immediate update.'
            ).classes('text-[#8899aa] text-sm')

            ui.label('To change sync time: set SYNC_TIME=HH:MM in .env and restart.').classes(
                'text-[#4a5568] text-xs mt-2'
            )
