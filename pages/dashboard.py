"""
pages/dashboard.py — Main dashboard
"""

import asyncio
from nicegui import ui, app


async def render():
    with ui.column().classes('w-full min-h-screen bg-[#0a0f1e] p-6 gap-6'):

        # ── Header row ──────────────────────────────────────────────────
        with ui.row().classes('w-full items-center justify-between'):
            with ui.column().classes('gap-1'):
                ui.label('Dashboard').classes('text-2xl font-bold text-white')
                ui.label('Your money, at a glance').classes('text-[#8899aa] text-sm')

            with ui.row().classes('gap-3'):
                sync_btn = ui.button('Sync Now', icon='sync').props('flat').classes(
                    'text-[#4fc3f7] border border-[#1e2d4a] hover:bg-[#1e2d4a]'
                )

        # ── Status cards row ────────────────────────────────────────────
        cards_row = ui.row().classes('w-full gap-4 flex-wrap')

        # ── Pending sweep approvals ─────────────────────────────────────
        pending_section = ui.column().classes('w-full gap-3')

        # ── Two-column layout: bank accounts + brokerage ─────────────
        with ui.row().classes('w-full gap-6 flex-wrap items-start'):
            bank_col     = ui.column().classes('flex-1 min-w-[300px] gap-4')
            brokerage_col = ui.column().classes('flex-1 min-w-[300px] gap-4')

        # ── Quick quotes ─────────────────────────────────────────────
        quotes_row = ui.column().classes('w-full gap-3')

        # ── Render functions ─────────────────────────────────────────

        def _card(label, value, icon, color='#4fc3f7', sub=''):
            with ui.card().classes(
                'flex-1 min-w-[160px] bg-[#0d1526] border border-[#1e2d4a] rounded-xl p-5'
            ):
                with ui.row().classes('items-center gap-3 mb-3'):
                    with ui.element('div').classes(
                        f'w-10 h-10 rounded-lg flex items-center justify-center'
                    ).style(f'background: {color}22'):
                        ui.icon(icon, size='1.2rem').style(f'color: {color}')
                    ui.label(label).classes('text-[#8899aa] text-xs font-medium uppercase tracking-wider')
                ui.label(value).classes('text-white text-2xl font-bold font-mono')
                if sub:
                    ui.label(sub).classes('text-[#8899aa] text-xs mt-1')

        def _section_header(title, icon):
            with ui.row().classes('items-center gap-2 mb-2'):
                ui.icon(icon, size='1rem').classes('text-[#4fc3f7]')
                ui.label(title).classes('text-white font-semibold text-sm uppercase tracking-wider')

        async def load_data():
            # Clear containers
            cards_row.clear()
            pending_section.clear()
            bank_col.clear()
            brokerage_col.clear()
            quotes_row.clear()

            loading = ui.spinner('dots', size='lg', color='#4fc3f7')
            await asyncio.sleep(0.1)

            teller_balances = []
            schwab_data     = {}
            quotes          = {}

            try:
                from teller_client import get_latest_balances
                teller_balances = get_latest_balances()
            except Exception as e:
                ui.notify(f"Teller error: {e}", type='negative')

            try:
                from schwab_client import get_balances_and_positions, get_quotes
                schwab_data = get_balances_and_positions()
                symbols = list({p["symbol"] for p in schwab_data.get("positions", [])} | {"SPY","QQQ"})
                quotes  = get_quotes(symbols)
            except Exception as e:
                ui.notify(f"Schwab error: {e}", type='negative')

            loading.delete()

            # ── Summary cards ──────────────────────────────────────────
            with cards_row:
                total_bank = sum(
                    float(b.get("available") or 0)
                    for b in teller_balances
                )
                brok_liq = schwab_data.get("liquidation_value", 0)
                total    = total_bank + brok_liq

                _card("Total Net Worth",   f"${total:,.0f}",    "account_balance_wallet", "#4fc3f7")
                _card("Bank Cash",         f"${total_bank:,.0f}", "savings",              "#34d399")
                _card("Brokerage Value",   f"${brok_liq:,.0f}", "trending_up",            "#a78bfa")
                _card("Buying Power",      f"${schwab_data.get('buying_power', 0):,.0f}", "bolt", "#f59e0b")

            # ── Pending sweep approvals ────────────────────────────────
            pending = getattr(app.state, 'pending_orders', [])
            if pending:
                with pending_section:
                    _section_header("Pending Recommendations", "notifications_active")
                    for i, rec in enumerate(pending):
                        with ui.card().classes(
                            'w-full bg-[#0d1526] border border-[#f59e0b55] rounded-xl p-5'
                        ):
                            with ui.row().classes('items-start justify-between gap-4'):
                                with ui.column().classes('gap-1'):
                                    with ui.row().classes('items-center gap-2'):
                                        ui.badge('SWEEP RECOMMENDATION', color='amber').classes('text-xs')
                                        ui.label(f"Buy {rec['shares']}× {rec['symbol']} @ ~${rec['price']:.2f}").classes('text-white font-bold text-lg')
                                    ui.label(rec['reason']).classes('text-[#8899aa] text-sm')
                                    ui.label(f"Estimated cost: ${rec['approx_cost']:,.2f}").classes('text-[#4fc3f7] text-sm font-mono')

                                with ui.row().classes('gap-2 shrink-0'):
                                    async def approve(idx=i, r=rec):
                                        try:
                                            from schwab_client import place_order
                                            from notifications import notify_order_filled
                                            result = place_order(r["order"])
                                            if result.get("status") in (200, 201):
                                                app.state.pending_orders = [
                                                    o for j, o in enumerate(app.state.pending_orders) if j != idx
                                                ]
                                                notify_order_filled(r["symbol"], r["shares"], "BUY")
                                                ui.notify(f"Order placed! ID: {result.get('order_id')}", type='positive')
                                                await load_data()
                                            else:
                                                ui.notify(f"Order failed: {result}", type='negative')
                                        except Exception as e:
                                            ui.notify(f"Error: {e}", type='negative')

                                    def dismiss(idx=i):
                                        app.state.pending_orders = [
                                            o for j, o in enumerate(app.state.pending_orders) if j != idx
                                        ]
                                        pending_section.clear()

                                    ui.button('Approve', icon='check', on_click=approve).classes(
                                        'bg-[#059669] text-white font-semibold'
                                    )
                                    ui.button('Dismiss', icon='close', on_click=dismiss).props('flat').classes(
                                        'text-[#8899aa]'
                                    )

            # ── Bank Accounts ──────────────────────────────────────────
            with bank_col:
                _section_header("Bank Accounts", "account_balance")
                if not teller_balances:
                    ui.label("No bank data — check Teller config in Settings").classes('text-[#8899aa] text-sm')
                for b in teller_balances:
                    try:
                        avail  = float(b.get("available") or 0)
                        ledger = float(b.get("ledger") or 0)
                    except (ValueError, TypeError):
                        avail = ledger = 0.0

                    from config import settings as cfg
                    border = 'border-[#ef444455]' if avail < cfg.low_balance_alert else 'border-[#1e2d4a]'

                    with ui.card().classes(f'w-full bg-[#0d1526] border {border} rounded-xl p-4'):
                        with ui.row().classes('items-center justify-between mb-2'):
                            with ui.column().classes('gap-0'):
                                ui.label(b.get("institution","")).classes('text-[#8899aa] text-xs')
                                ui.label(b.get("account_name","")).classes('text-white font-semibold')
                            ui.badge(b.get("subtype","").replace("_"," ").title(), color='blue').classes('text-xs')

                        with ui.row().classes('gap-6'):
                            with ui.column().classes('gap-0'):
                                ui.label("Available").classes('text-[#8899aa] text-xs')
                                ui.label(f"${avail:,.2f}").classes('text-white font-mono font-bold')
                            with ui.column().classes('gap-0'):
                                ui.label("Ledger").classes('text-[#8899aa] text-xs')
                                ui.label(f"${ledger:,.2f}").classes('text-[#8899aa] font-mono text-sm')

                        if avail < cfg.low_balance_alert:
                            with ui.row().classes('items-center gap-1 mt-2'):
                                ui.icon('warning', size='0.9rem').classes('text-[#ef4444]')
                                ui.label('Below minimum threshold').classes('text-[#ef4444] text-xs')

            # ── Brokerage ─────────────────────────────────────────────
            with brokerage_col:
                _section_header("Brokerage Positions", "candlestick_chart")
                if "error" in schwab_data:
                    ui.label(f"Schwab error: {schwab_data['error']}").classes('text-[#ef4444] text-sm')
                elif not schwab_data.get("positions"):
                    with ui.card().classes('w-full bg-[#0d1526] border border-[#1e2d4a] rounded-xl p-4'):
                        ui.label("No open positions").classes('text-[#8899aa] text-sm')
                        cash = schwab_data.get("cash_balance", 0)
                        if cash > 500:
                            ui.label(f"${cash:,.2f} idle cash — consider investing").classes('text-[#f59e0b] text-sm mt-1')
                else:
                    for pos in schwab_data.get("positions", []):
                        sym = pos["symbol"]
                        q   = quotes.get(sym, {})
                        pl  = pos.get("unrealized_pl", 0)
                        pl_color = '#34d399' if pl >= 0 else '#ef4444'

                        with ui.card().classes('w-full bg-[#0d1526] border border-[#1e2d4a] rounded-xl p-4'):
                            with ui.row().classes('items-center justify-between'):
                                with ui.row().classes('items-center gap-3'):
                                    with ui.element('div').classes(
                                        'w-10 h-10 rounded-lg bg-[#1e2d4a] flex items-center justify-center'
                                    ):
                                        ui.label(sym[:3]).classes('text-white font-bold text-xs')
                                    with ui.column().classes('gap-0'):
                                        ui.label(sym).classes('text-white font-bold')
                                        ui.label(f"{pos['quantity']} shares").classes('text-[#8899aa] text-xs')
                                with ui.column().classes('items-end gap-0'):
                                    ui.label(f"${pos['market_value']:,.2f}").classes('text-white font-mono font-bold')
                                    ui.label(f"{'+'if pl>=0 else ''}{pl:,.2f}").style(f'color:{pl_color}').classes('text-xs font-mono')

                            if q.get("last"):
                                ui.separator().classes('my-2 bg-[#1e2d4a]')
                                with ui.row().classes('gap-4 text-xs'):
                                    ui.label(f"Last ${q['last']:.2f}").classes('text-[#8899aa]')
                                    if q.get("pct") is not None:
                                        pct_color = '#34d399' if q['pct'] >= 0 else '#ef4444'
                                        ui.label(f"{'+'if q['pct']>=0 else ''}{q['pct']:.2f}%").style(f'color:{pct_color}')

            # ── Quick market quotes ────────────────────────────────────
            with quotes_row:
                _section_header("Market Overview", "show_chart")
                with ui.row().classes('gap-4 flex-wrap'):
                    for sym, q in quotes.items():
                        if not q.get("last"):
                            continue
                        pct      = q.get("pct", 0) or 0
                        pct_col  = '#34d399' if pct >= 0 else '#ef4444'
                        pct_icon = 'arrow_upward' if pct >= 0 else 'arrow_downward'
                        with ui.card().classes('bg-[#0d1526] border border-[#1e2d4a] rounded-xl px-5 py-3'):
                            ui.label(sym).classes('text-[#8899aa] text-xs font-medium')
                            ui.label(f"${q['last']:.2f}").classes('text-white font-mono font-bold text-lg')
                            with ui.row().classes('items-center gap-1'):
                                ui.icon(pct_icon, size='0.75rem').style(f'color:{pct_col}')
                                ui.label(f"{abs(pct):.2f}%").style(f'color:{pct_col}').classes('text-xs font-mono')

        # Wire up sync button
        async def on_sync():
            sync_btn.props('loading=true')
            try:
                from scheduler import trigger_manual_sync
                await trigger_manual_sync()
                await load_data()
                ui.notify("Sync complete", type='positive')
            except Exception as e:
                ui.notify(f"Sync error: {e}", type='negative')
            finally:
                sync_btn.props('loading=false')

        sync_btn.on('click', on_sync)

        # Initial load
        await load_data()
