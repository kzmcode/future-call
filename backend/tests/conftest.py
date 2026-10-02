import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from app.main import create_app


def make_wav(path, sec=25.0, sr=16000):
    t = np.arange(int(sec * sr)) / sr
    x = 0.3 * np.sin(2 * np.pi * 180 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 2 * t) ** 2)
    sf.write(str(path), x.astype(np.float32), sr, subtype="PCM_16")
    return path


def make_client(app):
    """CSRF 用ヘッダーと許可された Host 付きの TestClient。"""
    return TestClient(app, base_url="http://127.0.0.1:8000", headers={"X-Requested-With": "futurecall"})


def base_overrides(tmp_path, **extra):
    o = {
        "stt": {"engine": "mock"},
        "tts": {"engine": "mock"},
        "llm": {"engine": "template"},
        "pipeline": {"work_dir": str(tmp_path / "work"), "total_timeout_sec": 60},
        "logging": {"dir": str(tmp_path / "logs")},
    }
    for k, v in extra.items():
        o.setdefault(k, {}).update(v)
    return o


@pytest.fixture
def client(tmp_path):
    app = create_app(base_overrides(tmp_path))
    with make_client(app) as c:
        c.tmp_path = tmp_path
        yield c


@pytest.fixture
def wav25(tmp_path):
    return make_wav(tmp_path / "rec.wav", 25.0)
