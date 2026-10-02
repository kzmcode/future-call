"""FastAPI アプリ。`python -m app.main`(backend/ から)または `uvicorn app.main:app`。"""
from __future__ import annotations

import logging
import os
import threading
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import REPO_ROOT, frontend_config, load_config, resolve_path
from .logging_setup import setup_logging
from .pipeline import Engines, Pipeline
from .session import SessionStore

log = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 60 * 1024 * 1024
# 状態を変える API(POST/DELETE)に必須のヘッダー。他サイトからの単純な POST(CSRF)を防ぐ。
# このヘッダーは自作 JS でしか付けられず、別オリジンから付けるとブラウザが事前確認(CORS)を要求して拒否する。
CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "futurecall"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _host_only(host_header: str) -> str:
    h = (host_header or "").strip().lower()
    if h.startswith("["):  # [::1]:8000
        return h.split("]")[0] + "]"
    return h.split(":")[0]
FRONTEND_DIR = REPO_ROOT / "frontend"


class ClientLog(BaseModel):
    event: Literal["record_start", "record_submit", "ring_start", "answer", "call_end",
                   "missed_call", "staff_reset", "client_error"]
    ms: float = 0


def create_app(overrides: dict | None = None) -> FastAPI:
    cfg = load_config(overrides=overrides)
    wd = cfg["pipeline"].get("work_dir")
    store = SessionStore(str(resolve_path(wd)) if wd else None)
    engines = Engines(cfg)
    pipeline = Pipeline(cfg, engines, store)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        setup_logging(cfg)
        log.info("starting")
        store.cleanup_leftovers()
        engines.start_loading()
        store.start_purger()
        yield
        store.stop()
        pipeline.shutdown()
        store.delete_all()

    app = FastAPI(title="future-call", lifespan=lifespan)
    srv_cfg = cfg["server"]
    allowed_hosts = {str(h).lower() for h in (srv_cfg.get("allowed_hosts") or [])}
    allowed_hosts.add(str(srv_cfg.get("host", "127.0.0.1")).lower())

    @app.middleware("http")
    async def guard(request, call_next):
        # DNS rebinding 対策: 想定外の Host ヘッダーは拒否
        if _host_only(request.headers.get("host", "")) not in allowed_hosts:
            return JSONResponse({"detail": "forbidden host"}, status_code=403)
        # CSRF 対策: 状態を変える API は専用ヘッダー必須
        if request.url.path.startswith("/api/") and request.method not in SAFE_METHODS \
                and request.headers.get(CSRF_HEADER) != CSRF_VALUE:
            return JSONResponse({"detail": "forbidden"}, status_code=403)
        return await call_next(request)

    app.state.cfg, app.state.store = cfg, store
    app.state.engines, app.state.pipeline = engines, pipeline

    @app.get("/api/health")
    def health():
        return engines.health()

    @app.get("/api/config")
    def get_config():
        return frontend_config(cfg)

    @app.post("/api/sessions")
    def create_session():
        return {"session_id": store.create().id}

    def _session(sid: str):
        s = store.get(sid)
        if s is None:
            raise HTTPException(404, "session not found")
        return s

    @app.post("/api/sessions/{sid}/recording", status_code=202)
    def upload_recording(sid: str, audio: UploadFile = File(...), duration_sec: float = Form(0)):
        s = _session(sid)
        with s.lock:
            if s.started:
                return {"accepted": True}
            s.started = True
        ext = Path(audio.filename or "").suffix.lower().lstrip(".")
        if not ext.isalnum() or len(ext) > 5:
            ext = "wav"
        dst = s.path(f"upload.{ext}")
        size = 0
        try:
            with open(dst, "wb") as f:
                while chunk := audio.file.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_UPLOAD_BYTES:
                        raise HTTPException(413, "too large")
                    f.write(chunk)
        except FileNotFoundError:
            raise HTTPException(404, "session not found")
        log.info("recording received bytes=%d duration_sec=%.1f", size, duration_sec)
        pipeline.submit(s)
        return {"accepted": True}

    @app.get("/api/sessions/{sid}/status")
    def status(sid: str):
        return _session(sid).status()

    @app.get("/api/sessions/{sid}/chunks/{index}")
    def get_chunk(sid: str, index: int):
        s = _session(sid)
        with s.lock:
            ok = 0 <= index < s.chunks_ready and s.playback == "audio"
        path = s.path(f"chunk_{index}.wav")
        if not ok or not os.path.exists(path):
            raise HTTPException(404, "chunk not ready")
        return FileResponse(path, media_type="audio/wav", headers={"Cache-Control": "no-store"})

    @app.delete("/api/sessions/{sid}", status_code=204)
    def delete_session(sid: str):
        store.delete(sid)  # 存在しなくても 204(冪等)
        return Response(status_code=204)

    @app.post("/api/reset", status_code=204)
    def reset():
        store.delete_all()
        return Response(status_code=204)

    @app.post("/api/client-log")
    def client_log(body: ClientLog):
        log.info("client event=%s ms=%.0f", body.event, body.ms)
        return {"ok": True}

    if FRONTEND_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
    return app


app = create_app()


def main() -> None:
    import uvicorn

    srv = app.state.cfg["server"]
    if srv.get("open_browser"):
        threading.Timer(2.0, lambda: webbrowser.open(f"http://{srv['host']}:{srv['port']}/")).start()
    uvicorn.run(app, host=srv["host"], port=int(srv["port"]), log_level="warning")


if __name__ == "__main__":
    main()
