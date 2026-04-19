"""Per-instance config. Each timeframe runs as an independent process."""

# All three instances share the same strategy params (midpoints from bounds)
ROC_FAST_PERIOD = 14
ROC_SLOW_PERIOD = 16
TREND_PERIOD = 20
ATR_PERIOD = 12
BASE_TRAILING_ATR_MULT = 2.5
TRAIL_TIGHTEN_MULT = 1.25
MOM_STRONG_THRESHOLD = 2.5
MOM_DECAY_PERIOD = 5
WAIT_BUY = 9
WAIT_SELL = 27

# ── Kronos AI Signal Layer ─────────────────────────────────────────────────────
USE_KRONOS              = True
KRONOS_MODEL            = "NeoQuasar/Kronos-base"  # "NeoQuasar/Kronos-mini" | "NeoQuasar/Kronos-small"
KRONOS_HORIZON          = 5                         # bars ahead to forecast
KRONOS_BEARISH_THRESHOLD = 0.003                   # 0.3% predicted drop = bearish
KRONOS_INTERVAL         = 1                         # run Kronos every N bars (1 = every bar)

# Ticker proxy for XAUUSD via yfinance
TICKER = "GC=F"

# Each instance starts with this amount in its own paper broker
STARTING_CAPITAL = 10_000.0

# Commission: 0.02% per trade (spread simulation)
COMMISSION = 0.0002

# ── Per-timeframe config ────────────────────────────────────────────────────────

TIMEFRAMES = {
    "5m": {
        "interval":      "5m",
        "lookback_days": 2,
        "poll_cron":     "*/5 * * * *",
        "db_filename":   "trading_5m.db",
        "poll_seconds":   300,   # 5 min
    },
    "15m": {
        "interval":      "15m",
        "lookback_days": 5,
        "poll_cron":     "*/15 * * * *",
        "db_filename":   "trading_15m.db",
        "poll_seconds":   900,   # 15 min
    },
    "1h": {
        "interval":      "1h",
        "lookback_days": 30,
        "poll_cron":     "0 * * * *",
        "db_filename":   "trading_1h.db",
        "poll_seconds":   3600,  # 60 min
    },
}
