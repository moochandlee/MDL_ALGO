"""
pages/alerts.py — Alert history and manual notification test
"""

import asyncio
from nicegui import ui, app
from datetime import datetime


async def render():
    with ui.column().classes('w-full min-h-screen bg-[#0a0f1e] p-6 gap-6'):

        with ui.row().classes('w-full items-center justify-between'):
            with ui.column().classes('gap-1'):
                ui.label('Alerts').classes('text-2xl font-bold text-white')
                ui.label('Notifications history and test tools').classes('text-[#8899aa] text-sm')

        # ── Test notifications ────────────────────────────────────────
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
                        "Your iOS push notifications are working! 🎉",
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

        # ── ntfy.sh setup instructions ────────────────────────────────
        with ui.card().classes('w-full bg-[#0d1526] border border-[#1e2d4a] rounded-xl p-6'):
            ui.label('iOS Push Setup (ntfy.sh)').classes('text-white font-semibold mb-3')

            steps = [
                ("1", "Install the free ntfy app", "Download 'ntfy' from the App Store (free, open-source)"),
                ("2", "Choose a private topic name", "Use something hard to guess, e.g. finance-autopilot-x7k2m9"),
                ("3", "Subscribe in the app", "Tap '+' in ntfy and enter your topic name"),
                ("4", "Add to .env", "Set NTFY_TOPIC=your-topic-name in your .env file"),
                ("5", "Test it", "Use the 'Test iOS Push' button above"),
            ]

            for num, title, desc in steps:
                with ui.row().classes('items-start gap-4 mb-4'):
                    with ui.element('div').classes(
                        'w-8 h-8 rounded-full bg-[#4fc3f722] border border-[#4fc3f755] '
                        'flex items-center justify-center shrink-0 mt-0.5'
                    ):
                        ui.label(num).classes('text-[#4fc3f7] text-xs font-bold')
                    with ui.column().classes('gap-0'):
                        ui.label(title).classes('text-white text-sm font-medium')
                        ui.label(desc).classes('text-[#8899aa] text-xs')

            ui.label('Optional: Self-host ntfy on your server for full privacy. See ntfy.sh/docs').classes(
                'text-[#4a5568] text-xs mt-2'
            )

        # ── Alert queue ───────────────────────────────────────────────
        with ui.card().classes('w-full bg-[#0d1526] border border-[#1e2d4a] rounded-xl p-6'):
            ui.label('Recent Alerts').classes('text-white font-semibold mb-3')
            queue = getattr(app.state, 'alerts_queue', [])
            if not queue:
                ui.label('No alerts recorded this session.').classes('text-[#8899aa] text-sm')
            else:
                for alert in reversed(queue[-20:]):
                    with ui.row().classes('items-start gap-3 py-2 border-b border-[#1e2d4a]'):
                        ui.icon('notifications', size='1rem').classes('text-[#f59e0b] mt-0.5')
                        with ui.column().classes('gap-0'):
                            ui.label(alert.get("title","")).classes('text-white text-sm')
                            ui.label(alert.get("time","")).classes('text-[#8899aa] text-xs')
