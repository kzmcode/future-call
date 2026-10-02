import numpy as np
import pytest
import soundfile as sf

from app.tts import VoiceContext
from app.tts_chatterbox import ChatterboxSynthesizer, _looks_valid

SR = 24000
TEXT = "もしもし、十年後のわたしだよ。"


def tone(sec, amp=0.2):
    t = np.arange(int(SR * sec)) / SR
    return (amp * np.sin(2 * np.pi * 200 * t)).astype(np.float32)


class Wav:
    def __init__(self, y):
        self.y = y

    def detach(self):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return self.y[None, :]


class FakeModel:
    sr = SR

    def __init__(self, outputs=None):
        self.outputs = list(outputs or [tone(2.0)])
        self.conds = None
        self.calls = []
        self.prepared = []

    def prepare_conditionals(self, path, exaggeration=0.5):
        self.prepared.append(path)
        self.conds = "CONDS:" + path

    def generate(self, text, **kw):
        self.calls.append((self.conds, kw))
        y = self.outputs.pop(0) if len(self.outputs) > 1 else self.outputs[0]
        return Wav(y)


def make(model, cfg=None):
    s = ChatterboxSynthesizer(cfg or {})
    s._model = model
    return s


def test_looks_valid():
    assert _looks_valid(tone(2.0), SR, TEXT)
    assert not _looks_valid(np.zeros(SR * 2, np.float32), SR, TEXT)   # 無音
    assert not _looks_valid(tone(0.1), SR, TEXT)                      # 短すぎ
    assert not _looks_valid(tone(40.0), SR, TEXT)                     # 長すぎ


def test_prepare_voice_clone_and_synthesize(tmp_path):
    ref = tmp_path / "ref.wav"
    sf.write(str(ref), tone(3.0), SR)
    m = FakeModel()
    s = make(m)
    ctx = s.prepare_voice(str(ref), str(tmp_path), 180.0)
    assert ctx.mode == "clone" and ctx.target_se == "CONDS:" + str(ref)
    m.conds = "OTHER"  # 他セッションが上書きしても ctx の conds で合成される
    out = tmp_path / "o.wav"
    s.synthesize(ctx, TEXT, str(out))
    assert m.calls[-1][0] == "CONDS:" + str(ref)
    assert m.calls[-1][1]["language_id"] == "ja"
    y, sr = sf.read(str(out))
    assert sr == SR and len(y) == 2 * SR


def test_no_reference_uses_default_voice(tmp_path):
    m = FakeModel()
    s = make(m)
    ctx = s.prepare_voice(None, str(tmp_path), None)
    assert ctx.mode == "standard" and m.prepared == []
    s.synthesize(ctx, TEXT, str(tmp_path / "o.wav"))
    assert (tmp_path / "o.wav").exists()


def test_retry_on_silence(tmp_path):
    m = FakeModel([np.zeros(SR, np.float32), tone(2.0)])
    s = make(m, {"chatterbox": {"max_retries": 2}})
    s.synthesize(VoiceContext(mode="standard"), TEXT, str(tmp_path / "o.wav"))
    assert len(m.calls) == 2


def test_gives_up_but_keeps_last_audio(tmp_path):
    m = FakeModel([tone(0.2)])
    s = make(m, {"chatterbox": {"max_retries": 1}})
    s.synthesize(VoiceContext(mode="standard"), TEXT, str(tmp_path / "o.wav"))
    assert len(m.calls) == 2 and (tmp_path / "o.wav").exists()


def test_empty_audio_raises(tmp_path):
    s = make(FakeModel([np.zeros(0, np.float32)]), {"chatterbox": {"max_retries": 0}})
    with pytest.raises(RuntimeError):
        s.synthesize(VoiceContext(mode="standard"), TEXT, str(tmp_path / "o.wav"))


def test_age_shift_applies_to_everyone():
    on = make(FakeModel(), {"age_voice_shift": {"enabled": True, "semitones": -1.0}})
    assert on._age_shift() == -1.0
    assert make(FakeModel())._age_shift() == 0.0
