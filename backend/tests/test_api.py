import os
import time

import soundfile as sf

from conftest import HEADERS, make_wav


def wait_health(c, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        h = c.get("/api/health").json()
        if h["ready"]:
            return h
        time.sleep(0.05)
    raise AssertionError("not ready")


def upload(c, sid, path):
    with open(path, "rb") as f:
        return c.post(f"/api/sessions/{sid}/recording",
                      files={"audio": ("rec.wav", f, "audio/wav")}, data={"duration_sec": "25"})


def poll(c, sid, cond, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        st = c.get(f"/api/sessions/{sid}/status").json()
        if cond(st):
            return st
        time.sleep(0.05)
    raise AssertionError(f"timeout, last={st}")


def test_health(client):
    h = wait_health(client)
    assert set(h["engines"]) == {"stt", "llm", "tts"}
    assert h["engines"]["stt"] == "ok" and h["engines"]["tts"] == "ok"
    assert h["engines"]["llm"] == "ok"


def test_config_shape(client):
    c = client.get("/api/config").json()
    assert set(c) == {
        "future_years", "caller_name", "record_min_sec", "record_max_sec", "ring_timeout_sec",
        "missed_call_display_sec", "end_screen_sec", "consent_idle_sec", "low_volume_threshold",
        "ringtone_volume", "call_volume", "staff_reset_hold_ms", "status_poll_ms", "max_wait_sec",
        "reply_wait_enabled", "reply_no_speech_sec", "reply_silence_end_sec", "reply_max_sec",
        "reply_min_pause_sec", "reply_speech_threshold", "ambient_enabled", "ambient_volume",
        "ambient_file"}
    assert c["caller_name"] == "10年後の自分"
    assert c["max_wait_sec"] > 60
    assert c["reply_wait_enabled"] is True and c["reply_no_speech_sec"] == 5
    assert c["reply_silence_end_sec"] == 1.2 and c["reply_max_sec"] == 15
    assert c["reply_min_pause_sec"] == 0.6 and c["reply_speech_threshold"] == 0.03
    assert c["ambient_enabled"] is True and c["ambient_volume"] == 0.12 and c["ambient_file"] is None


def test_status_has_wait_after_default(client):
    sid = client.post("/api/sessions").json()["session_id"]
    assert client.get(f"/api/sessions/{sid}/status").json()["wait_after"] == []


def test_full_flow_and_delete(client, wav25):
    wait_health(client)
    sid = client.post("/api/sessions").json()["session_id"]
    st = client.get(f"/api/sessions/{sid}/status").json()
    assert st["phase"] == "processing" and st["sentences"] is None
    r = upload(client, sid, wav25)
    assert r.status_code == 202 and r.json() == {"accepted": True}
    st = poll(client, sid, lambda s: s["phase"] == "ready")
    assert st["playback"] == "audio" and st["chunks_ready"] >= 1
    st = poll(client, sid, lambda s: s["all_done"])
    assert st["chunks_total"] == st["chunks_ready"] >= 2 and st["step"] == "done"
    r = client.get(f"/api/sessions/{sid}/chunks/0")
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"
    out = client.tmp_path / "c0.wav"
    out.write_bytes(r.content)
    data, sr = sf.read(str(out))
    assert len(data) > 0 and sr > 0
    assert client.get(f"/api/sessions/{sid}/chunks/{st['chunks_ready']}").status_code == 404
    wd = [p for p in os.listdir(client.tmp_path / "work") if p.startswith("futurecall_")]
    assert len(wd) == 1
    assert client.delete(f"/api/sessions/{sid}").status_code == 204
    assert os.listdir(client.tmp_path / "work") == []
    assert client.get(f"/api/sessions/{sid}/status").status_code == 404
    assert client.get(f"/api/sessions/{sid}/chunks/0").status_code == 404


def test_new_session_deletes_old_and_reset(client):
    a = client.post("/api/sessions").json()["session_id"]
    b = client.post("/api/sessions").json()["session_id"]
    assert a != b
    assert client.get(f"/api/sessions/{a}/status").status_code == 404
    assert client.get(f"/api/sessions/{b}/status").status_code == 200
    assert len(os.listdir(client.tmp_path / "work")) == 1
    assert client.post("/api/reset").status_code == 204
    assert client.get(f"/api/sessions/{b}/status").status_code == 404
    assert os.listdir(client.tmp_path / "work") == []


def test_recording_unknown_session(client, wav25):
    assert upload(client, "nope", wav25).status_code == 404


def test_client_log_whitelist(client):
    assert client.post("/api/client-log", json={"event": "answer", "ms": 12}).status_code == 200
    assert client.post("/api/client-log", json={"event": "evil_text", "ms": 1}).status_code == 422


def test_delete_during_processing(tmp_path, wav25):
    from fastapi.testclient import TestClient
    from app.main import create_app
    from conftest import base_overrides
    app = create_app(base_overrides(tmp_path))
    with TestClient(app, headers=HEADERS) as c:
        wait_health(c)
        sid = c.post("/api/sessions").json()["session_id"]
        upload(c, sid, wav25)
        c.delete(f"/api/sessions/{sid}")
        time.sleep(0.5)
        assert os.listdir(tmp_path / "work") == []


def test_startup_removes_leftovers(tmp_path):
    from fastapi.testclient import TestClient
    from app.main import create_app
    from conftest import base_overrides
    work = tmp_path / "work"
    (work / "futurecall_old").mkdir(parents=True)
    (work / "futurecall_old" / "x.wav").write_bytes(b"x")
    with TestClient(create_app(base_overrides(tmp_path))):
        assert not (work / "futurecall_old").exists()


# ---------------------------------------------------------------- security
def test_post_without_csrf_header_forbidden(client):
    r = client.post("/api/sessions", headers={"X-Requested-With": ""})
    assert r.status_code == 403
    assert client.post("/api/reset", headers={"X-Requested-With": "other"}).status_code == 403
    assert client.delete("/api/sessions/x", headers={"X-Requested-With": ""}).status_code == 403
    assert client.post("/api/sessions").status_code == 200  # 既定ヘッダー付きは通る


def test_get_needs_no_csrf_header(client):
    assert client.get("/api/health", headers={"X-Requested-With": ""}).status_code == 200


def test_unexpected_host_forbidden(client):
    assert client.get("/api/health", headers={"Host": "evil.example"}).status_code == 403
    assert client.get("/api/health", headers={"Host": "evil.example:8000"}).status_code == 403
    assert client.get("/api/health", headers={"Host": "testserver:8000"}).status_code == 200
