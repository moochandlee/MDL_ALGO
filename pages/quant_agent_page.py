# pages/quant_agent_page.py
import json
from pathlib import Path
from nicegui import ui
from quant.ollama_bridge import QuantAgent
from quant.engine import run_ma_crossover, run_macd, run_custom
from strategy_store import save_strategies, load_strategies

agent = QuantAgent()

STATUS_OK = False  # populated on first render
chat_messages = []  # list of {"role", "text", "strategy", "backtest_result", "figure"}


async def render():
    global STATUS_OK
    status_ok, _ = await agent.check_connectivity()
    STATUS_OK = status_ok
    status_color = "bg-[#059669]" if status_ok else "bg-[#ef4444]"
    status_text = "connected" if status_ok else "offline"

    with ui.column().classes('w-full p-4'):
        # ── Header ──
        with ui.row().classes('items-center gap-3 w-full'):
            ui.label('Quant Strategy Research').classes('text-2xl text-white')
            ui.badge(status_text, color=status_color).classes('text-xs')

        # ── Chat display ──
        chat_container = ui.column().classes('w-full gap-3 mb-4')

        def rebuild_chat():
            chat_container.clear()
            with chat_container:
                for idx, msg in enumerate(chat_messages):
                    role = msg["role"]
                    text = msg.get("text", "")

                    # ── User messages ──
                    if role == "user":
                        with ui.row().classes('w-full justify-end'):
                            ui.label(text).classes(
                                'bg-[#1e3a5f] text-white rounded-xl rounded-br-sm px-4 py-2 '
                                'max-w-[70%] whitespace-pre-wrap'
                            )
                        continue

                    # ── System messages ──
                    if role == "system":
                        with ui.row().classes('w-full justify-center'):
                            ui.label(text).classes('text-[#8899aa] text-xs italic')
                        continue

                    # ── Error messages ──
                    if role == "error":
                        with ui.row().classes('w-full justify-start'):
                            ui.label(text).classes(
                                'bg-[#3a1515] text-[#ef4444] rounded-xl px-4 py-2 '
                                'max-w-[80%] text-sm border border-[#ef4444] whitespace-pre-wrap'
                            )
                        continue

                    # ── Agent messages ──
                    with ui.row().classes('w-full justify-start'):
                        ui.label(text).classes(
                            'bg-[#0d1526] text-[#a8d8ea] rounded-xl rounded-bl-sm px-4 py-2 '
                            'max-w-[80%] font-mono text-sm border border-[#1e2d4a] whitespace-pre-wrap'
                        )

                    # ── Strategy card (if present) ──
                    strategy = msg.get("strategy")
                    if strategy:
                        _render_strategy_card(strategy, idx, chat_messages, rebuild_chat, spinner)

                    # ── Backtest result + save button ──
                    bt_result = msg.get("backtest_result")
                    if bt_result:
                        with ui.row().classes('w-full justify-start ml-4'):
                            ui.label(bt_result).classes(
                                'bg-[#0a1f0a] text-[#4ade80] rounded-xl px-4 py-2 '
                                'text-sm border border-[#166534] font-mono whitespace-pre-wrap'
                            )

                        def on_add_to_strategies(i=idx):
                            _add_strategy_from_chat(chat_messages[i], rebuild_chat)

                        with ui.row().classes('w-full justify-start ml-4 gap-2'):
                            ui.button('Add to Strategies',
                                      on_click=on_add_to_strategies) \
                                .props('flat').classes('text-[#4ade80] text-xs')

                    # ── Plotly chart (if present) ──
                    figure = msg.get("figure")
                    if figure:
                        with ui.row().classes('w-full justify-start ml-4'):
                            ui.plotly(figure).classes('w-full rounded-xl')

            # Auto-scroll to latest message (best-effort, context may be gone
            # if called from a button handler that triggered a rebuild)
            try:
                ui.run_javascript(
                    'setTimeout(() => { window.scrollTo(0, document.body.scrollHeight); }, 50)'
                )
            except RuntimeError:
                pass

        # ── Quick-action buttons ──
        with ui.row().classes('gap-4 mb-2'):
            async def on_macro():
                await run_chat_ui("Get latest FRED macro data")

            async def on_backtest():
                await run_chat_ui("Run backtest for AAPL 20/50 MA crossover")

            ui.button('Fetch Macro Data', on_click=on_macro) \
                .props('outline color=primary')
            ui.button('Run Backtest (AAPL)', on_click=on_backtest) \
                .props('outline color=secondary')

        # ── Spinner ──
        spinner = ui.spinner('dots', size='lg', color='primary')
        spinner.set_visibility(False)

        # ── Input row ──
        async def on_send():
            await run_chat_ui(prompt.value)

        with ui.row().classes('w-full items-center gap-2'):
            prompt = ui.input(placeholder='Ask for a strategy... (e.g. "Create a MACD strategy for RIVN")') \
                .classes('flex-1') \
                .on('keydown.enter', on_send)
            ui.button('Send', on_click=on_send)

        # ── Core handlers ──
        async def run_chat_ui(user_input):
            if not user_input:
                return
            chat_messages.append({"role": "user", "text": user_input,
                                  "strategy": None, "backtest_result": None,
                                  "figure": None})
            prompt.value = ''
            rebuild_chat()
            spinner.set_visibility(True)

            try:
                result = await agent.chat(user_input)
                chat_messages.append({
                    "role": "agent",
                    "text": result["text"],
                    "strategy": result.get("strategy"),
                    "backtest_result": None,
                    "figure": None,
                })
            except Exception as e:
                chat_messages.append({"role": "error", "text": f"Error: {e}",
                                      "strategy": None, "backtest_result": None,
                                      "figure": None})
            finally:
                spinner.set_visibility(False)
                rebuild_chat()


def _render_strategy_card(strategy, msg_idx, messages, rebuild_fn, spinner=None):
    """Render an editable strategy card inside a chat message."""
    s_type = strategy.get("type", "macd")
    params = strategy.get("parameters", {})

    # Snapshot initial values for default bindings
    ticker_default = strategy.get("ticker", "AAPL")
    alloc_default = strategy.get("allocation_usd", 10000)
    sl_default = strategy.get("stop_loss_pct", 5)
    reinvest_default = strategy.get("reinvest_profits", True)

    with ui.card().classes('bg-[#0d1526] border border-[#1e2d4a] rounded-xl p-4 ml-4 mt-2 w-[90%]'):
        ui.label(f"Strategy: {strategy.get('name', 'Untitled')}") \
            .classes('text-lg font-semibold text-white')

        with ui.grid(columns=3).classes('gap-4 mt-2 w-full'):
            ticker_in = ui.input('Ticker', value=ticker_default).props('dense') \
                .classes('col-span-1')
            alloc_in = ui.number('Allocation ($)', value=alloc_default).props('dense') \
                .classes('col-span-1')
            sl_in = ui.number('Stop-Loss %', value=sl_default).props('dense') \
                .classes('col-span-1')

        # Strategy-specific parameters
        setup_in = entry_in = exit_in = None
        with ui.grid(columns=3).classes('gap-4 w-full'):
            if s_type == "macd":
                fp_in = ui.number('Fast Period', value=params.get("fast_window", 12)) \
                    .props('dense')
                sp_in = ui.number('Slow Period', value=params.get("slow_window", 26)) \
                    .props('dense')
                sig_in = ui.number('Signal Period', value=params.get("signal_window", 9)) \
                    .props('dense')
            elif s_type == "ma_crossover":
                ui.label('MA Crossover').classes('text-[#8899aa] text-sm col-span-3')
                fp_in = ui.number('Short Window',
                                  value=params.get("short_window") or params.get("fast_window", 20)) \
                    .props('dense')
                sp_in = ui.number('Long Window',
                                  value=params.get("long_window") or params.get("slow_window", 50)) \
                    .props('dense')
                sig_in = None
            elif s_type == "custom":
                ui.label('Custom Signals').classes('text-[#8899aa] text-sm col-span-3')
                setup_in = ui.textarea('Setup Code (optional)',
                                       value=params.get("setup_code", ""),
                                       placeholder='import numpy as np; sentiment = pd.Series(np.random.uniform(-1, 1, len(close)), index=close.index)') \
                    .props('dense outlined input-class=font-mono text-xs').classes('col-span-3 font-mono')
                entry_in = ui.input('Entry Condition',
                                    value=params.get("entry_condition", ""),
                                    placeholder='close > close.rolling(20).mean()') \
                    .props('dense outlined').classes('col-span-3 font-mono text-xs')
                exit_in = ui.input('Exit Condition',
                                   value=params.get("exit_condition", ""),
                                   placeholder='close < close.rolling(20).mean()') \
                    .props('dense outlined').classes('col-span-3 font-mono text-xs')
                fp_in = sp_in = sig_in = None
            else:
                ui.label(f'Type: {s_type}').classes('text-[#8899aa] text-sm col-span-3')
                fp_in = sp_in = sig_in = None

        reinvest_sw = ui.switch('Reinvest Profits', value=reinvest_default)

        # ── Date range ──
        from datetime import datetime, timedelta
        with ui.grid(columns=2).classes('gap-4 w-full mt-2'):
            sd_in = ui.input('Start Date', placeholder='YYYY-MM-DD',
                             value=(datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')) \
                .props('dense')
            ed_in = ui.input('End Date', placeholder='YYYY-MM-DD',
                             value=datetime.now().strftime('%Y-%m-%d')) \
                .props('dense')

        # ── Run Backtest button ──
        async def on_run_backtest(i=msg_idx, tick=ticker_in, alloc=alloc_in, sl=sl_in,
                                  rw=reinvest_sw, fp=fp_in, sp=sp_in, sig=sig_in,
                                  sd=sd_in, ed=ed_in, en=entry_in, ex=exit_in,
                                  su=setup_in, _spin=spinner):
            if _spin:
                _spin.set_visibility(True)
            await _run_backtest_for_message(messages[i], tick, alloc, sl, rw,
                                            s_type, fp, sp, sig, en, ex,
                                            sd, ed, su, rebuild_fn)
            if _spin:
                _spin.set_visibility(False)

        ui.button('Run Backtest', on_click=on_run_backtest) \
            .props('outline color=secondary').classes('mt-2')


async def _run_backtest_for_message(msg, ticker_in, alloc_in, sl_in, reinvest_sw,
                                     s_type, fp_in, sp_in, sig_in, entry_in, exit_in,
                                     sd_in, ed_in, setup_in, rebuild_fn):
    """Execute a backtest with the current widget values and store the result.
    Runs the heavy computation in a thread executor to avoid blocking the UI."""
    import asyncio
    from datetime import datetime
    symbol = ticker_in.value.upper().strip() or "AAPL"
    loop = asyncio.get_event_loop()

    # Parse dates
    def _parse_date(s):
        try:
            return datetime.strptime(s.strip(), '%Y-%m-%d') if s and s.strip() else None
        except ValueError:
            return None
    start_date = _parse_date(sd_in.value)
    end_date = _parse_date(ed_in.value)

    try:
        if s_type == "macd":
            fp = int(fp_in.value or 12)
            sp = int(sp_in.value or 26)
            sig = int(sig_in.value or 9)
            result = await loop.run_in_executor(
                None, lambda: run_macd(symbol, fp, sp, sig,
                                       start_date=start_date, end_date=end_date,
                                       return_plot=True)
            )
            label = f"MACD ({fp}/{sp}/{sig})"
        elif s_type == "ma_crossover":
            short_w = int(fp_in.value or 20)
            long_w = int(sp_in.value or 50)
            result = await loop.run_in_executor(
                None, lambda: run_ma_crossover(symbol, short_w, long_w,
                                                start_date=start_date, end_date=end_date,
                                                return_plot=True)
            )
            label = f"MA Crossover ({short_w}/{long_w})"
        elif s_type == "custom":
            entry_cond = entry_in.value if entry_in else ""
            exit_cond = exit_in.value if exit_in else ""
            setup_code = setup_in.value if setup_in else None
            if not entry_cond or not exit_cond:
                msg["backtest_result"] = "Enter both Entry and Exit conditions"
                rebuild_fn()
                return
            result = await loop.run_in_executor(
                None, lambda: run_custom(symbol, entry_cond, exit_cond,
                                          start_date=start_date, end_date=end_date,
                                          return_plot=True, setup_code=setup_code)
            )
            label = "Custom"
        else:
            msg["backtest_result"] = f"Unknown strategy type: {s_type}"
            rebuild_fn()
            return

        msg["backtest_result"] = (
            f"Backtest: {symbol} | {label}\n"
            f"Return: {result['return_pct']:.2f}%\n"
            f"Stop-Loss: {float(sl_in.value or 0)}% | "
            f"Reinvest: {'Yes' if reinvest_sw.value else 'No'}"
        )
        msg["figure"] = result.get("figure")
    except Exception as e:
        msg["backtest_result"] = f"Backtest Error ({symbol}): {e}"
        msg["figure"] = None

    rebuild_fn()


def _add_strategy_from_chat(msg, rebuild_fn):
    """Save a strategy from a chat message to strategies.json."""
    strategy = msg.get("strategy")
    bt_result = msg.get("backtest_result", "")
    if not strategy:
        ui.notify('No strategy data to save', type='warning')
        return

    # Parse return % from backtest result if available
    import re
    ret_match = re.search(r'Total Return:\s*([-\d.]+)%', bt_result)

    strat_entry = {
        "name": strategy.get("name", "Custom Strategy"),
        "ticker": strategy.get("ticker", "AAPL"),
        "allocation_usd": strategy.get("allocation_usd", 10000),
        "active": True,
        "reinvest_profits": strategy.get("reinvest_profits", True),
        "stop_loss_pct": strategy.get("stop_loss_pct", 5),
        "strategy_type": strategy.get("type", "macd"),
        "parameters": strategy.get("parameters", {}),
    }
    if ret_match:
        strat_entry["backtest_return_pct"] = float(ret_match.group(1))

    strategies = load_strategies()
    strategies.append(strat_entry)
    save_strategies(strategies)
    msg["saved"] = True
    ui.notify(f"Strategy '{strat_entry['name']}' added!", type='positive')
    rebuild_fn()
