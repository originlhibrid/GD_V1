"""
FastAPI REST + WebSocket API for the Gold Paper Trading Engine.
Each timeframe (5M / 15M / 1H) has its own SQLite DB.
Query param ?timeframe= routes reads to the correct DB.
"""

import asyncio
import logging
import os
import sqlite3
import threading
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# ── Project root ────────────────────────────────────────────────────────────────

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engine.config import (
    STARTING_CAPITAL,
    ROC_FAST_PERIOD, ROC_SLOW_PERIOD, TREND_PERIOD, ATR_PERIOD,
    BASE_TRAILING_ATR_MULT, TRAIL_TIGHTEN_MULT, MOM_STRONG_THRESHOLD,
    MOM_DECAY_PERIOD, WAIT_BUY,
)
from engine.db import (
    init_db, get_trades, get_equity, get_candles,
    get_latest_indicator, get_portfolio_status, get_all_equity,
    make_db_path,
)

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
    }


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
