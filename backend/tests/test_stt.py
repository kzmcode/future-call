import importlib.util
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.stt import SpeechRecognizer  # noqa: E402

HAS_FW = importlib.util.find_spec("faster_whisper") is not None


def test_init_is_light():
    r = SpeechRecognizer({"model_size": "tiny"})
    assert r._model is None


@pytest.mark.skipif(HAS_FW, reason="faster_whisper installed")
def test_load_raises_clear_error_when_missing():
    r = SpeechRecognizer({})
    with pytest.raises(RuntimeError, match="faster-whisper"):
        r.load()


@pytest.mark.skipif(not HAS_FW, reason="faster_whisper not installed")
def test_real_transcribe_silence(tmp_path):
    import numpy as np
    import soundfile as sf

    p = str(tmp_path / "s.wav")
    sf.write(p, np.zeros(16000, dtype=np.float32), 16000)
    r = SpeechRecognizer({"model_size": "tiny", "compute_type": "int8", "beam_size": 1})
    r.load()
    assert isinstance(r.transcribe(p), str)
