"""
pages/backtest_runner.py — Run historical and stochastic backtests from the UI.
"""

import asyncio
from datetime import datetime, timedelta

import pandas as pd
import plotly.graph_objects as go

from nicegui import ui

from quant.strategies import registry
from quant.data import fetch_close, fetch_ohlcv
from quant.metrics import compute_all
from quant.stochastic import simulate_multi


async def render():
    ui.label("Backtest Runner").classes("text-2xl font-bold text-white mb-2")
    ui.markdown(
        "Run historical and stochastic backtests for any strategy against real market data."
    ).classes("text-[#8899aa] mb-6")

    registry.discover()

    results_state = {"metrics": None, "figure": None}

    # Configuration row
    with ui.row().classes("w-full gap-4 mb-4 flex-wrap"):
        strat_select = ui.select(
            label="Strategy",
            options=[m.name for m in registry.list_all()],
            value="Bollinger Bands",
        ).classes("w-56").props("outlined dense dark")

        ticker = ui.input(
            label="Ticker", value="AAPL"
        ).classes("w-24").props("outlined dense dark")

        days = ui.number(
            label="History (days)", value=365 * 3, min=30, max=3650, format="%.2f"
        ).classes("w-32").props("outlined dense dark")

        n_paths = ui.number(
            label="Stochastic paths", value=100, min=0, max=5000, format="%.2f"
        ).classes("w-32").props("outlined dense dark")

        run_btn = ui.button(
            "Run Backtest", icon="science",
            on_click=lambda: asyncio.create_task(_run_backtest()),
        ).classes("bg-blue-600 text-white")

    # Progress
    progress = ui.linear_progress(value=0).classes("w-full mb-4")
    progress.set_visibility(False)
    status_label = ui.label("").classes("text-[#8899aa] text-sm")

    # Results area
    metrics_row = ui.row().classes("w-full gap-4 mb-4 flex-wrap")
    plot_area = ui.column().classes("w-full")

    async def _run_backtest():
        progress.set_visibility(True)
        progress.value = 0.1
        status_label.text = "Fetching data..."

        sym = ticker.value.strip().upper()
        try:
            df = fetch_ohlcv(sym, days=int(days.value))
        except Exception as e:
            ui.notify(f"Data fetch failed: {e}", type="negative")
            progress.set_visibility(False)
            return

        if len(df) < 30:
            ui.notify(f"Insufficient data: only {len(df)} rows", type="warning")
            progress.set_visibility(False)
            return

        progress.value = 0.3
        status_label.text = "Running strategy..."

        # Get strategy and generate signals
        cls = registry.get(strat_select.value)
        strat = cls()
        params = strat.default_params()
        entries, exits = strat.generate_signals(df, **params)

        progress.value = 0.5
        status_label.text = "Running historical backtest..."

        # Historical backtest via vectorbt
        import vectorbt as vbt
        close = df["close"]
        pf = vbt.Portfolio.from_signals(
            close, entries, exits, init_cash=10000, freq="1D"
        )
        daily_returns = pf.daily_returns().fillna(0)
        metrics = compute_all(daily_returns)

        # Build equity curve plot
        equity = pf.value()
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=equity.index, y=equity.values,
            mode="lines", name="Portfolio Equity",
            line=dict(color="#4CAF50", width=2),
        ))
        # Add buy/sell markers
        buy_idx = close.index[entries.values]
        sell_idx = close.index[exits.values]
        if len(buy_idx) > 0:
            fig.add_trace(go.Scatter(
                x=buy_idx, y=close[buy_idx],
                mode="markers", name="Buy", marker=dict(color="#00ff00", size=10, symbol="triangle-up"),
            ))
        if len(sell_idx) > 0:
            fig.add_trace(go.Scatter(
                x=sell_idx, y=close[sell_idx],
                mode="markers", name="Sell", marker=dict(color="#ff4444", size=10, symbol="triangle-down"),
            ))
        fig.update_layout(
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font_color="#a8d8ea",
            height=400,
            margin=dict(l=40, r=20, t=40, b=40),
            title=f"{strat.name} — {sym}",
        )

        # Stochastic simulation
        stochastic_results = {}
        if n_paths.value > 0:
            progress.value = 0.7
            status_label.text = f"Running stochastic simulation ({n_paths.value} paths)..."
            price_arr = close.values.astype("float64")
            synth = simulate_multi(
                price_arr, methods=["gbm", "bootstrap"],
                n_paths=int(n_paths.value), horizon_days=252, seed=42,
            )
            for method, paths in synth.items():
                # Run strategy on each path
                method_returns = []
                for i in range(len(paths)):
                    path_df = pd.DataFrame(
                        {"close": paths[i]},
                        index=pd.RangeIndex(len(paths[i])),
                    )
                    try:
                        e, x = strat.generate_signals(path_df, **params)
                        if e.sum() == 0 and x.sum() == 0:
                            continue
                        # Simple portfolio
                        in_pos = False
                        holdings = 0
                        cash = 10000
                        values = []
                        for t_idx in range(len(paths[i])):
                            if e.iloc[t_idx] and not in_pos and cash > 0:
                                holdings = cash / paths[i][t_idx]
                                cash = 0
                                in_pos = True
                            elif x.iloc[t_idx] and in_pos:
                                cash = holdings * paths[i][t_idx]
                                holdings = 0
                                in_pos = False
                            values.append(cash + holdings * paths[i][t_idx])
                        rets = pd.Series(values).pct_change().dropna()
                        if len(rets) > 5:
                            method_returns.append(rets)
                    except Exception:
                        continue

                if method_returns:
                    all_mets = [compute_all(r) for r in method_returns]
                    agg = {}
                    for k in all_mets[0]:
                        vals = [m[k] for m in all_mets if k in m]
                        if vals:
                            agg[k] = {
                                "mean": round(float(pd.Series(vals).mean()), 4),
                                "std": round(float(pd.Series(vals).std()), 4),
                            }
                    stochastic_results[method] = {
                        "success_paths": len(method_returns),
                        "metrics": agg,
                    }

        progress.value = 1.0
        status_label.text = "Done!"

        # Display metrics
        metrics_row.clear()
        with metrics_row:
            with ui.card().classes("bg-[#0a1a2a] p-4"):
                ui.label("Historical Backtest").classes("text-lg font-bold text-white mb-2")
                metric_grid = ui.grid(columns=3).classes("gap-2")
                key_metrics = [
                    ("Total Return", f"{metrics.get('total_return_pct', 0):.2f}%"),
                    ("CAGR", f"{metrics.get('cagr_pct', 0):.2f}%"),
                    ("Sharpe", f"{metrics.get('sharpe_ratio', 0):.2f}"),
                    ("Sortino", f"{metrics.get('sortino_ratio', 0):.2f}"),
                    ("Calmar", f"{metrics.get('calmar_ratio', 0):.2f}"),
                    ("Max DD", f"{metrics.get('max_drawdown_pct', 0):.2f}%"),
                    ("Win Rate", f"{metrics.get('win_rate', 0):.1%}"),
                    ("Profit Factor", f"{metrics.get('profit_factor', 0):.2f}"),
                    ("VaR 95%", f"{metrics.get('var_95_pct', 0):.2f}%"),
                    ("CVaR 95%", f"{metrics.get('cvar_95_pct', 0):.2f}%"),
                    ("Omega", f"{metrics.get('omega_ratio', 0):.2f}"),
                    ("Trades", str(metrics.get('n_trades', 'N/A'))),
                ]
                for label, value in key_metrics:
                    with metric_grid:
                        ui.label(label).classes("text-[#8899aa] text-xs")
                        ui.label(value).classes("text-white text-sm font-mono")

            if stochastic_results:
                with ui.card().classes("bg-[#0a1a2a] p-4"):
                    ui.label("Stochastic Simulation").classes("text-lg font-bold text-white mb-2")
                    for method, sres in stochastic_results.items():
                        ui.label(f"{method.upper()} ({sres['success_paths']} paths)").classes("text-[#a8d8ea] text-sm mt-2")
                        for mk, mv in sres["metrics"].items():
                            ui.label(f"  {mk}: {mv['mean']:.4f} ± {mv['std']:.4f}").classes("text-white text-xs font-mono")

        # Display plot
        plot_area.clear()
        with plot_area:
            ui.plotly(fig).classes("w-full")

        progress.set_visibility(False)
