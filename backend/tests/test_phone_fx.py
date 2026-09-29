import numpy as np
import soundfile as sf
from scipy import signal

from app.phone_fx import apply_phone_effect

CFG = {"enabled": True, "low_hz": 300, "high_hz": 3400, "noise_db": -45,
       "compress": True, "sample_rate": 16000}


def _band_energy(x, sr, lo, hi):
    f, p = signal.welch(x, sr, nperseg=2048)
    return p[(f >= lo) & (f < hi)].sum()


def _noise_wav(path, sr=24000, sec=2):
    rng = np.random.default_rng(0)
    sf.write(path, 0.3 * rng.standard_normal(sr * sec), sr)


def test_bandlimit_and_format(tmp_path):
    src, dst = str(tmp_path / "a.wav"), str(tmp_path / "b.wav")
    _noise_wav(src)
    apply_phone_effect(src, dst, CFG)
    info = sf.info(dst)
    assert (info.samplerate, info.channels, info.subtype) == (16000, 1, "PCM_16")
    assert abs(info.duration - 2.0) < 0.01
    y, sr = sf.read(dst)
    mid = _band_energy(y, sr, 500, 3000)
    assert _band_energy(y, sr, 0, 150) < mid * 0.05
    assert _band_energy(y, sr, 4200, 8000) < mid * 0.05
    assert 0.5 < np.max(np.abs(y)) <= 0.72


def test_disabled_only_converts(tmp_path):
    src, dst = str(tmp_path / "a.wav"), str(tmp_path / "b.wav")
    _noise_wav(src)
    apply_phone_effect(src, dst, {**CFG, "enabled": False})
    y, sr = sf.read(dst)
    assert sr == 16000 and y.ndim == 1
    assert _band_energy(y, sr, 4200, 8000) > _band_energy(y, sr, 500, 3000) * 0.1


def test_stereo_input(tmp_path):
    src, dst = str(tmp_path / "a.wav"), str(tmp_path / "b.wav")
    sf.write(src, np.random.default_rng(1).standard_normal((16000, 2)) * 0.1, 16000)
    apply_phone_effect(src, dst, CFG)
    assert sf.info(dst).channels == 1
