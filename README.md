# Gold Paper Trading System — XAUUSD (Gold)

Self-contained 24/7 paper trading simulation for XAUUSD (Gold) with **AI-assisted signal filtering via Kronos**.

**Stack:** Backtrader + yfinance + SQLite + FastAPI + React + Kronos (LLM-based market forecasting)

---

## Requirements

- **Python 3.12+** (WSL2 Ubuntu 24.04)
- **Node.js 18+** (for dashboard)
- **NVIDIA GPU with CUDA** (12GB VRAM recommended for Kronos float16 inference)
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

Kronos AI Layer (per bar):
  engine/kronos_wrapper.py  ← NeoQuasar/Kronos-base on HuggingFace
       ↓
  Filters / modifies strategy signals in real-time
```

**3 independent processes** — one per timeframe (5M, 15M, 1H). Each has its own $10,000 paper capital, SQLite DB, and polling loop. If one crashes, the others keep running.

---

## Quick Start

### 1. Run the WSL2 setup script
```bash
cd ~/GD_V1/gold-paper-trading
./setup.sh
```

This installs all system dependencies, Python packages (including PyTorch with CUDA 12.1), Kronos, and configures environment variables.

### 2. Add your API keys
```bash
nano .env
# Add: TWELVE_DATA_API_KEY=your_key_here
```

### 3. Verify the setup
```bash
source .venv/bin/activate
python test_setup.py
```

### 4. Start all services
```bash
./start.sh
```

- `screen -r engine` — Paper trader logs
- `screen -r api` — API server logs
- `screen -r dashboard` — Dashboard dev server
- `./stop.sh` — Stop all services

Dashboard: `http://localhost:3000` (or the port shown in the dashboard screen)

---

## Per-Timeframe Configuration

| Timeframe | SQLite DB | Polling Interval | Historical Lookback |
|-----------|-----------|------------------|---------------------|
| 5M | trading_5m.db | 300s | 2 days |
| 15M | trading_15m.db | 900s | 5 days |
| 1H | trading_1h.db | 3600s | 30 days |

Each instance starts with **$10,000 paper capital**.

---

## Kronos AI Signal Layer

Kronos (NeoQuasar/Kronos-base) is a LLM-based time-series forecasting model that runs locally on your GPU. It forecasts XAUUSD N bars ahead and overlays on the momentum strategy.

### Integration Rules

| Condition | Action |
|-----------|--------|
| Kronos bearish + strategy exit signal | **Exit immediately** (accelerate) |
| Kronos bearish + no exit signal yet | **Tighten trailing stop by 50%** |
| Kronos bullish + momentum decay exit signal | **Block momentum decay exit** (let trailing stop run) |
| Re-entry after trailing stop | **Only if Kronos also bullish** |

### Kronos Configuration (engine/config.py)

```python
USE_KRONOS              = True
KRONOS_MODEL            = "NeoQuasar/Kronos-base"
KRONOS_HORIZON          = 5    # bars ahead to forecast
KRONOS_BEARISH_THRESHOLD = 0.003  # 0.3% predicted drop = bearish
KRONOS_INTERVAL         = 1    # run every bar (1=every, 2=every other)
```

### Kronos API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/kronos/latest` | Latest Kronos prediction |
| GET | `/api/kronos/signals` | Last 100 Kronos signals |
| GET | `/api/kronos/stats` | Override / block / confirm counts |
| GET | `/api/kronos/status` | Model loaded, device, VRAM usage |
| POST | `/api/kronos/toggle` | Enable/disable Kronos at runtime |
| WS | `/ws` | Real-time push (includes `kronos` field) |

---

## Full API Endpoints

All endpoints accept `?timeframe=5m|15m|1h` query param (default: 15m):

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/summary` | Balance, equity, open trade, daily P&L |
| GET | `/candles` | Last N OHLCV candles |
| GET | `/trades` | Full trade log |
| GET | `/equity` | Equity curve data |
| GET | `/indicators` | ROC, EMA, ATR, MomDecay values |
| GET | `/params` | Strategy parameters |
| GET | `/api/kronos/latest` | Latest Kronos prediction |
| GET | `/api/kronos/signals` | Last 100 Kronos signals |
| GET | `/api/kronos/stats` | Kronos override/block/confirm counts |
| GET | `/api/kronos/status` | Kronos model status |
| POST | `/api/kronos/toggle` | Enable/disable Kronos |
| WS | `/ws` | Real-time push updates |

---

## Strategy: MomentumAdaptiveV7

**Entry conditions:**
- ROC_Fast > 0 AND ROC_Slow > 0 AND price > EMA20
- 9-bar cooldown between trades
- Quick re-entry: 2-bar cooldown after trailing-stop exit only

**Exit conditions:**
- Trailing stop: 2.5x ATR (tightened when momentum is strong)
- Momentum decay: ROC crossover + decay < 0
- **Kronos override:** Accelerate exit / tighten stop / block decay exit

**Paper commission:** 0.02% per trade

**Parameters:**
```
roc_fast=14, roc_slow=16, trend_ema=20, atr=12
base_trailing_atr_mult=2.5, trail_tighten_mult=1.25
mom_strong_threshold=2.5, mom_decay_period=5
wait_buy=9
```

---

## Backtesting

```bash
python engine/backtest.py \
    --csv data/historical/xauusd_m15.csv \
    --timeframe M15 \
    --mode backtest        # single run + plot
    --mode compare         # with vs without Kronos
    --mode optimize        # brute force param search
    --no-kronos            # disable Kronos for comparison
    --model kronos-base    # kronos-mini | kronos-small | kronos-base
```

Results are saved to `logs/plots/backtest_YYYYMMDD.png`.

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
Environment="MPLBACKEND=Agg"
Environment="HF_HOME=/path/to/gold-paper-trading/models"

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
ExecStart=/path/to/gold-paper-trading/.venv/bin/uvicorn api.api:app --host 0.0.0.0 --port 8000
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

## File Structure

```
gold-paper-trading/
├── engine/
│   ├── kronos_wrapper.py   # Kronos AI inference wrapper
│   ├── backtest.py         # Backtrader backtester
│   ├── live_strategy.py    # Strategy + Kronos integration
│   ├── main.py             # Paper trader entry point
│   ├── broker.py           # Custom broker (commission, sizer)
│   ├── config.py           # Per-timeframe config
│   ├── data_feed.py        # yfinance data feed
│   └── db.py               # SQLite persistence layer
├── api/
│   └── api.py              # FastAPI REST + WebSocket
├── dashboard/              # React + Vite + Tailwind
│   ├── src/components/
│   │   ├── KronosPanel.jsx # Kronos AI signal display
│   │   ├── MainChart.jsx   # TradingView chart
│   │   └── ...
│   └── dist/               # Built static files
├── strategy.py             # MomentumAdaptiveV7 (DO NOT MODIFY)
├── strategy_helpers.py     # (DO NOT MODIFY)
├── requirements.txt        # Python dependencies
├── setup.sh               # WSL2 environment setup
├── start.sh               # Launch all services
├── stop.sh                # Stop all services
├── test_setup.py          # Environment verification
└── .env                   # API keys (not committed)
```

---

## Notes

- **yfinance** rate-limits API calls. The 5M polling loop waits 300s between fetches to avoid being blocked. For production, use Twelve Data API (set `TWELVE_DATA_API_KEY` in `.env`).
- Dashboard WebSocket updates every 5 seconds via the API server.
- Historical warmup loads 2–30 days of candles before live trading begins (varies by timeframe).
- Kronos runs on GPU (float16) when CUDA is available, falls back to CPU gracefully.
- **WSL2 clock drift:** WSL2 clocks can drift vs Windows. The engine logs a warning if drift exceeds 2s.
- **Bug fix:** `strategy.py` originally used `self.broker.buy/sell()` which is incompatible with Backtrader 1.9+. Corrected to `self.buy/sell()` (strategy-level methods).
