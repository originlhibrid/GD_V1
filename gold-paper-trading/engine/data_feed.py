"""yfinance data fetching — one feed per timeframe."""

import pandas as pd
import yfinance as yf
import backtrader as bt

from .config import TICKER, TIMEFRAMES


def fetch_yfinance(tf_key: str) -> pd.DataFrame:
    """
    Fetch OHLCV data from yfinance for the given timeframe key.
    Returns a clean DataFrame with lowercase columns.
    """
    cfg = TIMEFRAMES[tf_key]
    interval = cfg["interval"]
    days = cfg["lookback_days"]

    start = pd.Timestamp.utcnow() - pd.Timedelta(days=days + 1)
    start_str = start.strftime("%Y-%m-%d")

    df = yf.download(
        TICKER, start=start_str, end=None,
        interval=interval, auto_adjust=True, progress=False
    )
    df = df.dropna()
    df.index = pd.to_datetime(df.index)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    # Rename to lowercase expected by Backtrader
    rename = {"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}
    df = df.rename(columns=rename)
    # Ensure correct column order
    df = df[["open", "high", "low", "close", "volume"]]
    return df


class YFinanceData(bt.feeds.PandasData):
    """Backtrader PandasData feed wrapping a yfinance DataFrame."""
    params = (
        ("datetime", None),
        ("open", "open"),
        ("high", "high"),
        ("low", "low"),
        ("close", "close"),
        ("volume", "volume"),
        ("openinterest", -1),
    )


def build_feed(tf_key: str) -> YFinanceData:
    """Fetch historical data and return a Backtrader feed for the timeframe."""
    df = fetch_yfinance(tf_key)
    return YFinanceData(dataname=df)


def fetch_latest_df(tf_key: str) -> pd.DataFrame:
    """
    Fetch the latest window of data for incremental bar updates.
    The caller is responsible for diffing against what it already has.
    """
    cfg = TIMEFRAMES[tf_key]
    interval = cfg["interval"]
    days = cfg["lookback_days"]

    start = pd.Timestamp.utcnow() - pd.Timedelta(days=days + 1)
    df = yf.download(
        TICKER, start=start.strftime("%Y-%m-%d"), end=None,
        interval=interval, auto_adjust=True, progress=False
    )
    df = df.dropna()
    df.index = pd.to_datetime(df.index)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    # Rename to lowercase expected by Backtrader
    rename = {"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}
    df = df.rename(columns=rename)
    # Ensure correct column order
    df = df[["open", "high", "low", "close", "volume"]]
    return df


def append_new_bars(data_feed, df_new):
    """
    Append closed bars from df_new that are not yet in data_feed.
    Tracks already-loaded bar count via data_feed._bar_count.
    """
    existing = getattr(data_feed, "_bar_count", 0)
    if existing == 0:
        existing = len(df_new)

    new_rows = df_new.iloc[existing:]
    if new_rows.empty:
        return 0

    for _, row in new_rows.iterrows():
        bar_time = row.name.to_pydatetime()
        bar_dt = bt.date2num(bar_time)
        o, h, l, c, v = (
            float(row.open), float(row.high),
            float(row.low), float(row.close), float(row.volume)
        )
        data_feed._insert((bar_dt, o, h, l, c, v, -1))

    data_feed._bar_count = existing + len(new_rows)
    return len(new_rows)
