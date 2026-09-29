"""faster-whisper による音声認識 (architecture.md §3.2). 認識テキストはログに出さない。"""
from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger(__name__)

_INITIAL_PROMPT = "こんにちは。今日は、失敗した話をします。"


class SpeechRecognizer:
    def __init__(self, cfg: dict):
        self.cfg = dict(cfg or {})
        self._model = None
        self._lock = threading.Lock()

    def load(self) -> None:
        with self._lock:
            if self._model is not None:
                return
            try:
                from faster_whisper import WhisperModel
            except ImportError as e:
                raise RuntimeError(
                    "faster-whisper is not installed (pip install faster-whisper)"
                ) from e
            t0 = time.time()
            self._model = WhisperModel(
                self.cfg.get("model_size", "small"),
                device="cpu",
                compute_type=self.cfg.get("compute_type", "int8"),
            )
            log.info("whisper model loaded in %.1fs", time.time() - t0)

    def transcribe(self, wav_path: str) -> str:
        if self._model is None:
            self.load()
        t0 = time.time()
        with self._lock:
            segments, _info = self._model.transcribe(
                wav_path,
                language="ja",
                beam_size=int(self.cfg.get("beam_size", 1)),
                vad_filter=True,
                condition_on_previous_text=False,
                initial_prompt=_INITIAL_PROMPT,
            )
            text = "".join(s.text for s in segments).strip()
        log.info("transcribed in %.1fs (%d chars)", time.time() - t0, len(text))
        return text
