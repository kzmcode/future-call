import contextlib
import time

from fastapi.testclient import TestClient

from app.main import create_app
from conftest import base_overrides, make_wav
from test_api import poll, upload, wait_health


@contextlib.contextmanager
def run(tmp_path, wav, patch=None, **extra):
    app = create_app(base_overrides(tmp_path, **extra))
    with TestClient(app) as c:
        wait_health(c)
        if patch:
            patch(app)
        sid = c.post("/api/sessions").json()["session_id"]
        upload(c, sid, wav)
        yield app, c, sid


class FakePart:
    def __init__(self, text, sentences, wait):
        self.text, self.sentences, self.wait_for_reply = text, sentences, wait


class FakeResult:
    source = "fake"

    def __init__(self, parts, style="やさしく"):
        self.parts, self.style = parts, style
        self.sentences = [x for p in parts for x in p.sentences]
        self.text = "".join(self.sentences)


def fake_story(monkeypatch, parts=None):
    from app import story
    parts = parts or [FakePart("ねえ、覚えてる？", ["ねえ、覚えてる？"], True),
                      FakePart("うん。そうだよね。ありがとう。", ["うん。", "そうだよね。", "ありがとう。"], False)]

    class Gen:
        def __init__(self, *a, **k):
            pass

        def generate(self, transcript):
            return FakeResult(parts)

    monkeypatch.setattr(story, "StoryGenerator", Gen)


def test_part_mode_chunks_and_wait(tmp_path, monkeypatch):
    fake_story(monkeypatch)
    styles = []

    def patch(app):
        real = app.state.engines.tts.synthesize

        def spy(ctx, text, out, style=None):
            styles.append(style)
            return real(ctx, text, out, style=style)
        app.state.engines.tts.synthesize = spy

    wav = make_wav(tmp_path / "r.wav")
    with run(tmp_path, wav, patch, tts={"chunk_unit": "part"}) as (app, c, sid):
        st = poll(c, sid, lambda s: s["phase"] == "ready")
        assert st["chunks_ready"] >= 1 and st["playback"] == "audio"  # 最初のチャンクで ready
        st = poll(c, sid, lambda s: s["all_done"])
        assert st["chunks_total"] == 2 and st["chunks_ready"] == 2
        assert st["wait_after"] == [0]
    assert styles == ["やさしく", "やさしく"]


def test_sentence_mode_wait_after_is_last_sentence_of_wait_part(tmp_path, monkeypatch):
    fake_story(monkeypatch)
    wav = make_wav(tmp_path / "r.wav")
    with run(tmp_path, wav, tts={"chunk_unit": "sentence"}) as (app, c, sid):
        st = poll(c, sid, lambda s: s["all_done"])
        assert st["chunks_total"] == 4 and st["wait_after"] == [0]


def test_sentence_mode_wait_in_middle(tmp_path, monkeypatch):
    fake_story(monkeypatch, [FakePart("あ。い。", ["あ。", "い。"], True), FakePart("う。", ["う。"], False)])
    wav = make_wav(tmp_path / "r.wav")
    with run(tmp_path, wav, tts={"chunk_unit": "sentence"}) as (app, c, sid):
        st = poll(c, sid, lambda s: s["all_done"])
        assert st["chunks_total"] == 3 and st["wait_after"] == [1]


def test_browser_tts_wait_after_uses_sentence_index(tmp_path, monkeypatch):
    fake_story(monkeypatch, [FakePart("あ。い。", ["あ。", "い。"], True), FakePart("う。", ["う。"], False)])
    wav = make_wav(tmp_path / "r.wav")
    with run(tmp_path, wav, patch=lambda a: a.state.engines.state.update(tts="unavailable")) as (app, c, sid):
        st = poll(c, sid, lambda s: s["phase"] == "ready")
        assert st["playback"] == "browser_tts" and st["sentences"] == ["あ。", "い。", "う。"]
        assert st["wait_after"] == [1]


def test_failed_chunk_renumbering_keeps_wait_valid(tmp_path, monkeypatch):
    parts = [FakePart("あ。い。", ["あ。", "い。"], True), FakePart("う。え。", ["う。", "え。"], False)]
    fake_story(monkeypatch, parts)

    def patch(app):
        real = app.state.engines.tts.synthesize

        def flaky(ctx, text, out, style=None):
            if text == "い。":  # 待ちパートの最後のチャンクが失敗
                raise RuntimeError("x")
            return real(ctx, text, out, style=style)
        app.state.engines.tts.synthesize = flaky

    wav = make_wav(tmp_path / "r.wav")
    with run(tmp_path, wav, patch, tts={"chunk_unit": "sentence"}) as (app, c, sid):
        st = poll(c, sid, lambda s: s["all_done"])
        assert st["chunks_total"] == 3 and st["wait_after"] == [0]  # 「あ。」に付け替え


def test_failed_wait_part_entirely_dropped(tmp_path, monkeypatch):
    fake_story(monkeypatch)

    def patch(app):
        real = app.state.engines.tts.synthesize

        def flaky(ctx, text, out, style=None):
            if text == "ねえ、覚えてる？":
                raise RuntimeError("x")
            return real(ctx, text, out, style=style)
        app.state.engines.tts.synthesize = flaky

    wav = make_wav(tmp_path / "r.wav")
    with run(tmp_path, wav, patch, tts={"chunk_unit": "part"}) as (app, c, sid):
        st = poll(c, sid, lambda s: s["all_done"])
        assert st["chunks_total"] == 1 and st["wait_after"] == []


def test_story_without_parts_attr(tmp_path, monkeypatch):
    from app import story

    class R:
        sentences = ["あ。", "い。"]
        text = "あ。い。"
        source = "x"

    class Gen:
        def __init__(self, *a, **k):
            pass

        def generate(self, t):
            return R()

    monkeypatch.setattr(story, "StoryGenerator", Gen)
    wav = make_wav(tmp_path / "r.wav")
    with run(tmp_path, wav, tts={"chunk_unit": "sentence"}) as (app, c, sid):
        st = poll(c, sid, lambda s: s["all_done"])
        assert st["chunks_total"] == 2 and st["wait_after"] == []


def test_api_key_fallback_for_old_constructor(monkeypatch):
    import importlib
    from app.config import load_config
    from app.pipeline import Engines
    cfg = load_config(overrides={"tts": {"engine": "gemini_openvoice"}})
    seen = {}

    class Old:
        def __init__(self, c):
            seen["ok"] = True

    class New:
        def __init__(self, c, api_key=None):
            seen["key"] = api_key

    real = importlib.import_module
    for cls in (Old, New):
        monkeypatch.setattr(importlib, "import_module",
                            lambda n, p=None, cls=cls: type("M", (), {"SpeechSynthesizer": cls}) if n == ".tts" else real(n, p))
        monkeypatch.setenv("GEMINI_API_KEY", "k123")
        Engines(cfg)._make("tts")
    assert seen == {"ok": True, "key": "k123"}


def test_browser_tts_when_tts_unavailable(tmp_path):
    wav = make_wav(tmp_path / "r.wav")
    with run(tmp_path, wav, patch=lambda a: a.state.engines.state.update(tts="unavailable")) as (app, c, sid):
        st = poll(c, sid, lambda s: s["phase"] == "ready")
        assert st["playback"] == "browser_tts" and st["all_done"]
        assert st["sentences"] and all(isinstance(x, str) for x in st["sentences"])
        assert c.get(f"/api/sessions/{sid}/chunks/0").status_code == 404


def test_synth_total_failure_falls_back(tmp_path):
    wav = make_wav(tmp_path / "r.wav")

    def patch(app):
        def boom(*a, **k):
            raise RuntimeError("x")
        app.state.engines.tts.synthesize = boom

    with run(tmp_path, wav, patch) as (app, c, sid):
        st = poll(c, sid, lambda s: s["phase"] == "ready")
        assert st["playback"] == "browser_tts" and st["sentences"]


def test_phone_fx_failure_uses_raw(tmp_path, monkeypatch):
    from app import phone_fx
    monkeypatch.setattr(phone_fx, "apply_phone_effect",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("fx")), raising=False)
    wav = make_wav(tmp_path / "r.wav")
    with run(tmp_path, wav) as (app, c, sid):
        st = poll(c, sid, lambda s: s["all_done"])
        assert st["playback"] == "audio" and st["chunks_ready"] >= 1
        assert c.get(f"/api/sessions/{sid}/chunks/0").status_code == 200


def test_total_timeout_falls_back_to_browser_tts(tmp_path):
    wav = make_wav(tmp_path / "r.wav")

    def patch(app):
        def slow(*a, **k):
            time.sleep(2)
            raise RuntimeError("slow")
        app.state.engines.tts.synthesize = slow

    with run(tmp_path, wav, patch, pipeline={"total_timeout_sec": 1}) as (app, c, sid):
        st = poll(c, sid, lambda s: s["phase"] == "ready", timeout=10)
        assert st["playback"] == "browser_tts" and st["sentences"]
        time.sleep(2.2)  # 遅い合成スレッドがテスト終了前に片付くのを待つ


def test_ring_after_chunks_and_no_content_in_logs(tmp_path, caplog):
    import logging
    caplog.set_level(logging.DEBUG)
    wav = make_wav(tmp_path / "r.wav")
    with run(tmp_path, wav) as (app, c, sid):
        st = poll(c, sid, lambda s: s["all_done"])
    from app.mocks import MOCK_TRANSCRIPT
    assert MOCK_TRANSCRIPT[:10] not in caplog.text
    assert "step=stt" in caplog.text


def test_tts_checkpoint_dir_resolved_against_repo_root(monkeypatch):
    """相対 checkpoint_dir は cwd(backend/)ではなくリポジトリ直下基準で tts に渡る。"""
    import importlib
    from app.config import REPO_ROOT, load_config
    from app.pipeline import Engines

    cfg = load_config(overrides={"tts": {"engine": "openvoice", "checkpoint_dir": "models/OpenVoiceV2"}})
    seen = {}

    class Fake:
        def __init__(self, c):
            seen.update(c)

    real = importlib.import_module
    monkeypatch.setattr(importlib, "import_module",
                        lambda n, p=None: type("M", (), {"SpeechSynthesizer": Fake}) if n == ".tts" else real(n, p))
    Engines(cfg)._make("tts")
    assert seen["checkpoint_dir"] == str(REPO_ROOT / "models" / "OpenVoiceV2")
    assert cfg["tts"]["checkpoint_dir"] == "models/OpenVoiceV2"  # 元 cfg は変更しない


def test_ring_after_all_waits_for_every_chunk(tmp_path, monkeypatch):
    fake_story(monkeypatch)
    seen = []

    def patch(app):
        real = app.state.engines.tts.synthesize

        def slow(ctx, text, out, style=None):
            time.sleep(0.3)
            return real(ctx, text, out, style=style) if style else real(ctx, text, out)
        app.state.engines.tts.synthesize = slow

    wav = make_wav(tmp_path / "r.wav")
    with run(tmp_path, wav, patch, pipeline={"ring_after_chunks": "all", "chunk_unit": "sentence"}) as (app, c, sid):
        def cond(s):
            if s["phase"] == "ready":
                seen.append((s["chunks_ready"], s["chunks_total"]))
            return s["all_done"]
        poll(c, sid, cond)
    assert seen and all(r == t for r, t in seen)


def test_group_sentences():
    from app.pipeline import group_sentences
    s = ["あ" * 30, "い" * 30, "う" * 30, "え" * 30, "お" * 30]
    g = group_sentences(s, 100)
    assert g == ["あ" * 30 + "い" * 30 + "う" * 30, "え" * 30 + "お" * 30]
    assert "".join(g) == "".join(s)
    assert group_sentences(["あ" * 150], 100) == ["あ" * 150]
    assert group_sentences([], 100) == []
