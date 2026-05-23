"""
pages/strategy_browser.py — Browse, search, and manage all 151 strategies.
"""

import asyncio
from nicegui import ui

from quant.strategies import registry


async def render():
    ui.label("Strategy Library").classes("text-2xl font-bold text-white mb-2")
    ui.markdown(
        "Browse the complete catalog of trading strategies based on "
        "Kakushadze & Serur (2018). Filter by category, asset class, or search by name."
    ).classes("text-[#8899aa] mb-6")

    # Discover strategies
    registry.discover()

    # Filter bar
    with ui.row().classes("w-full gap-4 mb-4"):
        search = ui.input(
            "Search strategies...",
            on_change=lambda: _refresh_table(),
        ).classes("w-64").props("outlined dense dark")

        cat_select = ui.select(
            label="Category",
            options=["All"] + registry.categories,
            value="All",
            on_change=lambda: _refresh_table(),
        ).classes("w-44").props("outlined dense dark")

        asset_select = ui.select(
            label="Asset Class",
            options=["All", "equity", "etf", "fx", "crypto"],
            value="All",
            on_change=lambda: _refresh_table(),
        ).classes("w-36").props("outlined dense dark")

    # Stats row
    stats = ui.row().classes("gap-4 mb-4")

    # Table container
    table_container = ui.column().classes("w-full")

    async def _refresh_table():
        table_container.clear()
        with table_container:
            query = (search.value or "").lower()
            cat = cat_select.value
            asset = asset_select.value

            metas = registry.list_all()
            if cat != "All":
                metas = [m for m in metas if m.category == cat]
            if asset != "All":
                metas = [m for m in metas if asset in m.asset_classes]
            if query:
                metas = [m for m in metas if query in m.name.lower()
                         or query in m.category.lower()
                         or query in m.description.lower()]

            with stats:
                stats.clear()
                ui.label(f"{len(metas)} strategies").classes("text-sm text-[#8899aa]")

            # Build the table using NiceGUI's grid
            columns = [
                {"name": "name", "label": "Strategy", "field": "name", "align": "left"},
                {"name": "category", "label": "Category", "field": "category"},
                {"name": "assets", "label": "Asset Classes", "field": "assets"},
                {"name": "section", "label": "Paper §", "field": "section"},
                {"name": "params", "label": "Params", "field": "params"},
            ]
            rows = [
                {
                    "name": m.name,
                    "category": m.category,
                    "assets": ", ".join(m.asset_classes),
                    "section": m.paper_section,
                    "params": m.param_count,
                }
                for m in metas
            ]

            ui.table(
                columns=columns, rows=rows,
                row_key="name",
                pagination={"rowsPerPage": 25, "sortBy": "category"},
            ).classes("w-full").props("dense dark")

    await _refresh_table()


async def _strategy_detail(strategy_name: str):
    """Show detail dialog for a strategy."""
    cls = registry.get(strategy_name)
    if cls is None:
        return
    meta = cls.to_meta()
    strat = cls()

    with ui.dialog().props("max-width=600px") as dialog, ui.card().classes("bg-[#0a0f1e] text-white p-6"):
        ui.label(meta.name).classes("text-xl font-bold mb-2")
        ui.markdown(meta.description).classes("text-[#8899aa] mb-4")

        with ui.grid(columns=2).classes("gap-2 mb-4"):
            ui.label("Category:").classes("text-[#8899aa]")
            ui.label(meta.category).classes("text-white")
            ui.label("Asset Classes:").classes("text-[#8899aa]")
            ui.label(", ".join(meta.asset_classes)).classes("text-white")
            ui.label("Paper Section:").classes("text-[#8899aa]")
            ui.label(meta.paper_section).classes("text-white")

        params = strat.default_params()
        if params:
            ui.label("Default Parameters:").classes("text-[#8899aa] mt-2")
            for k, v in params.items():
                ui.label(f"  {k}: {v}").classes("text-white text-sm")

        param_grid = strat.param_grid()
        if param_grid:
            ui.label("Parameter Grid:").classes("text-[#8899aa] mt-2")
            for k, v in param_grid.items():
                ui.label(f"  {k}: {v}").classes("text-white text-sm")

    dialog.open()
