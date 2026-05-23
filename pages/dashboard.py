"""
pages/dashboard.py — Consolidated dashboard (merges former overview + dashboard).

Shows at-a-glance metrics, account balances, cash flow projections,
expense analysis, net worth forecast, and sweep approvals.
"""

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from nicegui import ui, app

from config import settings

LOANS_FILE = settings.data_dir / "loans.json"
OTHER_ASSETS_FILE = settings.data_dir / "other_assets.json"


# ── Helpers ─────────────────────────────────────────────────────────────

def _safe_float(v) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (ValueError, TypeError):
        return 0.0


def load_loans() -> list[dict]:
    if LOANS_FILE.exists():
        try:
            return json.loads(LOANS_FILE.read_text())
        except Exception:
            pass
    return []


def save_loans(loans: list[dict]):
    LOANS_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOANS_FILE.write_text(json.dumps(loans, indent=2))


def load_other_assets() -> dict:
    if OTHER_ASSETS_FILE.exists():
        try:
            return json.loads(OTHER_ASSETS_FILE.read_text())
        except Exception:
            pass
    return {"aspp": 0}


def save_other_assets(assets: dict):
    OTHER_ASSETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    OTHER_ASSETS_FILE.write_text(json.dumps(assets, indent=2))


# ── Data fetching ───────────────────────────────────────────────────────

def _gather() -> dict:
    """Fetch all account data and return a structured summary dict."""
    from teller_client import get_latest_balances
    from schwab_client import get_balances_and_positions

    teller_bals = get_latest_balances()
    try:
        schwab = get_balances_and_positions()
    except Exception:
        schwab = {"error": "Schwab API unavailable"}
    loans = load_loans()

    tx_file = settings.data_dir / "transactions.csv"
    cc_last_payment = {}
    cc_daily_spend = {}
    if tx_file.exists():
        try:
            tdf = pd.read_csv(tx_file)
            tdf["date"] = pd.to_datetime(tdf["date"], errors="coerce")
            payments = tdf[(tdf["amount"] < 0) &
                           (tdf["description"].str.contains("payment|pmt|autopay", case=False, na=False))].copy()
            for aid in payments["account_id"].unique():
                acct_pmts = payments[payments["account_id"] == aid].sort_values("date", ascending=False)
                if not acct_pmts.empty:
                    cc_last_payment[aid] = abs(acct_pmts.iloc[0]["amount"])
            debits = tdf[(tdf["amount"] > 0) & (tdf["status"] == "posted")].copy()
            debits["month"] = debits["date"].dt.strftime("%Y-%m")
            for aid in debits["account_id"].unique():
                acct = debits[debits["account_id"] == aid]
                avg_monthly = acct.groupby("month")["amount"].sum().mean()
                cc_daily_spend[aid] = avg_monthly / 30 if pd.notna(avg_monthly) else 0
        except Exception:
            pass

    from accounts import load_registry, ensure_registry_from_balances
    registry = load_registry()
    if not registry:
        registry = ensure_registry_from_balances()

    checking = []
    credit_cards = []
    for b in teller_bals:
        aid = b.get("account_id", "")
        reg = registry.get(aid, {})
        entry = {
            "institution": reg.get("institution", b.get("institution", "")),
            "name": reg.get("name", b.get("account_name", "")),
            "type": reg.get("type", b.get("account_type", "")),
            "subtype": reg.get("subtype", b.get("subtype", "")),
            "available": _safe_float(b.get("available")),
            "ledger": _safe_float(b.get("ledger")),
        }
        if reg.get("type") == "credit":
            entry["account_id"] = aid
            entry["last_payment"] = cc_last_payment.get(aid, 0)
            entry["daily_spend"] = round(cc_daily_spend.get(aid, 0), 2)
            entry["statement_day"] = reg.get("statement_day", "")
            entry["payment_due_day"] = reg.get("payment_due_day", "")
            credit_cards.append(entry)
        else:
            checking.append(entry)

    brokerage = {
        "liquidation_value": schwab.get("liquidation_value", 0) if "error" not in schwab else 0,
        "cash_balance": schwab.get("cash_balance", 0) if "error" not in schwab else 0,
        "buying_power": schwab.get("buying_power", 0) if "error" not in schwab else 0,
        "positions": schwab.get("positions", []) if "error" not in schwab else [],
        "error": schwab.get("error"),
    }

    total_cash = sum(a["available"] for a in checking)
    total_credit = sum(abs(a["ledger"]) for a in credit_cards)
    total_loans = sum(_safe_float(l.get("balance")) for l in loans)
    total_brokerage = brokerage["liquidation_value"]
    other_assets = load_other_assets()
    aspp_val = _safe_float(other_assets.get("aspp", 0))

    from accounts import get_manual_items
    manual_assets = []
    manual_liabilities = []
    for item in get_manual_items():
        if item["type"] == "manual_asset":
            if item["subtype"] == "aspp":
                manual_assets.append({
                    "name": item["name"], "institution": item.get("institution", ""),
                    "value": aspp_val, "sub": "monthly ESPP",
                })
        elif item["type"] == "manual_liability":
            if item["subtype"] == "loan":
                matching = [l for l in loans if l.get("name", "").lower() == item["name"].lower()]
                if matching:
                    loan = matching[0]
                else:
                    loan = {"name": item["name"], "balance": 0, "interest_rate": 0,
                            "min_payment": 0, "payment_frequency": "Monthly"}
                manual_liabilities.append({
                    "name": item["name"], "institution": item.get("institution", ""),
                    "value": _safe_float(loan.get("balance", 0)),
                    "sub": f"{loan.get('interest_rate', '0')}% · ${_safe_float(loan.get('min_payment', 0)):,.0f}/{loan.get('payment_frequency', 'Monthly').split('-')[0].lower()}",
                })

    total_assets = total_cash + total_brokerage + aspp_val
    total_liabilities = total_credit + total_loans

    return {
        "checking": checking, "credit_cards": credit_cards, "loans": loans,
        "brokerage": brokerage, "other_assets": other_assets,
        "manual_assets": manual_assets, "manual_liabilities": manual_liabilities,
        "totals": {
            "cash": round(total_cash, 2), "credit_card_debt": round(total_credit, 2),
            "loan_debt": round(total_loans, 2), "brokerage": round(total_brokerage, 2),
            "aspp": round(aspp_val, 2), "assets": round(total_assets, 2),
            "liabilities": round(total_liabilities, 2),
            "net_worth": round(total_assets - total_liabilities, 2),
        },
    }


def get_cash_flow_projection(data: dict, expense: dict, avg_paycheck: float = 0) -> dict:
    """Project checking balance forward through each CC payment date."""
    checking_total = sum(a["available"] for a in data["checking"])
    daily_spend = expense.get("total_monthly", 0) / 30 if expense else 0
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    active_cards = [cc for cc in data["credit_cards"]
                    if int(cc.get("statement_day", 0)) and int(cc.get("payment_due_day", 0))]

    events = []
    for cc in active_cards:
        sd = int(cc.get("statement_day", 0))
        pd_ = int(cc.get("payment_due_day", 0))
        stmt_day = min(sd, 28)
        due_day = min(pd_, 28)

        if today.day < stmt_day:
            stmt_date = today.replace(day=stmt_day)
        else:
            stmt_date = (today.replace(day=1) + timedelta(days=32)).replace(day=stmt_day)
        due_date = (stmt_date.replace(day=1) + timedelta(days=32)).replace(day=due_day)

        days_to_stmt = (stmt_date - today).days
        days_to_due = (due_date - today).days
        current_ledger = abs(_safe_float(cc.get("ledger", 0)))
        card_daily_spend = _safe_float(cc.get("daily_spend", 0))
        projected_stmt = max(0, current_ledger + card_daily_spend * days_to_stmt)

        events.append({
            "type": "cc_payment", "card_name": f"{cc['institution']} · {cc['name']}",
            "current_balance": round(current_ledger, 2),
            "projected_statement": round(projected_stmt, 2),
            "amount": round(projected_stmt, 2),
            "stmt_spend": round(card_daily_spend * days_to_stmt, 2),
            "stmt_date": stmt_date, "due_date": due_date,
            "days_to_stmt": days_to_stmt, "days_to_due": days_to_due,
            "stmt_label": stmt_date.strftime("%b %d"), "due_label": due_date.strftime("%b %d"),
        })

    events.sort(key=lambda e: e["due_date"])

    running = checking_total
    prev_days = 0
    for ev in events:
        interval_days = ev["days_to_due"] - prev_days
        paychecks_in_interval = interval_days // 14
        paychecks_added = paychecks_in_interval * avg_paycheck
        running += paychecks_added
        ev["checking_before"] = round(running, 2)
        running -= ev["amount"]
        ev["checking_after"] = round(running, 2)
        ev["paychecks_added"] = round(paychecks_added, 2)
        prev_days = ev["days_to_due"]

    return {
        "checking_today": round(checking_total, 2), "events": events,
        "total_cc_payments": round(sum(e["amount"] for e in events), 2),
        "daily_spend": round(daily_spend, 2),
        "projected_checking_after_all": round(running, 2),
    }


def get_expense_analysis(months: int = 3) -> dict:
    """Analyze recent transactions for monthly spending by category."""
    from teller_client import get_recent_transactions
    df = get_recent_transactions(days=months * 31)
    if df.empty:
        return {"monthly_expenses": {}, "monthly_income": 0, "total_monthly": 0}

    df = df[df["status"] == "posted"].copy()
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    if df.empty:
        return {"monthly_expenses": {}, "monthly_income": 0, "total_monthly": 0}

    debits = df[df["amount"] > 0].copy()
    debits["category"] = debits["category"].fillna("uncategorized")
    debits["month"] = debits["date"].dt.strftime("%Y-%m")
    cat_avg = debits.groupby(["month", "category"])["amount"].sum().groupby("category").mean()
    total_monthly = round(float(cat_avg.sum()), 2)

    credits = df[df["amount"] < 0].copy()
    credits["month"] = credits["date"].dt.strftime("%Y-%m")
    monthly_income = round(abs(float(credits.groupby("month")["amount"].sum().mean())), 2)

    return {"monthly_expenses": cat_avg.round(2).to_dict(),
            "total_monthly": total_monthly, "monthly_income": monthly_income}


def project_net_worth(data: dict, expense: dict, months: int = 24) -> list[dict]:
    """Simple net worth projection based on current position and cash flow."""
    totals = data["totals"]
    loans_list = [dict(l) for l in data["loans"]]
    brokerage_val = totals["brokerage"]
    monthly_income = expense.get("monthly_income", 0)
    monthly_expenses = expense.get("total_monthly", 0)
    monthly_loan_payments = sum(_safe_float(l.get("min_payment", 0)) for l in loans_list)
    cash_flow = (monthly_income - monthly_expenses) - monthly_loan_payments

    projection = []
    nw = totals["net_worth"]
    cash = totals["cash"]
    credit = totals["credit_card_debt"]
    loan_debt = totals["loan_debt"]
    brok = brokerage_val

    projection.append({
        "month": "Now", "net_worth": round(nw, 0), "assets": round(totals["assets"], 0),
        "liabilities": round(totals["liabilities"], 0), "liquid": round(cash, 0),
        "ex_loan_nw": round(nw + loan_debt, 0),
    })

    for i in range(1, months + 1):
        brok *= 1.007
        cash = max(0, cash + cash_flow)
        for l in loans_list:
            bal = _safe_float(l.get("balance", 0))
            rate = _safe_float(l.get("interest_rate", 0)) / 100 / 12
            min_pmt = _safe_float(l.get("min_payment", 0))
            if bal > 0 and min_pmt > 0:
                interest = bal * rate
                principal = min(min_pmt - interest, bal)
                l["balance"] = max(0, bal - principal)

        new_loan_total = sum(_safe_float(l.get("balance")) for l in loans_list)
        assets = cash + brok
        liabilities = credit + new_loan_total
        nw = assets - liabilities
        label = f"Month {i}"
        if i % 6 == 0:
            label = (datetime.now() + timedelta(days=30 * i)).strftime("%b %Y")
        projection.append({
            "month": label, "net_worth": round(nw, 0), "assets": round(assets, 0),
            "liabilities": round(liabilities, 0), "liquid": round(cash, 0),
            "ex_loan_nw": round(nw + new_loan_total, 0),
        })
    return projection


# ── Chart helpers ───────────────────────────────────────────────────────

def _apply_dark_layout(fig: go.Figure, title: str = ""):
    fig.update_layout(
        template='plotly_dark', paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)', font_color='#a8d8ea',
        font_size=11, margin=dict(l=40, r=20, t=30, b=40),
        legend=dict(orientation='h', y=1.08, font=dict(size=10)),
        title=dict(text=title, font=dict(size=13, color='#a8d8ea'), x=0.5),
        hovermode='x unified',
    )
    fig.update_xaxes(gridcolor='#1e2d4a', zeroline=False)
    fig.update_yaxes(gridcolor='#1e2d4a', zeroline=False)


def _expense_chart(expense: dict):
    cats = expense.get("monthly_expenses", {})
    if not cats:
        return None
    sorted_cats = sorted(cats.items(), key=lambda x: x[1], reverse=True)
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=[c[0].replace("_", " ").title() for c in sorted_cats],
        y=[c[1] for c in sorted_cats],
        marker_color='#4fc3f7', marker_line_color='#1e2d4a', marker_line_width=1,
        hovertemplate='%{y:$,.0f}<extra></extra>',
    ))
    _apply_dark_layout(fig)
    fig.update_layout(height=250, showlegend=False)
    return fig


def _projection_chart(projection: list[dict]):
    if not projection:
        return None
    fig = go.Figure()
    for trace in [
        go.Scatter(x=[p["month"] for p in projection], y=[p["assets"] for p in projection],
                   mode='lines+markers', name='Assets', line=dict(color='#34d399', width=2), marker=dict(size=4)),
        go.Scatter(x=[p["month"] for p in projection], y=[p["liabilities"] for p in projection],
                   mode='lines+markers', name='Liabilities', line=dict(color='#ef4444', width=2), marker=dict(size=4)),
        go.Scatter(x=[p["month"] for p in projection], y=[p["net_worth"] for p in projection],
                   mode='lines+markers', name='Net Worth', line=dict(color='#4fc3f7', width=3), marker=dict(size=5)),
        go.Scatter(x=[p["month"] for p in projection], y=[p["liquid"] for p in projection],
                   mode='lines', name='Liquid', line=dict(color='#34d399', width=1.5, dash='dot')),
        go.Scatter(x=[p["month"] for p in projection], y=[p["ex_loan_nw"] for p in projection],
                   mode='lines', name='NW (ex. Loans)', line=dict(color='#a78bfa', width=1.5, dash='dash')),
    ]:
        fig.add_trace(trace)
    _apply_dark_layout(fig, "Net Worth Projection")
    fig.update_layout(height=300)
    return fig


# ── Loan dialog ─────────────────────────────────────────────────────────

def _build_loan_dialog() -> ui.dialog:
    dialog = ui.dialog()
    with dialog, ui.card().classes('w-full max-w-xl bg-[#0d1526] border border-[#1e2d4a] rounded-xl p-6'):
        with ui.row().classes('items-center justify-between w-full mb-4'):
            ui.label('Manage Loans').classes('text-white font-semibold text-lg')
            ui.button(icon='close', on_click=dialog.close).props('flat dense round').classes('text-[#8899aa]')

        form_card = ui.card().classes('w-full bg-[#0a0f1e] border border-[#1e2d4a] rounded-xl p-4 mb-4 hidden')
        with form_card:
            with ui.row().classes('gap-3 w-full'):
                inp_name = ui.input('Loan Name', placeholder='e.g. Auto Loan 1').classes('flex-1').props('dense outlined dark')
                inp_lender = ui.input('Lender', placeholder='e.g. Capital One').classes('flex-1').props('dense outlined dark')
            with ui.row().classes('gap-3 w-full'):
                inp_balance = ui.number('Balance', format='%.2f').classes('flex-1').props('dense outlined dark')
                inp_rate = ui.number('Interest Rate (%)', format='%.2f').classes('flex-1').props('dense outlined dark')
            with ui.row().classes('gap-3 w-full'):
                inp_min_pmt = ui.number('Min Payment', format='%.2f').classes('flex-1').props('dense outlined dark')
                inp_frequency = ui.select(
                    label='Frequency', options=['Monthly', 'Bi-Weekly', 'Weekly', 'Quarterly', 'Annually'], value='Monthly',
                ).classes('flex-1').props('dense outlined dark')
            with ui.row().classes('gap-3 w-full'):
                inp_next_date = ui.input('Next Payment Date', placeholder='YYYY-MM-DD').classes('flex-1').props('dense outlined dark')
                inp_last_four = ui.input('Last Four', placeholder='1234').classes('flex-1').props('dense outlined dark')
            with ui.row().classes('gap-3 w-full'):
                inp_auto_pay = ui.checkbox('Auto-Pay').classes('text-white text-sm')
            with ui.row().classes('gap-3 mt-2'):
                ui.button('Cancel', on_click=lambda: form_card.classes(add='hidden')).props('flat').classes('text-[#8899aa]')
                btn_save = ui.button('Save', icon='save').classes('bg-[#4fc3f7] text-white font-semibold')

        list_container = ui.column().classes('w-full gap-2')
        editing_idx = [-1]

        def rebuild_list():
            list_container.clear()
            with list_container:
                loans = load_loans()
                if not loans:
                    ui.label('No loans added yet. Tap "Add Loan" to get started.').classes('text-[#8899aa] text-sm py-4 text-center w-full')
                for idx, loan in enumerate(loans):
                    with ui.row().classes('items-center justify-between w-full bg-[#0a0f1e] rounded-lg px-4 py-3 border border-[#1e2d4a]'):
                        with ui.column().classes('gap-0'):
                            name = loan.get('name', 'Loan')
                            lender = loan.get('lender', '')
                            ui.label(f"{name} ({lender})" if lender else name).classes('text-white text-sm font-medium')
                            freq = loan.get('payment_frequency', 'Monthly')
                            freq_abbr = freq.split('-')[0].lower() if '-' in freq else freq[:3].lower()
                            detail = f"${_safe_float(loan.get('balance', 0)):,.0f} @ {loan.get('interest_rate', '0')}%  ·  ${_safe_float(loan.get('min_payment', 0)):,.0f}/{freq_abbr}"
                            if loan.get('last_four'):
                                detail += f"  ·  x{loan['last_four']}"
                            ui.label(detail).classes('text-[#8899aa] text-xs')
                        with ui.row().classes('gap-1'):
                            ui.button(icon='edit', on_click=lambda i=idx: start_edit(i)).props('flat dense round').classes('text-[#4fc3f7]')
                            ui.button(icon='delete', on_click=lambda i=idx: delete_loan(i)).props('flat dense round').classes('text-[#ef4444]')

        def start_add():
            editing_idx[0] = -1
            for inp in (inp_name, inp_lender, inp_next_date, inp_last_four):
                inp.value = ''
            for inp in (inp_balance, inp_rate, inp_min_pmt):
                inp.value = 0
            inp_frequency.value = 'Monthly'
            inp_auto_pay.value = False
            form_card.classes(remove='hidden')

        def start_edit(idx):
            editing_idx[0] = idx
            loans = load_loans()
            loan = loans[idx]
            inp_name.value = loan.get('name', '')
            inp_lender.value = loan.get('lender', '')
            inp_balance.value = _safe_float(loan.get('balance', 0))
            inp_rate.value = _safe_float(loan.get('interest_rate', 0))
            inp_min_pmt.value = _safe_float(loan.get('min_payment', 0))
            inp_frequency.value = loan.get('payment_frequency', 'Monthly')
            inp_next_date.value = loan.get('next_payment_date', '') or ''
            inp_last_four.value = loan.get('last_four', '') or ''
            inp_auto_pay.value = loan.get('auto_pay', False)
            form_card.classes(remove='hidden')

        def delete_loan(idx):
            loans = load_loans()
            if 0 <= idx < len(loans):
                loans.pop(idx)
                save_loans(loans)
                rebuild_list()

        def save_loan():
            loans = load_loans()
            entry = {
                'name': inp_name.value or 'Untitled Loan', 'lender': inp_lender.value or '',
                'balance': _safe_float(inp_balance.value), 'interest_rate': _safe_float(inp_rate.value),
                'min_payment': _safe_float(inp_min_pmt.value),
                'payment_frequency': inp_frequency.value or 'Monthly',
                'next_payment_date': inp_next_date.value or None,
                'last_four': inp_last_four.value or None, 'auto_pay': inp_auto_pay.value,
            }
            if editing_idx[0] >= 0:
                loans[editing_idx[0]] = entry
            else:
                loans.append(entry)
            save_loans(loans)
            form_card.classes(add='hidden')
            rebuild_list()

        btn_save.on('click', save_loan)

        with ui.row().classes('items-center justify-between w-full mb-2'):
            ui.label(f'{len(load_loans())} Loans').classes('text-[#8899aa] text-sm')
            ui.button('Add Loan', icon='add', on_click=start_add).props('flat').classes('text-[#4fc3f7]')

        rebuild_list()
    return dialog


# ── UI sections ─────────────────────────────────────────────────────────

def _summary_card(label, value, icon, color='#4fc3f7', sub=''):
    with ui.card().classes('flex-1 min-w-[160px] bg-[#0d1526] border border-[#1e2d4a] rounded-xl p-5'):
        with ui.row().classes('items-center gap-3 mb-3'):
            with ui.element('div').classes('w-10 h-10 rounded-lg flex items-center justify-center').style(f'background: {color}22'):
                ui.icon(icon, size='1.2rem').style(f'color: {color}')
            ui.label(label).classes('text-[#8899aa] text-xs font-medium uppercase tracking-wider')
        ui.label(value).classes('text-white text-2xl font-bold font-mono')
        if sub:
            ui.label(sub).classes('text-[#8899aa] text-xs mt-1')


def _render_net_worth_hero(data: dict):
    t = data["totals"]
    liquid = t["cash"] + t.get("aspp", 0)
    ex_loan_nw = t["net_worth"] + t["loan_debt"]
    with ui.card().classes('w-full bg-[#0d1526] border border-[#1e2d4a] rounded-xl p-6'):
        with ui.row().classes('items-center justify-between w-full'):
            with ui.column().classes('gap-0'):
                ui.label('Net Worth').classes('text-[#8899aa] text-xs uppercase tracking-wider')
                nw_color = '#34d399' if t["net_worth"] >= 0 else '#ef4444'
                ui.label(f"${t['net_worth']:,.0f}").style(f'color:{nw_color}').classes('text-3xl font-bold font-mono')
            with ui.row().classes('gap-6'):
                for item in [("Assets", t["assets"], "#34d399"), ("Liquid", liquid, "#4fc3f7"), ("Liabilities", t["liabilities"], "#ef4444")]:
                    with ui.column().classes('gap-0 items-end'):
                        ui.label(item[0]).classes('text-[#8899aa] text-xs')
                        ui.label(f"${item[1]:,.0f}").style(f'color:{item[2]}').classes('font-mono font-bold text-sm')
        ui.separator().classes('my-3 bg-[#1e2d4a]')
        with ui.grid(columns=3).classes('w-full gap-4'):
            for item in [
                ("Cash", t["cash"], "#4fc3f7"), ("Investments", t["brokerage"], "#a78bfa"),
                ("ASPP", t.get("aspp", 0), "#f472b6"), ("Credit Cards", t["credit_card_debt"], "#f59e0b"),
                ("Loans", t["loan_debt"], "#ef4444"), ("Net Worth (ex. Loans)", ex_loan_nw, "#a78bfa"),
            ]:
                with ui.column().classes('gap-0 items-center'):
                    ui.label(item[0]).classes('text-[#4a5568] text-xs')
                    ui.label(f"${item[1]:,.0f}").style(f'color:{item[2]}').classes('font-mono font-bold text-sm')


def _render_cash_flow(data: dict, expense: dict):
    other_assets = load_other_assets()
    avg_paycheck = _safe_float(other_assets.get("avg_paycheck", 0))
    cf = get_cash_flow_projection(data, expense, avg_paycheck)
    with ui.card().classes('w-full bg-[#0d1526] border border-[#1e2d4a] rounded-xl p-4'):
        with ui.row().classes('items-center justify-between w-full mb-3'):
            ui.label('Cash Flow').classes('text-white font-semibold text-sm')
            after_all = cf["projected_checking_after_all"]
            ui.label(f"After all payments: ${after_all:,.0f}").style(
                f'color:{"#34d399" if after_all >= 0 else "#ef4444"}'
            ).classes('font-mono text-sm font-bold')
        with ui.row().classes('items-center justify-between w-full py-1 border-b border-[#1e2d4a] mb-2'):
            ui.label('Checking Accounts').classes('text-[#8899aa] text-xs')
            ui.label(f"${cf['checking_today']:,.2f}").classes('text-white font-mono text-sm')
        with ui.row().classes('items-center justify-between w-full py-1 border-b border-[#1e2d4a] mb-2'):
            ui.label('Estimated daily spend').classes('text-[#8899aa] text-xs')
            ui.label(f"${cf['daily_spend']:,.0f}/day").classes('text-[#f59e0b] font-mono text-xs')
        if not cf["events"]:
            ui.label('Set statement & payment dates in Settings for each card to see projections.').classes('text-[#8899aa] text-xs')
        else:
            ui.label('Projected Timeline').classes('text-white text-xs font-semibold mt-1')
            for ev in cf["events"]:
                with ui.column().classes('w-full bg-[#0a0f1e] rounded-lg px-3 py-2 mt-1 border border-[#1e2d4a]'):
                    with ui.row().classes('items-center justify-between w-full'):
                        with ui.row().classes('items-center gap-2'):
                            ui.icon('credit_card', size='0.8rem').style('color:#f59e0b')
                            ui.label(ev['card_name']).classes('text-[#a8d8ea] text-xs')
                        ui.label(f"${ev['projected_statement']:,.0f}").style('color:#f59e0b').classes('font-mono text-xs font-bold')
                    with ui.row().classes('items-center gap-3 w-full text-xs'):
                        ui.label(f"Current: ${ev['current_balance']:,.0f}").classes('text-[#4a5568]')
                        if ev['days_to_stmt'] > 0:
                            ui.label(f"+ ~${ev['stmt_spend']:,.0f} spend").classes('text-[#ef4444]')
                        ui.label(f"→ Stmt {ev['stmt_label']}: ${ev['projected_statement']:,.0f}").classes('text-[#a8d8ea]')
                        ui.label(f"Due {ev['due_label']}").classes('text-[#ef4444]')
                    with ui.row().classes('items-center gap-3 w-full text-xs border-t border-[#1e2d4a] pt-1 mt-1'):
                        chk_color = '#34d399' if ev['checking_after'] >= 0 else '#ef4444'
                        ui.label(f"Checking today").classes('text-[#8899aa]')
                        ui.label(f"${cf['checking_today']:,.0f}").classes('text-white font-mono')
                        ui.label(f"+{ev['paychecks_added']:,.0f} paychecks").classes('text-[#34d399]')
                        ui.label(f"−${ev['amount']:,.0f}").classes('text-[#ef4444]')
                        ui.label(f"= ${ev['checking_after']:,.0f}").style(f'color:{chk_color}').classes('font-mono font-bold')
                    with ui.row().classes('items-center w-full text-xs'):
                        ui.label('* non-CC spending will further reduce checking').classes('text-[#4a5568] italic')
        ui.separator().classes('my-2 bg-[#1e2d4a]')
        with ui.row().classes('items-center gap-4 flex-wrap'):
            with ui.row().classes('items-center gap-2'):
                ui.label('Avg Bi-Weekly Paycheck').classes('text-[#8899aa] text-xs')
                paycheck_input = ui.number('', value=avg_paycheck, format='%.0f').props('dense outlined dark').classes('w-28')
                def on_paycheck_change(v=paycheck_input):
                    val = _safe_float(v.value)
                    assets = load_other_assets()
                    assets["avg_paycheck"] = val
                    save_other_assets(assets)
                paycheck_input.on('change', on_paycheck_change)


def _render_accounts(data: dict, loan_dialog: ui.dialog):
    sections = [
        ("Checking", "account_balance",
         [{"name": f"{a['institution']} · {a['name']}", "value": a["available"], "color": "#34d399"} for a in data["checking"]],
         "#34d399"),
        ("Credit Cards", "credit_card",
         [{"name": f"{a['institution']} · {a['name']}", "value": abs(a["ledger"]), "color": "#f59e0b", "val_color": "#f59e0b"} for a in data["credit_cards"]],
         "#f59e0b"),
        ("Brokerage", "trending_up",
         [{"name": p["symbol"], "value": p["market_value"], "color": "#a78bfa", "sub": f"{p['quantity']} shares"} for p in data["brokerage"].get("positions", [])]
         + ([{"name": "Cash", "value": _safe_float(data["brokerage"].get("cash_balance", 0)), "color": "#34d399", "sub": "available"}] if _safe_float(data["brokerage"].get("cash_balance", 0)) > 0 else []),
         "#a78bfa"),
        ("Assets", "monetization_on",
         [{"name": a.get("name", "Asset"), "value": _safe_float(a.get("value", 0)), "color": "#34d399", "val_color": "#34d399", "sub": a.get("sub", "")} for a in data["manual_assets"] if a.get("value", 0) > 0],
         "#34d399"),
    ]
    liability_rows = []
    for l in data["loans"]:
        freq = l.get('payment_frequency', 'Monthly')
        freq_abbr = freq.split('-')[0].lower() if '-' in freq else freq[:3].lower()
        liability_rows.append({
            "name": f"{l.get('lender','')} · {l.get('name','')}", "value": _safe_float(l.get("balance", 0)),
            "color": "#ef4444", "val_color": "#ef4444",
            "sub": f"{l.get('interest_rate','')}% · ${_safe_float(l.get('min_payment',0)):,.0f}/{freq_abbr}",
        })
    for li in data["manual_liabilities"]:
        if li.get("value", 0) > 0:
            liability_rows.append({
                "name": li.get("name", "Liability"), "value": _safe_float(li.get("value", 0)),
                "color": "#ef4444", "val_color": "#f59e0b",
                "sub": li.get("institution", "") + (f"  ·  {li.get('sub', '')}" if li.get('sub') else ""),
            })
    sections.append(("Loans & Liabilities", "savings", liability_rows, "#ef4444"))

    has_loans_or_liabilities = bool(data["loans"] or data["manual_liabilities"])

    with ui.column().classes('w-full gap-4'):
        ui.label('Accounts').classes('text-white font-semibold text-sm uppercase tracking-wider')
        for section_title, icon, rows, accent in sections:
            if not rows:
                continue
            with ui.card().classes('w-full bg-[#0d1526] border border-[#1e2d4a] rounded-xl p-4'):
                with ui.row().classes('items-center gap-2 mb-2'):
                    ui.icon(icon, size='1rem').style(f'color:{accent}')
                    ui.label(section_title).classes('text-white text-sm font-medium')
                    if section_title == "Loans & Liabilities" and has_loans_or_liabilities:
                        ui.space()
                        ui.button('Manage Loans', icon='settings', on_click=loan_dialog.open).props('flat dense').classes('text-[#4fc3f7] text-xs')
                for row in rows:
                    val_color = row.get("val_color", accent)
                    with ui.row().classes('items-center justify-between w-full py-1'):
                        with ui.row().classes('items-center gap-3'):
                            ui.icon('circle', size='0.5rem').style(f'color:{row.get("color", accent)}')
                            ui.label(row["name"]).classes('text-[#a8d8ea] text-sm')
                            if row.get("sub"):
                                ui.label(row["sub"]).classes('text-[#4a5568] text-xs')
                        ui.label(f"${row['value']:,.2f}").style(f'color:{val_color}').classes('font-mono text-sm font-bold')


def _render_expense_analysis(expense: dict):
    fig = _expense_chart(expense)
    monthly = expense.get("total_monthly", 0)
    income = expense.get("monthly_income", 0)
    net = income - monthly
    with ui.card().classes('w-full bg-[#0d1526] border border-[#1e2d4a] rounded-xl p-4'):
        with ui.row().classes('items-center justify-between w-full mb-2'):
            ui.label('Monthly Spending').classes('text-white font-semibold text-sm')
            with ui.row().classes('gap-4'):
                ui.label(f"In: ${income:,.0f}").classes('text-[#34d399] font-mono text-xs')
                ui.label(f"Out: ${monthly:,.0f}").classes('text-[#ef4444] font-mono text-xs')
                ui.label(f"Net: ${net:,.0f}").style(f'color:{"#34d399" if net >= 0 else "#ef4444"}').classes('font-mono text-xs font-bold')
        if fig:
            ui.plotly(fig).classes('w-full')


def _render_projection(proj: list[dict], data: dict):
    fig = _projection_chart(proj)
    cc_debt = data["totals"]["credit_card_debt"]
    payoff_month = "—"
    for p in proj[1:]:
        if p["liabilities"] - cc_debt <= 0:
            payoff_month = p["month"]
            break
    with ui.card().classes('w-full bg-[#0d1526] border border-[#1e2d4a] rounded-xl p-4'):
        with ui.row().classes('items-center justify-between w-full mb-2'):
            ui.label('Net Worth Forecast').classes('text-white font-semibold text-sm')
            with ui.row().classes('gap-3'):
                ui.label(f'Loans paid off: {payoff_month}').classes('text-[#34d399] font-mono text-xs')
                ui.label('Based on recent spending & income trends').classes('text-[#4a5568] text-xs')
        if fig:
            ui.plotly(fig).classes('w-full')


# ── Sweep approvals ─────────────────────────────────────────────────────

def _render_sweep_approvals(section, load_callback):
    pending = getattr(app.state, 'pending_orders', [])
    if not pending:
        return
    with section:
        with ui.row().classes('items-center gap-2 mb-2'):
            ui.icon('notifications_active', size='1rem').classes('text-[#4fc3f7]')
            ui.label('Pending Recommendations').classes('text-white font-semibold text-sm uppercase tracking-wider')
        for i, rec in enumerate(pending):
            with ui.card().classes('w-full bg-[#0d1526] border border-[#f59e0b55] rounded-xl p-5'):
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
                                    app.state.pending_orders = [o for j, o in enumerate(app.state.pending_orders) if j != idx]
                                    notify_order_filled(r["symbol"], r["shares"], "BUY")
                                    ui.notify(f"Order placed! ID: {result.get('order_id')}", type='positive')
                                    await load_callback()
                                else:
                                    ui.notify(f"Order failed: {result}", type='negative')
                            except Exception as e:
                                ui.notify(f"Error: {e}", type='negative')

                        def dismiss(idx=i):
                            app.state.pending_orders = [o for j, o in enumerate(app.state.pending_orders) if j != idx]
                            section.clear()

                        ui.button('Approve', icon='check', on_click=approve).classes('bg-[#059669] text-white font-semibold')
                        ui.button('Dismiss', icon='close', on_click=dismiss).props('flat').classes('text-[#8899aa]')


# ── Main render ─────────────────────────────────────────────────────────

async def render():
    with ui.column().classes('w-full min-h-screen bg-[#0a0f1e] p-6 gap-6'):

        # ── Header ──────────────────────────────────────────────────────
        with ui.row().classes('w-full items-center justify-between'):
            with ui.column().classes('gap-1'):
                ui.label('Dashboard').classes('text-2xl font-bold text-white')
                ui.label('Your money, at a glance').classes('text-[#8899aa] text-sm')
            sync_btn = ui.button('Sync Now', icon='sync').props('flat').classes(
                'text-[#4fc3f7] border border-[#1e2d4a] hover:bg-[#1e2d4a]'
            )

        # ── Content containers ──────────────────────────────────────────
        summary_row = ui.row().classes('w-full gap-4 flex-wrap')
        sweep_section = ui.column().classes('w-full gap-3')
        content = ui.column().classes('w-full gap-6')

        async def load_all():
            loading = ui.spinner('dots', size='lg', color='#4fc3f7')
            await asyncio.sleep(0.1)

            try:
                data = _gather()
                expense = get_expense_analysis(months=3)
                proj = project_net_worth(data, expense)
                loan_dialog = _build_loan_dialog()
            except Exception as e:
                loading.delete()
                ui.notify(f"Error loading data: {e}", type='negative')
                return

            loading.delete()

            summary_row.clear()
            sweep_section.clear()
            content.clear()

            # Summary cards
            with summary_row:
                total_bank = 0
                for b in data["checking"]:
                    total_bank += b["available"]
                total_credit_abs = sum(abs(a["ledger"]) for a in data["credit_cards"])
                _summary_card("Total Net Worth", f"${data['totals']['net_worth']:,.0f}", "account_balance_wallet", "#4fc3f7")
                _summary_card("Bank Cash", f"${total_bank:,.0f}", "savings", "#34d399")
                _summary_card("Credit Cards", f"${total_credit_abs:,.0f}", "credit_card", "#f59e0b")
                _summary_card("Brokerage Value", f"${data['brokerage']['liquidation_value']:,.0f}", "trending_up", "#a78bfa")
                _summary_card("Buying Power", f"${data['brokerage'].get('buying_power', 0):,.0f}", "bolt", "#f59e0b")

            # Sweep approvals
            _render_sweep_approvals(sweep_section, load_all)

            # Deep analysis
            with content:
                _render_net_worth_hero(data)
                _render_cash_flow(data, expense)
                _render_accounts(data, loan_dialog)
                _render_expense_analysis(expense)
                _render_projection(proj, data)

        # Sync button
        async def on_sync():
            sync_btn.props('loading=true')
            try:
                from scheduler import trigger_manual_sync
                await trigger_manual_sync()
                await load_all()
                ui.notify("Sync complete", type='positive')
            except Exception as e:
                ui.notify(f"Sync error: {e}", type='negative')
            finally:
                sync_btn.props('loading=false')

        sync_btn.on('click', on_sync)

        await load_all()
