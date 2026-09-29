import os
import sys

import numpy as np
import pytest
import soundfile as sf

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.audio_prep import ReferenceInfo, normalize_input, prepare_reference  # noqa: E402

@pytest.fixture(autouse=True)
def _no_noisereduce(monkeypatch):
    # 合成音は定常ノイズ扱いで消されるため、任意依存の noisereduce は使わず
    # 内蔵の簡易スペクトルゲートで検証する(入っている環境でも結果を一定にする)。
    monkeypatch.setitem(sys.modules, "noisereduce", None)


CFG = {"max_sec": 30, "min_voiced_sec": 8, "denoise": True}


def voiced(sr, dur, f0=150.0, amp=0.3):
    t = np.arange(int(dur * sr)) / sr
    x = sum(np.sin(2 * np.pi * f0 * k * t) / k for k in range(1, 12))
    env = 0.6 + 0.4 * np.sin(2 * np.pi * 3 * t)
    return (amp * x / 2.5 * env).astype(np.float32)


def scene(sr, seconds_voiced, gaps=1.0, noise=0.003, f0=150.0, seed=0):
    rng = np.random.default_rng(seed)
    parts = [np.zeros(int(gaps * sr))]
    left = seconds_voiced
    while left > 0:
        d = min(2.0, left)
        parts += [voiced(sr, d, f0), np.zeros(int(gaps * sr))]
        left -= d
    x = np.concatenate(parts)
    return (x + noise * rng.standard_normal(x.size)).astype(np.float32)


def test_normalize_48k_stereo(tmp_path):
    sr = 48000
    m = voiced(sr, 2.5)
    st = np.stack([m, 0.5 * m], axis=1)
    src, dst = str(tmp_path / "in.wav"), str(tmp_path / "out.wav")
    sf.write(src, st, sr, subtype="PCM_16")
    dur = normalize_input(src, dst, 16000)
    assert abs(dur - 2.5) < 0.02
    data, r = sf.read(dst)
    assert r == 16000 and data.ndim == 1
    assert sf.info(dst).subtype == "PCM_16"
    assert abs(len(data) / r - dur) < 1e-6
    assert np.max(np.abs(data)) > 0.5


def test_normalize_garbage_raises(tmp_path):
    src = tmp_path / "bad.webm"
    src.write_bytes(b"not audio at all" * 10)
    with pytest.raises(Exception):
        normalize_input(str(src), str(tmp_path / "o.wav"))


def test_prepare_trims_silence_and_f0(tmp_path):
    sr = 24000
    x = scene(sr, 12.0, gaps=1.0, f0=150.0)
    p, o = str(tmp_path / "r.wav"), str(tmp_path / "ref.wav")
    sf.write(p, x, sr, subtype="PCM_16")
    info = prepare_reference(p, o, CFG)
    assert isinstance(info, ReferenceInfo)
    assert info.path == o and os.path.exists(o)
    assert 10.0 <= info.voiced_sec <= 14.5  # silence (~7s) removed
    assert info.ok
    assert info.median_f0_hz is not None
    assert abs(info.median_f0_hz - 150.0) / 150.0 < 0.10


def test_prepare_f0_other_pitch(tmp_path):
    sr = 16000
    x = scene(sr, 10.0, f0=220.0)
    p, o = str(tmp_path / "r.wav"), str(tmp_path / "ref.wav")
    sf.write(p, x, sr, subtype="PCM_16")
    info = prepare_reference(p, o, CFG)
    assert abs(info.median_f0_hz - 220.0) / 220.0 < 0.10


def test_prepare_respects_max_sec(tmp_path):
    sr = 16000
    x = scene(sr, 40.0)
    p, o = str(tmp_path / "r.wav"), str(tmp_path / "ref.wav")
    sf.write(p, x, sr, subtype="PCM_16")
    info = prepare_reference(p, o, {**CFG, "max_sec": 10})
    d = sf.info(o).duration
    assert d <= 10.05 and info.voiced_sec <= 10.05
    assert info.voiced_sec > 8


def test_prepare_ok_flag_short(tmp_path):
    sr = 16000
    x = scene(sr, 3.0)
    p, o = str(tmp_path / "r.wav"), str(tmp_path / "ref.wav")
    sf.write(p, x, sr, subtype="PCM_16")
    info = prepare_reference(p, o, CFG)
    assert not info.ok
    assert 2.0 < info.voiced_sec < 4.5
    info2 = prepare_reference(p, o, {**CFG, "min_voiced_sec": 2})
    assert info2.ok


def test_prepare_no_denoise(tmp_path):
    sr = 16000
    x = scene(sr, 9.0)
    p, o = str(tmp_path / "r.wav"), str(tmp_path / "ref.wav")
    sf.write(p, x, sr, subtype="PCM_16")
    info = prepare_reference(p, o, {**CFG, "denoise": False})
    assert info.ok


def test_prepare_never_raises(tmp_path):
    o = str(tmp_path / "ref.wav")
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"garbage")
    empty = tmp_path / "empty.wav"
    empty.write_bytes(b"")
    short = str(tmp_path / "short.wav")
    sf.write(short, np.random.randn(50).astype(np.float32) * 0.1, 16000)
    silent = str(tmp_path / "silent.wav")
    sf.write(silent, np.zeros(16000 * 3, dtype=np.float32), 16000)
    for pth in [str(bad), str(empty), str(tmp_path / "missing.wav"), short, silent]:
        info = prepare_reference(pth, o, CFG)
        assert isinstance(info, ReferenceInfo)
        assert not info.ok
    assert isinstance(prepare_reference(str(bad), o, {}), ReferenceInfo)
