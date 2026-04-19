"""
Kronos AI Signal Layer — wraps NeoQuasar/Kronos-base from HuggingFace.

Device  : cuda:0 (float16) → fallback to CPU on failure
Cache    : ~/GD_V1/gold-paper-trading/models/
Thread-safe via threading.Lock
Logs     : logs/kronos_signals.csv

Usage:
    k = KronosWrapper()
    signal = k.predict(df, horizon=5)
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

# WSL2 NOTE: set MPLBACKEND before any matplotlib import
os.environ.setdefault("MPLBACKEND", "Agg")

logger = logging.getLogger("kronos")

# ── Paths ──────────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
MODELS_DIR   = PROJECT_ROOT / "models"
LOGS_DIR     = PROJECT_ROOT / "logs"
CSV_LOG      = LOGS_DIR     / "kronos_signals.csv"

# ── torch setup (defer until needed) ──────────────────────────────────────────

_torch = None
_model = None
_tokenizer = None
_device: Optional[str] = None
_lock = threading.Lock()
_initialized = False
_init_error: Optional[str] = None

# ── Lazy torch import ─────────────────────────────────────────────────────────

def _get_torch():
    global _torch
    if _torch is None:
        import torch as _t
        _torch = _t
    return _torch


# ── Device resolution ──────────────────────────────────────────────────────────

def _resolve_device() -> tuple[str, bool]:
    """
    Returns (device_str, is_cuda).
    WSL2 NOTE: torch.cuda.is_available() checks nvidia-smi via WSL2 interop.
    """
    torch = _get_torch()
    if torch.cuda.is_available():
        return ("cuda:0", True)
    logger.warning("CUDA not available — falling back to CPU")
    return ("cpu", False)


# ── Model loading ──────────────────────────────────────────────────────────────

def _load_model():
    """
    Load NeoQuasar/Kronos-base (or Kronos-mini if base unavailable).
    Caches to MODELS_DIR. Uses float16 on CUDA.
    """
    global _model, _tokenizer, _device, _init_error

    torch = _get_torch()
    device, is_cuda = _resolve_device()
    _device = device

    # WSL2 NOTE: on WSL2, CUDA_VISIBLE_DEVICES must be set; check here
    if is_cuda:
        gpu_name = torch.cuda.get_device_name(0)
        vram_gb  = torch.cuda.get_device_properties(0).total_memory / 1e9
        logger.info(f"WSL2 GPU detected: {gpu_name} ({vram_gb:.1f} GB VRAM)")

    # Ensure cache dir
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    try:
        from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
    except ImportError as e:
        _init_error = f"transformers not installed: {e}"
        logger.error(_init_error)
        return False

    # Try kronos-base first, then fall back to kronos-mini
    model_names = ["NeoQuasar/Kronos-base", "NeoQuasar/Kronos-mini", "NeoQuasar/Kronos-small"]
    model_loaded = None

    for model_name in model_names:
        try:
            logger.info(f"Attempting to load {model_name} ...")
            tokenizer = AutoTokenizer.from_pretrained(
                model_name,
                cache_dir=str(MODELS_DIR),
            )
            model = AutoModelForSeq2SeqLM.from_pretrained(
                model_name,
                cache_dir=str(MODELS_DIR),
                torch_dtype=torch.float16 if is_cuda else torch.float32,
                low_cpu_mem_usage=True,
            )
            model.to(device)
            model.eval()
            _tokenizer = tokenizer
            _model = model
            logger.info(f"✅ Kronos model loaded: {model_name} on {device}")
            return True
        except Exception as e:
            logger.warning(f"  Failed to load {model_name}: {e}")
            continue

    _init_error = "Could not load any Kronos model from HuggingFace"
    logger.error(_init_error)
    return False


# ── Core class ─────────────────────────────────────────────────────────────────

class KronosWrapper:
    """
    Thread-safe Kronos inference wrapper.

    predict() is safe to call from multiple threads.
    Returns None if model is not loaded or inference fails.
    """

    def __init__(
        self,
        model_name: str = "NeoQuasar/Kronos-base",
        horizon: int = 5,
        bearish_threshold: float = 0.003,
    ):
        self.model_name = model_name
        self.horizon = horizon
        self.bearish_threshold = bearish_threshold

        self._lock = threading.Lock()
        self._enabled = True

        with _lock:
            global _initialized  # declare before read
            if not _initialized:
                ok = _load_model()
                _initialized = True
                if not ok:
                    logger.error("KronosWrapper init failed — predict() will return None")

    @property
    def is_loaded(self) -> bool:
        return _model is not None and _tokenizer is not None

    @property
    def device(self) -> Optional[str]:
        return _device

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool):
        self._enabled = bool(value)
        logger.info(f"Kronos {'enabled' if self._enabled else 'disabled'}")

    # ── predict ──────────────────────────────────────────────────────────────

    def predict(self, df: pd.DataFrame, horizon: int = None) -> Optional[dict]:
        """
        Run Kronos inference on the last 512 bars of df.

        Parameters
        ----------
        df : pd.DataFrame
            Must have columns: open, high, low, close, volume (last 512 rows)
        horizon : int, default=self.horizon
            Bars ahead to forecast

        Returns
        -------
        dict or None:
            {
                "direction":   "bullish" | "bearish" | "neutral",
                "confidence":  float,       # 0.0–1.0
                "predicted_close": float,  # price N bars ahead
                "volatility_high": bool,
                "raw_forecast": np.ndarray  # raw predicted returns per bar
            }
        Returns None on any failure.
        """
        if not self._enabled:
            return None

        if not self.is_loaded:
            return None

        if horizon is None:
            horizon = self.horizon

        with self._lock:
            return self._predict_impl(df, horizon)

    def _predict_impl(self, df: pd.DataFrame, horizon: int) -> Optional[dict]:
        try:
            torch = _get_torch()

            # ── Prepare input ─────────────────────────────────────────────────
            df = df.tail(512).copy()
            if len(df) < 50:
                return None

            close_prices = df["close"].values.astype(np.float32)
            high_prices  = df["high"].values.astype(np.float32)
            low_prices   = df["low"].values.astype(np.float32)
            volume_arr   = df["volume"].values.astype(np.float32)

            # Normalise to 0–1 per column (min-max)
            def _norm(arr):
                mn, mx = arr.min(), arr.max()
                if mx == mn:
                    return np.zeros_like(arr, dtype=np.float32)
                return (arr - mn) / (mx - mn)

            seq = np.stack([
                _norm(close_prices),
                _norm(high_prices),
                _norm(low_prices),
                _norm(volume_arr),
            ], axis=-1)  # (T, 4)

            # Build prompt in the style Kronos expects
            # Format: "asset|t1,t2,...,tN" where ti = "o,h,l,c,v"
            def _row_str(row):
                return f"{row[0]:.4f},{row[1]:.4f},{row[2]:.4f},{row[3]:.4f}"

            seq_str = ";".join(_row_str(r) for r in seq[-100:])  # last 100 bars

            prompt = f"XAUUSD|{seq_str}"

            # ── Tokenise ─────────────────────────────────────────────────────
            inputs = _tokenizer(
                prompt,
                return_tensors="pt",
                truncation=True,
                max_length=512,
            )
            inputs = {k: v.to(_device) for k, v in inputs.items()}

            # ── Generate ─────────────────────────────────────────────────────
            with torch.no_grad():
                output_ids = _model.generate(
                    **inputs,
                    max_new_tokens=horizon,
                    do_sample=False,
                    num_beams=1,
                )

            generated = _tokenizer.decode(output_ids[0], skip_special_tokens=True)

            # ── Parse output ─────────────────────────────────────────────────
            # Kronos outputs: "up|conf|vol|price1,price2,..."
            # or similar tabular format — parse robustly
            parts = generated.strip().split("|")
            direction_str = parts[0].lower().strip() if parts else "neutral"

            if "up" in direction_str or "bull" in direction_str:
                direction = "bullish"
            elif "down" in direction_str or "bear" in direction_str:
                direction = "bearish"
            else:
                direction = "neutral"

            # Parse confidence (second field or last field)
            confidence = 0.5
            if len(parts) > 1:
                try:
                    confidence = float(parts[1].strip())
                    confidence = max(0.0, min(1.0, confidence))
                except ValueError:
                    pass

            # Parse predicted returns / prices (last field)
            raw_forecast = np.zeros(horizon, dtype=np.float32)
            predicted_close = float(close_prices[-1])

            if len(parts) >= 3:
                try:
                    price_vals = [float(x) for x in parts[-1].replace(",", " ").split() if x]
                    for i, pv in enumerate(price_vals[:horizon]):
                        raw_forecast[i] = pv
                        predicted_close = pv
                except ValueError:
                    pass

            # If forecast values are normalised, denormalise
            if raw_forecast.max() <= 1.0 and raw_forecast.min() >= 0.0:
                raw_forecast = raw_forecast * (close_prices.max() - close_prices.min()) + close_prices.min()

            # Volatility: compare ATR of last 14 bars vs prior 14
            try:
                from strategy_helpers import atr_np
                recent_atr  = atr_np(high_prices[-28:], low_prices[-28:], close_prices[-28:], 14)
                prior_atr  = atr_np(high_prices[-42:-14], low_prices[-42:-14], close_prices[-42:-14], 14)
                vol_high = bool(recent_atr[-1] > prior_atr[-1] * 1.15) if len(recent_atr) and len(prior_atr) else False
            except Exception:
                vol_high = False

            # Confidence derived from spread of forecast if parsing failed
            if confidence == 0.5 and horizon > 0:
                price_changes = np.diff(raw_forecast) if raw_forecast[-1] != 0 else np.zeros(horizon - 1)
                if len(price_changes):
                    conf_pct = abs(price_changes.mean()) / (close_prices.std() + 1e-8)
                    confidence = max(0.0, min(1.0, conf_pct))

            result = {
                "direction":       direction,
                "confidence":      float(confidence),
                "predicted_close": float(predicted_close),
                "volatility_high": bool(vol_high),
                "raw_forecast":    raw_forecast,
            }

            # ── Log to CSV ───────────────────────────────────────────────────
            self._log_signal(result)
            return result

        except Exception as e:
            logger.debug(f"Kronos predict error: {e}")
            return None

    # ── CSV logging ──────────────────────────────────────────────────────────

    def _log_signal(self, signal: dict):
        """Append one prediction to logs/kronos_signals.csv (thread-safe)."""
        try:
            LOGS_DIR.mkdir(parents=True, exist_ok=True)
            import csv

            row = {
                "timestamp":       pd.Timestamp.now().isoformat(),
                "direction":       signal.get("direction", ""),
                "confidence":      signal.get("confidence", 0),
                "predicted_close": signal.get("predicted_close", 0),
                "volatility_high": int(signal.get("volatility_high", False)),
            }

            file_exists = CSV_LOG.exists()
            with open(CSV_LOG, "a", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=row.keys())
                if not file_exists:
                    writer.writeheader()
                writer.writerow(row)
        except Exception as e:
            logger.debug(f"Failed to log Kronos signal: {e}")


# ── Singleton accessor ──────────────────────────────────────────────────────────

_kronos_instance: Optional[KronosWrapper] = None


def get_kronos(
    model_name: str   = "NeoQuasar/Kronos-base",
    horizon: int      = 5,
    bearish_threshold: float = 0.003,
) -> KronosWrapper:
    """Thread-safe singleton accessor."""
    global _kronos_instance
    if _kronos_instance is None:
        with _lock:
            if _kronos_instance is None:
                _kronos_instance = KronosWrapper(
                    model_name=model_name,
                    horizon=horizon,
                    bearish_threshold=bearish_threshold,
                )
    return _kronos_instance


# ── Convenience: check if CUDA is usable ───────────────────────────────────────

def check_cuda_status() -> dict:
    """Return CUDA status dict for API / status endpoint."""
    torch = _get_torch()
    available = torch.cuda.is_available()
    gpu_name  = torch.cuda.get_device_name(0) if available else None
    vram_gb   = torch.cuda.get_device_properties(0).total_memory / 1e9 if available else 0

    return {
        "cuda_available": available,
        "device":         _device,
        "gpu_name":       gpu_name,
        "vram_gb":        round(vram_gb, 2),
        "model_loaded":   _model is not None,
        "model_name":    getattr(_model, "name_or_path", None) if _model else None,
        "init_error":    _init_error,
    }
