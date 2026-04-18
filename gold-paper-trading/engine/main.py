"""
Gold Paper Trading Engine — 3 independent Backtrader instances.

Each timeframe (5M / 15M / 1H) runs in its own process with:
  - its own Backtrader Cerebro + paper broker ($10,000)
  - its own SQLite DB (trading_5m.db / trading_15m.db / trading_1h.db)
  - its own APScheduler polling yfinance at the correct cadence

Usage:
  python engine/main.py              # start all 3 instances
  python engine/main.py --timeframe 5m   # start just one (for debugging)
"""

import argparse
import logging
import os
import sys
import time
import multiprocessing as mp
from functools import partial

# ── Ensure project root on path ─────────────────────────────────────────────────
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engine.config import (
    STARTING_CAPITAL, COMMISSION, TIMEFRAMES,
    ROC_FAST_PERIOD, ROC_SLOW_PERIOD, TREND_PERIOD, ATR_PERIOD,
    BASE_TRAILING_ATR_MULT, TRAIL_TIGHTEN_MULT, MOM_STRONG_THRESHOLD,
    MOM_DECAY_PERIOD, WAIT_BUY,
)
from engine.db import init_db, save_params, write_candle
from engine.data_feed import fetch_yfinance, fetch_latest_df, append_new_bars, YFinanceData
from engine.strategy import MomentumAdaptiveV7

# ── Logging ────────────────────────────────────────────────────────────────────

def _setup_logger(tf):
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
    import backtrader as bt
    from apscheduler.schedulers.background import BackgroundScheduler

    log = _setup_logger(tf)
    cfg = TIMEFRAMES[tf]
    db_path = os.path.join(ROOT, cfg["db_filename"])

    log.info(f"Starting instance — DB: {db_path}, interval: {cfg['interval']}")

    # ── Init DB ──────────────────────────────────────────────────────────────
    init_db(db_path)
    save_params(db_path, {
        "name":                    "momentum_adaptive_v7",
        "tf":                      tf,
        "roc_fast_period":         ROC_FAST_PERIOD,
        "roc_slow_period":         ROC_SLOW_PERIOD,
        "trend_period":            TREND_PERIOD,
        "atr_period":              ATR_PERIOD,
        "base_trailing_atr_mult":  BASE_TRAILING_ATR_MULT,
        "trail_tighten_mult":      TRAIL_TIGHTEN_MULT,
        "mom_strong_threshold":    MOM_STRONG_THRESHOLD,
        "mom_decay_period":        MOM_DECAY_PERIOD,
        "wait_buy":               WAIT_BUY,
        "capital":                STARTING_CAPITAL,
    })

    # ── Build Cerebro ────────────────────────────────────────────────────────
    cerebro = bt.Cerebro()
    cerebro.broker.setcash(STARTING_CAPITAL)
    cerebro.broker.setcommission(commission=COMMISSION)

    # Add strategy with db_path so it writes to the right DB
    cerebro.addstrategy(MomentumAdaptiveV7, db_path=db_path)

    # Historical data feed
    df_hist = fetch_yfinance(tf)
    feed = YFinanceData(dataname=df_hist)
    cerebro.adddata(feed, name=tf)

    # Track bar count for incremental updates
    feed._bar_count = len(df_hist)

    log.info(f"Loaded {len(df_hist)} historical bars for {tf}")

    # ── Historical run (warmup) ──────────────────────────────────────────────
    cerebro.run(runonce=False)
    final_pv = cerebro.broker.getvalue()
    log.info(f"Historical run complete — portfolio: ${final_pv:.2f}")

    # ── Live polling ────────────────────────────────────────────────────────
    scheduler = BackgroundScheduler(timezone="UTC")

    def poll_job():
        """Fetch latest data, append new closed bars, run strategy next()."""
        try:
            df_new = fetch_latest_df(tf)
            if df_new.empty:
                log.warning(f"[{tf}] yfinance returned empty data")
                return

            n = append_new_bars(feed, df_new)
            if n == 0:
                log.debug(f"[{tf}] No new bars")
                return

            log.info(f"[{tf}] Appended {n} new bar(s), close={df_new.iloc[-1].close:.2f}")

            # Write candle for the last bar
            last = df_new.iloc[-1]
            write_candle(
                db_path,
                str(last.name.to_pydatetime().strftime("%Y-%m-%d %H:%M:%S")),
                float(last.open), float(last.high),
                float(last.low), float(last.close),
                float(last.volume),
            )

            # Run strategy on all newly added bars
            strat = cerebro.strats[0][0]
            for _ in range(n):
                strat.next()

        except Exception as e:
            log.exception(f"[{tf}] poll error: {e}")

    # Schedule polling at the correct interval for this timeframe
    poll_secs = cfg["poll_seconds"]
    scheduler.add_job(
        poll_job, "interval", seconds=poll_secs,
        id=f"poll_{tf}", misfire_grace_time=poll_secs // 2,
    )
    scheduler.start()
    log.info(f"[{tf}] Scheduler started — polling every {poll_secs}s")

    # ── Keep process alive ──────────────────────────────────────────────────
    try:
        while True:
            time.sleep(poll_secs)
    except KeyboardInterrupt:
        log.info(f"[{tf}] Shutting down...")
        scheduler.shutdown()
        sys.exit(0)


# ── Launcher ───────────────────────────────────────────────────────────────────

def launch_all():
    """Spawn all 3 instances in separate processes."""
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
            # Check for crashed processes
            for tf, p in processes.items():
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
