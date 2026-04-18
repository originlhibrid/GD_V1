"""
Bar-by-bar live trading using your exact _execute entry/exit logic.


Maintains a rolling buffer of up to MAX_BUFFER bars.
On each new candle: recomputes indicators, runs entry/exit bar-by-bar.
"""

from __future__ import annotations

import numpy as np
from typing import Optional

from strategy_helpers import roc_np, ema_np, atr_np


class LiveStrategy:
    """
    Bar-by-bar momentum-adaptive strategy for a single timeframe.
    Uses full Kelly position sizing (all-in, all-out) matching _execute.
    """

    MAX_BUFFER = 200

    def __init__(
        self,
        broker,
        db_path: str,
        tf_key: str,
        # Strategy params (must match strategy.py defaults)
        roc_fast_period: int = 14,
        roc_slow_period: int = 16,
        trend_period: int = 20,
        atr_period: int = 12,
        base_trailing_atr_mult: float = 2.5,
        trail_tighten_mult: float = 1.25,
        mom_strong_threshold: float = 2.5,
        mom_decay_period: int = 5,
        wait_buy: int = 9,
        wait_sell: int = 27,
    ):
        self.broker = broker
        self.db_path = db_path
        self.tf_key = tf_key

        # Params
        self.roc_fast_period = roc_fast_period
        self.roc_slow_period = roc_slow_period
        self.trend_period = trend_period
        self.atr_period = atr_period
        self.base_trailing_atr_mult = base_trailing_atr_mult
        self.trail_tighten_mult = trail_tighten_mult
        self.mom_strong_threshold = mom_strong_threshold
        self.mom_decay_period = mom_decay_period
        self.wait_buy = wait_buy
        self.wait_sell = wait_sell

        # Rolling lists
        self._times: list[str]  = []
        self._close:  list[float] = []
        self._high:   list[float] = []
        self._low:    list[float] = []
        self._volume: list[float] = []

        # Indicators
        self.roc_fast:  np.ndarray = np.array([])
        self.roc_slow:  np.ndarray = np.array([])
        self.trend:     np.ndarray = np.array([])
        self.atr:       np.ndarray = np.array([])
        self.mom_decay: np.ndarray = np.array([])

        # Trailing stop state (mirrors _execute)
        self._peak = 0.0
        self._trail_level = 0.0
        self._exit_reason_trailing = False

        self._min_bars: int = max(
            self.roc_fast_period, self.roc_slow_period,
            self.trend_period, self.atr_period, self.mom_decay_period,
        )

    # ── Append new candle ────────────────────────────────────────────────────

    def append(self, timestamp: str, o: float, h: float, l: float,
               c: float, v: float) -> int:
        self._times.append(timestamp)
        self._close.append(c)
        self._high.append(h)
        self._low.append(l)
        self._volume.append(v)

        if len(self._times) > self.MAX_BUFFER:
            self._times  = self._times[-self.MAX_BUFFER:]
            self._close  = self._close[-self.MAX_BUFFER:]
            self._high   = self._high[-self.MAX_BUFFER:]
            self._low    = self._low[-self.MAX_BUFFER:]
            self._volume = self._volume[-self.MAX_BUFFER:]

        self._recompute()
        return len(self._times) - 1

    def _recompute(self):
        n = len(self._close)
        if n < self._min_bars:
            return

        c = np.array(self._close, dtype=np.float64)
        h = np.array(self._high,  dtype=np.float64)
        l = np.array(self._low,   dtype=np.float64)

        self.roc_fast  = roc_np(c, self.roc_fast_period)
        self.roc_slow  = roc_np(c, self.roc_slow_period)
        self.trend     = ema_np(c, self.trend_period)
        self.atr       = atr_np(h, l, c, self.atr_period)
        self.mom_decay = roc_np(self.roc_fast, self.mom_decay_period)

    # ── Core bar execution (mirrors _execute exactly) ────────────────────────

    def on_new_bar(self, timestamp: str) -> list[dict]:
        """
        Entry/exit logic identical to _execute in strategy.py.
        Full Kelly sizing: buy_all = cash/price, sell_all = close entire position.
        """
        events = []
        bar_idx = len(self._times) - 1  # 0-based bar index

        if len(self.roc_fast) == 0 or np.isnan(self.roc_fast[-1]):
            return events

        price          = self._close[-1]
        c_roc_fast     = self.roc_fast[-1]
        c_roc_slow     = self.roc_slow[-1]
        c_trend        = self.trend[-1]
        c_atr          = self.atr[-1]
        c_mom_decay    = self.mom_decay[-1]

        pv   = self.broker.get_portfolio_value(price)
        cash = self.broker.cash

        # ── Update peak ─────────────────────────────────────────────────────
        if self.broker.in_position and price > self._peak:
            self._peak = price

        # ── Compute trailing stop level ─────────────────────────────────────
        if self.broker.in_position:
            if c_atr > 0 and price > 0:
                stop_distance_pct = (self.base_trailing_atr_mult * c_atr) / price
                momentum_strength = c_roc_fast - c_roc_slow
                if momentum_strength > self.mom_strong_threshold:
                    tighten_amount = (self.trail_tighten_mult * c_atr) / price
                    stop_distance_pct = max(stop_distance_pct - tighten_amount, 0.01)
            else:
                stop_distance_pct = 0.05
            self._trail_level = self._peak * (1.0 - stop_distance_pct)
        else:
            self._trail_level = 0.0

        bars_since = self.broker.bars_since_trade(bar_idx)

        # ── EXIT ─────────────────────────────────────────────────────────────
        if self.broker.in_position:
            exit_reason = None

            # Trailing stop hit
            if price < self._trail_level:
                exit_reason = "trailing_stop"

            # Momentum decay exit
            elif c_roc_fast < c_roc_slow and c_mom_decay < 0:
                exit_reason = "momentum_decay"

            if exit_reason:
                # Full Kelly sell — close entire position
                result = self.broker.sell(price, exit_reason=exit_reason)
                if result["success"]:
                    self.broker.mark_trade_bar(bar_idx)
                    self._exit_reason_trailing = (exit_reason == "trailing_stop")
                    self._peak = 0.0
                    events.append({
                        "type": "trade",
                        "timestamp": timestamp,
                        "side": "SELL",
                        "price": price,
                        "qty": result["quantity"],
                        "pnl": result["pnl"],
                        "exit_reason": exit_reason,
                        "cash_after": result["cash_after"],
                        "pv_after": pv,
                    })
                    events.append({
                        "type": "equity",
                        "timestamp": timestamp,
                        "portfolio_value": pv,
                        "cash": cash,
                        "position_value": 0.0,
                        "num_oz": 0.0,
                        "trail_level": 0.0,
                    })

        # ── ENTRY ──────────────────────────────────────────────────────────
        else:
            entered = False

            # Standard entry after wait_buy bars
            if bars_since > self.wait_buy:
                if (c_roc_fast > 0 and c_roc_slow > 0 and price > c_trend):
                    # Full Kelly buy
                    result = self.broker.buy(price)
                    if result["success"]:
                        self.broker.mark_trade_bar(bar_idx)
                        self._peak = price
                        self._exit_reason_trailing = False
                        entered = True
                        events.append({
                            "type": "trade",
                            "timestamp": timestamp,
                            "side": "BUY",
                            "price": price,
                            "qty": result["quantity"],
                            "cash_after": result["cash_after"],
                            "pv_after": pv,
                        })

            # Quick re-entry after trailing stop exit (2-bar cooldown)
            elif (self._exit_reason_trailing
                    and bars_since > 2
                    and bars_since <= self.wait_buy):
                if (c_roc_fast > 0 and c_roc_slow > 0 and price > c_trend):
                    result = self.broker.buy(price)
                    if result["success"]:
                        self.broker.mark_trade_bar(bar_idx)
                        self._peak = price
                        self._exit_reason_trailing = False
                        entered = True
                        events.append({
                            "type": "trade",
                            "timestamp": timestamp,
                            "side": "BUY",
                            "price": price,
                            "qty": result["quantity"],
                            "cash_after": result["cash_after"],
                            "pv_after": pv,
                        })

            if entered:
                events.append({
                    "type": "equity",
                    "timestamp": timestamp,
                    "portfolio_value": pv,
                    "cash": cash,
                    "position_value": result["quantity"] * price,
                    "num_oz": result["quantity"],
                    "trail_level": self._trail_level,
                })

        # ── Always log equity ──────────────────────────────────────────────
        if not any(e["type"] == "equity" for e in events):
            events.append({
                "type": "equity",
                "timestamp": timestamp,
                "portfolio_value": pv,
                "cash": cash,
                "position_value": pv - cash,
                "num_oz": self.broker.position_size,
                "trail_level": self._trail_level,
            })

        return events

    # ── Historical warmup ────────────────────────────────────────────────────

    def warmup(self, df) -> list[dict]:
        """Run strategy over historical DataFrame row by row."""
        events = []
        for i, row in df.iterrows():
            ts = str(row.name.to_pydatetime().strftime("%Y-%m-%d %H:%M:%S"))
            self.append(
                timestamp=ts,
                o=float(row.open),
                h=float(row.high),
                l=float(row.low),
                c=float(row.close),
                v=float(row.volume),
            )
            if len(self._close) >= self._min_bars:
                events.extend(self.on_new_bar(ts))
        return events
