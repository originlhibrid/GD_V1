#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# Stop all Gold Paper Trading screen sessions
# ─────────────────────────────────────────────────────────────────────────────
echo "Stopping all services..."
screen -X -S engine quit 2>/dev/null && echo "  engine stopped" || true
screen -X -S api quit 2>/dev/null && echo "  api stopped" || true
screen -X -S dashboard quit 2>/dev/null && echo "  dashboard stopped" || true
echo "🛑 All services stopped"
