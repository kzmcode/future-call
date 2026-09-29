import os
import shutil
import sys

import pytest

from app import tts
from app.tts import SpeechSynthesizer, VoiceContext


class FakeMelo:
    def __init__(self, fail=False):
        self.fail = fail

    def tts_to_file(self, text, spk, path, speed=1.0):
        if self.fail:
            raise RuntimeError("boom")
        with open(path, "wb") as f:
            f.write(b"base")


class FakeConv:
    def __init__(self, fail=False):
        self.fail = fail

    def extract_se(self, wavs):
        if self.fail:
            raise ValueError("bad")
        return "SE"

    def convert(self, audio_src_path, src_se, tgt_se, output_path, tau=0.3, message=""):
        if self.fail:
            raise RuntimeError("bad")
        with open(output_path, "wb") as f:
            f.write(b"conv")


def make(melo=None, conv=None, **cfg):
    s = SpeechSynthesizer(cfg)
    s._melo, s._converter, s._speaker_id, s._src_se = melo, conv, 0, "SRC"
    return s


def test_load_without_deps(monkeypatch):
    # melo が入っている環境でも「未インストール」を再現する
    monkeypatch.setitem(sys.modules, "melo", None)
    monkeypatch.setitem(sys.modules, "melo.api", None)
    with pytest.raises(ImportError):
        SpeechSynthesizer({}).load()


def test_prepare_standard_cases(tmp_path):
    s = SpeechSynthesizer({})
    assert s.prepare_voice(None, str(tmp_path), 200, False).mode == "standard"
    ref = tmp_path / "r.wav"
    ref.write_bytes(b"x")
    assert s.prepare_voice(str(ref), str(tmp_path), None, False).mode == "standard"


def test_prepare_clone_and_failure(tmp_path):
    ref = tmp_path / "r.wav"
    ref.write_bytes(b"x")
    assert make(FakeMelo(), FakeConv()).prepare_voice(str(ref), str(tmp_path), 120, False).mode == "clone"
    ctx = make(FakeMelo(), FakeConv(fail=True)).prepare_voice(str(ref), str(tmp_path), 110, False)
    assert ctx.mode == "standard" and ctx.pitch_semitones == -8.0


def test_melo_engine_always_standard(tmp_path):
    ref = tmp_path / "r.wav"
    ref.write_bytes(b"x")
    s = make(FakeMelo(), FakeConv(), engine="melo")
    assert s.prepare_voice(str(ref), str(tmp_path), None, False).mode == "standard"


def test_age_shift():
    s = SpeechSynthesizer({"age_voice_shift": {"enabled": True, "semitones": -1.5, "skip_if_child": True}})
    assert s.prepare_voice(None, "", None, False).age_semitones == -1.5
    assert s.prepare_voice(None, "", None, True).age_semitones == 0.0
    assert SpeechSynthesizer({}).prepare_voice(None, "", None, False).age_semitones == 0.0


def test_synthesize_clone_ok(tmp_path):
    out = str(tmp_path / "o.wav")
    make(FakeMelo(), FakeConv()).synthesize(VoiceContext("clone", target_se="SE"), "テスト", out)
    assert open(out, "rb").read() == b"conv"
    assert os.listdir(tmp_path) == ["o.wav"]


def test_synthesize_clone_falls_back(tmp_path):
    out = str(tmp_path / "o.wav")
    make(FakeMelo(), FakeConv(fail=True)).synthesize(VoiceContext("clone", target_se="SE"), "テスト", out)
    assert open(out, "rb").read() == b"base"


def test_synthesize_standard_failure_raises(tmp_path):
    out = str(tmp_path / "o.wav")
    with pytest.raises(RuntimeError):
        make(FakeMelo(fail=True), None).synthesize(VoiceContext("standard"), "x", out)
    assert os.listdir(tmp_path) == []


def test_pitch_shift_called(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(tts, "_pitch_shift_file", lambda p, st: calls.append(st))
    out = str(tmp_path / "o.wav")
    make(FakeMelo(), None).synthesize(
        VoiceContext("standard", pitch_semitones=-3.0, age_semitones=-1.0), "x", out)
    assert calls == [-3.0, -1.0]


# ---------------------------------------------------------------- gemini
import base64
import struct
import time
import wave as _wave


def _wav_bytes(n=2400):
    import io
    b = io.BytesIO()
    with _wave.open(b, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(struct.pack("<h", 100) * n)
    return b.getvalue()


class _Audio:
    def __init__(self, data, mime_type=""):
        self.data, self.mime_type = data, mime_type


class _Inter:
    def __init__(self, audio):
        self.output_audio = audio


class FakeGenai:
    def __init__(self, audio=None, exc=None, delay=0.0):
        self.calls = []
        self._audio, self._exc, self._delay = audio, exc, delay
        self.interactions = self

    def create(self, **kw):
        self.calls.append(kw)
        if self._delay:
            time.sleep(self._delay)
        if self._exc:
            raise self._exc
        a = self._audio if self._audio is not None else _Audio(
            base64.b64encode(_wav_bytes()).decode(), "audio/wav")
        return _Inter(a)


class ConvSE(FakeConv):
    def __init__(self):
        super().__init__()
        self.extracted = []
        self.converts = []
        self.taus = []

    def extract_se(self, wavs):
        self.extracted.append(wavs)
        return "GSE"

    def convert(self, audio_src_path, src_se, tgt_se, output_path, tau=0.3, message=""):
        self.taus.append(tau)
        self.converts.append((src_se, tgt_se, os.path.basename(audio_src_path)))
        with open(output_path, "wb") as f:
            f.write(b"conv")


GCFG = {"model": "m", "timeout_sec": 1, "voice_low": "Charon", "voice_high": "Kore",
        "voice_split_f0_hz": 165, "default_style": "default-style"}


def gmake(client, melo=None, conv=None, key="k", **extra):
    cfg = {"engine": "gemini_openvoice", "gemini": dict(GCFG), **extra}
    s = SpeechSynthesizer(cfg, api_key=key)
    s._melo, s._converter, s._speaker_id, s._src_se = melo or FakeMelo(), conv, 0, "SRC"
    s._gemini_client = client
    return s


def test_voice_selection_by_f0(tmp_path):
    s = gmake(None)
    d = str(tmp_path)
    assert s.prepare_voice(None, d, 120, False).voice_name == "Charon"
    assert s.prepare_voice(None, d, 220, False).voice_name == "Kore"
    assert s.prepare_voice(None, d, None, False).voice_name == "Kore"


def test_no_api_key_behaves_like_openvoice(tmp_path):
    s = gmake(None, key=None)
    assert s.prepare_voice(None, str(tmp_path), 120, False).voice_name is None
    out = str(tmp_path / "o.wav")
    s.synthesize(VoiceContext("standard"), "x", out)
    assert open(out, "rb").read() == b"base"


def test_gemini_standard_success_and_style(tmp_path):
    c = FakeGenai()
    s = gmake(c)
    out = str(tmp_path / "o.wav")
    s.synthesize(VoiceContext("standard", voice_name="Kore"), "秘密の本文", out, style="やさしく")
    with _wave.open(out) as w:
        assert w.getframerate() == 24000
    kw = c.calls[0]
    blk = kw["input"][0]["content"][0]
    assert blk["annotations"][0] == {"type": "speech_metadata", "style": "やさしく"}
    assert kw["generation_config"]["speech_config"] == [{"voice": "Kore"}]
    assert kw["response_format"] == {"type": "audio"}
    assert os.listdir(tmp_path) == ["o.wav"]


def test_gemini_default_style_used(tmp_path):
    c = FakeGenai()
    s = gmake(c)
    s.synthesize(VoiceContext("standard", voice_name="Kore"), "x", str(tmp_path / "o.wav"))
    assert c.calls[0]["input"][0]["content"][0]["annotations"][0]["style"] == "default-style"


def test_gemini_clone_converts_and_caches_se(tmp_path):
    conv = ConvSE()
    s = gmake(FakeGenai(), conv=conv)
    ctx = VoiceContext("clone", target_se="USER", voice_name="Charon")
    for i in range(2):
        out = str(tmp_path / f"o{i}.wav")
        s.synthesize(ctx, "x", out)
        assert open(out, "rb").read() == b"conv"
    assert len(conv.extracted) == 1
    assert conv.converts[0][:2] == ("GSE", "USER")
    assert conv.converts[1][:2] == ("GSE", "USER")
    assert sorted(os.listdir(tmp_path)) == ["o0.wav", "o1.wav"]


def test_gemini_raw_pcm_wrapped(tmp_path):
    raw = struct.pack("<h", 5) * 480
    c = FakeGenai(audio=_Audio(base64.b64encode(raw).decode(), "audio/l16;rate=24000"))
    out = str(tmp_path / "o.wav")
    gmake(c).synthesize(VoiceContext("standard", voice_name="Kore"), "x", out)
    with _wave.open(out) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()) == (1, 2, 24000, 480)


def test_gemini_timeout_falls_back_to_melo(tmp_path):
    s = gmake(FakeGenai(delay=1.5))
    s._gcfg["timeout_sec"] = 0.2
    out = str(tmp_path / "o.wav")
    s.synthesize(VoiceContext("standard", voice_name="Kore"), "x", out)
    assert open(out, "rb").read() == b"base"


def test_gemini_empty_audio_falls_back(tmp_path):
    s = gmake(FakeGenai(audio=_Audio("")))
    out = str(tmp_path / "o.wav")
    s.synthesize(VoiceContext("standard", voice_name="Kore"), "x", out)
    assert open(out, "rb").read() == b"base"


class Quota(Exception):
    code = 429


class PerModel(FakeGenai):
    """モデルごとに例外/遅延を返す偽クライアント。"""
    def __init__(self, excs=None, delays=None):
        super().__init__()
        self.excs, self.delays = dict(excs or {}), dict(delays or {})

    def create(self, **kw):
        m = kw["model"]
        self.calls.append(kw)
        if self.delays.get(m):
            time.sleep(self.delays[m])
        if self.excs.get(m):
            raise self.excs[m]
        return _Inter(_Audio(base64.b64encode(_wav_bytes()).decode(), "audio/wav"))

    def models(self):
        return [c["model"] for c in self.calls]


def cmake(client, conv=None, **g):
    s = gmake(client, conv=conv)
    s._gcfg.update({"model": "P", "fallback_models": ["L"], "timeout_sec": 30,
                    "quota_cooldown_sec": 300, **g})
    return s


def _run(s, tmp_path, n=1, ctx=None):
    ctx = ctx or VoiceContext("standard", voice_name="Kore")
    outs = []
    for i in range(n):
        out = str(tmp_path / f"o{len(list(tmp_path.iterdir()))}_{i}.wav")
        s.synthesize(ctx, "x", out)
        outs.append(open(out, "rb").read())
    return outs


def test_primary_quota_uses_fallback_and_skips_next_chunk(tmp_path):
    c = PerModel({"P": Quota("RESOURCE_EXHAUSTED")})
    s = cmake(c)
    outs = _run(s, tmp_path, 3)
    assert all(o != b"base" for o in outs)
    assert c.models() == ["P", "L", "L", "L"]  # P は 1 回だけ、以後は飛ばす


def test_src_se_cache_keyed_by_model(tmp_path):
    conv = ConvSE()
    c = PerModel({"P": Quota("RESOURCE_EXHAUSTED")})
    s = cmake(c, conv=conv)
    ctx = VoiceContext("clone", target_se="T", voice_name="Kore")
    _run(s, tmp_path, 2, ctx)           # L で 2 チャンク: 抽出は 1 回
    assert len(conv.extracted) == 1
    s._cooldown_until.clear()
    c.excs.clear()                      # P 復帰: P 用の src_se を別に抽出
    _run(s, tmp_path, 2, ctx)
    assert len(conv.extracted) == 2
    assert set(s._voice_se) == {("P", "Kore"), ("L", "Kore")}


def test_all_models_quota_then_melo_without_calls(tmp_path):
    c = PerModel({"P": Quota("RESOURCE_EXHAUSTED"), "L": Quota("RESOURCE_EXHAUSTED")})
    s = cmake(c)
    outs = _run(s, tmp_path, 3)
    assert outs == [b"base"] * 3
    assert c.models() == ["P", "L"]


def test_cooldown_expiry_reprobes_primary(tmp_path):
    c = PerModel({"P": Quota("RESOURCE_EXHAUSTED")})
    s = cmake(c)
    _run(s, tmp_path, 2)
    assert c.models() == ["P", "L", "L"]
    s._cooldown_until["P"] = time.monotonic() - 1
    c.excs.clear()
    _run(s, tmp_path)
    assert c.models() == ["P", "L", "L", "P"]


def test_perday_long_cooldown(tmp_path):
    c = PerModel({"P": Quota("quota exceeded ... GenerateRequestsPerDayPerProjectPerModel")})
    s = cmake(c, quota_cooldown_sec=10)
    _run(s, tmp_path)
    assert s._cooldown_until["P"] - time.monotonic() > 1700
    assert s._cooldown_until.get("L") is None


def test_404_remembered_for_process(tmp_path):
    class NF(Exception):
        code = 404

    c = PerModel({"P": NF("NOT_FOUND")})
    s = cmake(c)
    _run(s, tmp_path, 2)
    assert "P" in s._unavailable
    assert c.models() == ["P", "L", "L"]
    s._cooldown_until.clear()
    assert s._is_cooling("P")  # 期限とは無関係に飛ばし続ける


def test_503_not_remembered(tmp_path):
    class Unav(Exception):
        code = 503

    c = PerModel({"P": Unav("UNAVAILABLE")})
    s = cmake(c)
    _run(s, tmp_path, 2)
    assert c.models() == ["P", "L", "P", "L"]  # 毎回 P から試す
    assert not s._cooldown_until and not s._unavailable


def test_timeout_budget_not_multiplied(tmp_path):
    c = PerModel(delays={"P": 1.5, "L": 1.5})
    s = cmake(c, timeout_sec=0.3)
    t0 = time.monotonic()
    assert _run(s, tmp_path) == [b"base"]
    assert time.monotonic() - t0 < 1.0
    assert c.models() == ["P"]  # 予算切れ後は次のモデルを試さない


def test_fast_429_leaves_budget_for_fallback(tmp_path):
    c = PerModel({"P": Quota("RESOURCE_EXHAUSTED")}, delays={"L": 0.4})
    s = cmake(c, timeout_sec=0.3)  # 後続モデルは最低 8 秒の枠がある
    assert _run(s, tmp_path)[0] != b"base"


def test_logs_have_no_text(tmp_path, caplog):
    c = PerModel({"P": Quota("RESOURCE_EXHAUSTED")})
    s = cmake(c)
    ctx = VoiceContext("standard", voice_name="Kore")
    with caplog.at_level("DEBUG"):
        s.synthesize(ctx, "秘密の文章", str(tmp_path / "o.wav"), style="秘密の話し方")
    assert "秘密" not in caplog.text and "model=P" in caplog.text


def test_gemini_ok_after_convert_failure_uses_preset(tmp_path):
    conv = ConvSE()
    conv.convert = lambda **k: (_ for _ in ()).throw(RuntimeError("x"))
    s = gmake(FakeGenai(), conv=conv)
    out = str(tmp_path / "o.wav")
    s.synthesize(VoiceContext("clone", target_se="U", voice_name="Kore"), "x", out)
    with _wave.open(out) as w:
        assert w.getframerate() == 24000


def test_voice_table_nearest_f0(tmp_path):
    s = gmake(None)
    s._gcfg["voices"] = [{"name": "Lo", "f0_hz": 100}, {"name": "Mid", "f0_hz": 120},
                         {"name": "Hi", "f0_hz": 160}, {"name": "Top", "f0_hz": 230}]
    d = str(tmp_path)
    pick = lambda f0: s.prepare_voice(None, d, f0, False).voice_name
    assert pick(90) == "Lo" and pick(125) == "Mid" and pick(150) == "Hi"
    assert pick(250) == "Top" and pick(None) == "Top"   # unknown -> 200 Hz -> Top(230)


def test_tau_passed_to_converter(tmp_path):
    conv = ConvSE()
    s = gmake(FakeGenai(), conv=conv, tau=0.7)
    ctx = VoiceContext("clone", target_se="T", voice_name="Kore")
    s.synthesize(ctx, "テスト", str(tmp_path / "o.wav"))
    assert conv.taus == [0.7]
    conv2 = ConvSE()
    s2 = gmake(FakeGenai(), conv=conv2)
    s2.synthesize(ctx, "テスト", str(tmp_path / "o2.wav"))
    assert conv2.taus == [0.5]  # default


def test_build_converter_signature_fallback():
    """OpenVoice revisions whose base class rejects enable_watermark."""
    class Base:
        def __init__(self, config_path, device="cpu"):
            self.hps = type("H", (), {"_version_": "v2"})()
            self.device = device

    class Conv(Base):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)  # TypeError on enable_watermark
            self.watermark_model = "WM"  # must never be reached

    s = SpeechSynthesizer({})
    c = s._build_converter(Conv, "cfg.json")
    assert isinstance(c, Conv) and c.watermark_model is None and c.version == "v2"

    class Ok(Base):
        def __init__(self, cfg, device="cpu", enable_watermark=True):
            super().__init__(cfg, device=device)
            self.wm = enable_watermark

    assert s._build_converter(Ok, "cfg.json").wm is False


class HttpxFamilyQuota(Exception):
    """interactions API(httpx 系 APIStatusError)相当: code ではなく status_code だけを持つ。"""
    status_code = 429


def test_httpx_family_429_moves_on_immediately(tmp_path):
    c = PerModel({"P": HttpxFamilyQuota("Error code: 429 - RESOURCE_EXHAUSTED")})
    s = cmake(c)
    t0 = time.monotonic()
    outs = _run(s, tmp_path, 2)
    assert time.monotonic() - t0 < 2
    assert all(o != b"base" for o in outs)
    assert c.models() == ["P", "L", "L"]


def test_all_429_chain_overhead_small(tmp_path):
    c = PerModel({"P": HttpxFamilyQuota("x"), "L": Quota("RESOURCE_EXHAUSTED")})
    s = cmake(c)
    t0 = time.monotonic()
    assert _run(s, tmp_path)[0] == b"base"
    assert time.monotonic() - t0 < 2
    assert c.models() == ["P", "L"]


def test_permin_cooldown_uses_retry_delay():
    e = Quota("429 {'details': [{'retryDelay': '20s'}]} GenerateRequestsPerMinutePerProject")
    assert tts._quota_cooldown_sec(e, 300) == 30  # 20+2 → 最小 30
    e = Quota("{'retryDelay': '57s'}")
    assert tts._quota_cooldown_sec(e, 300) == 59
    assert tts._quota_cooldown_sec(Quota("RESOURCE_EXHAUSTED"), 300) == 300


def _sdk_client_with_429s(tmp_path):
    httpx = pytest.importorskip("httpx")
    pytest.importorskip("google.genai")
    body = {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "q", "details": [
        {"violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel"}]},
        {"retryDelay": "20s"}]}}
    hits = []

    def handler(req):
        hits.append(1)
        return httpx.Response(429, json=body, headers={"retry-after": "20"})

    from google import genai
    from google.genai import types
    ms = 25000
    client = genai.Client(api_key="x", http_options=types.HttpOptions(
        timeout=ms, retry_options=tts._retry_options(types),
        httpx_client=httpx.Client(transport=httpx.MockTransport(handler))))
    return client, hits


def test_real_sdk_interactions_429_not_retried(tmp_path):
    client, hits = _sdk_client_with_429s(tmp_path)
    s = cmake(client)
    t0 = time.monotonic()
    with pytest.raises(Exception) as ei:
        s._gemini_call("x", None, "Kore", "P")
    assert time.monotonic() - t0 < 2  # 既定だと retry-after(20s)を待つ
    assert len(hits) == 1
    assert tts._is_quota_error(ei.value)
    assert tts._quota_cooldown_sec(ei.value, 300) >= 1800


def test_get_client_disables_429_retry():
    pytest.importorskip("google.genai")
    s = cmake(None)
    s.api_key = "x"
    s._gemini_client = None
    c = s._get_client()
    ro = c._api_client._http_options.retry_options
    assert ro is not None and 429 not in ro.http_status_codes
    assert 503 not in ro.http_status_codes
