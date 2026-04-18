"""SQLite schema and helpers — one DB per timeframe instance."""

import sqlite3
import os
from datetime import datetime
from typing import Optional

# ── Default paths (overridden at runtime per instance) ─────────────────────────

DEFAULT_DB_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def make_db_path(tf: str) -> str:
    """Return absolute path for a timeframe's DB file."""
    return os.path.join(DEFAULT_DB_DIR, f"trading_{tf}.db")


# ── Connection helper ─────────────────────────────────────────────────────────

def getconn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


# ── Schema init ───────────────────────────────────────────────────────────────

def init_db(db_path: str):
    """Create all tables for a single timeframe instance DB."""
    conn = getconn(db_path)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            side TEXT NOT NULL,
            price REAL NOT NULL,
            quantity REAL NOT NULL,
            cash_after REAL NOT NULL,
            portfolio_value REAL NOT NULL,
            exit_reason TEXT,
            pnl REAL DEFAULT 0
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS equity_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            portfolio_value REAL NOT NULL,
            cash REAL NOT NULL,
            position_value REAL NOT NULL,
            num_coins REAL NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS candles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT UNIQUE NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume REAL NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS indicators (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            roc_fast REAL,
            roc_slow REAL,
            trend_ema REAL,
            atr REAL,
            mom_decay REAL,
            trailing_stop_level REAL,
            peak_price REAL,
            momentum_strength REAL,
            in_position INTEGER
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS params (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


# ── Write helpers ─────────────────────────────────────────────────────────────

def write_trade(db_path: str, timestamp: str, side: str, price: float,
                quantity: float, cash_after: float, portfolio_value: float,
                exit_reason: Optional[str], pnl: float):
    conn = getconn(db_path)
    c = conn.cursor()
    c.execute("""
        INSERT INTO trades (timestamp, side, price, quantity, cash_after,
                           portfolio_value, exit_reason, pnl)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (timestamp, side, price, quantity, cash_after, portfolio_value,
          exit_reason, pnl))
    conn.commit()
    conn.close()


def write_equity_snapshot(db_path: str, timestamp: str,
                          portfolio_value: float, cash: float,
                          position_value: float, num_coins: float):
    conn = getconn(db_path)
    c = conn.cursor()
    c.execute("""
        INSERT INTO equity_snapshots (timestamp, portfolio_value, cash,
                                      position_value, num_coins)
        VALUES (?, ?, ?, ?, ?)
    """, (timestamp, portfolio_value, cash, position_value, num_coins))
    conn.commit()
    conn.close()


def write_candle(db_path: str, timestamp: str,
                 o: float, h: float, l: float, c: float, v: float):
    conn = getconn(db_path)
    c = conn.cursor()
    c.execute("""
        INSERT OR REPLACE INTO candles (timestamp, open, high, low, close, volume)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (timestamp, o, h, l, c, v))
    conn.commit()
    conn.close()


def write_indicators(db_path: str, timestamp: str,
                     roc_fast: float, roc_slow: float, trend_ema: float,
                     atr: float, mom_decay: float,
                     trailing_stop_level: float, peak_price: float,
                     momentum_strength: float, in_position: bool):
    conn = getconn(db_path)
    c = conn.cursor()
    c.execute("""
        INSERT INTO indicators (timestamp, roc_fast, roc_slow, trend_ema, atr,
                               mom_decay, trailing_stop_level, peak_price,
                               momentum_strength, in_position)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (timestamp, roc_fast, roc_slow, trend_ema, atr, mom_decay,
          trailing_stop_level, peak_price, momentum_strength,
          1 if in_position else 0))
    conn.commit()
    conn.close()


def save_params(db_path: str, params: dict):
    conn = getconn(db_path)
    c = conn.cursor()
    for k, v in params.items():
        c.execute("INSERT OR REPLACE INTO params (key, value) VALUES (?, ?)",
                  (k, str(v)))
    conn.commit()
    conn.close()


# ── Read helpers ──────────────────────────────────────────────────────────────

def get_trades(db_path: str, limit: int = 50) -> list:
    conn = getconn(db_path)
    c = conn.cursor()
    rows = c.execute(
        "SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_equity(db_path: str, hours: int = 24) -> list:
    conn = getconn(db_path)
    c = conn.cursor()
    cutoff_ts = datetime.utcnow().timestamp() - hours * 3600
    cutoff_dt = datetime.fromtimestamp(cutoff_ts).isoformat()
    rows = c.execute(
        "SELECT * FROM equity_snapshots WHERE timestamp >= ? ORDER BY id ASC",
        (cutoff_dt,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_equity(db_path: str) -> list:
    conn = getconn(db_path)
    c = conn.cursor()
    rows = c.execute(
        "SELECT * FROM equity_snapshots ORDER BY id ASC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_candles(db_path: str, limit: int = 200) -> list:
    conn = getconn(db_path)
    c = conn.cursor()
    rows = c.execute(
        "SELECT * FROM candles ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in reversed(rows)]


def get_latest_indicator(db_path: str) -> Optional[dict]:
    conn = getconn(db_path)
    c = conn.cursor()
    row = c.execute(
        "SELECT * FROM indicators ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_portfolio_status(db_path: str) -> dict:
    conn = getconn(db_path)
    c = conn.cursor()
    snap = c.execute(
        "SELECT * FROM equity_snapshots ORDER BY id DESC LIMIT 1"
    ).fetchone()
    last_trade = c.execute(
        "SELECT * FROM trades ORDER BY id DESC LIMIT 1"
    ).fetchone()
    trade_count = c.execute(
        "SELECT COUNT(*) FROM trades"
    ).fetchone()[0]
    wins = c.execute(
        "SELECT COUNT(*) FROM trades WHERE pnl > 0"
    ).fetchone()[0]
    win_rate = (wins / trade_count * 100) if trade_count > 0 else 0.0
    conn.close()
    return {
        "snapshot": dict(snap) if snap else None,
        "last_trade": dict(last_trade) if last_trade else None,
        "trade_count": trade_count,
        "win_rate": win_rate,
    }


def get_latest_candle_time(db_path: str) -> Optional[str]:
    conn = getconn(db_path)
    c = conn.cursor()
    row = c.execute(
        "SELECT timestamp FROM candles ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return row["timestamp"] if row else None
