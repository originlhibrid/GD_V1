"""Pure numpy/numba indicator helpers — """

import numpy as np
from numba import njit


def roc_np(close: np.ndarray, period: int) -> np.ndarray:
    """Rate of Change."""
    close = np.asarray(close, dtype=np.float64)
    out = np.full_like(close, np.nan)
    out[period:] = (close[period:] - close[:-period]) / close[:-period] * 100
    return out


def ema_np(close: np.ndarray, period: int) -> np.ndarray:
    """Exponential Moving Average."""
    close = np.asarray(close, dtype=np.float64)
    out = np.full_like(close, np.nan)
    if len(close) < period:
        return out
    alpha = 2.0 / (period + 1)
    out[period - 1] = np.mean(close[:period])
    for i in range(period, len(close)):
        out[i] = alpha * close[i] + (1 - alpha) * out[i - 1]
    return out


def atr_np(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int) -> np.ndarray:
    """Average True Range."""
    high = np.asarray(high, dtype=np.float64)
    low  = np.asarray(low,  dtype=np.float64)
    close = np.asarray(close, dtype=np.float64)
    tr = np.full_like(high, np.nan)
    tr[1:] = np.maximum(
        high[1:] - low[1:],
        np.maximum(np.abs(high[1:] - close[:-1]), np.abs(low[1:] - close[:-1]))
    )
    alpha = 2.0 / (period + 1)
    atr = np.full_like(tr, np.nan)
    if len(tr) < period:
        return atr
    atr[period - 1] = np.mean(tr[:period])
    for i in range(period, len(tr)):
        if not np.isnan(atr[i - 1]) and not np.isnan(tr[i]):
            atr[i] = alpha * tr[i] + (1 - alpha) * atr[i - 1]
        elif not np.isnan(tr[i]):
            atr[i] = tr[i]
    return atr


# ── Numba helpers used inside _execute ─────────────────────────────────────────

@njit
def buy_all(cash: float, num_coins: float, price: float):
    """Full Kelly-style buy at given price. Returns (new_cash, new_num_coins)."""
    if cash <= 0 or price <= 0:
        return cash, num_coins
    num_coins = cash / price
    cash = 0.0
    return cash, num_coins


@njit
def sell_all(cash: float, num_coins: float, price: float):
    """Sell entire position at given price. Returns (new_cash, new_num_coins)."""
    if num_coins <= 0 or price <= 0:
        return cash, num_coins
    cash += num_coins * price
    num_coins = 0.0
    return cash, num_coins


@njit
def trailing_stop_hit(price: float, peak: float, stop_distance_pct: float) -> bool:
    """Check if price has dropped below the trailing stop level."""
    if peak <= 0 or stop_distance_pct <= 0:
        return False
    stop_level = peak * (1.0 - stop_distance_pct)
    return price < stop_level
