"""
Pure Python + Numba momentum_adaptive_v7 strategy.
No Backtrader dependency. Uses your exact _execute numba loop.
"""

import numpy as np
from numba import njit

from strategy_helpers import (
    roc_np, ema_np, atr_np,
    buy_all, sell_all, trailing_stop_hit,
)


def get_strategy() -> dict:
    return dict(
        name="momentum_adaptive_v7",
        variables=[
            "roc_fast", "roc_slow", "trend_period", "atr_period",
            "base_trailing_atr_mult", "trail_tighten_mult",
            "mom_strong_threshold", "mom_decay_period",
            "wait_buy", "wait_sell",
        ],
        bounds=(
            [10, 12, 15, 8, 1.5, 0.5, 1, 3, 3, 15],
            [18, 20, 25, 16, 3.5, 2.0, 4, 8, 15, 40],
        ),
        simulate=simulate,
    )


def simulate(
    close: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    volume: np.ndarray,
    x: np.ndarray,
) -> tuple:
    """
    Batch backtest entry point.
    x = [roc_fast_period, roc_slow_period, trend_period, atr_period,
         base_trailing_atr_mult, trail_tighten_mult, mom_strong_threshold,
         mom_decay_period, wait_buy, wait_sell]
    Returns (final_equity_ratio, num_trades).
    """
    roc_fast_period     = max(int(x[0]), 1)
    roc_slow_period     = max(int(x[1]), 1)
    trend_period        = max(int(x[2]), 1)
    atr_period          = max(int(x[3]), 1)
    mom_decay_period    = max(int(x[7]), 1)

    roc_fast   = roc_np(close, roc_fast_period)
    roc_slow   = roc_np(close, roc_slow_period)
    trend      = ema_np(close, trend_period)
    atr        = atr_np(high, low, close, atr_period)
    mom_decay  = roc_np(roc_fast, mom_decay_period)

    base_trailing_atr_mult = x[4]
    trail_tighten_mult     = x[5]
    mom_strong_threshold   = x[6]

    return _execute(
        close, high, low,
        1_000_000.0,
        roc_fast, roc_slow, trend,
        atr, mom_decay,
        base_trailing_atr_mult, trail_tighten_mult,
        mom_strong_threshold,
        int(x[8]), int(x[9]),
    )


@njit
def _execute(
    close, high, low,
    start_cash,
    roc_fast, roc_slow, trend,
    atr, mom_decay,
    base_trailing_atr_mult, trail_tighten_mult,
    mom_strong_threshold,
    wait_buy, wait_sell,
):
    """
    Numba-optimized inner loop. Full Kelly buy/sell.
    Returns (final_cash / start_cash, num_trades).
    """
    cash = start_cash
    num_coins = 0.0
    last_trade = 0
    num_trades = 0
    peak = 0.0
    in_position = False
    exit_reason_trailing = False

    for i in range(len(close)):
        price = close[i]
        c_roc_fast  = roc_fast[i]
        c_roc_slow  = roc_slow[i]
        c_trend     = trend[i]
        c_atr       = atr[i]
        c_mom_decay = mom_decay[i]

        if (np.isnan(c_roc_fast) or np.isnan(c_roc_slow)
                or np.isnan(c_trend) or np.isnan(c_atr) or np.isnan(c_mom_decay)):
            continue

        # ── EXIT ─────────────────────────────────────────────────────────────
        if in_position:
            if price > peak:
                peak = price

            if c_atr > 0 and price > 0:
                stop_distance_pct = (base_trailing_atr_mult * c_atr) / price
                momentum_strength = c_roc_fast - c_roc_slow
                if momentum_strength > mom_strong_threshold:
                    tighten_amount = (trail_tighten_mult * c_atr) / price
                    stop_distance_pct = max(stop_distance_pct - tighten_amount, 0.01)
            else:
                stop_distance_pct = 0.05

            if trailing_stop_hit(price, peak, stop_distance_pct):
                cash, num_coins = sell_all(cash, num_coins, price)
                in_position = False
                last_trade = i
                num_trades += 1
                exit_reason_trailing = True
                continue

            if c_roc_fast < c_roc_slow and c_mom_decay < 0:
                cash, num_coins = sell_all(cash, num_coins, price)
                in_position = False
                last_trade = i
                num_trades += 1
                exit_reason_trailing = False
                continue

        # ── ENTRY ─────────────────────────────────────────────────────────────
        if not in_position:
            # Standard entry after wait_buy bars
            if i > last_trade + wait_buy:
                if (c_roc_fast > 0 and c_roc_slow > 0
                        and price > c_trend):
                    cash, num_coins = buy_all(cash, num_coins, price)
                    in_position = True
                    peak = price
                    last_trade = i
                    num_trades += 1
                    exit_reason_trailing = False

            # Quick re-entry after trailing-stop exit
            elif (exit_reason_trailing
                    and i > last_trade + 2
                    and i <= last_trade + wait_buy):
                if (c_roc_fast > 0 and c_roc_slow > 0
                        and price > c_trend):
                    cash, num_coins = buy_all(cash, num_coins, price)
                    in_position = True
                    peak = price
                    last_trade = i
                    num_trades += 1
                    exit_reason_trailing = False

    # Force close at end
    cash, num_coins = sell_all(cash, num_coins, close[-1])
    return cash / start_cash, num_trades
