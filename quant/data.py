"""
Multi-source market data layer with local caching.

Providers: yfinance (free, default), Schwab API (authenticated), Alpaca (free tier),
           FRED (macro, via OpenBB).

Asset classes: equities, ETFs, FX, crypto — all through a single interface.

Cache: SQLite database in data/market_cache/ avoids re-downloading identical queries.
"""

import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

CACHE_DIR = Path("data/market_cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DB = CACHE_DIR / "ohlcv_cache.db"


# ── SQLite cache ──────────────────────────────────────────────────────────────

def _cache_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(CACHE_DB))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS ohlcv ("
        "  symbol TEXT NOT NULL,"
        "  provider TEXT NOT NULL,"
        "  interval TEXT NOT NULL,"
        "  date TEXT NOT NULL,"
        "  open REAL, high REAL, low REAL, close REAL, volume REAL,"
        "  PRIMARY KEY (symbol, provider, interval, date)"
        ")"
    )
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _cache_key(symbol: str, provider: str, interval: str) -> str:
    return f"{symbol}:{provider}:{interval}"


def _read_cache(symbol: str, provider: str, interval: str,
                start: datetime, end: datetime) -> Optional[pd.DataFrame]:
    conn = _cache_conn()
    df = pd.read_sql_query(
        "SELECT date, open, high, low, close, volume FROM ohlcv "
        "WHERE symbol=? AND provider=? AND interval=? AND date BETWEEN ? AND ? "
        "ORDER BY date",
        conn,
        params=(symbol, provider, interval,
                start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")),
    )
    conn.close()
    if df.empty:
        return None
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    # Return only if we have >50% of expected trading days
    expected_days = max((end - start).days * 0.6, 10)
    if len(df) < expected_days:
        return None
    return df


def _write_cache(df: pd.DataFrame, symbol: str, provider: str, interval: str) -> None:
    conn = _cache_conn()
    rows = []
    for idx, row in df.iterrows():
        rows.append((
            symbol, provider, interval,
            idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10],
            float(row.get("open", np.nan)), float(row.get("high", np.nan)),
            float(row.get("low", np.nan)), float(row["close"]),
            float(row.get("volume", 0) if not pd.isna(row.get("volume", np.nan)) else 0),
        ))
    conn.executemany(
        "INSERT OR REPLACE INTO ohlcv VALUES (?,?,?,?,?,?,?,?,?)", rows
    )
    conn.commit()
    conn.close()


# ── Providers ─────────────────────────────────────────────────────────────────

def _fetch_yfinance(symbol: str, start: datetime, end: datetime,
                    interval: str = "1d") -> pd.DataFrame:
    """Fetch OHLCV from Yahoo Finance (free, no auth needed)."""
    import yfinance as yf

    yf_interval = {"1d": "1d", "1h": "1h", "1wk": "1wk", "1mo": "1mo"}.get(interval, "1d")

    for attempt in range(3):
        try:
            df = yf.download(
                symbol, start=start.strftime("%Y-%m-%d"),
                end=end.strftime("%Y-%m-%d"),
                interval=yf_interval, progress=False, auto_adjust=True,
            )
            if df.empty:
                time.sleep(2 ** attempt)
                continue

            # Normalize columns — yfinance may return MultiIndex
            if isinstance(df.columns, pd.MultiIndex):
                cols = {}
                for c in df.columns:
                    cols[c[0].lower()] = df[c]
                df = pd.DataFrame(cols, index=df.index)
            else:
                df.columns = [c.lower() for c in df.columns]

            if "close" not in df.columns:
                time.sleep(2 ** attempt)
                continue

            return df.astype({c: "float64" for c in df.columns})
        except Exception:
            time.sleep(2 ** attempt)

    raise RuntimeError(f"yfinance: no data for {symbol} after 3 attempts")


def _fetch_schwab(symbol: str, start: datetime, end: datetime) -> pd.DataFrame:
    """Fetch OHLCV from Schwab API (requires auth)."""
    from schwab_client import get_client

    client = get_client()
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    total_years = max((end - start).days / 365.0, 0.5)
    period = min(max(1, round(total_years)), 20)

    r = client.price_history(
        symbol, periodType="year", period=period,
        startDate=start_ms, endDate=end_ms,
        frequencyType="daily", frequency=1,
    )
    if not r.ok:
        raise RuntimeError(f"Schwab API error: {r.status_code}")

    candles = r.json().get("candles", [])
    if len(candles) < 20:
        raise RuntimeError(f"Schwab: insufficient data for {symbol}")

    df = pd.DataFrame(candles)
    df["date"] = pd.to_datetime(df["datetime"], unit="ms")
    df = df.rename(columns={"open": "open", "high": "high", "low": "low",
                              "close": "close", "volume": "volume"})
    return df.set_index("date")[["open", "high", "low", "close", "volume"]]


def _fetch_alpaca(symbol: str, start: datetime, end: datetime,
                  interval: str = "1d") -> pd.DataFrame:
    """Fetch OHLCV from Alpaca Markets (free tier, no auth for IEX data)."""
    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
    except ImportError:
        raise ImportError("alpaca-py required: pip install alpaca-py")

    timeframe_map = {"1d": TimeFrame.Day, "1h": TimeFrame.Hour}
    tf = timeframe_map.get(interval, TimeFrame.Day)

    client = StockHistoricalDataClient()  # free tier works without key for IEX
    request = StockBarsRequest(
        symbol_or_symbols=symbol, timeframe=tf,
        start=start, end=end,
    )
    bars = client.get_stock_bars(request)
    if not bars.data:
        raise RuntimeError(f"Alpaca: no data for {symbol}")

    rows = []
    for bar in bars.data.get(symbol, []):
        rows.append({
            "date": bar.timestamp, "open": bar.open, "high": bar.high,
            "low": bar.low, "close": bar.close, "volume": bar.volume,
        })
    df = pd.DataFrame(rows)
    return df.set_index("date").astype({c: "float64" for c in ["open", "high", "low", "close", "volume"]})


# ── Public API ────────────────────────────────────────────────────────────────

def fetch_ohlcv(
    symbol: str,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    days: int = 365,
    provider: str = "yfinance",
    interval: str = "1d",
    use_cache: bool = True,
) -> pd.DataFrame:
    """
    Fetch OHLCV data for a symbol.

    Parameters
    ----------
    symbol : str
        Ticker symbol. FX pairs use yfinance format: EURUSD=X
        Crypto: BTC-USD, ETH-USD
    provider : {"yfinance", "schwab", "alpaca"}
    interval : {"1d", "1h", "1wk", "1mo"}
    use_cache : bool
        If True, check SQLite cache first and write results back.

    Returns
    -------
    pd.DataFrame
        Columns: open, high, low, close, volume. Index: datetime.
    """
    if end is None:
        end = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    if start is None:
        start = end - timedelta(days=days)
    if start.tzinfo is not None:
        start = start.replace(tzinfo=None)
    if end.tzinfo is not None:
        end = end.replace(tzinfo=None)

    # Check cache
    if use_cache:
        cached = _read_cache(symbol, provider, interval, start, end)
        if cached is not None:
            return cached

    # Fetch
    fetchers = {
        "yfinance": lambda: _fetch_yfinance(symbol, start, end, interval),
        "schwab": lambda: _fetch_schwab(symbol, start, end),
        "alpaca": lambda: _fetch_alpaca(symbol, start, end, interval),
    }
    fetcher = fetchers.get(provider)
    if fetcher is None:
        raise ValueError(f"Unknown provider: {provider}. Choose: {list(fetchers)}")

    df = fetcher()

    # Write cache
    if use_cache:
        _write_cache(df, symbol, provider, interval)

    return df


def fetch_multiple(
    symbols: list[str],
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    days: int = 365,
    provider: str = "yfinance",
    interval: str = "1d",
    use_cache: bool = True,
) -> dict[str, pd.DataFrame]:
    """Fetch OHLCV for multiple symbols. Returns {symbol: DataFrame}."""
    results = {}
    for sym in symbols:
        try:
            results[sym] = fetch_ohlcv(
                sym, start=start, end=end, days=days,
                provider=provider, interval=interval, use_cache=use_cache,
            )
        except Exception as e:
            results[sym] = e
    return results


def get_available_tickers(asset_class: str = "equity") -> list[str]:
    """
    Return a curated list of tickers for each asset class.

    These are the canonical test tickers used to evaluate strategies.
    Adjust based on what's freely available via yfinance.
    """
    tickers = {
        "equity": [
            "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "JPM",
            "JNJ", "V", "PG", "XOM", "WMT", "MA", "HD", "BAC", "DIS", "NFLX",
            "ADBE", "CRM", "AMD", "INTC", "QCOM", "T", "VZ", "PFE", "MRK",
            "KO", "PEP", "CSCO", "ORCL", "IBM", "GE", "CAT", "BA", "LMT",
            "SPY", "QQQ", "IWM", "DIA", "VTI", "VEA",
        ],
        "etf": [
            "SPY", "QQQ", "IWM", "DIA", "VTI", "VEA", "VWO", "BND", "AGG",
            "GLD", "SLV", "USO", "XLF", "XLE", "XLK", "XLV", "XLI", "XLY",
            "TLT", "IEF", "LQD", "HYG", "EEM", "EFA",
        ],
        "fx": [
            "EURUSD=X", "GBPUSD=X", "USDJPY=X", "AUDUSD=X", "USDCAD=X",
            "USDCHF=X", "NZDUSD=X", "EURGBP=X", "EURJPY=X", "GBPJPY=X",
        ],
        "crypto": [
            "BTC-USD", "ETH-USD", "SOL-USD", "ADA-USD", "DOGE-USD",
            "DOT-USD", "AVAX-USD", "MATIC-USD", "LINK-USD", "UNI-USD",
        ],
    }
    return tickers.get(asset_class, tickers["equity"])


# ── Convenience ───────────────────────────────────────────────────────────────

def fetch_close(
    symbol: str, days: int = 365,
    start: Optional[datetime] = None, end: Optional[datetime] = None,
    provider: str = "yfinance",
) -> pd.Series:
    """Fetch just the close price series. Matches the old _fetch_prices signature."""
    df = fetch_ohlcv(symbol, start=start, end=end, days=days, provider=provider)
    return df["close"].astype("float64").dropna()


def compute_returns(prices: pd.Series) -> pd.Series:
    """Compute daily log returns from a price series."""
    return np.log(prices / prices.shift(1)).dropna()
