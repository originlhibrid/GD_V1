#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# Start all Gold Paper Trading services in screen sessions
# Usage: bash start.sh
# ─────────────────────────────────────────────────────────────────────────────
set -e

source ~/GD_V1/venv/bin/activate 2>/dev/null || true
cd ~/GD_V1/gold-paper-trading

export MPLBACKEND=Agg
export HF_HOME=~/GD_V1/gold-paper-trading/models
export TRANSFORMERS_CACHE=~/GD_V1/gold-paper-trading/models

# Kill existing sessions
echo "Stopping existing sessions..."
screen -X -S engine quit 2>/dev/null || true
screen -X -S api quit 2>/dev/null || true
screen -X -S dashboard quit 2>/dev/null || true
sleep 1

# Create dirs
mkdir -p logs/plots data/historical data/live models

echo "Starting engine (paper trader)..."
screen -dmS engine bash -c "
    cd ~/GD_V1/gold-paper-trading
    source ~/GD_V1/venv/bin/activate
    export MPLBACKEND=Agg
    export HF_HOME=~/GD_V1/gold-paper-trading/models
    export TRANSFORMERS_CACHE=~/GD_V1/gold-paper-trading/models
    python engine/main.py
    exec bash
"

sleep 2

echo "Starting API server..."
screen -dmS api bash -c "
    cd ~/GD_V1/gold-paper-trading
    source ~/GD_V1/venv/bin/activate
    export MPLBACKEND=Agg
    export HF_HOME=~/GD_V1/gold-paper-trading/models
    export TRANSFORMERS_CACHE=~/GD_V1/gold-paper-trading/models
    uvicorn api.api:app --host 0.0.0.0 --port 8000
    exec bash
"

echo "Starting dashboard..."
screen -dmS dashboard bash -c "
    cd ~/GD_V1/gold-paper-trading/dashboard
    npm run dev
    exec bash
"

sleep 1

echo ""
echo "✅ All services started"
echo ""
echo "  screen -r engine     → Trading engine (5m, 15m, 1h)"
echo "  screen -r api        → API server (port 8000)"
echo "  screen -r dashboard  → Dashboard dev server"
echo ""
echo "To stop:  bash stop.sh"
