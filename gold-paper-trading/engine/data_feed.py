"""yfinance data fetching — no Backtrader dependency."""

from __future__ import annotations

import pandas as pd
import yfinance as yf

from .config import TICKER, TIMEFRAMES


def _normalize_yf_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalize a yfinance DataFrame to lowercase columns [open, high, low, close, volume].
    Handles both MultiIndex columns and single-level column names,
    and auto_adjust=True (which omits Adjusted Close).
    """
    if df.empty:
        return df

    df = df.copy()
    df.index = pd.to_datetime(df.index)

    # Normalize column names to Title case
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df.columns = [str(c).Title() if hasattr(str(c), 'Title') else str(c).capitalize()
                  for c in df.columns]

    # Map Title case to lowercase
    rename = {
        "Open": "open", "High": "high", "Low": "low",
        "Close": "close", "Volume": "volume",
    }
    df = df.rename(columns=rename)

    # Keep only OHLCV columns that exist
    cols = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
    df = df[cols]

    # Drop rows missing close
    df = df.dropna(subset=["close"])

    return df


def fetch_yfinance(tf_key: str) -> pd.DataFrame:
    """
    Fetch full OHLCV history from yfinance for the given timeframe key.
    Used for initial historical seeding of the buffer.
    """
    cfg = TIMEFRAMES[tf_key]
    interval = cfg["interval"]
    days = cfg["lookback_days"]

    start = pd.Timestamp.utcnow() - pd.Timedelta(days=days + 1)
    start_str = start.strftime("%Y-%m-%d")

    df = yf.download(
        TICKER,
        start=start_str,
        end=None,
        interval=interval,
        auto_adjust=True,
        progress=False,
    )
    return _normalize_yf_df(df)


def fetch_latest(tf_key: str) -> pd.DataFrame:
    """
    Fetch the most recent window of data from yfinance for incremental updates.
    Caller diffs against its last known timestamp to avoid duplicates.
    """
    cfg = TIMEFRAMES[tf_key]
    interval = cfg["interval"]
    days = cfg["lookback_days"]

    start = pd.Timestamp.utcnow() - pd.Timedelta(days=days + 1)
    df = yf.download(
        TICKER,
        start=start.strftime("%Y-%m-%d"),
        end=None,
        interval=interval,
        auto_adjust=True,
        progress=False,
    )
    return _normalize_yf_df(df)


def iter_new_candles(
    df_new: pd.DataFrame,
    last_ts: pd.Timestamp | None,
) -> list[tuple[str, float, float, float, float, float]]:
    """
    Yield only rows from df_new that are strictly after last_ts.
    Returns list of (timestamp_str, open, high, low, close, volume).
    """
    if df_new.empty:
        return []

    if last_ts is None:
        rows = df_new
    else:
        rows = df_new[df_new.index > last_ts]

    result = []
    for ts, row in rows.iterrows():
        result.append((
            ts.to_pydatetime().strftime("%Y-%m-%d %H:%M:%S"),
            float(row.open),
            float(row.high),
            float(row.low),
            float(row.close),
            float(row.volume),
        ))
    return result
