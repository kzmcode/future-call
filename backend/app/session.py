"""セッション管理(メモリ内)。1セッション=1作業ディレクトリ。削除でディレクトリごと消す (S-02)。"""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
import threading
import time
import uuid
from pathlib import Path

log = logging.getLogger(__name__)

DIR_PREFIX = "futurecall_"
STALE_SEC = 15 * 60


class Session:
    def __init__(self, sid: str, work_dir: str):
        self.id = sid
        self.work_dir = work_dir
        self.created_at = time.time()
        self.lock = threading.RLock()
        self.cancelled = threading.Event()
        self.started = False
        self.timed_out = False
        self._sentences: list[str] | None = None  # 非公開(browser_tts フォールバック用)
        self._wait_sentences: list[int] = []      # 非公開(browser_tts 時の返事待ち文番号)
        # 公開状態
        self.phase = "processing"
        self.step = "upload"
        self.playback = "audio"
        self.chunks_ready = 0
        self.chunks_total: int | None = None
        self.all_done = False
        self.sentences: list[str] | None = None  # browser_tts のときのみ公開
        self.wait_after: list[int] = []  # 返事を待つ位置(audio: チャンク番号 / browser_tts: 文番号)

    def path(self, name: str) -> str:
        return os.path.join(self.work_dir, name)

    def status(self) -> dict:
        with self.lock:
            return {
                "phase": self.phase,
                "step": self.step,
                "playback": self.playback,
                "chunks_ready": self.chunks_ready,
                "chunks_total": self.chunks_total,
                "all_done": self.all_done,
                "sentences": self.sentences if self.playback == "browser_tts" else None,
                "wait_after": list(self.wait_after),
            }


def _rmtree(path: str) -> None:
    for _ in range(3):
        shutil.rmtree(path, ignore_errors=True)
        if not os.path.exists(path):
            return
        time.sleep(0.05)


class SessionStore:
    def __init__(self, base_dir: str | None = None):
        self.base_dir = str(base_dir) if base_dir else tempfile.gettempdir()
        os.makedirs(self.base_dir, exist_ok=True)
        self._sessions: dict[str, Session] = {}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def create(self) -> Session:
        """新規セッション。既存はすべて削除する(展示は1台1人)。"""
        self.delete_all()
        sid = uuid.uuid4().hex
        wd = tempfile.mkdtemp(prefix=DIR_PREFIX, dir=self.base_dir)
        s = Session(sid, wd)
        with self._lock:
            self._sessions[sid] = s
        return s

    def get(self, sid: str) -> Session | None:
        with self._lock:
            return self._sessions.get(sid)

    def delete(self, sid: str) -> bool:
        with self._lock:
            s = self._sessions.pop(sid, None)
        if s is None:
            return False
        s.cancelled.set()
        _rmtree(s.work_dir)
        return True

    def delete_all(self) -> None:
        with self._lock:
            ids = list(self._sessions)
        for sid in ids:
            self.delete(sid)

    def purge_stale(self, max_age: float = STALE_SEC) -> int:
        now = time.time()
        with self._lock:
            old = [sid for sid, s in self._sessions.items() if now - s.created_at > max_age]
        for sid in old:
            self.delete(sid)
        if old:
            log.info("purged stale sessions: %d", len(old))
        return len(old)

    def cleanup_leftovers(self) -> int:
        """前回クラッシュ時などに残った作業ディレクトリを削除。"""
        n = 0
        with self._lock:
            live = {s.work_dir for s in self._sessions.values()}
        for p in Path(self.base_dir).glob(DIR_PREFIX + "*"):
            if str(p) not in live and p.is_dir():
                _rmtree(str(p))
                n += 1
        if n:
            log.info("removed leftover work dirs: %d", n)
        return n

    def start_purger(self, interval: float = 60.0) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()

        def loop():
            while not self._stop.wait(interval):
                try:
                    self.purge_stale()
                except Exception as e:  # noqa: BLE001
                    log.warning("purge error: %s", type(e).__name__)

        self._thread = threading.Thread(target=loop, name="purger", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
