import pandas as pd
import vectorbt as vbt
import plotly.graph_objects as go
from datetime import datetime, timedelta
from typing import Optional


def _fig_from(fw) -> go.Figure:
    """Convert a vectorbt plot (FigureWidget) to a standard plotly Figure."""
    return go.Figure(data=fw.data, layout=fw.layout)


def _fetch_prices(symbol: str, days: int = 365,
                  start_date: Optional[datetime] = None,
                  end_date: Optional[datetime] = None) -> pd.Series:
    """Fetch historical close prices, trying Schwab first then yfinance."""
    if end_date is None:
        end_date = datetime.now()
    if start_date is None:
        start_date = end_date - timedelta(days=days)
    if start_date.tzinfo is None:
        start_date = start_date.replace(tzinfo=None)
    if end_date.tzinfo is None:
        end_date = end_date.replace(tzinfo=None)

    # Try Schwab API first (authenticated, no rate limits)
    try:
        from schwab_client import get_client
        client = get_client()
        start_ms = int(start_date.timestamp() * 1000)
        end_ms = int(end_date.timestamp() * 1000)
        # Schwab needs periodType when using daily frequency
        total_years = max((end_date - start_date).days / 365.0, 0.5)
        period = min(max(1, round(total_years)), 20)
        r = client.price_history(symbol, periodType='year', period=period,
                                 startDate=start_ms, endDate=end_ms,
                                 frequencyType='daily', frequency=1)
        if r.ok:
            candles = r.json().get("candles", [])
            if len(candles) > 20:
                df = pd.DataFrame(candles)
                df['datetime'] = pd.to_datetime(df['datetime'], unit='ms')
                series = df.set_index('datetime')['close'].astype('float64').sort_index()
                expected = max((end_date - start_date).days * 2 // 5, 20)
                if len(series) >= expected * 0.3:
                    return series
    except Exception:
        pass

    # Fall back to yfinance
    return _fetch_prices_yfinance(symbol, start_date=start_date, end_date=end_date)


def _fetch_prices_yfinance(symbol: str, days: int = 365,
                            start_date: Optional[datetime] = None,
                            end_date: Optional[datetime] = None) -> pd.Series:
    """Fetch historical close prices via yfinance (free fallback)."""
    import time
    if end_date is None:
        end_date = datetime.now()
    if start_date is None:
        start_date = end_date - timedelta(days=days)

    try:
        import yfinance as yf
        for attempt in range(3):
            df = yf.download(symbol, start=start_date.strftime('%Y-%m-%d'),
                             end=end_date.strftime('%Y-%m-%d'), progress=False,
                             auto_adjust=True)
            if not df.empty:
                break
            time.sleep(2 ** attempt)
        if df.empty:
            raise ValueError(f"No data returned for {symbol}")
        if hasattr(df.columns, 'levels'):
            if ('Close', symbol) in df.columns:
                close = df[('Close', symbol)]
            else:
                close = df['Close'].iloc[:, 0] if df['Close'].ndim > 1 else df['Close']
        else:
            close = df['Close']
        return close.astype('float64').dropna()
    except ImportError:
        raise ImportError("yfinance is required for backtesting. Install with: pip install yfinance")


def run_ma_crossover(symbol: str, short_window: int, long_window: int,
                     start_date: Optional[datetime] = None,
                     end_date: Optional[datetime] = None,
                     return_plot: bool = False):
    """
    Run a Moving Average crossover backtest.
    Returns total return as a percentage float, or dict with 'return_pct' and 'figure'
    when return_plot=True.
    """
    min_days = max(long_window * 4, 365)
    data = _fetch_prices(symbol, days=min_days, start_date=start_date, end_date=end_date)

    if len(data) < long_window:
        return 0.0

    fast_ma = vbt.MA.run(data, short_window)
    slow_ma = vbt.MA.run(data, long_window)

    entries = fast_ma.ma_crossed_above(slow_ma)
    exits = fast_ma.ma_crossed_below(slow_ma)

    pf = vbt.Portfolio.from_signals(data, entries, exits, init_cash=10000)
    ret = round(float(pf.total_return()) * 100, 2)

    if return_plot:
        fig = _fig_from(pf.plot())
        return {"return_pct": ret, "figure": fig}
    return ret


def run_macd(symbol: str, fast_window: int = 12, slow_window: int = 26,
             signal_window: int = 9,
             start_date: Optional[datetime] = None,
             end_date: Optional[datetime] = None,
             return_plot: bool = False):
    """
    Run a MACD crossover backtest.
    Entry: MACD line crosses above signal line.
    Exit: MACD line crosses below signal line.
    Returns total return as a percentage float, or dict with 'return_pct' and 'figure'
    when return_plot=True.
    """
    min_days = max(slow_window * 4, 365)
    data = _fetch_prices(symbol, days=min_days, start_date=start_date, end_date=end_date)

    if len(data) < slow_window:
        return 0.0

    macd = vbt.MACD.run(data, fast_window=fast_window, slow_window=slow_window,
                        signal_window=signal_window)

    entries = macd.macd_crossed_above(macd.signal)
    exits = macd.macd_crossed_below(macd.signal)

    pf = vbt.Portfolio.from_signals(data, entries, exits, init_cash=10000)
    ret = round(float(pf.total_return()) * 100, 2)

    if return_plot:
        fig = _fig_from(pf.plot())
        fig.update_layout(
            template='plotly_dark',
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            font_color='#a8d8ea',
            height=400,
            margin=dict(l=40, r=20, t=20, b=40),
            legend=dict(orientation='h', y=1.02),
        )
        return {"return_pct": ret, "figure": fig}
    return ret


def run_custom(symbol: str,
               entry_condition: str,
               exit_condition: str,
               start_date: Optional[datetime] = None,
               end_date: Optional[datetime] = None,
               return_plot: bool = False,
               setup_code: Optional[str] = None):
    """
    Run a backtest using arbitrary pandas expressions for entry/exit signals.

    The condition strings are evaluated against a pandas Series of close prices
    named ``close``.  Example conditions:

      "close > close.rolling(20).mean()"
      "close < close.shift(1) * 0.98"
      "close.rolling(5).mean() > close.rolling(20).mean()"

    When ``setup_code`` is provided, it is executed first in the same namespace.
    This allows computing synthetic indicators or external data.  Example::

      setup_code = '''
    import numpy as np
    sentiment = pd.Series(np.random.uniform(-1, 1, len(close)), index=close.index)
    '''

    Returns total return as a percentage float, or dict with 'return_pct' and
    'figure' when return_plot=True.
    """
    data = _fetch_prices(symbol, days=365, start_date=start_date, end_date=end_date)
    if len(data) < 10:
        return 0.0

    import numpy as np
    ns: dict = {"close": data, "pd": pd, "np": np}

    # Run optional setup code to populate the namespace with synthetic data
    if setup_code:
        try:
            exec(compile(setup_code, "<setup_code>", "exec"), ns)
        except Exception as e:
            raise ValueError(f"Setup code error: {e}") from e

    try:
        entries = eval(entry_condition, {"__builtins__": {}}, ns)
        exits = eval(exit_condition, {"__builtins__": {}}, ns)
        if not isinstance(entries, pd.Series) or not isinstance(exits, pd.Series):
            raise ValueError("Conditions must produce a boolean Series")
        entries = entries.fillna(False).astype(bool)
        exits = exits.fillna(False).astype(bool)
    except Exception as e:
        raise ValueError(f"Condition parse error: {e}") from e

    pf = vbt.Portfolio.from_signals(data, entries, exits, init_cash=10000)
    ret = round(float(pf.total_return()) * 100, 2)

    if return_plot:
        fig = _fig_from(pf.plot())
        fig.update_layout(
            template='plotly_dark',
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            font_color='#a8d8ea',
            height=400,
            margin=dict(l=40, r=20, t=20, b=40),
            legend=dict(orientation='h', y=1.02),
        )
        return {"return_pct": ret, "figure": fig}
    return ret
