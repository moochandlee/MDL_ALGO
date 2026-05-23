"""
pages/results_dashboard.py — View strategy ranking results and top performers.
"""

import json
import asyncio
from pathlib import Path

import plotly.graph_objects as go
from nicegui import ui

from quant.strategies import registry
from quant.data import get_available_tickers
from quant.ranking import RANKINGS_DIR

RANKINGS_FILE = RANKINGS_DIR / "latest.json"


async def render():
    ui.label("Results Dashboard").classes("text-2xl font-bold text-white mb-2")
    ui.markdown(
        "View the latest strategy ranking results. Run a batch ranking to find the "
        "best strategies for your hardware and asset constraints."
    ).classes("text-[#8899aa] mb-6")

    registry.discover()

    # Control bar
    with ui.row().classes("w-full gap-4 mb-4"):
        asset_btn = ui.select(
            label="Asset Class",
            options=["equity", "etf", "fx", "crypto"],
            value="equity",
        ).classes("w-36").props("outlined dense dark")

        run_btn = ui.button(
            "Run Ranking", icon="analytics",
            on_click=lambda: asyncio.create_task(_run_ranking()),
        ).classes("bg-blue-600 text-white")

        ui.button(
            "Load Latest", icon="folder_open",
            on_click=lambda: _load_results(),
        ).classes("bg-[#1e2d4a] text-white")

    progress = ui.linear_progress(value=0).classes("w-full mb-4")
    progress.set_visibility(False)
    status_label = ui.label("").classes("text-[#8899aa] text-sm")

    results_container = ui.column().classes("w-full")

    async def _run_ranking():
        from quant.ranking import RankingConfig, run_batch_ranking

        progress.set_visibility(True)
        status_label.text = "Starting batch ranking..."

        asset_class = asset_btn.value
        tickers = get_available_tickers(asset_class)[:10]  # top 10 for speed

        progress.value = 0.1
        status_label.text = f"Evaluating {registry.count} strategies on {len(tickers)} {asset_class} tickers..."

        def update_progress(msg, frac):
            status_label.text = msg
            progress.value = 0.1 + frac * 0.85

        config = RankingConfig(
            n_stochastic_paths=200,  # lower for UI responsiveness
            max_strategies=30,
            n_jobs=1,
        )

        try:
            strategy_classes = [registry.get(m.name) for m in registry.list_all()
                              if asset_class in m.asset_classes or "all" in m.asset_classes]
            strategy_classes = [c for c in strategy_classes if c is not None]

            results = run_batch_ranking(
                strategy_classes,
                tickers_by_asset={asset_class: tickers},
                output_file=str(RANKINGS_FILE),
                config=config,
                progress_callback=update_progress,
            )
        except Exception as e:
            ui.notify(f"Ranking failed: {e}", type="negative")
            progress.set_visibility(False)
            return

        progress.value = 1.0
        status_label.text = f"Done! {len(results)} strategy+ticker combos ranked."
        progress.set_visibility(False)

        _display_results(results)

    def _load_results():
        if not RANKINGS_FILE.exists():
            ui.notify("No ranking results found. Run a ranking first.", type="warning")
            return
        results = json.loads(RANKINGS_FILE.read_text())
        _display_results(results)

    def _display_results(results):
        results_container.clear()
        with results_container:
            if not results:
                ui.label("No results yet.").classes("text-[#8899aa]")
                return

            # Summary stats
            top10 = results[:min(10, len(results))]
            top_return = max(r.get("historical", {}).get("total_return_pct", 0) for r in results)
            top_sharpe = max(r.get("historical", {}).get("sharpe_ratio", 0) for r in results)

            with ui.row().classes("gap-4 mb-4"):
                with ui.card().classes("bg-[#0a1a2a] p-4"):
                    ui.label(f"{len(results)}").classes("text-3xl font-bold text-white")
                    ui.label("Strategy Combos").classes("text-[#8899aa] text-sm")
                with ui.card().classes("bg-[#0a1a2a] p-4"):
                    ui.label(f"{top_return:.1f}%").classes("text-3xl font-bold text-green-400")
                    ui.label("Best Return").classes("text-[#8899aa] text-sm")
                with ui.card().classes("bg-[#0a1a2a] p-4"):
                    ui.label(f"{top_sharpe:.2f}").classes("text-3xl font-bold text-blue-400")
                    ui.label("Best Sharpe").classes("text-[#8899aa] text-sm")

            # Bar chart of top 10 composite scores
            fig = go.Figure()
            names = [f"{r['strategy'][:25]}\n{r.get('ticker','')}" for r in top10]
            scores = [r.get("composite_score", 0) for r in top10]
            fig.add_trace(go.Bar(
                x=names, y=scores,
                marker_color=["#4CAF50" if s > 50 else "#FFC107" if s > 30 else "#F44336"
                             for s in scores],
                text=[f"{s:.1f}" for s in scores],
                textposition="auto",
            ))
            fig.update_layout(
                template="plotly_dark",
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font_color="#a8d8ea",
                height=350,
                margin=dict(l=20, r=20, t=20, b=80),
                title="Top 10 — Composite Score",
                xaxis_tickangle=-45,
            )
            ui.plotly(fig).classes("w-full mb-4")

            # Full results table
            columns = [
                {"name": "rank", "label": "#", "field": "rank", "sortable": True},
                {"name": "strategy", "label": "Strategy", "field": "strategy", "align": "left"},
                {"name": "ticker", "label": "Ticker", "field": "ticker"},
                {"name": "category", "label": "Category", "field": "category"},
                {"name": "composite", "label": "Score", "field": "composite", "sortable": True},
                {"name": "return", "label": "Return%", "field": "return_pct", "sortable": True},
                {"name": "sharpe", "label": "Sharpe", "field": "sharpe", "sortable": True},
                {"name": "maxdd", "label": "MaxDD%", "field": "maxdd", "sortable": True},
            ]
            rows = []
            for i, r in enumerate(results):
                h = r.get("historical", {})
                rows.append({
                    "rank": i + 1,
                    "strategy": r.get("strategy", ""),
                    "ticker": r.get("ticker", ""),
                    "category": r.get("category", ""),
                    "composite": r.get("composite_score", 0),
                    "return_pct": round(h.get("total_return_pct", 0), 1),
                    "sharpe": round(h.get("sharpe_ratio", 0), 2),
                    "maxdd": round(h.get("max_drawdown_pct", 0), 1),
                })

            ui.table(
                columns=columns, rows=rows,
                row_key="rank",
                pagination={"rowsPerPage": 20, "sortBy": "composite", "descending": True},
            ).classes("w-full").props("dense dark")

    # Auto-load if results exist
    _load_results()
