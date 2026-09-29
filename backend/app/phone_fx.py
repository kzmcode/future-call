"""Telephone-line effect (numpy/scipy only). See docs/architecture.md §3.4."""
from __future__ import annotations

import numpy as np
import soundfile as sf
from scipy import signal


def _to_mono(x: np.ndarray) -> np.ndarray:
    return x.mean(axis=1) if x.ndim > 1 else x


def _resample(x: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    if sr_in == sr_out or len(x) == 0:
        return x
    from math import gcd

    g = gcd(int(sr_in), int(sr_out))
    return signal.resample_poly(x, sr_out // g, sr_in // g)


def _normalize(x: np.ndarray, peak_db: float = -3.0) -> np.ndarray:
    peak = float(np.max(np.abs(x))) if len(x) else 0.0
    if peak < 1e-9:
        return x
    return x * (10 ** (peak_db / 20.0) / peak)


def _compress(x: np.ndarray, threshold_db: float = -18.0, ratio: float = 3.0,
              knee_db: float = 12.0) -> np.ndarray:
    """Static soft-knee compressor (sample-wise gain computer) with makeup gain."""
    eps = 1e-9
    level_db = 20 * np.log10(np.abs(x) + eps)
    over = level_db - threshold_db
    slope = 1.0 / ratio - 1.0
    gain_db = np.where(
        over <= -knee_db / 2, 0.0,
        np.where(over >= knee_db / 2, slope * over,
                 slope * (over + knee_db / 2) ** 2 / (2 * knee_db)))
    # smooth gain to avoid distortion from sample-wise gain changes
    return x * (10 ** (gain_db / 20.0))


def apply_phone_effect(in_wav: str, out_wav: str, cfg: dict) -> None:
    sr = int(cfg.get("sample_rate", 16000))
    data, sr_in = sf.read(in_wav, dtype="float64", always_2d=False)
    x = _resample(_to_mono(np.asarray(data)), int(sr_in), sr)

    if cfg.get("enabled", True) and len(x) > 0:
        low = float(cfg.get("low_hz", 300))
        high = min(float(cfg.get("high_hz", 3400)), sr / 2 * 0.95)
        sos = signal.butter(4, [low, high], btype="bandpass", fs=sr, output="sos")
        pad = min(len(x) - 1, 3 * sr // 10) if len(x) > 1 else 0
        x = signal.sosfiltfilt(sos, x, padlen=max(pad, 0)) if len(x) > 12 else x
        x = _normalize(x, -6.0)
        if cfg.get("compress", True):
            x = _compress(x)
            x = _normalize(x, -6.0)
        x = np.tanh(1.4 * x) / np.tanh(1.4)  # light saturation
        noise_db = cfg.get("noise_db", -45)
        if noise_db is not None and noise_db > -120:
            rng = np.random.default_rng()
            n = rng.standard_normal(len(x))
            n = signal.sosfiltfilt(sos, n) if len(n) > 12 else n
            n *= 10 ** (float(noise_db) / 20.0) / (float(np.sqrt(np.mean(n ** 2))) + 1e-12)
            x = x + n

    x = _normalize(x, -3.0)
    x = np.clip(x, -1.0, 1.0)
    sf.write(out_wav, x, sr, subtype="PCM_16", format="WAV")
