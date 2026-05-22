"""
pages/strategies.py — Strategy backtests + live signal dashboard
"""

import asyncio
import traceback
import pandas as pd
import yfinance as yf
import numpy as np
from nicegui import ui

from config import settings

SECTORS = {
    "XLK": "Technology", "XLF": "Financials", "XLE": "Energy",
    "XLV": "Health Care", "XLP": "Consumer Staples", "XLY": "Consumer Disc.",
    "XLI": "Industrials", "XLB": "Materials", "XLU": "Utilities",
    "XLRE": "Real Estate", "SMH": "Semiconductors",
}


async def render():
    ui.label("Strategy Lab").classes("text-2xl font-bold text-white mb-6")
    ui.markdown("Backtest and monitor trading strategies using **yfinance** data.").classes("text-[#8899aa] mb-8")

    with ui.tabs().classes("w-full bg-[#0a0f1e]") as tabs:
        s_rot = ui.tab("Sector Rotation", icon="swap_horiz")
        w_opt = ui.tab("Options Wheel", icon="currency_exchange")
        b_ts = ui.tab("Backtest Runner", icon="science")

    with ui.tab_panels(tabs, value=s_rot).classes("w-full bg-[#0a0f1e] border border-[#1e2d4a] rounded-xl p-6"):
        with ui.tab_panel(s_rot):    await _sector_rotation()
        with ui.tab_panel(w_opt):    await _options_wheel()
        with ui.tab_panel(b_ts):     await _backtest()


async def _sector_rotation():
    ui.label("Sector Momentum").classes("text-lg font-semibold text-white mb-2")
    ui.markdown("Top 3 sectors by 1-month momentum. Rotate monthly.").classes("text-[#8899aa] mb-4")

    output = ui.column().classes("w-full")
    with output:
        ui.spinner(size="lg").classes("text-[#4fc3f7]")

    await asyncio.sleep(0.5)

    try:
        data = yf.download(list(SECTORS), period="3mo", progress=False, auto_adjust=True)
        closes = data["Close"] if isinstance(data.columns, pd.MultiIndex) else pd.DataFrame()
        if closes.empty:
            raise ValueError("No data returned from yfinance")

        rows = []
        for t in closes.columns:
            px = closes[t].dropna()
            if len(px) > 5:
                r1m = float((px.iloc[-1] / px.iloc[-int(len(px)**0.35)] - 1) * 100)
                r3m = float((px.iloc[-1] / px.iloc[0] - 1) * 100)
                rows.append({"ticker": t, "name": SECTORS.get(t, ""), "r1m": r1m, "r3m": r3m})

        rows.sort(key=lambda r: r["r1m"], reverse=True)
        top3 = [r["ticker"] for r in rows[:3]]

        output.clear()
        with output:
            cols = [
                {"name": "t", "label": "Ticker", "field": "ticker", "align": "left"},
                {"name": "n", "label": "Sector", "field": "name"},
                {"name": "m1", "label": "1M %", "field": "r1m", "sortable": True},
                {"name": "m3", "label": "3M %", "field": "r3m", "sortable": True},
            ]

            ui.table(columns=cols, rows=rows, row_key="ticker").classes("w-full")

            if top3:
                ui.markdown(
                    f"**Signal:** Hold **{', '.join(top3)}**"
                ).classes("mt-4 p-3 bg-[#0d1f12] rounded-lg text-[#4caf50] font-bold")

    except Exception as e:
        tb = traceback.format_exc()
        output.clear()
        with output:
            ui.markdown(f"**Could not load data:** {e}").classes("text-red-400 p-4")
            ui.markdown(f"```\n{tb}\n```").classes("text-[#8899aa] text-xs")


async def _options_wheel():
    ui.label("Options Wheel Scanner").classes("text-lg font-semibold text-white mb-2")

    inp = ui.input("Tickers (comma sep)", value="SOFI, PLTR, CHWY, HOOD").classes("w-full max-w-lg mb-4")
    out = ui.column().classes("w-full")

    async def scan():
        out.clear()
        with out:
            s = ui.spinner(size="lg").classes("text-[#4fc3f7]")

        tickers = [t.strip().upper() for t in inp.value.split(",") if t.strip()]
        try:
            data = yf.download(tickers, period="5d", progress=False, auto_adjust=True)
            closes = data["Close"] if isinstance(data.columns, pd.MultiIndex) else pd.DataFrame()
            out.clear()
            with out:
                for t in tickers:
                    try:
                        px = closes[t].dropna()
                        if px.empty:
                            continue
                        price = float(px.iloc[-1])
                        prem = round(price * 0.025, 2)
                        coll = round(price * 0.80, 2)
                        yld = round((prem / coll) * 100, 1)
                        ann = round(yld * 12, 1)
                        c = "text-green-400" if ann > 15 else "text-yellow-400" if ann > 10 else "text-gray-400"
                        ui.markdown(f"**{t}** ${price:.2f} | Prem: ${prem} | Coll: ${coll:.0f} | {yld}% ({ann}% ann.)").classes(f"p-2 mb-1 bg-[#111827] rounded {c}")
                    except Exception:
                        continue
        except Exception as e:
            tb = traceback.format_exc()
            out.clear()
            with out:
                ui.markdown(f"**Error:** {e}").classes("text-red-400")
                ui.markdown(f"```\n{tb}\n```").classes("text-[#8899aa] text-xs")

    ui.button("Scan", on_click=scan, icon="search").props("flat").classes("bg-[#1e3a5f] text-white mb-4")


async def _backtest():
    ui.label("Sector Rotation Backtest").classes("text-lg font-semibold text-white mb-2")
    ui.markdown("Each month: buy top 3 sectors, hold 1 month, repeat.").classes("text-[#8899aa] mb-4")

    out = ui.column().classes("w-full")

    async def run():
        out.clear()
        with out:
            ui.spinner(size="lg").classes("text-[#4fc3f7]")
            ui.label("Downloading 3 years of data...").classes("text-[#8899aa]")
        await asyncio.sleep(0.5)

        try:
            data = yf.download(list(SECTORS), period="3y", progress=False, auto_adjust=True)
            prices = data["Close"] if isinstance(data.columns, pd.MultiIndex) else pd.DataFrame()
            if prices.empty:
                raise ValueError("No data")

            arr = prices.to_numpy(dtype=np.float64, na_value=np.nan)
            bal = 10000.0
            for i in range(3, len(arr)):
                r = arr[i-1] / arr[i-3] - 1.0
                top_idx = np.argsort(r)[-3:]
                if i + 1 < len(arr):
                    ret = float(np.nanmean(arr[i+1][top_idx]) / np.nanmean(arr[i][top_idx]) - 1.0)
                    bal *= (1.0 + ret)

            total = round((bal - 10000.0) / 10000.0 * 100, 1)
            spy = yf.download("SPY", period="3y", progress=False, auto_adjust=True)
            spy_c = spy["Close"] if isinstance(spy.columns, pd.MultiIndex) else spy
            spy_r = round((float(spy_c.iloc[-1]) / float(spy_c.iloc[0]) - 1) * 100, 1)

            out.clear()
            with out:
                ui.markdown(f"**Start:** $10,000  →  **End:** ${bal:,.0f}").classes("text-lg")
                ui.markdown(f"**Strategy:** +{total}%  |  **SPY:** +{spy_r}%").classes("text-lg")
                if total > spy_r:
                    ui.markdown(f"**Beat SPY by {total - spy_r}%**").classes("text-green-400 font-bold")
                else:
                    ui.markdown(f"**Underperformed SPY by {spy_r - total}%**").classes("text-red-400 font-bold")

        except Exception as e:
            tb = traceback.format_exc()
            out.clear()
            with out:
                ui.markdown(f"**Error:** {e}").classes("text-red-400")
                ui.markdown(f"```\n{tb}\n```").classes("text-[#8899aa] text-xs")

    ui.button("Run 3-Year Backtest", on_click=run, icon="play_arrow").props("flat").classes("bg-[#1e3a5f] text-white mb-4")
    ui.markdown("Past performance != future results.").classes("text-[#667788] text-sm")
