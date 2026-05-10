"""
scheduler.py — APScheduler background jobs
"""

import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime
from nicegui import app

from config import settings


scheduler = AsyncIOScheduler()


async def daily_sync_job():
    """Main daily sync: Teller + Schwab + alerts + sweep check."""
    from teller_client import sync_teller, get_latest_balances
    from schwab_client import get_balances_and_positions, recommend_sweep
    from notifications import (
        notify_low_balance, notify_large_debit,
        notify_sweep_recommendation, notify_daily_summary,
    )

    print(f"[scheduler] Daily sync started at {datetime.now().isoformat()}")

    # 1. Sync Teller
    teller_result = {}
    try:
        teller_result = sync_teller()
    except Exception as e:
        print(f"[scheduler] Teller sync error: {e}")

    # 2. Get Schwab data
    schwab_data = {}
    try:
        schwab_data = get_balances_and_positions()
    except Exception as e:
        print(f"[scheduler] Schwab error: {e}")

    # 3. Check alerts
    bank_balances = get_latest_balances()

    for b in bank_balances:
        try:
            avail = float(b.get("available") or 0)
            if avail < settings.low_balance_alert:
                notify_low_balance(b.get("account_name",""), b.get("institution",""), avail)
        except Exception:
            pass

    # Check large debits from today's new transactions
    new_txns = teller_result.get("new_transactions", 0)
    # (Full debit scan happens in ledger page; here we use the queue)

    # 4. Sweep recommendation
    try:
        rec = recommend_sweep(bank_balances, schwab_data)
        if rec:
            # Queue for dashboard approval
            app.state.pending_orders = app.state.pending_orders + [rec]
            notify_sweep_recommendation(
                rec["symbol"], rec["shares"], rec["approx_cost"], rec["reason"]
            )
    except Exception as e:
        print(f"[scheduler] Sweep check error: {e}")

    # 5. Daily push summary
    try:
        liq = schwab_data.get("liquidation_value", 0)
        notify_daily_summary(len(bank_balances), new_txns, liq)
    except Exception:
        pass

    # 6. Update app state
    app.state.last_sync = datetime.now().strftime("%H:%M")
    print(f"[scheduler] Daily sync complete.")


def start_scheduler():
    hour, minute = settings.sync_time.split(":")

    scheduler.add_job(
        daily_sync_job,
        CronTrigger(hour=int(hour), minute=int(minute)),
        id="daily_sync",
        replace_existing=True,
    )

    # Also allow a manual trigger from UI (job ID "manual_sync")
    scheduler.start()
    print(f"[scheduler] Scheduler started. Daily sync at {settings.sync_time}.")


async def trigger_manual_sync():
    """Called from dashboard 'Sync Now' button."""
    await daily_sync_job()
