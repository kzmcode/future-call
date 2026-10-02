"""Speech synthesis: Chatterbox Multilingual (ローカル・ゼロショット声クローン)。

参照音声は端末の外に出ない。重い import は遅延させる。
テキストはログに出さない(S-02)。中間ファイルは呼び出し側の work_dir 配下。
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any, Optional

from .tts import VoiceContext, _pitch_shift_file

log = logging.getLogger(__name__)

_WARMUP_TEXT = "もしもし。"
_MIN_SEC_PER_CHAR = 0.04     # これより短い合成は途切れ・空とみなす
_MAX_SEC_PER_CHAR = 0.60     # これより長い合成は暴走(繰り返し)とみなす
_MIN_RMS = 0.003


def _looks_valid(y: Any, sr: int, text: str) -> bool:
    import numpy as np

    n = max(1, len("".join(text.split())))
    dur = len(y) / float(sr)
    if dur < 0.3 or dur < _MIN_SEC_PER_CHAR * n or dur > _MAX_SEC_PER_CHAR * n + 3.0:
        return False
    return float(np.sqrt(np.mean(np.square(y)))) >= _MIN_RMS


class ChatterboxSynthesizer:
    def __init__(self, cfg: dict, api_key: Optional[str] = None):
        self.cfg = cfg or {}
        self._ccfg: dict = self.cfg.get("chatterbox") or {}
        self._model: Any = None
        self._device = "cpu"
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ load
    def _resolve_device(self, torch: Any) -> str:
        dev = str(self.cfg.get("device", "auto")).lower()
        if dev == "auto":
            mps = getattr(getattr(torch, "backends", None), "mps", None)
            return "mps" if mps is not None and mps.is_available() else "cpu"
        return dev

    def _from_pretrained(self, torch: Any, device: str) -> Any:
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS

        # CUDA で保存された重みを mps/cpu へ読み込むための対応
        orig = torch.load
        map_location = torch.device(device)

        def patched(*a: Any, **kw: Any) -> Any:
            kw.setdefault("map_location", map_location)
            return orig(*a, **kw)

        torch.load = patched
        try:
            return ChatterboxMultilingualTTS.from_pretrained(device=device)
        finally:
            torch.load = orig

    def load(self) -> None:
        try:
            import torch
            import chatterbox.mtl_tts  # noqa: F401
        except ImportError as e:
            raise ImportError(
                "chatterbox-tts / torch is not installed (scripts/setup.sh を実行); "
                f"original error: {type(e).__name__}") from e
        with self._lock:
            dev = self._resolve_device(torch)
            try:
                self._model = self._from_pretrained(torch, dev)
            except Exception as e:
                if dev == "cpu":
                    raise
                log.error("Chatterbox load on %s failed (%s); retrying on cpu",
                          dev, type(e).__name__)
                dev = "cpu"
                self._model = self._from_pretrained(torch, dev)
            self._device = dev
            self._warm_up()

    def _warm_up(self) -> None:
        try:
            self._generate(_WARMUP_TEXT)
        except Exception as e:
            log.warning("TTS warm-up failed (%s)", type(e).__name__)

    # --------------------------------------------------------------- prepare
    def _f(self, key: str, default: float) -> float:
        try:
            return float(self._ccfg.get(key, default))
        except (TypeError, ValueError):
            return default

    def _age_shift(self) -> float:
        a = self.cfg.get("age_voice_shift") or {}
        if not a.get("enabled", False):
            return 0.0
        return float(a.get("semitones", -1.0))

    def prepare_voice(self, reference_wav: Optional[str], work_dir: str,
                      median_f0_hz: Optional[float] = None) -> VoiceContext:
        try:
            ctx = VoiceContext(mode="standard", age_semitones=self._age_shift())
            if reference_wav and os.path.exists(reference_wav) and self._model is not None:
                try:
                    with self._lock:
                        self._model.prepare_conditionals(
                            reference_wav, exaggeration=self._f("exaggeration", 0.5))
                        ctx.target_se = self._model.conds
                    ctx.mode = "clone"
                except Exception as e:
                    log.error("reference conditioning failed (%s); default voice",
                              type(e).__name__)
            return ctx
        except Exception as e:  # never raise
            log.error("prepare_voice failed (%s)", type(e).__name__)
            return VoiceContext(mode="standard")

    # ------------------------------------------------------------ synthesize
    def _generate(self, text: str, conds: Any = None) -> Any:
        """1 回生成して float32 の 1 次元 numpy 配列を返す。"""
        import numpy as np

        if self._model is None:
            raise RuntimeError("TTS not loaded")
        m = self._model
        if conds is not None:
            m.conds = conds
        wav = m.generate(
            text, language_id=str(self._ccfg.get("language_id", "ja")),
            exaggeration=self._f("exaggeration", 0.5),
            cfg_weight=self._f("cfg_weight", 0.5),
            temperature=self._f("temperature", 0.8))
        y = wav.detach().cpu().numpy().astype(np.float32).reshape(-1)
        return y

    def synthesize(self, ctx: VoiceContext, text: str, out_wav: str,
                   style: Optional[str] = None) -> None:
        import soundfile as sf

        conds = ctx.target_se if ctx.mode == "clone" else None
        tries = 1 + max(0, int(self._ccfg.get("max_retries", 2)))
        y = None
        with self._lock:
            sr = int(getattr(self._model, "sr", 24000))
            for i in range(tries):
                cand = self._generate(text, conds)
                if len(cand) and (y is None or len(y) == 0):
                    y = cand
                if _looks_valid(cand, sr, text):
                    y = cand
                    break
                log.warning("Chatterbox output looks invalid (try %d/%d)", i + 1, tries)
        if y is None or len(y) == 0:
            raise RuntimeError("Chatterbox produced no audio")
        sf.write(out_wav, y, sr, subtype="PCM_16")
        if ctx.age_semitones:
            try:
                _pitch_shift_file(out_wav, ctx.age_semitones)
            except Exception as e:
                log.warning("age shift failed (%s)", type(e).__name__)
