"""
pages/orders.py — Order placement with preview/confirm flow
"""

import asyncio
from nicegui import ui


async def render():
    with ui.column().classes('w-full min-h-screen bg-[#0a0f1e] p-6 gap-6'):

        # ── Header ──────────────────────────────────────────────────────
        with ui.row().classes('w-full items-center justify-between'):
            with ui.column().classes('gap-1'):
                ui.label('Orders').classes('text-2xl font-bold text-white')
                ui.label('Preview before every trade — nothing executes without your approval').classes('text-[#8899aa] text-sm')

        # ── Two panels ──────────────────────────────────────────────────
        with ui.row().classes('w-full gap-6 flex-wrap items-start'):

            # ── Order builder ──────────────────────────────────────────
            with ui.card().classes('flex-1 min-w-[300px] bg-[#0d1526] border border-[#1e2d4a] rounded-xl p-6'):
                ui.label('New Order').classes('text-white font-semibold mb-4')

                symbol_input = ui.input(label='Symbol', placeholder='e.g. AAPL').classes('w-full')
                symbol_input.props('outlined dark dense')

                with ui.row().classes('gap-4 w-full'):
                    side_select = ui.select(['BUY', 'SELL'], value='BUY', label='Side').classes('flex-1')
                    side_select.props('outlined dark dense')

                    order_type = ui.select(['LIMIT', 'MARKET'], value='LIMIT', label='Type').classes('flex-1')
                    order_type.props('outlined dark dense')

                qty_input = ui.number(label='Quantity (shares)', value=1, min=1, step=1).classes('w-full')
                qty_input.props('outlined dark dense')

                price_input = ui.number(label='Limit Price ($)', value=0.0, min=0, step=0.01).classes('w-full')
                price_input.props('outlined dark dense')

                def toggle_price():
                    price_input.set_visibility(order_type.value == 'LIMIT')

                order_type.on('update:model-value', lambda _: toggle_price())

                # Quote lookup
                quote_label = ui.label('').classes('text-[#4fc3f7] text-sm font-mono')

                async def lookup_quote():
                    sym = symbol_input.value.upper().strip()
                    if not sym:
                        return
                    try:
                        from schwab_client import get_quotes
                        q = get_quotes([sym]).get(sym, {})
                        if q.get("last"):
                            price_input.set_value(q["last"])
                            quote_label.set_text(
                                f"{sym}  Last ${q['last']:.2f}  Bid ${q.get('bid','—')}  Ask ${q.get('ask','—')}"
                            )
                        else:
                            quote_label.set_text("No quote found")
                    except Exception as e:
                        quote_label.set_text(f"Error: {e}")

                ui.button('Get Quote', icon='refresh', on_click=lookup_quote).props('flat').classes(
                    'text-[#4fc3f7] self-start'
                )

                preview_area = ui.column().classes('w-full gap-3 mt-2')

                async def build_preview():
                    preview_area.clear()
                    sym  = symbol_input.value.upper().strip()
                    qty  = int(qty_input.value or 1)
                    side = side_select.value
                    otype= order_type.value
                    price= float(price_input.value or 0)

                    if not sym or qty < 1:
                        ui.notify("Enter symbol and quantity", type='warning')
                        return

                    from schwab_client import build_limit_order, build_market_order, preview_order

                    if otype == 'LIMIT':
                        order = build_limit_order(sym, qty, price, side)
                    else:
                        order = build_market_order(sym, qty, side)

                    with preview_area:
                        with ui.card().classes('w-full bg-[#0a0f1e] border border-[#4fc3f755] rounded-xl p-4'):
                            ui.label('Order Preview').classes('text-[#4fc3f7] font-semibold text-sm mb-3')

                            est_cost = qty * price if otype == 'LIMIT' else None

                            rows = [
                                ("Symbol",   sym),
                                ("Side",     side),
                                ("Type",     otype),
                                ("Quantity", str(qty)),
                            ]
                            if est_cost:
                                rows.append(("Est. Cost", f"${est_cost:,.2f}"))

                            for label, val in rows:
                                with ui.row().classes('justify-between text-sm'):
                                    ui.label(label).classes('text-[#8899aa]')
                                    ui.label(val).classes('text-white font-mono')

                            ui.separator().classes('my-3 bg-[#1e2d4a]')

                            # Schwab preview call
                            spinner = ui.spinner('dots', color='#4fc3f7')
                            await asyncio.sleep(0.1)
                            try:
                                result = preview_order(order)
                                spinner.delete()
                                status = result.get("status")
                                if status in (200, 201):
                                    ui.label('✓ Schwab preview accepted').classes('text-[#34d399] text-sm')
                                else:
                                    body = result.get("body", "")
                                    ui.label(f'Preview response: {status}').classes('text-[#f59e0b] text-sm')
                                    if body:
                                        ui.label(str(body)[:200]).classes('text-[#8899aa] text-xs')
                            except Exception as e:
                                spinner.delete()
                                ui.label(f'Preview failed: {e}').classes('text-[#ef4444] text-sm')

                            ui.separator().classes('my-3 bg-[#1e2d4a]')

                            with ui.row().classes('gap-3 justify-end'):
                                async def confirm_order(o=order, s=sym, q=qty, sd=side):
                                    try:
                                        from schwab_client import place_order
                                        from notifications import notify_order_filled
                                        res = place_order(o)
                                        if res.get("status") in (200, 201):
                                            notify_order_filled(s, q, sd)
                                            ui.notify(f"Order placed! ID: {res.get('order_id','—')}", type='positive')
                                            preview_area.clear()
                                        else:
                                            ui.notify(f"Order rejected: {res}", type='negative')
                                    except Exception as e:
                                        ui.notify(f"Error: {e}", type='negative')

                                ui.button('Cancel', on_click=preview_area.clear).props('flat').classes('text-[#8899aa]')
                                ui.button('Confirm & Place', icon='check', on_click=confirm_order).classes(
                                    'bg-[#059669] text-white font-semibold'
                                )

                ui.button('Preview Order', icon='visibility', on_click=build_preview).classes(
                    'w-full bg-[#1e2d4a] text-[#4fc3f7] font-semibold mt-4'
                )

            # ── Transfer planner ───────────────────────────────────────
            with ui.card().classes('flex-1 min-w-[300px] bg-[#0d1526] border border-[#1e2d4a] rounded-xl p-6'):
                ui.label('Monthly Transfer Rules').classes('text-white font-semibold mb-1')
                ui.label(
                    'Document recurring transfers here so the app knows expected cash flow '
                    'and can calculate accurate excess-cash sweeps.'
                ).classes('text-[#8899aa] text-xs mb-4')

                transfers = ui.column().classes('w-full gap-3')
                transfer_list: list[dict] = []

                def add_transfer_row():
                    with transfers:
                        idx = len(transfer_list)
                        entry = {}
                        transfer_list.append(entry)
                        with ui.card().classes('w-full bg-[#0a0f1e] border border-[#1e2d4a] rounded-lg p-3'):
                            with ui.row().classes('gap-2 flex-wrap items-end'):
                                n = ui.input(placeholder='Label', value='').classes('flex-1 min-w-[100px]')
                                n.props('dense outlined dark')
                                a = ui.number(placeholder='Amount', min=0, step=50).classes('w-24')
                                a.props('dense outlined dark')
                                d = ui.number(label='Day', min=1, max=31, value=1).classes('w-16')
                                d.props('dense outlined dark')
                                dir_ = ui.select(['→ Brokerage','→ Checking','→ Savings'], value='→ Brokerage').classes('w-36')
                                dir_.props('dense outlined dark')

                                def save(i=idx, ni=n, ai=a, di=d, dri=dir_):
                                    transfer_list[i] = {
                                        "label":     ni.value,
                                        "amount":    ai.value,
                                        "day":       di.value,
                                        "direction": dri.value,
                                    }
                                    ui.notify(f"Saved: {ni.value}", type='positive')

                                ui.button('Save', icon='save', on_click=save).props('flat dense').classes(
                                    'text-[#34d399]'
                                )

                ui.button('+ Add Transfer Rule', on_click=add_transfer_row).props('flat').classes(
                    'text-[#4fc3f7] mb-2'
                )

                ui.separator().classes('my-4 bg-[#1e2d4a]')

                # ── Idle cash warning ──────────────────────────────────
                ui.label('Idle Cash Watch').classes('text-white font-semibold mb-2')

                idle_container = ui.column().classes('w-full gap-2')

                async def check_idle():
                    idle_container.clear()
                    try:
                        from schwab_client import get_balances_and_positions
                        from config import settings
                        data = get_balances_and_positions()
                        cash = data.get("cash_balance", 0)
                        with idle_container:
                            if cash > settings.min_cash_buffer:
                                with ui.row().classes('items-center gap-2'):
                                    ui.icon('warning', size='1rem').classes('text-[#f59e0b]')
                                    ui.label(f"${cash:,.2f} idle in brokerage cash").classes('text-[#f59e0b] text-sm')
                                ui.label(
                                    f"Consider buying {settings.sweep_symbol} or another position."
                                ).classes('text-[#8899aa] text-xs')
                            else:
                                with ui.row().classes('items-center gap-2'):
                                    ui.icon('check_circle', size='1rem').classes('text-[#34d399]')
                                    ui.label(f"${cash:,.2f} brokerage cash — looks healthy").classes('text-[#34d399] text-sm')
                    except Exception as e:
                        with idle_container:
                            ui.label(f"Error: {e}").classes('text-[#ef4444] text-sm')

                ui.button('Check Now', icon='search', on_click=check_idle).props('flat').classes(
                    'text-[#4fc3f7]'
                )
                await check_idle()
