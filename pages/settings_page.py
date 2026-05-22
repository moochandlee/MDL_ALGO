"""
pages/settings_page.py — System settings and account registry management
"""

import asyncio
from nicegui import ui
from pathlib import Path


async def render():
    with ui.column().classes('w-full min-h-screen bg-[#0a0f1e] p-6 gap-6'):

        with ui.row().classes('w-full items-center justify-between'):
            with ui.column().classes('gap-1'):
                ui.label('Settings').classes('text-2xl font-bold text-white')
                ui.label('Credentials, accounts, and sync schedule').classes('text-[#8899aa] text-sm')

        from config import settings, Settings
        cfg = settings

        # ── Tabs ────────────────────────────────────────────────────────
        with ui.tabs().classes('w-full') as tabs:
            ui.tab('System', icon='settings')
            ui.tab('Accounts', icon='account_balance')

        with ui.tab_panels(tabs, value='System').classes('w-full'):

            # ═══════════════════════════════════════════════════════════════
            # SYSTEM TAB
            # ═══════════════════════════════════════════════════════════════
            with ui.tab_panel('System'):

                # ── Integration status ────────────────────────────────────
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

                # ── Daily sync schedule ───────────────────────────────────
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

                # ── Test Notifications ────────────────────────────────────
                with ui.card().classes('w-full bg-[#0d1526] border border-[#1e2d4a] rounded-xl p-6'):
                    ui.label('Test Notifications').classes('text-white font-semibold mb-3')
                    ui.label('Verify your email and iOS push are configured correctly.').classes('text-[#8899aa] text-sm mb-4')

                    with ui.row().classes('gap-3 flex-wrap'):
                        async def test_email():
                            from notifications import send_email, _alert_email_html
                            ok = send_email(
                                "Test Alert",
                                _alert_email_html("Test Alert", [{
                                    "title": "Finance Autopilot is working!",
                                    "body": "Your email notifications are configured correctly.",
                                    "level": "info",
                                }])
                            )
                            ui.notify("Email sent!" if ok else "Email failed — check SMTP settings", type='positive' if ok else 'negative')

                        async def test_push():
                            from notifications import send_push
                            ok = send_push(
                                "Finance Autopilot",
                                "Your iOS push notifications are working!",
                                priority="default",
                                tags=["white_check_mark"]
                            )
                            ui.notify("Push sent!" if ok else "Push failed — check NTFY_TOPIC in settings", type='positive' if ok else 'negative')

                        async def test_sweep():
                            from notifications import notify_sweep_recommendation
                            notify_sweep_recommendation("SNSXX", 50, 500.00, "Test sweep recommendation")
                            ui.notify("Test sweep notification sent", type='positive')

                        ui.button('Test Email', icon='email', on_click=test_email).classes(
                            'bg-[#1e2d4a] text-[#4fc3f7]'
                        )
                        ui.button('Test iOS Push', icon='phone_iphone', on_click=test_push).classes(
                            'bg-[#1e2d4a] text-[#4fc3f7]'
                        )
                        ui.button('Test Sweep Alert', icon='trending_up', on_click=test_sweep).classes(
                            'bg-[#1e2d4a] text-[#4fc3f7]'
                        )

            # ═══════════════════════════════════════════════════════════════
            # ACCOUNTS TAB
            # ═══════════════════════════════════════════════════════════════
            with ui.tab_panel('Accounts'):

                # ── Linked Bank Accounts (Teller) ─────────────────────────
                with ui.card().classes('w-full bg-[#0d1526] border border-[#1e2d4a] rounded-xl p-6'):
                    with ui.row().classes('items-center justify-between w-full mb-3'):
                        ui.label('Linked Bank Accounts').classes('text-white font-semibold')
                        ui.badge('Teller.io', color='blue').classes('text-xs')

                    token_container = ui.column().classes('gap-2 w-full')

                    def rebuild_tokens():
                        token_container.clear()
                        with token_container:
                            from teller_client import load_teller_tokens, _migrate_token_labels
                            tokens = _migrate_token_labels()
                            if tokens:
                                for lbl in tokens:
                                    with ui.row().classes('items-center gap-2 bg-[#0a0f1e] rounded-lg px-3 py-2 border border-[#1e2d4a]'):
                                        ui.icon('account_balance', size='1rem').classes('text-[#4fc3f7]')
                                        ui.label(lbl.replace("_", " ").title()).classes('text-white text-sm')
                                        ui.label('••••••••••').classes('text-[#4a5568] text-xs font-mono')
                            else:
                                ui.label('No bank accounts linked yet.').classes('text-[#8899aa] text-sm')

                    rebuild_tokens()

                    app_id_dialog = ui.dialog()
                    with app_id_dialog, ui.card().classes('bg-[#0d1526] border border-[#1e2d4a] rounded-xl p-6'):
                        ui.label('Link a Bank Account').classes('text-white font-semibold text-lg mb-2')
                        ui.label('Enter your Teller Application ID to start the connection flow.').classes(
                            'text-[#8899aa] text-sm mb-4')
                        app_id_input = ui.input('Application ID',
                                                 placeholder='app_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx',
                                                 value=cfg.teller_app_id).classes('w-80')
                        app_id_input.props('dense outlined dark')

                        with ui.row().classes('gap-3 mt-4'):
                            ui.button('Cancel', on_click=app_id_dialog.close).props('flat').classes('text-[#8899aa]')
                            link_btn = ui.button('Open Teller Connect',
                                                 icon='link').classes('bg-[#4fc3f7] text-white font-semibold')

                            async def on_link():
                                aid = app_id_input.value.strip()
                                if not aid:
                                    ui.notify('Enter your Teller Application ID', type='warning')
                                    return
                                app_id_dialog.close()
                                link_btn.props('loading=true')
                                try:
                                    from teller_client import connect_bank
                                    token = await connect_bank(aid)
                                    ui.notify(f'Bank linked! Token saved.', type='positive')
                                    rebuild_tokens()
                                except TimeoutError:
                                    ui.notify('Timed out waiting for Teller enrollment.', type='negative')
                                except Exception as e:
                                    ui.notify(f'Error: {e}', type='negative')
                                finally:
                                    link_btn.props('loading=false')

                            link_btn.on('click', on_link)

                    def _safe_notify(msg: str, type='positive'):
                        try:
                            ui.notify(msg, type=type)
                        except RuntimeError:
                            pass

                    async def _start_connect():
                        from teller_client import connect_bank
                        if not cfg.teller_app_id:
                            app_id_dialog.open()
                            return
                        try:
                            link_btn.props('loading=true')
                        except RuntimeError:
                            pass
                        try:
                            token = await connect_bank(cfg.teller_app_id)
                            _safe_notify('Bank linked! Token saved.')
                            try:
                                rebuild_tokens()
                            except RuntimeError:
                                pass
                        except TimeoutError:
                            _safe_notify('Timed out waiting for Teller enrollment.', 'negative')
                        except Exception as e:
                            _safe_notify(f'Error: {e}', 'negative')
                        finally:
                            try:
                                link_btn.props('loading=false')
                            except RuntimeError:
                                pass

                    ui.button('Link Bank Account', icon='add_link',
                              on_click=_start_connect).props('flat').classes(
                        'text-[#4fc3f7] mt-2')

                # ── Credit Card Dates ───────────────────────────────────────
                with ui.card().classes('w-full bg-[#0d1526] border border-[#1e2d4a] rounded-xl p-6'):
                    with ui.row().classes('items-center justify-between w-full mb-3'):
                        ui.label('Credit Card Statement & Payment Dates').classes('text-white font-semibold')
                        ui.badge('per card', color='orange').classes('text-xs')

                    ui.label('Set the statement closing date and payment due date for each card. '
                             'This lets the cash flow forecast show when payments hit your checking account.').classes(
                        'text-[#8899aa] text-xs mb-4')

                    cc_container = ui.column().classes('gap-3 w-full')

                    def rebuild_cc_settings():
                        cc_container.clear()
                        with cc_container:
                            from accounts import load_registry, save_registry, ensure_registry_from_balances

                            registry = load_registry()
                            if not registry:
                                registry = ensure_registry_from_balances()
                            cards = [v for v in registry.values() if v.get("type") == "credit"]

                            if not cards:
                                ui.label('No credit cards found from linked accounts.').classes('text-[#8899aa] text-sm')
                                return

                            for card in cards:
                                aid = card.get("id", "")
                                inst = card.get("institution", "")
                                name = card.get("name", "")
                                sd_val = int(card.get("statement_day") or 15)
                                pd_val = int(card.get("payment_due_day") or 1)

                                with ui.row().classes('items-center gap-4 bg-[#0a0f1e] rounded-lg px-4 py-3 border border-[#1e2d4a] w-full'):
                                    ui.label(f"{inst} · {name}").classes('text-white text-sm font-medium w-48')

                                    ui.label('Statement day').classes('text-[#8899aa] text-xs')
                                    sd_in = ui.number('', value=sd_val, min=1, max=31).props('dense').classes('w-16')

                                    ui.label('Payment due').classes('text-[#8899aa] text-xs')
                                    pd_in = ui.number('', value=pd_val, min=1, max=31).props('dense').classes('w-16')

                                    def save_card(aid=aid, sd=sd_in, pd=pd_in, inst=inst, name=name):
                                        async def _save():
                                            reg = load_registry()
                                            if aid not in reg:
                                                reg[aid] = {"id": aid, "institution": inst, "name": name,
                                                             "type": "credit", "subtype": "credit_card",
                                                             "display_order": len(reg), "statement_day": None,
                                                             "payment_due_day": None}
                                            reg[aid]["statement_day"] = int(sd.value)
                                            reg[aid]["payment_due_day"] = int(pd.value)
                                            save_registry(reg)
                                            ui.notify(f"{inst} {name} dates saved", type='positive')
                                        return _save

                                    ui.button('Save', icon='check', on_click=save_card()) \
                                        .props('flat dense').classes('text-[#34d399] text-xs')

                    rebuild_cc_settings()

                # ── Manual Assets & Liabilities ──────────────────────────────
                with ui.card().classes('w-full bg-[#0d1526] border border-[#1e2d4a] rounded-xl p-6'):
                    with ui.row().classes('items-center justify-between w-full mb-3'):
                        ui.label('Manual Assets & Liabilities').classes('text-white font-semibold')
                        ui.badge('tracked items', color='purple').classes('text-xs')

                    ui.label('Add manually-tracked items like ASPP or student loans to the account registry. '
                             'Click a loan to manage its details (balance, rate, payment) on the Dashboard.').classes(
                        'text-[#8899aa] text-xs mb-4')

                    manual_container = ui.column().classes('gap-2 w-full')

                    def rebuild_manual():
                        manual_container.clear()
                        with manual_container:
                            from accounts import load_registry, get_manual_items, remove_manual_item

                            registry = load_registry()
                            items = get_manual_items(registry)

                            if items:
                                for item in items:
                                    with ui.row().classes('items-center justify-between bg-[#0a0f1e] rounded-lg px-3 py-2 border border-[#1e2d4a]'):
                                        with ui.row().classes('items-center gap-3'):
                                            icon = 'monetization_on' if item['type'] == 'manual_asset' else 'savings'
                                            color = '#34d399' if item['type'] == 'manual_asset' else '#ef4444'
                                            ui.icon(icon, size='1rem').style(f'color:{color}')
                                            ui.label(item['name']).classes('text-white text-sm')
                                            inst = item.get('institution', '')
                                            if inst:
                                                ui.label(f"({inst})").classes('text-[#8899aa] text-xs')
                                            ui.label(item['subtype']).classes('text-[#4a5568] text-xs')

                                        def on_remove(iid=item['id']):
                                            reg = load_registry()
                                            if remove_manual_item(reg, iid):
                                                ui.notify('Removed from registry', type='positive')
                                                rebuild_manual()

                                        ui.button(icon='delete', on_click=on_remove) \
                                            .props('flat dense round').classes('text-[#ef4444]')
                            else:
                                ui.label('No manual items tracked yet.').classes('text-[#8899aa] text-sm')

                            add_dialog = ui.dialog()
                            with add_dialog, ui.card().classes('bg-[#0d1526] border border-[#1e2d4a] rounded-xl p-6'):
                                ui.label('Add Manual Item').classes('text-white font-semibold text-lg mb-2')
                                ui.label('Select the type of item to track.').classes('text-[#8899aa] text-sm mb-4')

                                item_type = ui.select(
                                    label='Item Type',
                                    options={
                                        'aspp': 'ASPP - Employee Stock Purchase Plan',
                                        'loan': 'Student Loan',
                                    },
                                    value='aspp',
                                ).classes('w-full').props('dense outlined dark')

                                name_input = ui.input('Display Name', value='ASPP').classes('w-full').props('dense outlined dark')
                                inst_input = ui.input('Institution / Lender (optional)').classes('w-full').props('dense outlined dark')

                                async def on_add():
                                    st = item_type.value
                                    nm = name_input.value.strip() or 'Untitled'
                                    inst = inst_input.value.strip()
                                    reg = load_registry()

                                    if st == 'aspp' and any(e.get('subtype') == 'aspp' for e in reg.values()):
                                        ui.notify('ASPP is already in the registry', type='warning')
                                        return

                                    from accounts import add_manual_item
                                    add_manual_item(reg, 'manual_asset' if st == 'aspp' else 'manual_liability',
                                                    st, nm, institution=inst)
                                    ui.notify(f'Added {nm} to registry', type='positive')
                                    add_dialog.close()
                                    name_input.value = 'ASPP'
                                    inst_input.value = ''
                                    rebuild_manual()

                                with ui.row().classes('gap-3 mt-4'):
                                    ui.button('Cancel', on_click=add_dialog.close).props('flat').classes('text-[#8899aa]')
                                    ui.button('Add', icon='add', on_click=on_add).classes('bg-[#4fc3f7] text-white font-semibold')

                            ui.button('Add Manual Item', icon='add_circle_outline',
                                      on_click=add_dialog.open).props('flat').classes('text-[#a78bfa] mt-2')

                    rebuild_manual()
