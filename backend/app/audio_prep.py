"""入力音声の正規化・参照音声の前処理・F0推定 (architecture.md §3.1).

内容(音声データ・認識結果)はログに出さない。数値と例外クラス名のみ。
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from math import gcd

import numpy as np
import soundfile as sf
from scipy import signal

log = logging.getLogger(__name__)


@dataclass
class ReferenceInfo:
    path: str | None
    voiced_sec: float
    median_f0_hz: float | None
    ok: bool


# ---------------------------------------------------------------- helpers

def _to_mono(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float32)
    if x.ndim == 2:
        x = x.mean(axis=1)
    return np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)


def _resample(x: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    if sr_in == sr_out or x.size == 0:
        return x
    g = gcd(int(sr_in), int(sr_out))
    return signal.resample_poly(x, sr_out // g, sr_in // g).astype(np.float32)


def _read_with_av(path: str) -> tuple[np.ndarray, int]:
    import av  # lazy, optional

    chunks = []
    with av.open(path) as container:
        stream = next(s for s in container.streams if s.type == "audio")
        sr = int(stream.rate or 48000)
        resampler = av.AudioResampler(format="flt", layout="mono", rate=sr)
        for frame in container.decode(stream):
            for f in resampler.resample(frame):
                chunks.append(f.to_ndarray().reshape(-1))
    if not chunks:
        raise ValueError("no audio decoded")
    return np.concatenate(chunks).astype(np.float32), sr


def _read_with_ffmpeg(path: str) -> tuple[np.ndarray, int]:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("ffmpeg not available")
    fd, tmp = tempfile.mkstemp(suffix=".wav", dir=os.path.dirname(os.path.abspath(path)))
    os.close(fd)
    try:
        subprocess.run(
            [exe, "-y", "-loglevel", "error", "-i", path, "-ac", "1", "-f", "wav", tmp],
            check=True, timeout=60, capture_output=True,
        )
        data, sr = sf.read(tmp, dtype="float32", always_2d=False)
        return _to_mono(data), int(sr)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _read_audio(path: str) -> tuple[np.ndarray, int]:
    try:
        data, sr = sf.read(path, dtype="float32", always_2d=False)
        return _to_mono(data), int(sr)
    except Exception as e_sf:  # webm/ogg-opus etc.
        log.info("soundfile could not read input (%s); trying fallbacks", type(e_sf).__name__)
    try:
        data, sr = _read_with_av(path)
        return _to_mono(data), sr
    except Exception as e_av:
        log.info("PyAV fallback failed (%s)", type(e_av).__name__)
    data, sr = _read_with_ffmpeg(path)  # raises on failure
    return data, sr


def _write_wav(path: str, x: np.ndarray, sr: int) -> None:
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    sf.write(path, np.clip(x, -1.0, 1.0), sr, subtype="PCM_16", format="WAV")


# ---------------------------------------------------------------- normalize_input

def normalize_input(src_path: str, dst_wav_path: str, sample_rate: int = 16000) -> float:
    """任意形式の入力をモノラル 16bit WAV に変換。長さ(秒)を返す。失敗時は例外。"""
    x, sr = _read_audio(src_path)
    if x.size == 0 or sr <= 0:
        raise ValueError("empty audio")
    x = _resample(x, sr, sample_rate)
    peak = float(np.max(np.abs(x))) if x.size else 0.0
    if peak > 1e-4:
        # gentle: raise quiet input up to 0.9 peak (max +18 dB); tame clipping
        x = x * min(0.9 / peak, 8.0)
    _write_wav(dst_wav_path, x, sample_rate)
    return float(x.size) / float(sample_rate)


# ---------------------------------------------------------------- reference prep

def _highpass(x: np.ndarray, sr: int, fc: float = 80.0) -> np.ndarray:
    sos = signal.butter(4, fc / (sr / 2.0), btype="highpass", output="sos")
    if x.size > 64:
        try:
            return signal.sosfiltfilt(sos, x).astype(np.float32)
        except ValueError:
            pass
    return signal.sosfilt(sos, x).astype(np.float32)


def _spectral_gate(x: np.ndarray, sr: int) -> np.ndarray:
    """Simple spectral subtraction; noise profile from the quietest frames."""
    try:
        import noisereduce as nr  # optional

        return nr.reduce_noise(y=x, sr=sr, stationary=False).astype(np.float32)
    except Exception:
        pass
    nper = 512
    if x.size < nper * 2:
        return x
    f, t, Z = signal.stft(x, fs=sr, nperseg=nper, noverlap=nper * 3 // 4)
    mag = np.abs(Z)
    frame_e = mag.sum(axis=0)
    k = max(3, int(0.1 * frame_e.size))
    quiet = np.argsort(frame_e)[:k]
    noise = mag[:, quiet].mean(axis=1, keepdims=True)
    gain = np.maximum(1.0 - 1.5 * noise / (mag + 1e-10), 0.1)
    gain = signal.convolve2d(gain, np.ones((1, 3)) / 3.0, mode="same", boundary="symm")
    _, y = signal.istft(Z * gain, fs=sr, nperseg=nper, noverlap=nper * 3 // 4)
    y = y[: x.size]
    if y.size < x.size:
        y = np.pad(y, (0, x.size - y.size))
    return y.astype(np.float32)


def _frame_db(x: np.ndarray, flen: int, hop: int) -> np.ndarray:
    n = 1 + max(0, (x.size - flen) // hop)
    idx = np.arange(flen)[None, :] + hop * np.arange(n)[:, None]
    fr = x[np.minimum(idx, x.size - 1)]
    rms = np.sqrt(np.mean(fr ** 2, axis=1) + 1e-12)
    return 20.0 * np.log10(rms + 1e-9)


def _vad_segments(x: np.ndarray, sr: int, seg_max_sec: float = 5.0):
    """Return (segments[(start,end) samples], noise_floor_db, frame_db, hop)."""
    flen, hop = int(0.025 * sr), int(0.010 * sr)
    db = _frame_db(x, flen, hop)
    floor = float(np.percentile(db, 10))
    thr = max(floor + 9.0, float(db.max()) - 35.0)
    active = db > thr
    # close short gaps (<150 ms), drop short blips (<200 ms)
    segs: list[list[int]] = []
    i, n = 0, active.size
    while i < n:
        if active[i]:
            j = i
            while j < n and active[j]:
                j += 1
            if segs and i - segs[-1][1] <= 15:
                segs[-1][1] = j
            else:
                segs.append([i, j])
            i = j
        else:
            i += 1
    out = []
    maxf = int(seg_max_sec * 100)
    for a, b in segs:
        if b - a < 20:
            continue
        while b - a > maxf * 1.5:  # split long ones
            out.append((a, a + maxf))
            a += maxf
        out.append((a, b))
    pad = int(0.03 * sr)
    res = [(max(0, a * hop - pad), min(x.size, b * hop + flen + pad)) for a, b in out]
    return res, floor, db, hop


def _yin_f0(x: np.ndarray, sr: int, fmin=70.0, fmax=500.0, thresh=0.15) -> float | None:
    """Median F0 over frames that look voiced; None if not estimable."""
    if sr > 16000:
        x = _resample(x, sr, 16000)
        sr = 16000
    flen, hop = int(0.04 * sr), int(0.02 * sr)
    tmin, tmax = int(sr / fmax), int(sr / fmin)
    if x.size < flen + tmax:
        return None
    db = _frame_db(x, flen, hop)
    gate = float(db.max()) - 25.0
    f0s = []
    W = flen
    for k, start in enumerate(range(0, x.size - (W + tmax) + 1, hop)):
        if k >= db.size or db[k] < gate:
            continue
        fr = x[start:start + W + tmax].astype(np.float64)
        fr = fr - fr.mean()
        # difference function d(tau)=sum_j (x[j]-x[j+tau])^2 via FFT cross-correlation
        n = fr.size
        nfft = 1 << (2 * n - 1).bit_length()
        cc = np.fft.irfft(np.fft.rfft(fr, nfft) * np.conj(np.fft.rfft(fr[:W], nfft)), nfft)
        taus = np.arange(tmax + 1)
        cs = np.concatenate(([0.0], np.cumsum(fr ** 2)))
        e1 = cs[W] - cs[0]
        e2 = cs[W + taus] - cs[taus]
        d = e1 + e2 - 2.0 * cc[taus]
        d[0] = 0.0
        cm = np.ones_like(d)
        run = np.cumsum(d[1:])
        cm[1:] = d[1:] * taus[1:] / (run + 1e-12)
        cand = np.where(cm[tmin:tmax] < thresh)[0]
        if cand.size == 0:
            continue
        t = tmin + int(cand[0])
        while t + 1 < tmax and cm[t + 1] < cm[t]:
            t += 1
        if 1 <= t < tmax:  # parabolic interpolation
            a, b, c = cm[t - 1], cm[t], cm[t + 1]
            den = a - 2 * b + c
            if abs(den) > 1e-12:
                t = t + 0.5 * (a - c) / den
        f0s.append(sr / float(t))
    if len(f0s) < 3:
        return None
    return float(np.median(f0s))


def _concat_crossfade(parts: list[np.ndarray], sr: int, fade_sec: float = 0.02) -> np.ndarray:
    if not parts:
        return np.zeros(0, dtype=np.float32)
    out = parts[0]
    for p in parts[1:]:
        nf = min(int(fade_sec * sr), out.size, p.size)
        if nf > 0:
            ramp = np.linspace(0.0, 1.0, nf, dtype=np.float32)
            mix = out[-nf:] * (1 - ramp) + p[:nf] * ramp
            out = np.concatenate([out[:-nf], mix, p[nf:]])
        else:
            out = np.concatenate([out, p])
    return out


def prepare_reference(wav_path: str, out_path: str, cfg: dict) -> ReferenceInfo:
    """参照音声の前処理。決して例外を投げない。"""
    try:
        max_sec = float(cfg.get("max_sec", 30))
        min_voiced = float(cfg.get("min_voiced_sec", 8))
        x, sr = _read_audio(wav_path)
        if x.size < int(0.3 * sr) or sr <= 0:
            return ReferenceInfo(None, 0.0, None, False)
        if sr > 24000:
            x = _resample(x, sr, 24000)
            sr = 24000
        x = _highpass(x, sr)
        if cfg.get("denoise", False):
            x = _spectral_gate(x, sr)

        segs, floor, db, hop = _vad_segments(x, sr)
        if not segs:
            return ReferenceInfo(None, 0.0, None, False)

        def snr(s):
            a, b = s
            seg = x[a:b]
            return 20.0 * np.log10(np.sqrt(np.mean(seg ** 2) + 1e-12) + 1e-9) - floor

        chosen, total = [], 0.0
        for s in sorted(segs, key=snr, reverse=True):
            dur = (s[1] - s[0]) / sr
            if total + dur > max_sec:
                remain = max_sec - total
                if remain >= 1.0:
                    s = (s[0], s[0] + int(remain * sr))
                    dur = remain
                else:
                    continue
            chosen.append(s)
            total += dur
            if total >= max_sec - 1e-6:
                break
        if not chosen:
            return ReferenceInfo(None, 0.0, None, False)
        chosen.sort()
        y = _concat_crossfade([x[a:b] for a, b in chosen], sr)
        y = y[: int(max_sec * sr)]
        peak = float(np.max(np.abs(y)))
        if peak > 1e-4:
            y = y * (0.9 / peak)
        voiced_sec = float(y.size) / sr
        f0 = _yin_f0(y, sr)
        _write_wav(out_path, y, sr)
        return ReferenceInfo(out_path, voiced_sec, f0, voiced_sec >= min_voiced)
    except Exception as e:  # never raise
        log.warning("prepare_reference failed: %s", type(e).__name__)
        return ReferenceInfo(None, 0.0, None, False)
