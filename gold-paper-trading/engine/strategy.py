"""Backtrader Strategy: momentum_adaptive_v7 — runs independently per timeframe."""

import backtrader as bt

from .config import (
    ROC_FAST_PERIOD, ROC_SLOW_PERIOD, TREND_PERIOD, ATR_PERIOD,
    BASE_TRAILING_ATR_MULT, TRAIL_TIGHTEN_MULT, MOM_STRONG_THRESHOLD,
    MOM_DECAY_PERIOD, WAIT_BUY,
)


class MomentumAdaptiveV7(bt.Strategy):
    """
    Multi-timeframe momentum strategy with adaptive trailing stop.
    Each timeframe runs its own instance with its own cerebro/broker.
    """

    params = dict(
        roc_fast_period=ROC_FAST_PERIOD,
        roc_slow_period=ROC_SLOW_PERIOD,
        trend_period=TREND_PERIOD,
        atr_period=ATR_PERIOD,
        base_trailing_atr_mult=BASE_TRAILING_ATR_MULT,
        trail_tighten_mult=TRAIL_TIGHTEN_MULT,
        mom_strong_threshold=MOM_STRONG_THRESHOLD,
        mom_decay_period=MOM_DECAY_PERIOD,
        wait_buy=WAIT_BUY,
    )

    def __init__(self, db_path=None):
        self.db_path = db_path or ""
        self.last_trade_bar = 0
        self.exit_reason_trailing = False
        self.peak = 0.0
        self.entry_price = 0.0

        # Indicators
        self.roc_fast  = bt.indicators.ROC(self.data.close, period=self.p.roc_fast_period)
        self.roc_slow  = bt.indicators.ROC(self.data.close, period=self.p.roc_slow_period)
        self.trend_ema = bt.indicators.EMA(self.data.close, period=self.p.trend_period)
        self.atr       = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.mom_decay = bt.indicators.ROC(self.roc_fast, period=self.p.mom_decay_period)

    @property
    def in_pos(self):
        return self.position.size > 0

    def _mom_str(self):
        return self.roc_fast[0] - self.roc_slow[0]

    def _stop_pct(self):
        price = self.data.close[0]
        if self.atr[0] > 0 and price > 0:
            sp = (self.p.base_trailing_atr_mult * self.atr[0]) / price
            if self._mom_str() > self.p.mom_strong_threshold:
                tighten = (self.p.trail_tighten_mult * self.atr[0]) / price
                sp = max(sp - tighten, 0.01)
            return sp
        return 0.05

    def _trailing_hit(self):
        if not self.in_pos or self.peak <= 0:
            return False
        stop_lvl = self.peak * (1 - self._stop_pct())
        return self.data.close[0] < stop_lvl

    def _bars_since_trade(self):
        return len(self.data) - self.last_trade_bar

    def _entry_ok(self):
        return self._bars_since_trade() > self.p.wait_buy

    def _quick_reentry_ok(self):
        if not self.exit_reason_trailing:
            return False
        bars = self._bars_since_trade()
        return 2 < bars <= self.p.wait_buy

    def _trend_ok(self):
        return (self.roc_fast[0] > 0 and
                self.roc_slow[0] > 0 and
                self.data.close[0] > self.trend_ema[0])

    def _do_buy(self):
        size = self.broker.getvalue() / self.data.close[0]
        size = max(size, 0.001)
        self.entry_price = self.data.close[0]
        self.peak = self.entry_price
        self.buy(data=self.data, size=size)

    def _do_sell(self, reason: str):
        if not self.in_pos:
            return 0.0
        price = self.data.close[0]
        size = self.position.size
        pnl = size * (price - self.entry_price)
        self.sell(data=self.data, size=size)
        self.last_trade_bar = len(self.data)
        self.exit_reason_trailing = (reason == "trailing_stop")
        return pnl

    def next(self):
        price = self.data.close[0]
        now = self.data.datetime.datetime(0).strftime("%Y-%m-%d %H:%M:%S")
        pv   = self.broker.getvalue()
        cash = self.broker.getcash()

        # ── EXIT ─────────────────────────────────────────────────────────────
        if self.in_pos:
            if price > self.peak:
                self.peak = price

            trail_lvl = self.peak * (1 - self._stop_pct())

            if self._trailing_hit():
                pnl = self._do_sell("trailing_stop")
                self._log_trade(now, "SELL", price, self.position.size,
                                cash, pv, "trailing_stop", pnl)

            elif self.roc_fast[0] < self.roc_slow[0] and self.mom_decay[0] < 0:
                pnl = self._do_sell("momentum_decay")
                self._log_trade(now, "SELL", price, self.position.size,
                                cash, pv, "momentum_decay", pnl)

        # ── ENTRY ─────────────────────────────────────────────────────────────
        else:
            if self._entry_ok() and self._trend_ok():
                self._do_buy()
                self._log_trade(now, "BUY", price, self.position.size,
                                cash, pv, None, 0.0)

            elif self._quick_reentry_ok() and self._trend_ok():
                self._do_buy()
                self._log_trade(now, "BUY", price, self.position.size,
                                cash, pv, None, 0.0)

        # ── Persistence ──────────────────────────────────────────────────────
        self._persist(now, pv, cash, trail_lvl if self.in_pos else 0.0)

    def _log_trade(self, ts, side, price, qty, cash, pv, reason, pnl):
        if not self.db_path:
            return
        from .db import write_trade
        write_trade(self.db_path, ts, side, price, qty, cash, pv, reason, pnl)

    def _persist(self, ts, pv, cash, trail_lvl):
        if not self.db_path:
            return
        from .db import write_equity_snapshot, write_indicators
        price = self.data.close[0]
        pos_val = pv - cash
        num_coins = pos_val / price if price > 0 else 0.0
        write_equity_snapshot(self.db_path, ts, pv, cash, pos_val, num_coins)
        write_indicators(
            self.db_path, ts,
            float(self.roc_fast[0]),
            float(self.roc_slow[0]),
            float(self.trend_ema[0]),
            float(self.atr[0]),
            float(self.mom_decay[0]),
            trail_lvl,
            float(self.peak),
            self._mom_str(),
            self.in_pos,
        )
