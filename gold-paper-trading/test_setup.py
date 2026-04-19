#!/usr/bin/env python3
"""
test_setup.py — Verify the Gold Paper Trading + Kronos environment.
Run: python test_setup.py
"""

from __future__ import annotations

import os
import sys
import sqlite3
from pathlib import Path

# WSL2 NOTE: set MPLBACKEND before any matplotlib import
os.environ.setdefault("MPLBACKEND", "Agg")

PASS = "\u2705"
FAIL = "\u274c"
WARN = "\u26a0\ufe0f"

ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(ROOT))


def check(name: str, condition: bool, details: str = ""):
    icon = PASS if condition else FAIL
    status = "PASS" if condition else "FAIL"
    detail = f"  → {details}" if details else ""
    print(f"  {icon} [{status}] {name}{detail}")
    return condition


def run():
    print("\n" + "═" * 50)
    print(" Gold Paper Trading — Environment Check")
    print("═" * 50)

    all_pass = True

    # ── Python ────────────────────────────────────────────────────────────────
    print("\n[ Python ]")
    all_pass &= check("Python 3.11+", sys.version_info >= (3, 11), sys.version.split()[0])

    # ── CUDA ────────────────────────────────────────────────────────────────
    print("\n[ CUDA ]")
    try:
        import torch
        cuda = torch.cuda.is_available()
        all_pass &= check("CUDA available", cuda)
        if cuda:
            gpu_name = torch.cuda.get_device_name(0)
            vram_gb  = torch.cuda.get_device_properties(0).total_memory / 1e9
            all_pass &= check("VRAM >= 8GB", vram_gb >= 8, f"{vram_gb:.1f} GB ({gpu_name})")
            try:
                x = torch.zeros(1, device="cuda:0", dtype=torch.float16)
                all_pass &= check("float16 on GPU works", True)
                del x
                torch.cuda.empty_cache()
            except Exception as e:
                all_pass &= check("float16 on GPU works", False, str(e))
        else:
            print(f"  {WARN}  GPU not available — Kronos will run on CPU")
    except ImportError:
        all_pass &= check("PyTorch installed", False, "torch not installed")
        print(f"  {WARN}  Skipping GPU checks")

    # ── Kronos / Transformers ─────────────────────────────────────────────────
    print("\n[ Kronos ]")
    try:
        from engine.kronos_wrapper import get_kronos, check_cuda_status
        all_pass &= check("kronos_wrapper imports OK", True)
        status = check_cuda_status()
        all_pass &= check("Kronos model loaded", status.get("model_loaded", False),
                          status.get("init_error") or status.get("device") or "")
    except ImportError:
        all_pass &= check("kronos_wrapper imports OK", False)
        print(f"  {WARN}  Transformers not installed — run: pip install transformers accelerate")

    # ── Core strategy deps ───────────────────────────────────────────────────
    print("\n[ Strategy Dependencies ]")
    deps = [
        ("yfinance",          "yfinance"),
        ("pandas",            "pandas"),
        ("numpy",             "numpy"),
        ("numba",             "numba"),
        ("apscheduler",       "apscheduler"),
        ("fastapi",           "fastapi"),
        ("uvicorn",           "uvicorn"),
        ("sqlalchemy",        "sqlalchemy"),
    ]
    for pkg, import_name in deps:
        try:
            __import__(import_name)
            all_pass &= check(f"{pkg} installed", True)
        except ImportError:
            all_pass &= check(f"{pkg} installed", False)
            all_pass = False

    try:
        from strategy_helpers import roc_np, ema_np, atr_np
        all_pass &= check("strategy_helpers imports OK", True)
    except ImportError as e:
        all_pass &= check("strategy_helpers imports OK", False, str(e))

    # Numba JIT compile
    print("\n[ Numba JIT ]")
    try:
        import numpy as np
        from numba import njit
        @njit
        def _jit_test(x, y):
            return x + y
        _jit_test(np.array([1.0]), np.array([2.0]))
        all_pass &= check("Numba JIT compiles", True)
    except Exception as e:
        all_pass &= check("Numba JIT compiles", False, str(e))

    # ── Backtrader ──────────────────────────────────────────────────────────
    print("\n[ Backtrader ]")
    try:
        import backtrader as bt
        all_pass &= check("Backtrader installed", True)
    except ImportError:
        all_pass &= check("Backtrader installed", False)
        all_pass = False

    # ── Directories ─────────────────────────────────────────────────────────
    print("\n[ Directories ]")
    for d in ["logs", "logs/plots", "data/historical", "data/live", "models"]:
        p = ROOT / d
        exists = p.exists()
        all_pass &= check(f"  {d}/ exists", exists, str(p))
        if not exists:
            p.mkdir(parents=True, exist_ok=True)

    # ── SQLite DBs ──────────────────────────────────────────────────────────
    print("\n[ SQLite DBs ]")
    for tf, db_name in [("5m", "trading_5m.db"), ("15m", "trading_15m.db"), ("1h", "trading_1h.db")]:
        db_path = ROOT / db_name
        exists = db_path.exists()
        all_pass &= check(f"  {db_name}", exists)
        if exists:
            try:
                conn = sqlite3.connect(str(db_path))
                cur = conn.cursor()
                cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = [r[0] for r in cur.fetchall()]
                has_kronos = "kronos_signals" in tables
                all_pass &= check(f"    kronos_signals table", has_kronos)
                conn.close()
            except Exception as e:
                all_pass &= check(f"  {db_name} readable", False, str(e))

    # ── API ─────────────────────────────────────────────────────────────────
    print("\n[ API ]")
    try:
        import requests
        resp = requests.get("http://localhost:8000/status", timeout=3)
        all_pass &= check("API reachable", resp.status_code == 200,
                          f"status={resp.status_code}")
    except Exception as e:
        all_pass &= check("API reachable", False, "not running on port 8000")
        print(f"  {WARN}  Start API with: uvicorn api.api:app --host 0.0.0.0 --port 8000")

    # ── Misc ─────────────────────────────────────────────────────────────────
    print("\n[ Misc ]")
    all_pass &= check(".env file exists", (ROOT / ".env").exists(), str(ROOT / ".env"))

    # WSL2 clock drift
    try:
        import subprocess
        result = subprocess.run(
            ["wsl.exe", "-e", "date"], capture_output=True, text=True, timeout=5
        )
        all_pass &= check("WSL2 clock accessible", result.returncode == 0)
    except Exception:
        print(f"  {WARN}  WSL2 interop not needed for trading")

    # RAM check
    try:
        import subprocess
        result = subprocess.run(["free", "-m"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            lines = result.stdout.strip().split("\n")
            if len(lines) > 1:
                mem_kb = int(lines[1].split()[6])
                mem_gb = mem_kb / 1024
                all_pass &= check("RAM >= 8GB available", mem_gb >= 8, f"{mem_gb:.0f} GB")
    except Exception:
        pass

    # ── Summary ─────────────────────────────────────────────────────────────
    print("\n" + "═" * 50)
    if all_pass:
        print(f"{PASS} ALL CHECKS PASSED — Ready to run!")
    else:
        print(f"{FAIL} SOME CHECKS FAILED — Fix issues above")
    print("═" * 50 + "\n")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(run())
