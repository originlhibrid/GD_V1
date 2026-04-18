# Gold Paper Trading System — XAUUSD (Gold)

Self-contained 24/7 paper trading simulation for XAUUSD (Gold).
No brokerage API required — runs entirely on your machine.

**Stack:** yfinance + Pure Python/Numba + SQLite + FastAPI + React + TradingView Lightweight Charts

---

## Architecture

```
yfinance (GC=F — CME Gold Futures)
       ↓
engine/main.py  ← 3 independent processes (historical warmup + live polling)
       ↓
   SQLite DBs (5m, 15m, 1h — one per timeframe)
       ↑
  api/api.py  ← FastAPI REST + WebSocket
       ↑
  React Dashboard (Vite, TradingView Charts, Tailwind CSS)
```

**3 independent processes** — one per timeframe (5M, 15M, 1H).
Each has its own $10,000 paper capital, SQLite DB, and polling loop.
If one crashes, the others keep running.

---

## Strategy: momentum_adaptive_v7

**Entry conditions:**
- ROC_Fast > 0 AND ROC_Slow > 0 AND price > EMA20
- wait_buy-bar cooldown between trades
- Quick re-entry: 2-bar cooldown after trailing-stop exit only

**Exit conditions:**
- Trailing stop: 2.5x ATR (tightened when momentum is strong)
- Momentum decay: ROC crossover + decay < 0

**Position sizing:** Full Kelly (all-in, all-out).

**Parameters:**
```
roc_fast=14, roc_slow=16, trend_ema=20, atr=12
base_trailing_atr_mult=2.5, trail_tighten_mult=1.25
mom_strong_threshold=2.5, mom_decay_period=5
wait_buy=9, wait_sell=27
```

---

## Quick Start

### 1. Install dependencies
```bash
cd gold-paper-trading
uv venv --python 3.11 .venv && source .venv/bin/activate
uv pip install -r requirements.txt
```

### 2. Start the trading engine (all 3 timeframes)
```bash
python engine/main.py
```
Leave this running. It starts 3 background processes polling yfinance.

### 3. Start the API server (new terminal)
```bash
uvicorn api.api:app --host 0.0.0.0 --port 8000
```

### 4. Build and serve dashboard (new terminal)
```bash
cd dashboard && npm install && npm run build
npx serve -s dist -l 3000
```
Open `http://localhost:3000`

---

## Per-Timeframe Configuration

| Timeframe | SQLite DB | Polling Interval | Historical Lookback |
|-----------|-----------|------------------|---------------------|
| 5M | trading_5m.db | 300s | 2 days |
| 15M | trading_15m.db | 900s | 5 days |
| 1H | trading_1h.db | 3600s | 30 days |

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
ExecStart=/path/to/gold-paper-trading/.venv/bin/python engine/main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo -S -p '' systemctl daemon-reload
sudo -S -p '' systemctl enable trading-engine
sudo -S -p '' systemctl start trading-engine
```
