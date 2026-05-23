"""
pages/ledger.py — Transaction ledger with cascading search/filter
"""

import asyncio
from nicegui import ui
from datetime import date, timedelta


def _load_registry():
    from accounts import load_registry, ensure_registry_from_balances
    registry = load_registry()
    if not registry:
        registry = ensure_registry_from_balances()
    return registry


def _acct_type_reverse(registry: dict) -> dict:
    """Build account_id -> type_label reverse map."""
    rev = {}
    for aid, reg in registry.items():
        atype = reg.get("type", "")
        if atype == "credit":
            rev[aid] = "Credit Cards"
        elif atype == "depository":
            rev[aid] = "Checking"
        elif atype == "manual_asset":
            rev[aid] = "Assets"
        elif atype == "manual_liability":
            rev[aid] = "Liabilities"
        else:
            rev[aid] = atype.replace("_", " ").title()
    return rev


async def render():
    registry = _load_registry()
    acct_rev = _acct_type_reverse(registry)

    # Build full option sets and cross-reference maps
    # Use DICT options everywhere — NiceGUI handles dict option changes more reliably
    known_types = sorted(set(acct_rev.values()))
    type_opts = {t: t for t in known_types}  # dict: key=value=label
    full_acct_opts = {}
    type_to_accts = {}
    for aid, reg in registry.items():
        name = reg.get("name", "")
        inst = reg.get("institution", "")
        if name:
            full_acct_opts[aid] = f"{inst} · {name}" if inst else name
        t = acct_rev.get(aid, "Other")
        type_to_accts.setdefault(t, []).append(aid)

    with ui.column().classes('w-full min-h-screen bg-[#0a0f1e] p-6 gap-6'):

        # ── Shared filter state (persists across refreshes) ─────────────
        F = {'days': 30, 'types': [], 'accts': [], 'status': 'all', 'search': ''}
        _render_gen = [0]

        def get_restricted_acct_opts():
            """Account options limited by selected types."""
            if F['types']:
                allowed = set()
                for t in F['types']:
                    allowed.update(type_to_accts.get(t, []))
                return {aid: lbl for aid, lbl in full_acct_opts.items() if aid in allowed}
            return dict(full_acct_opts)

        def get_restricted_type_opts():
            """Type options limited by selected accounts."""
            if F['accts']:
                allowed = {acct_rev.get(a, "Other") for a in F['accts'] if a in full_acct_opts}
                return {t: t for t in known_types if t in allowed}
            return dict(type_opts)

        def handle_change(key, value):
            if key == 'days':
                value = int(value)
            elif key in ('types', 'accts') and value is None:
                value = []
            F[key] = value
            filter_ui.refresh()
            _render_gen[0] += 1
            asyncio.create_task(load_table(_render_gen[0]))

        @ui.refreshable
        def filter_ui():
            with ui.card().classes('w-full bg-[#0d1526] border border-[#1e2d4a] rounded-xl p-4'):
                with ui.row().classes('gap-4 flex-wrap items-end'):
                    ui.select(
                        {7: 'Last 7 days', 30: 'Last 30 days', 90: 'Last 90 days', 365: 'Last year'},
                        value=F['days'], label='Period',
                        on_change=lambda e: handle_change('days', e.value),
                    ).classes('w-40')

                    search_input = ui.input(placeholder='Search description...', value=F['search']).classes('flex-1 min-w-[200px]')
                    search_input.props('dense outlined dark')
                    search_input.on('keydown.enter', lambda: (
                        F.__setitem__('search', search_input.value),
                        _render_gen.__setitem__(0, _render_gen[0] + 1),
                        asyncio.create_task(load_table(_render_gen[0])),
                    ))

                    ui.select(
                        get_restricted_type_opts(), value=F['types'],
                        label='Account Type', multiple=True, clearable=True,
                        on_change=lambda e: handle_change('types', e.value),
                    ).classes('w-52')

                    ui.select(
                        get_restricted_acct_opts(), value=F['accts'],
                        label='Account', multiple=True, clearable=True,
                        on_change=lambda e: handle_change('accts', e.value),
                    ).classes('w-52')

                    ui.select(
                        {'all': 'All', 'posted': 'Posted', 'pending': 'Pending'},
                        value=F['status'], label='Status',
                        on_change=lambda e: handle_change('status', e.value),
                    ).classes('w-40')

        # ── Header ──────────────────────────────────────────────────────
        with ui.row().classes('w-full items-center justify-between'):
            with ui.column().classes('gap-1'):
                ui.label('Transaction Ledger').classes('text-2xl font-bold text-white')
                ui.label('All accounts · synced daily').classes('text-[#8899aa] text-sm')

            export_btn = ui.button('Export CSV', icon='download').props('flat').classes(
                'text-[#4fc3f7] border border-[#1e2d4a]'
            )

        # ── Filters ─────────────────────────────────────────────────────
        filter_ui()

        # ── Summary chips ────────────────────────────────────────────────
        summary_row = ui.row().classes('gap-4 flex-wrap')

        # ── Table ────────────────────────────────────────────────────────
        table_container = ui.column().classes('w-full')

        # ── Load data ───────────────────────────────────────────────────

        async def load_table(gen: int = 0):
            def safe_str(val):
                import math
                if val is None or (isinstance(val, float) and math.isnan(val)):
                    return "—"
                return str(val)

            from teller_client import get_recent_transactions
            import pandas as pd

            if gen != _render_gen[0]:
                return

            table_container.clear()
            summary_row.clear()

            df = get_recent_transactions(days=int(F['days']))

            if df.empty:
                with table_container:
                    with ui.card().classes('w-full bg-[#0d1526] border border-[#1e2d4a] rounded-xl p-8 items-center'):
                        ui.icon('receipt_long', size='3rem').classes('text-[#1e2d4a] mb-2')
                        ui.label('No transactions found').classes('text-[#8899aa]')
                        ui.label('Run a sync or check your Teller configuration').classes('text-[#4a5568] text-sm')
                return

            # Apply search
            if F['search']:
                df = df[df["description"].str.contains(F['search'], case=False, na=False)]

            # Apply account type filter
            sel_types = F['types']
            if sel_types and isinstance(sel_types, list):
                matching_ids = {aid for aid, t in acct_rev.items() if t in sel_types}
                df = df[df["account_id"].isin(matching_ids)]

            # Apply account filter
            sel_accts = F['accts']
            if sel_accts and isinstance(sel_accts, list):
                df = df[df["account_id"].isin(sel_accts)]

            # Build account-type-aware debit/credit mask
            df["_acct_type"] = df["account_id"].map(acct_rev).fillna("Other")
            df["_is_checking"] = df["_acct_type"] == "Checking"
            df["_is_debit"] = (df["amount"] > 0) != df["_is_checking"]

            # Apply status filter
            if F['status'] != 'all':
                df = df[df["status"] == F['status']]

            # ── Summary chips ──────────────────────────────────────────
            with summary_row:
                total_debits  = df[df["_is_debit"]]["amount"].abs().sum()
                total_credits = df[~df["_is_debit"]]["amount"].abs().sum()
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
                df[df["_is_debit"]]
                .groupby("category")["amount"]
                .sum()
                .abs()
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
                    is_debit = bool(row.get("_is_debit", False))
                    acct_type = row.get("_acct_type", "")
                    rows.append({
                        "date":        row.get("date",""),
                        "institution": f"{acct_type}  ·  {row.get('institution','')} · {row.get('account_name','')}",
                        "description": row.get("description",""),
                        "category":    safe_str(row.get("category")).replace("_", " ").title(),
                        "status":      row.get("status",""),
                        "amount_fmt":  f"{'-'if is_debit else '+'}${abs(amt):,.2f}",
                        "_debit":      is_debit,
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
            df = get_recent_transactions(days=int(F['days']))
            path = '/tmp/transactions_export.csv'
            df.to_csv(path, index=False)
            ui.download(path, 'transactions.csv')

        export_btn.on('click', export_csv)

        await load_table()

