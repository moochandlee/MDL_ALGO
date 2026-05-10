"""
Finance Autopilot — main.py
NiceGUI app combining Schwab brokerage + Teller bank data
"""

import asyncio
from nicegui import app, ui
from datetime import datetime

from config import settings
from scheduler import start_scheduler
from pages import dashboard, ledger, orders, settings_page, alerts


# ── PWA manifest + service worker registration ──────────────────────────────
app.add_static_files('/static', 'static')

@app.get('/manifest.json')
async def manifest():
    from fastapi.responses import JSONResponse
    return JSONResponse({
        "name": "Finance Autopilot",
        "short_name": "Autopilot",
        "description": "Personal finance automation dashboard",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0a0f1e",
        "theme_color": "#0a0f1e",
        "icons": [
            {"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png"},
        ]
    })


# ── Shared state (in-memory, survives page navigation) ──────────────────────
app.state.last_sync     = None
app.state.alerts_queue  = []
app.state.pending_orders = []


# ── Global layout shell ──────────────────────────────────────────────────────
def nav_shell():
    menu_btn = None

    with ui.header(elevated=True).classes('items-center justify-between px-6 bg-[#0a0f1e] border-b border-[#1e2d4a]').style('padding-top: max(12px, env(safe-area-inset-top)); padding-bottom: 12px;'):
        with ui.row().classes('items-center gap-3'):
            menu_btn = ui.button(icon='menu').props('flat round dense').classes('text-white')
            ui.icon('auto_awesome', size='1.6rem').classes('text-[#4fc3f7]')
            ui.label('Finance Autopilot').classes('text-white font-bold text-lg tracking-tight')

        with ui.row().classes('items-center gap-2'):
            clock = ui.label().classes('text-[#8899aa] text-sm font-mono')
            async def tick():
                while True:
                    clock.set_text(datetime.now().strftime('%a %b %d  %H:%M:%S'))
                    await asyncio.sleep(1)
            asyncio.create_task(tick())

            ui.badge('', color='green').bind_text_from(
                app.state, 'last_sync',
                backward=lambda v: f"Synced {v}" if v else "Not synced"
            ).classes('text-xs')

    drawer = ui.left_drawer(fixed=True).classes('bg-[#060c1a] border-r border-[#1e2d4a] pt-4')
    menu_btn.on('click', drawer.toggle)

    with drawer:
        nav_items = [
            ('dashboard',   'Dashboard',   '/'),
            ('receipt_long','Ledger',      '/ledger'),
            ('trending_up', 'Orders',      '/orders'),
            ('notifications','Alerts',     '/alerts'),
            ('settings',    'Settings',    '/settings'),
        ]
        for icon, label, path in nav_items:
            with ui.link(target=path).classes('no-underline w-full'):
                with ui.row().classes(
                    'items-center gap-3 px-4 py-3 rounded-lg mx-2 mb-1 '
                    'text-[#8899aa] hover:text-white hover:bg-[#1e2d4a] cursor-pointer transition-colors'
                ):
                    ui.icon(icon, size='1.2rem')
                    ui.label(label).classes('text-sm font-medium')


# ── Routes ───────────────────────────────────────────────────────────────────
@ui.page('/')
async def index():
    ui.add_head_html('''
        <link rel="manifest" href="/manifest.json">
        <meta name="theme-color" content="#0a0f1e">
        <meta name="apple-mobile-web-app-capable" content="yes">
        <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
        <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
        <style>
            body { background: #0a0f1e; }
            .nicegui-content { padding: 0 !important; }
        </style>
    ''')
    nav_shell()
    await dashboard.render()


@ui.page('/ledger')
async def ledger_page():
    ui.add_head_html('<style>body{background:#0a0f1e}</style>')
    nav_shell()
    await ledger.render()


@ui.page('/orders')
async def orders_page():
    ui.add_head_html('<style>body{background:#0a0f1e}</style>')
    nav_shell()
    await orders.render()


@ui.page('/alerts')
async def alerts_page():
    ui.add_head_html('<style>body{background:#0a0f1e}</style>')
    nav_shell()
    await alerts.render()


@ui.page('/settings')
async def settings_pg():
    ui.add_head_html('<style>body{background:#0a0f1e}</style>')
    nav_shell()
    await settings_page.render()


# ── Startup ──────────────────────────────────────────────────────────────────
@app.on_startup
async def startup():
    start_scheduler()
    print("Finance Autopilot started.")


ui.run(
    title='Finance Autopilot',
    favicon='💹',
    dark=True,
    port=8080,
    reload=False,
)
