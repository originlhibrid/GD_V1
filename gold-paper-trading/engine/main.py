"""
Gold Paper Trading Engine — 3 independent pure-Python instances.

Each timeframe (5M / 15M / 1H) runs in its own PROCESS with:
  - its own PaperBroker ($10,000 starting capital)
  - its own SQLite DB (trading_5m.db / trading_15m.db / trading_1h.db)
  - its own LiveStrategy (bar-by-bar execution)
  - its own APScheduler polling yfinance at the correct cadence

Usage:
  python engine/main.py              # all 3 instances
  python engine/main.py --timeframe 5m   # single instance (debugging)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
import multiprocessing as mp
from datetime import datetime

# ── Project root on path ───────────────────────────────────────────────────────
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engine.config import (
    STARTING_CAPITAL, COMMISSION, TIMEFRAMES,
    ROC_FAST_PERIOD, ROC_SLOW_PERIOD, TREND_PERIOD, ATR_PERIOD,
    BASE_TRAILING_ATR_MULT, TRAIL_TIGHTEN_MULT, MOM_STRONG_THRESHOLD,
    MOM_DECAY_PERIOD, WAIT_BUY,
)
from engine.db import init_db, save_params, write_candle, write_trade, write_equity_snapshot, write_indicators
from engine.data_feed import fetch_yfinance, fetch_latest, iter_new_candles
from engine.broker import PaperBroker
from engine.live_strategy import LiveStrategy


# ── Logging ────────────────────────────────────────────────────────────────────

def _setup_logger(tf: str) -> logging.Logger:
    log = logging.getLogger(f"engine.{tf}")
    log.setLevel(logging.INFO)
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(logging.Formatter(
        f"%(asctime)s [%(levelname)s] [{tf}] %(message)s"
    ))
    log.addHandler(h)
    return log


# ── Per-instance subprocess ────────────────────────────────────────────────────

def run_instance(tf: str):
    """
    Full lifecycle for one timeframe instance.
    Runs in a SEPARATE process — own memory, own broker, own DB.
    """
    import pandas as pd  # local import
    from apscheduler.schedulers.background import BackgroundScheduler

    log = _setup_logger(tf)
    cfg = TIMEFRAMES[tf]
    db_path = os.path.join(ROOT, cfg["db_filename"])

    log.info(f"Starting — DB: {db_path}, interval: {cfg['interval']}")

    # ── Init DB ──────────────────────────────────────────────────────────────
    init_db(db_path)
    save_params(db_path, {
        "name":                   "momentum_adaptive_v7",
        "tf":                     tf,
        "roc_fast_period":        ROC_FAST_PERIOD,
        "roc_slow_period":        ROC_SLOW_PERIOD,
        "trend_period":           TREND_PERIOD,
        "atr_period":             ATR_PERIOD,
        "base_trailing_atr_mult":  BASE_TRAILING_ATR_MULT,
        "trail_tighten_mult":     TRAIL_TIGHTEN_MULT,
        "mom_strong_threshold":   MOM_STRONG_THRESHOLD,
        "mom_decay_period":       MOM_DECAY_PERIOD,
        "wait_buy":               WAIT_BUY,
        "capital":                STARTING_CAPITAL,
    })

    # ── Build broker and strategy ─────────────────────────────────────────────
    broker = PaperBroker(starting_cash=STARTING_CAPITAL, commission_rate=COMMISSION)

    strategy = LiveStrategy(
        broker=broker,
        db_path=db_path,
        tf_key=tf,
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

    # ── Historical warmup ─────────────────────────────────────────────────────
    log.info(f"[{tf}] Fetching historical data...")
    df_hist = fetch_yfinance(tf)

    if df_hist.empty:
        log.error(f"[{tf}] No historical data returned — aborting")
        sys.exit(1)

    log.info(f"[{tf}] Loaded {len(df_hist)} historical bars — running warmup...")
    events = strategy.warmup(df_hist)

    # Persist warmup events to DB
    for ev in events:
        if ev["type"] == "trade":
            write_trade(
                db_path, ev["timestamp"], ev["side"],
                ev["price"], ev.get("qty", 0),
                ev["cash_after"], ev["pv_after"],
                ev.get("exit_reason"), ev.get("pnl", 0.0),
            )
        elif ev["type"] == "equity":
            write_equity_snapshot(
                db_path, ev["timestamp"],
                ev["portfolio_value"], ev["cash"],
                ev["position_value"], ev["num_oz"],
            )

    final_pv = broker.get_portfolio_value(df_hist.iloc[-1]["close"])
    log.info(f"[{tf}] Warmup complete — portfolio: ${final_pv:.2f}")

    # Track last processed timestamp to avoid duplicates
    last_ts = df_hist.index[-1].to_pydatetime()

    # ── Live polling ──────────────────────────────────────────────────────────
    scheduler = BackgroundScheduler(timezone="UTC")
    poll_secs = cfg["poll_seconds"]

    def poll_job():
        """Fetch latest data, append new bars, run strategy."""
        nonlocal last_ts
        try:
            df_new = fetch_latest(tf)
            if df_new.empty:
                log.warning(f"[{tf}] yfinance returned empty data")
                return

            candles = iter_new_candles(df_new, last_ts)
            if not candles:
                log.debug(f"[{tf}] No new candles")
                return

            log.info(f"[{tf}] New {len(candles)} candle(s)")

            for ts, o, h, l, c, v in candles:
                # Write candle to DB
                write_candle(db_path, ts, o, h, l, c, v)
                # Append to strategy buffer
                strategy.append(ts, o, h, l, c, v)
                # Run bar-by-bar logic
                events = strategy.on_new_bar(ts)
                # Persist events
                for ev in events:
                    if ev["type"] == "trade":
                        write_trade(
                            db_path, ev["timestamp"], ev["side"],
                            ev["price"], ev.get("qty", 0),
                            ev["cash_after"], ev["pv_after"],
                            ev.get("exit_reason"), ev.get("pnl", 0.0),
                        )
                    elif ev["type"] == "equity":
                        write_equity_snapshot(
                            db_path, ev["timestamp"],
                            ev["portfolio_value"], ev["cash"],
                            ev["position_value"], ev["num_oz"],
                        )
                # Persist indicators
                _write_indicators_from_strategy(db_path, ts, strategy, broker, c)

            last_ts = df_new.index[-1].to_pydatetime()

        except Exception:
            log.exception(f"[{tf}] poll error:")

    def _write_indicators_from_strategy(db_path, ts, strat, broker, close_price):
        """Read current indicator values from strategy and write to DB."""
        try:
            roc_f  = float(strat.roc_fast[-1])
            roc_s  = float(strat.roc_slow[-1])
            trend_v = float(strat.trend[-1])
            atr_v  = float(strat.atr[-1])
            mom_d  = float(strat.mom_decay[-1])
            trail_lvl = strat._trail_level
            peak   = float(broker.peak_price)
            mom_str = float(roc_f - roc_s)
            write_indicators(
                db_path, ts,
                roc_f, roc_s, trend_v, atr_v, mom_d,
                trail_lvl, peak, mom_str,
                broker.in_position,
            )
        except (IndexError, ValueError):
            pass

    scheduler.add_job(
        poll_job, "interval", seconds=poll_secs,
        id=f"poll_{tf}", misfire_grace_time=poll_secs // 2,
    )
    scheduler.start()
    log.info(f"[{tf}] Scheduler started — polling every {poll_secs}s")

    # ── Keep alive ───────────────────────────────────────────────────────────
    try:
        while True:
            time.sleep(poll_secs)
    except KeyboardInterrupt:
        log.info(f"[{tf}] Shutting down...")
        scheduler.shutdown()
        sys.exit(0)


# ── Launcher ───────────────────────────────────────────────────────────────────

def launch_all():
    log = logging.getLogger("engine")
    log.setLevel(logging.INFO)
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    log.addHandler(h)

    log.info("=" * 60)
    log.info("Gold Paper Trading Engine — 3 independent instances")
    log.info("Timeframes: 5M | 15M | 1H  |  Capital per instance: $10,000")
    log.info("=" * 60)

    processes = {}
    for tf in ["5m", "15m", "1h"]:
        p = mp.Process(name=f"engine-{tf}", target=run_instance, args=(tf,))
        p.start()
        processes[tf] = p
        log.info(f"Started process {p.name} (pid={p.pid})")

    log.info("All instances running. Press Ctrl+C to stop all.")

    try:
        while True:
            time.sleep(30)
            for tf, p in list(processes.items()):
                if not p.is_alive():
                    log.error(f"Process {tf} died! Restarting in 5s...")
                    time.sleep(5)
                    p2 = mp.Process(name=f"engine-{tf}", target=run_instance, args=(tf,))
                    p2.start()
                    processes[tf] = p2
                    log.info(f"Restarted {tf} (pid={p2.pid})")
    except KeyboardInterrupt:
        log.info("Stopping all instances...")
        for tf, p in processes.items():
            p.terminate()
            p.join(timeout=5)
        log.info("All stopped.")


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gold Paper Trading Engine")
    parser.add_argument(
        "--timeframe", "-t",
        choices=["5m", "15m", "1h"],
        help="Run a single timeframe instance (for debugging)",
    )
    args = parser.parse_args()

    if args.timeframe:
        run_instance(args.timeframe)
    else:
        launch_all()
