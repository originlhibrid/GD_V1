# Gold Paper Trading System — XAUUSD (Gold)

Self-contained 24/7 paper trading simulation for XAUUSD (Gold). No brokerage API required — runs entirely on your machine.

**Stack:** Backtrader + yfinance + SQLite + FastAPI + React + TradingView Lightweight Charts

---

## Requirements

- Python 3.10+
- Node.js 18+ (for dashboard)
- All Python packages: `pip install -r requirements.txt`
- Dashboard packages: `cd dashboard && npm install`

---

## Architecture

```
yfinance (GC=F — CME Gold Futures)
       ↓
engine/main.py  ← Backtrader Cerebro (historical warmup)
       ↓            + APScheduler (live polling every 5/15/60 min)
   SQLite DBs (5m, 15m, 1h — one per timeframe)
       ↑
  api/api.py  ← FastAPI REST + WebSocket
       ↑
  React Dashboard (Vite, TradingView Charts, Tailwind CSS)
```

**3 independent processes** — one per timeframe (5M, 15M, 1H). Each has its own $10,000 paper capital, SQLite DB, and polling loop. If one crashes, the others keep running.

---

## Quick Start

### 1. Install dependencies
```bash
# Python deps
pip install -r requirements.txt

# Dashboard deps
cd dashboard && npm install && cd ..
```

### 2. Start the trading engine (all 3 timeframes)
```bash
python3 engine/main.py
```
Leave this running. It starts 3 background processes polling yfinance.

### 3. Start the API server (new terminal)
```bash
uvicorn api.api:app --host 0.0.0.0 --port 8000
```

### 4. Build and serve dashboard (new terminal)
```bash
cd dashboard
npm run build
# Serve dist/ with any static server, e.g.:
npx serve -s dist -l 3000
```
Open `http://localhost:3000`

---

## Per-Timeframe Configuration

| Timeframe | SQLite DB | Polling Interval | Historical Lookback |
|-----------|-----------|------------------|---------------------|
| 5M | trading_5m.sqlite | 300s | 2 days |
| 15M | trading_15m.sqlite | 900s | 5 days |
| 1H | trading_1h.sqlite | 3600s | 30 days |

Each instance starts with **$10,000 paper capital**.

---

## API Endpoints

All endpoints take `?timeframe=5m|15m|1h` query param:

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /summary | Balance, equity, open trade, daily P&L |
| GET | /candles | Last N OHLCV candles |
| GET | /trades | Full trade log |
| GET | /equity | Equity curve data |
| GET | /indicators | ROC, EMA, ATR, MomDecay values |
| GET | /params | Strategy parameters |
| WS | /ws | Real-time push updates |

---

## Strategy: MomentumAdaptiveV7

**Entry conditions:**
- ROC_Fast > 0 AND ROC_Slow > 0 AND price > EMA20
- 9-bar cooldown between trades
- Quick re-entry: 2-bar cooldown after trailing-stop exit only

**Exit conditions:**
- Trailing stop: 2.5x ATR (tightened when momentum is strong)
- Momentum decay: ROC crossover + decay < 0

**Paper commission:** 0.02% per trade

**Parameters:**
```
roc_fast=14, roc_slow=16, trend_ema=20, atr=12
base_trailing_atr_mult=2.5, trail_tighten_mult=1.25
mom_strong_threshold=2.5, mom_decay_period=5
wait_buy=9
```

---

## Deployment (systemd)

Create `/etc/systemd/system/trading-engine.service`:
```ini
[Unit]
Description=Gold Paper Trading Engine
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/gold-paper-trading
ExecStart=/usr/bin/python3 engine/main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Create `/etc/systemd/system/trading-api.service`:
```ini
[Unit]
Description=Gold Trading API
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/gold-paper-trading
ExecStart=/usr/bin/uvicorn api.api:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Then:
```bash
sudo systemctl daemon-reload
sudo systemctl enable trading-engine trading-api
sudo systemctl start trading-engine trading-api
```

---

## Notes

- **yfinance** rate-limits API calls. The 5M polling loop waits 300s between fetches to avoid being blocked.
- Dashboard WebSocket updates every 5 seconds via the API server.
- Historical warmup loads 2–30 days of candles before live trading begins (varies by timeframe).
- **Bug fixed:** `strategy.py` originally used `self.broker.buy/sell()` which is incompatible with Backtrader 1.9+. Corrected to `self.buy/sell()` (strategy-level methods).
