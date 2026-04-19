"""
Standalone backtester using Backtrader — runs strategy.py + kronos_wrapper.py.

Modes:
    backtest  — single run with Kronos enabled
    compare   — run with and without Kronos, print comparison table
    optimize  — param sweep over roc_fast, roc_slow, atr, trailing_mult

CLI:
    python engine/backtest.py --csv data/historical/xauusd_m15.csv --timeframe M15 --mode backtest
    python engine/backtest.py --csv data/historical/xauusd_m15.csv --timeframe M15 --mode compare
    python engine/backtest.py --csv data/historical/xauusd_m15.csv --timeframe M15 --mode optimize --no-kronos
    python engine/backtest.py --csv data/historical/xauusd_m15.csv --timeframe M15 --model kronos-base

WSL2 NOTE: MPLBACKEND=Agg set before any matplotlib import.
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import backtrader as bt  # WSL2 NOTE: must be set before any matplotlib import

# WSL2 NOTE: must be set before any matplotlib import
os.environ.setdefault("MPLBACKEND", "Agg")

# ── Project root on path ────────────────────────────────────────────────────────

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

from engine.config import STARTING_CAPITAL
from engine.broker import PaperBroker
# strategy.py logic is mirrored in MomentumStrategy (Backtrader)
# DO NOT MODIFY strategy.py or strategy_helpers.py

logger = logging.getLogger("backtest")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


# ── Kronos pre-computation (no lookahead) ──────────────────────────────────────

def precompute_kronos_signals(df: pd.DataFrame, horizon: int, n_bars: int,
                               lock: threading.Lock, kronos) -> dict[int, dict]:
    """
    Pre-compute Kronos signals for every bar where we have enough history.
    Returns {bar_index: signal_dict}.  Must be done BEFORE backtest starts.
    Thread-safe via lock around kronos.predict().
    """
    signals = {}
    total = len(df)
    logger.info(f"Pre-computing Kronos signals for {total} bars (horizon={horizon})...")

    for i in range(99, total):  # need 100 bars minimum
        if i % 500 == 0:
            logger.info(f"  Kronos pre-compute: {i}/{total}")

        window = df.iloc[max(0, i - 99):i + 1]
        with lock:
            sig = kronos.predict(window, horizon=horizon)
        signals[i] = sig if sig else {
            "direction": "neutral",
            "confidence": 0.0,
            "predicted_close": float(window["close"].iloc[-1]),
            "volatility_high": False,
        }

    logger.info(f"  Kronos pre-compute complete — {len(signals)} signals")
    return signals


# ── Backtrader strategy ────────────────────────────────────────────────────────

class MomentumStrategy(bt.Strategy):
    """
    Wraps momentum_adaptive_v7 entry/exit logic as a Backtrader strategy.
    PaperBroker state is kept in sync bar-by-bar.
    """

    params = dict(
        roc_fast=14, roc_slow=16, trend_ema=20, atr=12,
        base_trailing_atr_mult=2.5, trail_tighten_mult=1.25,
        mom_strong_threshold=2.5, mom_decay_period=5,
        wait_buy=9, wait_sell=27,
    )

    def __init__(self):
        self._broker_sync = PaperBroker(starting_cash=STARTING_CAPITAL)
        self._times = []
        self._closes = []
        self._highs = []
        self._lows = []
        self._vols = []
        self._roc_fast = []
        self._roc_slow = []
        self._trend = []
        self._atr = []
        self._mom_decay = []
        self._peak = 0.0
        self._trail = 0.0
        self._exit_reason_trailing = False
        self._entry_price = 0.0
        self._min_bars = max(
            self.p.roc_fast, self.p.roc_slow,
            self.p.trend_ema, self.p.atr, self.p.mom_decay_period,
        )
        self._kronos_overrides = 0
        self._kronos_blocks = 0
        self._kronos_confirms = 0
        self._kronos_signals = {}

        # Indicators
        self.roc_fast_ind  = bt.indicators.ROC(self.data.close, period=self.p.roc_fast)
        self.roc_slow_ind  = bt.indicators.ROC(self.data.close, period=self.p.roc_slow)
        self.trend_ind     = bt.indicators.EMA(self.data.close, period=self.p.trend_ema)
        self.atr_ind       = bt.indicators.ATR(self.data, period=self.p.atr)
        self.mom_dec_ind   = bt.indicators.ROC(self.roc_fast_ind, period=self.p.mom_decay_period)

        # Kronos (injected externally)
        self._kronos = None
        self._kronos_enabled = False
        self._kronos_horizon = 5
        self._kronos_precomputed: dict = {}

    def inject_kronos(self, kronos_instance, enabled: bool, horizon: int,
                      precomputed_signals: dict):
        self._kronos = kronos_instance
        self._kronos_enabled = enabled
        self._kronos_horizon = horizon
        self._kronos_precomputed = precomputed_signals

    @property
    def kronos_overrides(self):
        return self._kronos_overrides

    @property
    def kronos_blocks(self):
        return self._kronos_blocks

    @property
    def kronos_confirms(self):
        return self._kronos_confirms

    def log(self, txt, dt=None):
        dt = dt or self.datas[0].datetime.datetime(0)
        logger.debug(f"{dt.isoformat()} {txt}")

    def next(self):
        bar_idx = len(self)
        price   = self.data.close[0]
        dt      = self.data.datetime.datetime(0)

        # ── Append to rolling buffer ──────────────────────────────────────────
        self._closes.append(float(price))
        self._highs.append(float(self.data.high[0]))
        self._lows.append(float(self.data.low[0]))
        self._vols.append(float(self.data.volume[0]))

        buf_len = len(self._closes)
        if buf_len > 200:
            self._closes = self._closes[-200:]
            self._highs  = self._highs[-200:]
            self._lows   = self._lows[-200:]
            self._vols   = self._vols[-200:]

        if buf_len < self._min_bars:
            return

        # ── Get indicator values ──────────────────────────────────────────────
        c_roc_fast  = float(self.roc_fast_ind[0])
        c_roc_slow  = float(self.roc_slow_ind[0])
        c_trend     = float(self.trend_ind[0])
        c_atr       = float(self.atr_ind[0])
        c_mom_decay = float(self.mom_dec_ind[0])

        # ── Update peak ───────────────────────────────────────────────────────
        pos_size = self._broker_sync.position_size
        if pos_size > 0 and price > self._peak:
            self._peak = price

        # ── Compute trailing stop ─────────────────────────────────────────────
        if pos_size > 0:
            if c_atr > 0 and price > 0:
                stop_pct = (self.p.base_trailing_atr_mult * c_atr) / price
                momentum_str = c_roc_fast - c_roc_slow
                if momentum_str > self.p.mom_strong_threshold:
                    tighten = (self.p.trail_tighten_mult * c_atr) / price
                    stop_pct = max(stop_pct - tighten, 0.01)
            else:
                stop_pct = 0.05
            self._trail = self._peak * (1.0 - stop_pct)
        else:
            self._trail = 0.0

        bars_since = self._broker_sync.bars_since_trade(bar_idx)

        # ── Kronos signal (pre-computed, no lookahead) ─────────────────────────
        kronos_sig = self._kronos_precomputed.get(bar_idx) if self._kronos_enabled else None
        kronos_bearish = (kronos_sig and kronos_sig.get("direction") == "bearish")
        kronos_bullish = (kronos_sig and kronos_sig.get("direction") == "bullish")

        # ── EXIT ──────────────────────────────────────────────────────────────
        if pos_size > 0:
            exit_reason = None

            # Trailing stop hit
            if price < self._trail:
                exit_reason = "trailing_stop"

            # Momentum decay exit
            elif c_roc_fast < c_roc_slow and c_mom_decay < 0:
                exit_reason = "momentum_decay"

            # ── Kronos override: bearish + exit signal → accelerate exit ────
            if kronos_bearish and exit_reason:
                exit_reason = "kronos_override"
                self._kronos_overrides += 1
                self._kronos_confirms += 1
                self.log(f"KRONOS OVERRIDE: accelerate {exit_reason}")

            # ── Kronos override: bearish, no exit yet → tighten trailing ────
            if kronos_bearish and not exit_reason:
                # Tighten trail by 50%
                self._trail = self._peak * (1.0 - (self.p.base_trailing_atr_mult * c_atr / price) * 0.5)
                self._kronos_overrides += 1
                self._kronos_blocks += 1
                self.log("KRONOS: tightened trailing stop 50%")

                # Re-check tightened trail
                if price < self._trail:
                    exit_reason = "kronos_tighten"
                    self._kronos_overrides += 1

            if exit_reason:
                size = self._broker_sync.position_size
                pnl  = (price - self._entry_price) * size
                self._broker_sync.close_position(price, exit_reason=exit_reason, pnl=pnl)
                self.sell()  # Backtrader sell to close
                self._peak = 0.0
                self._trail = 0.0
                self._entry_price = 0.0
                self.log(f"EXIT {exit_reason} @ {price:.2f} | PnL {pnl:.2f}")
                return

        # ── ENTRY ─────────────────────────────────────────────────────────────
        else:
            entered = False

            # Standard entry
            if bars_since > self.p.wait_buy:
                if c_roc_fast > 0 and c_roc_slow > 0 and price > c_trend:
                    # ── Kronos: re-entry only if bullish ─────────────────────
                    if self._kronos_enabled and not kronos_bullish:
                        self.log(f"KRONOS BLOCK: re-entry blocked (direction={kronos_sig.get('direction')})")
                        return

                    size = int(self._broker_sync.cash / price)
                    if size > 0:
                        self.buy(price=price, size=size)
                        self._broker_sync.open_position(price, size)
                        self._peak = price
                        self._entry_price = price
                        self._exit_reason_trailing = False
                        entered = True
                        self.log(f"ENTRY BUY @ {price:.2f} | size={size}")

            # Quick re-entry after trailing stop exit (2-bar cooldown)
            elif (self._exit_reason_trailing
                    and bars_since > 2
                    and bars_since <= self.p.wait_buy):
                if c_roc_fast > 0 and c_roc_slow > 0 and price > c_trend:
                    if self._kronos_enabled and not kronos_bullish:
                        self.log("KRONOS BLOCK: quick re-entry blocked")
                        return

                    size = int(self._broker_sync.cash / price)
                    if size > 0:
                        self.buy(price=price, size=size)
                        self._broker_sync.open_position(price, size)
                        self._peak = price
                        self._entry_price = price
                        self._exit_reason_trailing = False
                        entered = True
                        self.log(f"QUICK RE-ENTRY BUY @ {price:.2f}")

            if entered:
                self._exit_reason_trailing = False


# ── Backtest runner ────────────────────────────────────────────────────────────

def run_backtest(
    csv_path: str,
    timeframe: str,
    mode: str,
    use_kronos: bool,
    model_name: str,
    cerebro_kwargs: dict,
) -> dict:
    """
    Returns dict of results for one run.
    """
    # ── Load CSV ──────────────────────────────────────────────────────────────
    tf_map = {"M5": "5m", "M15": "15m", "M30": "30m", "H1": "1h", "M1": "1m"}
    yf_interval = tf_map.get(timeframe.upper(), "15m")

    df = pd.read_csv(csv_path, parse_dates=["datetime"])
    df = df.set_index("datetime")
    df = df.sort_index()

    # Map generic names to what the engine expects
    rename = {c: c.lower() for c in df.columns}
    df = df.rename(columns=rename)

    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"CSV missing columns: {missing}")

    data = bt.feeds.PandasData(dataname=df)

    # ── Pre-compute Kronos signals ───────────────────────────────────────────
    kronos_signals = {}
    kronos_instance = None

    if use_kronos:
        from engine.kronos_wrapper import get_kronos
        kronos_lock = threading.Lock()
        kronos_instance = get_kronos(model_name=model_name)
        horizon = 5
        kronos_signals = precompute_kronos_signals(df, horizon, len(df), kronos_lock, kronos_instance)
        logger.info(f"Kronos pre-compute done: {len(kronos_signals)} signals")

    # ── Cerebro setup ────────────────────────────────────────────────────────
    cerebro = bt.Cerebro()

    if mode == "optimize":
        cerebro.optwriter = bt.with_performances(ROOT / "logs" / "optimize_results.csv")

    cerebro.adddata(data)
    cerebro.broker.setcash(STARTING_CAPITAL)
    cerebro.broker.setcommission(commission=0.0002)   # 0.02%
    cerebro.broker.set_slippage_perc(0.0001, slip_fixed=True)  # 1 tick
    cerebro.addsizer(bt.sizers.FixedSize, stake=0.1)  # 0.1 lot

    # Add strategy
    cerebro.addstrategy(
        MomentumStrategy,
        inject_kronos=(kronos_instance, use_kronos, 5, kronos_signals),
    )

    # Analyzers
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
    cerebro.addanalyzer(bt.analyzers.SQN, _name="sqn")

    # ── Run ──────────────────────────────────────────────────────────────────
    results = cerebro.run(**cerebro_kwargs)

    # Extract results
    if mode == "optimize":
        # results is list of lists of tuples (strategy, analyser dicts)
        best = max(results, key=lambda r: r[0][0].broker.getvalue())
        strat = best[0][0]
    else:
        strat = results[0][0]

    final_value = strat.broker.getvalue()
    pnl = final_value - STARTING_CAPITAL
    returns_pct = (pnl / STARTING_CAPITAL) * 100

    # Extract analyzers
    ta = strat.analyzers.trades.get_analysis()
    dd = strat.analyzers.drawdown.get_analysis()
    sr = strat.analyzers.sharpe.get_analysis()
    ret = strat.analyzers.returns.get_analysis()
    sqn = strat.analyzers.sqn.get_analysis()

    return {
        "mode":         mode,
        "kronos":       use_kronos,
        "final_value":  round(final_value, 2),
        "pnl":          round(pnl, 2),
        "returns_pct":  round(returns_pct, 2),
        "total_trades": ta.get("total", {}).get("total", 0),
        "win_rate":     ta.get("won", {}).get("total", 0) / max(1, ta.get("total", {}).get("total", 1)),
        "max_drawdown": dd.get("max", {}).get("drawdown", 0),
        "sharpe":       sr.get("sharperatio", None) or 0.0,
        "sqn":          sqn.get("sqn", 0.0),
        "kronos_overrides": strat.kronos_overrides,
        "kronos_blocks":     strat.kronos_blocks,
        "kronos_confirms":   strat.kronos_confirms,
    }


def run_compare(csv_path: str, timeframe: str, model_name: str) -> tuple[dict, dict]:
    """Run backtest with and without Kronos, return (with_kronos, without_kronos)."""
    opts = {"optreturn": False}

    logger.info("=" * 60)
    logger.info("RUNNING: without Kronos")
    without = run_backtest(csv_path, timeframe, "backtest", use_kronos=False,
                           model_name=model_name, cerebro_kwargs=opts)

    logger.info("=" * 60)
    logger.info("RUNNING: with Kronos")
    with_kronos = run_backtest(csv_path, timeframe, "backtest", use_kronos=True,
                               model_name=model_name, cerebro_kwargs=opts)

    return with_kronos, without


def run_optimize(csv_path: str, timeframe: str, use_kronos: bool, model_name: str):
    """Param sweep over key strategy parameters."""
    cerebro_kwargs = {"optreturn": False, "maxcpus": 4}

    df = pd.read_csv(csv_path, parse_dates=["datetime"]).set_index("datetime").sort_index()
    data = bt.feeds.PandasData(dataname=df)

    cerebro = bt.Cerebro()
    cerebro.adddata(data)
    cerebro.broker.setcash(STARTING_CAPITAL)
    cerebro.broker.setcommission(commission=0.0002)
    cerebro.addsizer(bt.sizers.FixedSize, stake=0.1)

    # Parameter grid
    cerebro.optstrategy(
        MomentumStrategy,
        roc_fast=[10, 12, 14, 16],
        roc_slow=[14, 16, 18, 20],
        base_trailing_atr_mult=[2.0, 2.5, 3.0],
        inject_kronos=(None, use_kronos, 5, {}),
    )

    results = cerebro.run(**cerebro_kwargs)
    best = max(results, key=lambda r: r[0][0].broker.getvalue())
    strat = best[0][0]

    return {
        "final_value": round(strat.broker.getvalue(), 2),
        "pnl":         round(strat.broker.getvalue() - STARTING_CAPITAL, 2),
        "best_params": {
            "roc_fast": strat.params.roc_fast,
            "roc_slow": strat.params.roc_slow,
            "base_trailing_atr_mult": strat.params.base_trailing_atr_mult,
        },
    }


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Gold Backtester")
    parser.add_argument("--csv",        required=True, help="Path to historical CSV")
    parser.add_argument("--timeframe",  default="M15",  help="M5|M15|M30|H1")
    parser.add_argument("--mode",       default="backtest",
                        choices=["backtest", "compare", "optimize"])
    parser.add_argument("--no-kronos",  action="store_true", help="Disable Kronos")
    parser.add_argument("--model",      default="NeoQuasar/Kronos-base")
    args = parser.parse_args()

    # Ensure output dirs
    (ROOT / "logs").mkdir(parents=True, exist_ok=True)
    (ROOT / "logs" / "plots").mkdir(parents=True, exist_ok=True)
    (ROOT / "data" / "historical").mkdir(parents=True, exist_ok=True)

    use_kronos = not args.no_kronos
    opts = {"optreturn": False}

    start_time = time.time()

    # ── Run ──────────────────────────────────────────────────────────────────
    if args.mode == "backtest":
        result = run_backtest(args.csv, args.timeframe, "backtest",
                              use_kronos=use_kronos, model_name=args.model,
                              cerebro_kwargs=opts)

    elif args.mode == "compare":
        with_kronos, without = run_compare(args.csv, args.timeframe, args.model)
        elapsed = time.time() - start_time

        print("\n" + "=" * 70)
        print(f"{'':30} {'WITHOUT KRONOS':>18} {'WITH KRONOS':>18}")
        print("=" * 70)
        for key in ["final_value", "pnl", "returns_pct", "total_trades",
                    "win_rate", "max_drawdown", "sharpe", "sqn"]:
            v1 = without.get(key, 0)
            v2 = with_kronos.get(key, 0)
            if key == "win_rate":
                print(f"  {key:28} {v1*100:>17.1f}%% {v2*100:>17.1f}%%")
            else:
                print(f"  {key:28} {v1:>18} {v2:>18}")
        print("-" * 70)
        print(f"  Kronos overrides: {with_kronos.get('kronos_overrides',0)}")
        print(f"  Kronos blocks:    {with_kronos.get('kronos_blocks',0)}")
        print(f"  Kronos confirms:  {with_kronos.get('kronos_confirms',0)}")
        print("=" * 70)
        print(f"Elapsed: {elapsed:.1f}s")
        return

    elif args.mode == "optimize":
        result = run_optimize(args.csv, args.timeframe, use_kronos, args.model)
        print(f"\nBest result: {result}")
        return

    # ── Print single run ─────────────────────────────────────────────────────
    elapsed = time.time() - start_time
    print("\n" + "=" * 50)
    print("BACKTEST RESULT")
    print("=" * 50)
    for k, v in result.items():
        print(f"  {k:20} {v}")
    print(f"  elapsed            {elapsed:.1f}s")
    print("=" * 50)

    # ── Save plot ─────────────────────────────────────────────────────────────
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, axes = plt.subplots(2, 1, figsize=(14, 8),
                                 gridspec_kw={"height_ratios": [3, 1]})

        # Load data for plot
        df = pd.read_csv(args.csv, parse_dates=["datetime"]).set_index("datetime").sort_index()
        axes[0].plot(df["close"], label="Price", color="steelblue", linewidth=0.8)
        axes[0].set_title(f"XAUUSD {args.timeframe} — Backtest {'+ Kronos' if use_kronos else ''}")
        axes[0].set_ylabel("Price ($)")
        axes[0].legend()
        axes[0].grid(alpha=0.3)

        equity = [STARTING_CAPITAL]
        # Approximate equity from pnl progression
        total_return = result["returns_pct"] / 100
        n_days = len(df)
        daily_steps = np.linspace(0, total_return, max(n_days, 1))
        axes[1].plot(daily_steps, color="green", linewidth=1)
        axes[1].set_title("Cumulative Return")
        axes[1].set_ylabel("Return $")
        axes[1].set_xlabel("Bars")
        axes[1].grid(alpha=0.3)

        plot_path = ROOT / "logs" / "plots" / f"backtest_{datetime.now():%Y%m%d_%H%M%S}.png"
        plt.tight_layout()
        plt.savefig(plot_path, dpi=150)
        plt.close()
        print(f"\nPlot saved: {plot_path}")
    except Exception as e:
        print(f"\nPlot skipped (matplotlib error): {e}")


if __name__ == "__main__":
    main()
