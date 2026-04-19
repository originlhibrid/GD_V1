"""
FastAPI REST + WebSocket API for the Gold Paper Trading Engine.
Each timeframe (5M / 15M / 1H) has its own SQLite DB.
Query param ?timeframe= routes reads to the correct DB.
"""

import asyncio
import logging
import os
import sqlite3
import sys
import threading
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# WSL2 NOTE: set MPLBACKEND before any matplotlib import
os.environ.setdefault("MPLBACKEND", "Agg")

# ── Project root ────────────────────────────────────────────────────────────────

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engine.config import (
    STARTING_CAPITAL,
    ROC_FAST_PERIOD, ROC_SLOW_PERIOD, TREND_PERIOD, ATR_PERIOD,
    BASE_TRAILING_ATR_MULT, TRAIL_TIGHTEN_MULT, MOM_STRONG_THRESHOLD,
    MOM_DECAY_PERIOD, WAIT_BUY,
    USE_KRONOS, KRONOS_MODEL, KRONOS_HORIZON,
    KRONOS_BEARISH_THRESHOLD, KRONOS_INTERVAL,
)
from engine.db import (
    init_db, get_trades, get_equity, get_candles,
    get_latest_indicator, get_portfolio_status, get_all_equity,
    make_db_path, get_kronos_signals as _get_kronos_signals,
    get_kronos_stats as _get_kronos_stats,
)
from engine.kronos_wrapper import get_kronos, check_cuda_status

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api")

app = FastAPI(title="Gold Paper Trading API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

VALID_TF = {"5m", "15m", "1h"}
DEFAULT_TF = "5m"

# ── DB helpers ────────────────────────────────────────────────────────────────

def get_db_path(timeframe: str) -> str:
    return os.path.join(ROOT, f"trading_{timeframe}.db")

def ensure_db(tf: str):
    p = get_db_path(tf)
    if not os.path.exists(p):
        init_db(p)

# ── Shared WebSocket state per timeframe ─────────────────────────────────────

class TfState:
    """Lightweight latest values for WS broadcast — written by polling, read by WS."""
    def __init__(self, tf: str):
        self.tf = tf
        self.lock = threading.Lock()
        self.latest_price = 0.0
        self.portfolio_value = STARTING_CAPITAL
        self.cash = STARTING_CAPITAL
        self.in_position = False
        self.trailing_stop = 0.0
        self.peak_price = 0.0
        self.entry_price = 0.0
        self.roc_fast = 0.0
        self.roc_slow = 0.0
        self.mom_decay = 0.0
        self.momentum_strength = 0.0
        self.last_bar_time = None
        self.trade_count = 0
        self.win_rate = 0.0
        self.unrealized_pnl = 0.0

    def to_dict(self):
        return {
            "timeframe": self.tf,
            "latest_price": self.latest_price,
            "portfolio_value": self.portfolio_value,
            "cash": self.cash,
            "in_position": self.in_position,
            "trailing_stop": self.trailing_stop,
            "peak_price": self.peak_price,
            "entry_price": self.entry_price,
            "roc_fast": self.roc_fast,
            "roc_slow": self.roc_slow,
            "mom_decay": self.mom_decay,
            "momentum_strength": self.momentum_strength,
            "last_bar_time": self.last_bar_time,
            "trade_count": self.trade_count,
            "win_rate": self.win_rate,
            "unrealized_pnl": self.unrealized_pnl,
        }

# One state object per timeframe
tf_states = {tf: TfState(tf) for tf in VALID_TF}

# ── Global Kronos runtime toggle ───────────────────────────────────────────────

_kronos_runtime_enabled = True  # can be toggled at runtime via POST


def _get_kronos_signal_for_tf(tf: str) -> dict:
    """Return the latest Kronos signal from the strategy for a given timeframe."""
    # Strategy instance lives in the engine process (not this API process).
    # The API reads the latest signal from the timeframe's SQLite DB instead.
    db = get_db_path(tf)
    if not os.path.exists(db):
        return {}
    try:
        signals = _get_kronos_signals(db, limit=1)
        if signals:
            s = signals[0]
            return {
                "direction":        s.get("direction", "neutral"),
                "confidence":       s.get("confidence", 0.0),
                "predicted_close":  s.get("pred_close", 0.0),
                "volatility_high":  bool(s.get("vol_high", 0)),
                "action":           s.get("action_taken", "none"),
            }
    except Exception:
        pass
    return {}


def refresh_state(tf: str):
    """Pull latest values from SQLite into the TfState for broadcast."""
    db = get_db_path(tf)
    if not os.path.exists(db):
        return
    st = tf_states[tf]
    try:
        ind = get_latest_indicator(db)
        ps = get_portfolio_status(db)
        snap = ps.get("snapshot")
        last_trade = ps.get("last_trade")

        with st.lock:
            if ind:
                st.roc_fast = ind.get("roc_fast", 0) or 0
                st.roc_slow = ind.get("roc_slow", 0) or 0
                st.mom_decay = ind.get("mom_decay", 0) or 0
                st.momentum_strength = ind.get("momentum_strength", 0) or 0
                st.trailing_stop = ind.get("trailing_stop_level", 0) or 0
                st.peak_price = ind.get("peak_price", 0) or 0
                st.in_position = bool(ind.get("in_position", 0))
                st.last_bar_time = ind.get("timestamp")

            if snap:
                st.portfolio_value = snap.get("portfolio_value", STARTING_CAPITAL) or STARTING_CAPITAL
                st.cash = snap.get("cash", STARTING_CAPITAL) or STARTING_CAPITAL
                price = st.latest_price
                if st.in_position and st.entry_price > 0:
                    pos_val = st.portfolio_value - st.cash
                    st.unrealized_pnl = pos_val * (price - st.entry_price) / st.entry_price if st.entry_price > 0 else 0

            st.trade_count = ps.get("trade_count", 0) or 0
            st.win_rate = ps.get("win_rate", 0.0) or 0.0
    except Exception as e:
        logger.debug(f"[{tf}] refresh_state error: {e}")


# ── REST Endpoints ─────────────────────────────────────────────────────────────

@app.get("/status")
def get_status(timeframe: str = Query(DEFAULT_TF, regex="^(5m|15m|1h)$")):
    """Current portfolio, position, live price for the selected timeframe."""
    db = get_db_path(timeframe)
    ensure_db(timeframe)
    refresh_state(timeframe)
    st = tf_states[timeframe]
    with st.lock:
        d = st.to_dict()
    return d


@app.get("/indicators")
def get_indicators(timeframe: str = Query(DEFAULT_TF, regex="^(5m|15m|1h)$")):
    """Latest indicator values for the selected timeframe."""
    db = get_db_path(timeframe)
    ensure_db(timeframe)
    ind = get_latest_indicator(db)
    return ind if ind else {}


@app.get("/trades")
def get_trades_endpoint(
    limit: int = Query(50, ge=1, le=500),
    timeframe: str = Query(DEFAULT_TF, regex="^(5m|15m|1h)$"),
):
    db = get_db_path(timeframe)
    ensure_db(timeframe)
    return get_trades(db, limit=limit)


@app.get("/equity")
def get_equity_endpoint(
    hours: int = Query(24, ge=1, le=168),
    timeframe: str = Query(DEFAULT_TF, regex="^(5m|15m|1h)$"),
):
    db = get_db_path(timeframe)
    ensure_db(timeframe)
    if hours >= 168:
        return get_all_equity(db)
    return get_equity(db, hours=hours)


@app.get("/candles/{tf}")
def get_candles_endpoint(
    tf: str,
    limit: int = Query(200, ge=1, le=500),
):
    if tf not in VALID_TF:
        tf = DEFAULT_TF
    db = get_db_path(tf)
    ensure_db(tf)
    return get_candles(db, limit=limit)


@app.get("/params")
def get_params(timeframe: str = Query(DEFAULT_TF, regex="^(5m|15m|1h)$")):
    """Current strategy parameters (same across all timeframes)."""
    return {
        "name":                   "momentum_adaptive_v7",
        "timeframe":              timeframe,
        "roc_fast_period":        ROC_FAST_PERIOD,
        "roc_slow_period":        ROC_SLOW_PERIOD,
        "trend_period":           TREND_PERIOD,
        "atr_period":             ATR_PERIOD,
        "base_trailing_atr_mult": BASE_TRAILING_ATR_MULT,
        "trail_tighten_mult":     TRAIL_TIGHTEN_MULT,
        "mom_strong_threshold":    MOM_STRONG_THRESHOLD,
        "mom_decay_period":       MOM_DECAY_PERIOD,
        "wait_buy":               WAIT_BUY,
        "starting_capital":       STARTING_CAPITAL,
        "use_kronos":             _kronos_runtime_enabled,
        "kronos_model":           KRONOS_MODEL,
        "kronos_horizon":         KRONOS_HORIZON,
    }


# ── Kronos AI Endpoints ────────────────────────────────────────────────────────

@app.get("/api/kronos/latest")
def get_kronos_latest(timeframe: str = Query(DEFAULT_TF, regex="^(5m|15m|1h)$")):
    """Latest Kronos signal for the selected timeframe."""
    db = get_db_path(timeframe)
    ensure_db(timeframe)
    signals = _get_kronos_signals(db, limit=1)
    if not signals:
        return {"direction": "neutral", "confidence": 0.0,
                "predicted_close": 0.0, "volatility_high": False, "action": "none"}
    s = signals[0]
    return {
        "direction":        s.get("direction", "neutral"),
        "confidence":       s.get("confidence", 0.0),
        "predicted_close":  s.get("pred_close", 0.0),
        "volatility_high":  bool(s.get("vol_high", 0)),
        "action":           s.get("action_taken", "none"),
        "timestamp":        s.get("timestamp"),
    }


@app.get("/api/kronos/signals")
def get_kronos_signals_endpoint(
    limit: int = Query(100, ge=1, le=500),
    timeframe: str = Query(DEFAULT_TF, regex="^(5m|15m|1h)$"),
):
    """Last N Kronos signal records from DB."""
    db = get_db_path(timeframe)
    ensure_db(timeframe)
    signals = _get_kronos_signals(db, limit=limit)
    return signals


@app.get("/api/kronos/stats")
def get_kronos_stats_endpoint(
    timeframe: str = Query(DEFAULT_TF, regex="^(5m|15m|1h)$"),
):
    """Override / block / confirm counts for the selected timeframe."""
    db = get_db_path(timeframe)
    ensure_db(timeframe)
    return _get_kronos_stats(db)


@app.get("/api/kronos/status")
def get_kronos_status():
    """Model loaded state, device, VRAM usage, runtime toggle."""
    cuda = check_cuda_status()
    return {
        "model_loaded":  cuda.get("model_loaded", False),
        "device":        cuda.get("device"),
        "gpu_name":      cuda.get("gpu_name"),
        "vram_gb":       cuda.get("vram_gb"),
        "cuda_available": cuda.get("cuda_available"),
        "init_error":    cuda.get("init_error"),
        "runtime_enabled": _kronos_runtime_enabled,
        "model_name":    KRONOS_MODEL,
        "horizon":       KRONOS_HORIZON,
    }


@app.post("/api/kronos/toggle")
async def post_kronos_toggle(body: dict):
    """Enable or disable Kronos at runtime."""
    global _kronos_runtime_enabled
    enabled = bool(body.get("enabled", True))
    _kronos_runtime_enabled = enabled
    # Propagate to KronosWrapper singleton if loaded
    try:
        k = get_kronos()
        if k is not None:
            k.enabled = enabled
    except Exception:
        pass
    return {"enabled": enabled, "status": "ok"}


# ── WebSocket ───────────────────────────────────────────────────────────────────

class WsManager:
    """Manages WebSocket connections grouped by selected timeframe."""
    def __init__(self):
        self.lock = threading.Lock()
        # tf -> list of WebSockets
        self.subs: dict[str, list[WebSocket]] = {tf: [] for tf in VALID_TF}

    async def connect(self, ws: WebSocket, tf: str):
        await ws.accept()
        with self.lock:
            self.subs[tf].append(ws)

    def disconnect(self, ws: WebSocket, tf: str):
        with self.lock:
            if ws in self.subs[tf]:
                self.subs[tf].remove(ws)

    async def broadcast_tf(self, tf: str):
        """Push latest state for a specific timeframe to all its subscribers."""
        st = tf_states[tf]
        with st.lock:
            payload = st.to_dict()
        # Append latest Kronos signal to the WS payload
        payload["kronos"] = _get_kronos_signal_for_tf(tf)
        msg = {"type": "tick", "data": payload}
        dead = []
        with self.lock:
            for ws in self.subs[tf]:
                try:
                    await ws.send_json(msg)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self.subs[tf].remove(ws)


ws_manager = WsManager()


async def ws_broadcaster():
    """
    Background loop: every 5s, refresh state from each timeframe's DB
    and push to its respective WebSocket subscribers.
    """
    while True:
        await asyncio.sleep(5)
        for tf in VALID_TF:
            refresh_state(tf)
            await ws_manager.broadcast_tf(tf)


@app.websocket("/ws")
async def ws_endpoint(
    websocket: WebSocket,
    timeframe: str = Query(DEFAULT_TF, regex="^(5m|15m|1h)$"),
):
    await ws_manager.connect(websocket, timeframe)
    try:
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                if data == "ping":
                    await websocket.send_text("pong")
            except asyncio.TimeoutError:
                # Send keepalive tick
                await ws_manager.broadcast_tf(timeframe)
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, timeframe)


@app.on_event("startup")
async def startup():
    # Init all 3 DBs
    for tf in VALID_TF:
        ensure_db(tf)
    asyncio.create_task(ws_broadcaster())
    logger.info("API started — broadcasting for timeframes: 5m, 15m, 1h")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
