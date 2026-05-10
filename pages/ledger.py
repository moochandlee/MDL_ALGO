"""
pages/ledger.py — Transaction ledger with search/filter
"""

import asyncio
from nicegui import ui
from datetime import date, timedelta


async def render():
    with ui.column().classes('w-full min-h-screen bg-[#0a0f1e] p-6 gap-6'):

        # ── Header ──────────────────────────────────────────────────────
        with ui.row().classes('w-full items-center justify-between'):
            with ui.column().classes('gap-1'):
                ui.label('Transaction Ledger').classes('text-2xl font-bold text-white')
                ui.label('All accounts · synced daily').classes('text-[#8899aa] text-sm')

            export_btn = ui.button('Export CSV', icon='download').props('flat').classes(
                'text-[#4fc3f7] border border-[#1e2d4a]'
            )

        # ── Filters ─────────────────────────────────────────────────────
        with ui.card().classes('w-full bg-[#0d1526] border border-[#1e2d4a] rounded-xl p-4'):
            with ui.row().classes('gap-4 flex-wrap items-end'):
                days_select = ui.select(
                    {7: 'Last 7 days', 30: 'Last 30 days', 90: 'Last 90 days', 365: 'Last year'},
                    value=30, label='Period'
                ).classes('w-40')

                search_input = ui.input(placeholder='Search description...').classes('flex-1 min-w-[200px]')
                search_input.props('dense outlined dark')

                type_filter = ui.select(
                    {'all': 'All types', 'debit': 'Debits only', 'credit': 'Credits only'},
                    value='all', label='Type'
                ).classes('w-40')

                status_filter = ui.select(
                    {'all': 'All', 'posted': 'Posted', 'pending': 'Pending'},
                    value='all', label='Status'
                ).classes('w-40')

                ui.button('Apply', icon='filter_list', on_click=lambda: asyncio.create_task(load_table())).classes(
                    'bg-[#1e2d4a] text-[#4fc3f7]'
                )

        # ── Summary chips ────────────────────────────────────────────────
        summary_row = ui.row().classes('gap-4 flex-wrap')

        # ── Table ────────────────────────────────────────────────────────
        table_container = ui.column().classes('w-full')

        async def load_table():
            def safe_str(val):
                import math
                if val is None or (isinstance(val, float) and math.isnan(val)):
                    return "—"
                return str(val)
            table_container.clear()
            summary_row.clear()

            from teller_client import get_recent_transactions
            import pandas as pd

            df = get_recent_transactions(days=days_select.value)

            if df.empty:
                with table_container:
                    with ui.card().classes('w-full bg-[#0d1526] border border-[#1e2d4a] rounded-xl p-8 items-center'):
                        ui.icon('receipt_long', size='3rem').classes('text-[#1e2d4a] mb-2')
                        ui.label('No transactions found').classes('text-[#8899aa]')
                        ui.label('Run a sync or check your Teller configuration').classes('text-[#4a5568] text-sm')
                return

            # Apply filters
            if search_input.value:
                mask = df["description"].str.contains(search_input.value, case=False, na=False)
                df   = df[mask]

            if type_filter.value == 'debit':
                df = df[df["amount"] > 0]
            elif type_filter.value == 'credit':
                df = df[df["amount"] < 0]

            if status_filter.value != 'all':
                df = df[df["status"] == status_filter.value]

            # ── Summary chips ──────────────────────────────────────────
            with summary_row:
                total_debits  = df[df["amount"] > 0]["amount"].sum()
                total_credits = df[df["amount"] < 0]["amount"].abs().sum()
                net           = total_credits - total_debits

                def chip(label, value, color):
                    with ui.card().classes(f'bg-[#0d1526] border border-[#1e2d4a] rounded-lg px-4 py-2'):
                        ui.label(label).classes('text-[#8899aa] text-xs')
                        ui.label(value).style(f'color:{color}').classes('font-mono font-bold')

                chip("Total Debits",  f"-${total_debits:,.2f}",  "#ef4444")
                chip("Total Credits", f"+${total_credits:,.2f}", "#34d399")
                chip("Net",           f"{'+'if net>=0 else ''}{net:,.2f}", "#34d399" if net >= 0 else "#ef4444")
                chip("Transactions",  str(len(df)),               "#4fc3f7")

            # ── Category breakdown ─────────────────────────────────────
            cats = (
                df[df["amount"] > 0]
                .groupby("category")["amount"]
                .sum()
                .sort_values(ascending=False)
                .head(5)
            )

            if not cats.empty:
                with table_container:
                    with ui.card().classes('w-full bg-[#0d1526] border border-[#1e2d4a] rounded-xl p-4 mb-4'):
                        ui.label('Top Spending Categories').classes('text-white font-semibold text-sm mb-3')
                        max_val = cats.max()
                        with ui.column().classes('gap-2 w-full'):
                            for cat, amt in cats.items():
                                pct = (amt / max_val * 100) if max_val else 0
                                cat_label = (cat or "uncategorized").replace("_"," ").title()
                                with ui.row().classes('items-center gap-3 w-full'):
                                    ui.label(cat_label).classes('text-[#8899aa] text-xs w-32 shrink-0')
                                    with ui.element('div').classes('flex-1 bg-[#0a0f1e] rounded-full h-2 overflow-hidden'):
                                        ui.element('div').classes('h-2 rounded-full bg-[#4fc3f7]').style(f'width:{pct:.0f}%')
                                    ui.label(f"${amt:,.2f}").classes('text-white font-mono text-xs w-24 text-right shrink-0')

            # ── Transactions table ─────────────────────────────────────
            with table_container:
                columns = [
                    {"name": "date",        "label": "Date",        "field": "date",        "sortable": True, "align": "left"},
                    {"name": "institution", "label": "Account",     "field": "institution", "sortable": True, "align": "left"},
                    {"name": "description", "label": "Description", "field": "description", "sortable": False,"align": "left"},
                    {"name": "category",    "label": "Category",    "field": "category",    "sortable": True, "align": "left"},
                    {"name": "status",      "label": "Status",      "field": "status",      "sortable": True, "align": "center"},
                    {"name": "amount",      "label": "Amount",      "field": "amount_fmt",  "sortable": True, "align": "right"},
                ]

                rows = []
                for _, row in df.head(200).iterrows():
                    amt = row.get("amount", 0)
                    try:
                        amt = float(amt)
                    except (ValueError, TypeError):
                        amt = 0.0
                    rows.append({
                        "date":        row.get("date",""),
                        "institution": f"{row.get('institution','')} · {row.get('account_name','')}",
                        "description": row.get("description",""),
                        "category":    safe_str(row.get("category")).replace("_", " ").title(),
                        "status":      row.get("status",""),
                        "amount_fmt":  f"{'+'if amt<0 else '-'}${abs(amt):,.2f}",
                        "_debit":      amt > 0,
                    })

                table = ui.table(columns=columns, rows=rows, row_key="date").classes(
                    'w-full bg-[#0d1526] rounded-xl border border-[#1e2d4a]'
                )
                table.props('dark flat dense')
                table.add_slot('body-cell-status', '''
                    <q-td :props="props">
                        <q-badge :color="props.value === 'posted' ? 'green' : 'orange'" :label="props.value" />
                    </q-td>
                ''')
                table.add_slot('body-cell-amount', '''
                    <q-td :props="props" :class="props.row._debit ? 'text-red-400' : 'text-green-400'"
                          style="font-family:monospace;font-weight:600">
                        {{ props.value }}
                    </q-td>
                ''')

        # Export handler
        def export_csv():
            from teller_client import get_recent_transactions
            df = get_recent_transactions(days=days_select.value)
            path = '/tmp/transactions_export.csv'
            df.to_csv(path, index=False)
            ui.download(path, 'transactions.csv')

        export_btn.on('click', export_csv)

        await load_table()
