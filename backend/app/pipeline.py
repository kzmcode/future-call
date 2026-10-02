"""STT -> LLM -> TTS -> FX のオーケストレーション (architecture.md §3.6)。

ログには処理時間・文字数・例外クラス名のみを出す(S-03)。
"""
from __future__ import annotations

import importlib
import logging
import os
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import ModuleType

import numpy as np
import soundfile as sf

from .config import get_api_key, resolve_path
from .mocks import MockRecognizer, MockSynthesizer
from .session import Session, SessionStore

log = logging.getLogger(__name__)

PKG = __package__ or "app"


def _optional(name: str) -> ModuleType | None:
    """app.<name> を防御的に import。失敗したら None。"""
    try:
        return importlib.import_module(f".{name}", PKG)
    except Exception as e:  # noqa: BLE001
        log.warning("module %s unavailable: %s", name, type(e).__name__)
        return None


def builtin_sentences(years: int) -> list[str]:
    """story モジュールすら使えない場合の最終フォールバック文。"""
    return [
        f"もしもし、びっくりしたよね。{years}年後の自分だよ。",
        "あのときのこと、よく覚えているよ。とても悔しかったよね。",
        "でもね、あの経験があったから、次の一歩を踏み出せたんだ。",
        "うまくいかなかった日のことが、あとで大きな力になったよ。",
        f"{years}年たった今、あのときの自分にありがとうって言いたい。",
        "だから大丈夫。ゆっくりでいいから、進んでいってね。",
        "じゃあ、またね。",
    ]


def group_sentences(sents: list[str], max_chars: int) -> list[str]:
    """隣り合う文を max_chars 程度までまとめる。1 回の合成ごとの固定コスト(約 5 秒)を減らす。"""
    out: list[str] = []
    cur = ""
    for x in sents:
        if cur and len(cur) + len(x) > max_chars:
            out.append(cur)
            cur = ""
        cur += x
    if cur:
        out.append(cur)
    return out


def story_units(result, sentences: list[str]) -> list[tuple[list[str], str, bool]]:
    """StoryResult を (文リスト, パート本文, 返事待ちか) のリストにする。parts が無ければ 1 パート・待ちなし。"""
    parts = getattr(result, "parts", None)
    units = []
    for p in parts or []:
        sents = [x for x in (getattr(p, "sentences", None) or []) if x]
        text = (getattr(p, "text", "") or "").strip()
        if not text:
            text = "".join(sents)
        if not text and not sents:
            continue
        units.append((sents or [text], text, bool(getattr(p, "wait_for_reply", False))))
    if not units:
        units = [(list(sentences), "".join(sentences), False)]
    return units


def sentence_wait_after(units, n_sentences: int) -> list[int]:
    """browser_tts 用: 返事待ちパートの最後の文の番号(文リスト範囲内のみ)。"""
    out, off = [], 0
    for sents, _text, wait in units:
        off += len(sents)
        if wait and 0 <= off - 1 < n_sentences:
            out.append(off - 1)
    return sorted(set(out))


def _llm_available(lcfg: dict) -> bool:
    """template は常に可。ollama はローカルサーバーが応答すれば可。gemini は API キーの有無。"""
    eng = lcfg.get("engine")
    if eng == "template":
        return True
    if eng == "ollama":
        import urllib.request
        try:
            url = str(lcfg.get("ollama_url", "http://127.0.0.1:11434")).rstrip("/") + "/api/tags"
            urllib.request.urlopen(url, timeout=2).close()
            return True
        except Exception:  # noqa: BLE001
            log.warning("ollama server not reachable; story falls back to templates")
            return False
    return bool(get_api_key())


class Engines:
    """STT/TTS エンジンの選択・バックグラウンド読み込み・状態管理。"""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.stt = None
        self.tts = None
        self.stt_lock = threading.Lock()
        self.tts_lock = threading.Lock()
        self._done = {"stt": threading.Event(), "tts": threading.Event()}
        llm_ok = _llm_available(cfg["llm"])
        self.state = {"stt": "loading", "llm": "ok" if llm_ok else "unavailable", "tts": "loading"}
        self._thread: threading.Thread | None = None

    def start_loading(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._load_all, name="model-loader", daemon=True)
        self._thread.start()

    def _make(self, kind: str):
        if kind == "stt":
            if self.cfg["stt"]["engine"] == "mock":
                return MockRecognizer(self.cfg["stt"])
            return importlib.import_module(".stt", PKG).SpeechRecognizer(self.cfg["stt"])
        if self.cfg["tts"]["engine"] == "mock":
            return MockSynthesizer(self.cfg["tts"])
        tcfg = dict(self.cfg["tts"])
        # 相対パスは cwd(backend/)ではなくリポジトリ直下基準で解決する
        tcfg["checkpoint_dir"] = str(resolve_path(tcfg.get("checkpoint_dir") or "models/OpenVoiceV2"))
        if tcfg.get("engine") == "chatterbox":
            return importlib.import_module(".tts_chatterbox", PKG).ChatterboxSynthesizer(tcfg)
        cls = importlib.import_module(".tts", PKG).SpeechSynthesizer
        try:
            return cls(tcfg, api_key=get_api_key())
        except TypeError:  # api_key 未対応の旧シグネチャ
            return cls(tcfg)

    def _load_one(self, kind: str) -> None:
        t0 = time.monotonic()
        try:
            eng = self._make(kind)
            eng.load()
            setattr(self, kind, eng)
            self.state[kind] = "ok"
        except Exception as e:  # noqa: BLE001
            self.state[kind] = "unavailable"
            log.warning("%s engine unavailable: %s", kind, type(e).__name__)
        finally:
            self._done[kind].set()
            log.info("load %s state=%s ms=%d", kind, self.state[kind], (time.monotonic() - t0) * 1000)

    def _load_all(self) -> None:
        self._load_one("stt")
        self._load_one("tts")

    def wait(self, kind: str, timeout: float) -> bool:
        """ロード完了を待つ。使用可能なら True。"""
        self._done[kind].wait(max(timeout, 0))
        return self.state[kind] == "ok"

    def health(self) -> dict:
        return {"ready": all(self.state[k] != "loading" for k in ("stt", "tts")),
                "engines": dict(self.state)}


class _Stop(Exception):
    """キャンセル/タイムアウトで静かに中断する。"""


def _fallback_normalize(src: str, dst: str, sr: int = 16000) -> float:
    from scipy.signal import resample_poly
    x, in_sr = sf.read(src, dtype="float32", always_2d=True)
    x = x.mean(axis=1)
    if in_sr != sr:
        from math import gcd
        g = gcd(int(in_sr), sr)
        x = resample_poly(x, sr // g, int(in_sr) // g).astype(np.float32)
    sf.write(dst, x, sr, subtype="PCM_16")
    return len(x) / sr


class Pipeline:
    def __init__(self, cfg: dict, engines: Engines, store: SessionStore):
        self.cfg = cfg
        self.engines = engines
        self.store = store
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pipeline")
        self.aux = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pipeline-aux")

    def submit(self, session: Session) -> None:
        self.executor.submit(self._run_safe, session)

    def shutdown(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.aux.shutdown(wait=False, cancel_futures=True)

    # ---- 状態更新 ----
    def _check(self, s: Session) -> None:
        if s.cancelled.is_set() or s.timed_out:
            raise _Stop()

    def _set_step(self, s: Session, step: str) -> None:
        with s.lock:
            if not s.timed_out:
                s.step = step

    def _years(self) -> int:
        return int(self.cfg["experience"]["future_years"])

    def _fallback_sentences(self) -> tuple[list[str], list[int]]:
        """テンプレート台本の (文リスト, wait_after)。使えなければ組み込み文と []。"""
        story = _optional("story")
        try:
            if story:
                cfg = dict(self.cfg["llm"], engine="template")
                res = story.StoryGenerator(cfg, None, self._years()).generate("")
                if res.sentences:
                    sents = list(res.sentences)
                    return sents, sentence_wait_after(story_units(res, sents), len(sents))
        except Exception as e:  # noqa: BLE001
            log.warning("template fallback failed: %s", type(e).__name__)
        return builtin_sentences(self._years()), []

    def _finish_browser_tts(self, s: Session, sentences: list[str] | None,
                            wait_after: list[int] | None = None) -> None:
        if sentences:
            sents, wait = sentences, list(wait_after or [])
        else:
            sents, wait = self._fallback_sentences()
        wait = [i for i in wait if 0 <= i < len(sents)]
        with s.lock:
            s.playback = "browser_tts"
            s.wait_after = wait
            s.sentences = list(sents)
            s.chunks_ready = 0
            s.chunks_total = len(sents)
            s.step = "done"
            s.all_done = True
            s.phase = "ready"
        log.info("playback=browser_tts sentences=%d", len(sents))

    def _on_timeout(self, s: Session) -> None:
        with s.lock:
            if s.cancelled.is_set() or s.all_done:
                return
            s.timed_out = True
            ready = s.chunks_ready
            if ready > 0:
                s.wait_after = [i for i in s.wait_after if i < ready]
                s.chunks_total = ready
                s.all_done = True
                s.phase = "ready"
                s.step = "done"
        log.warning("total timeout reached chunks_ready=%d", ready)
        if ready == 0:
            self._finish_browser_tts(s, getattr(s, "_sentences", None), getattr(s, "_wait_sentences", None))

    # ---- 本体 ----
    def _run_safe(self, s: Session) -> None:
        total = float(self.cfg["pipeline"]["total_timeout_sec"])
        t_start = time.monotonic()
        timer = threading.Timer(total, self._on_timeout, args=(s,))
        timer.daemon = True
        timer.start()
        try:
            self._run(s, t_start)
        except _Stop:
            log.info("pipeline stopped")
        except Exception as e:  # noqa: BLE001
            if not s.cancelled.is_set() and not s.timed_out:
                log.error("pipeline error: %s", type(e).__name__)
                self._finish_browser_tts(s, getattr(s, "_sentences", None), getattr(s, "_wait_sentences", None))
        finally:
            timer.cancel()
            log.info("pipeline total ms=%d", (time.monotonic() - t_start) * 1000)
            if s.cancelled.is_set():
                shutil.rmtree(s.work_dir, ignore_errors=True)

    def _find_input(self, s: Session) -> str:
        for name in os.listdir(s.work_dir):
            if name.startswith("upload."):
                return os.path.join(s.work_dir, name)
        return s.path("input.wav")

    def _run(self, s: Session, t_start: float) -> None:
        cfg, eng = self.cfg, self.engines
        deadline = t_start + float(cfg["pipeline"]["total_timeout_sec"])
        remaining = lambda: max(deadline - time.monotonic(), 0.0)  # noqa: E731
        audio_prep = _optional("audio_prep")
        phone_fx = _optional("phone_fx")

        # 1. 正規化
        self._set_step(s, "upload")
        t = time.monotonic()
        src, wav = self._find_input(s), s.path("input.wav")
        norm_ok = True
        try:
            if audio_prep:
                dur = audio_prep.normalize_input(src, wav)
            else:
                dur = _fallback_normalize(src, wav)
        except Exception as e:  # noqa: BLE001
            try:
                dur = _fallback_normalize(src, wav)
            except Exception:  # noqa: BLE001
                norm_ok = False
                dur = 0.0
                log.warning("normalize failed: %s", type(e).__name__)
        log.info("step=normalize ms=%d dur_sec=%.1f", (time.monotonic() - t) * 1000, dur)
        self._check(s)

        # 2. 並列: 参照音声の前処理 + STT
        self._set_step(s, "stt")
        ref_path = s.path("reference.wav")

        def do_ref():
            t0 = time.monotonic()
            try:
                if not (audio_prep and norm_ok):
                    return None
                info = audio_prep.prepare_reference(wav, ref_path, cfg["reference"])
                log.info("step=reference ms=%d ok=%s voiced_sec=%.1f",
                         (time.monotonic() - t0) * 1000, info.ok, info.voiced_sec)
                return info
            except Exception as e:  # noqa: BLE001
                log.warning("reference failed: %s", type(e).__name__)
                return None

        ref_future = self.aux.submit(do_ref)
        transcript = ""
        t0 = time.monotonic()
        if norm_ok and eng.wait("stt", min(remaining(), 120)):
            try:
                with eng.stt_lock:
                    transcript = eng.stt.transcribe(wav) or ""
            except Exception as e:  # noqa: BLE001
                log.warning("stt failed: %s", type(e).__name__)
        log.info("step=stt ms=%d chars=%d", (time.monotonic() - t0) * 1000, len(transcript))
        ref_info = ref_future.result()
        self._check(s)

        # 3. ストーリー生成 + 声の準備
        self._set_step(s, "story")
        ref_ok = bool(ref_info and ref_info.ok and ref_info.path and os.path.exists(ref_info.path))
        ref_wav = ref_info.path if ref_ok else None
        f0 = getattr(ref_info, "median_f0_hz", None) if ref_info else None
        tts_ok = eng.wait("tts", min(remaining(), 120))
        shift_on = bool(cfg["tts"].get("age_voice_shift", {}).get("enabled"))

        def do_voice():
            t1 = time.monotonic()
            try:
                with eng.tts_lock:
                    ctx = eng.tts.prepare_voice(ref_wav, s.work_dir, f0)
                log.info("step=prepare_voice ms=%d mode=%s", (time.monotonic() - t1) * 1000,
                         getattr(ctx, "mode", "?"))
                return ctx
            except Exception as e:  # noqa: BLE001
                log.warning("prepare_voice failed: %s", type(e).__name__)
                return None

        voice_future = self.aux.submit(do_voice) if (tts_ok and not shift_on) else None

        t0 = time.monotonic()
        result = None
        story = _optional("story")
        try:
            if story:
                api_key = None if cfg["llm"]["engine"] == "template" else get_api_key()
                result = story.StoryGenerator(cfg["llm"], api_key, self._years()).generate(transcript)
        except Exception as e:  # noqa: BLE001
            log.warning("story failed: %s", type(e).__name__)
        if result and result.sentences:
            sentences = list(result.sentences)
            units = story_units(result, sentences)
            style = getattr(result, "style", None) or None
        else:
            sentences = builtin_sentences(self._years())
            units = [(list(sentences), "".join(sentences), False)]
            style = None
        s._sentences = sentences
        s._wait_sentences = sentence_wait_after(units, len(sentences)) if result and result.sentences else []
        log.info("step=story ms=%d source=%s sentences=%d", (time.monotonic() - t0) * 1000,
                 getattr(result, "source", "builtin"), len(sentences))
        ctx = None
        if tts_ok:
            ctx = voice_future.result() if voice_future else do_voice()
        self._check(s)
        if ctx is None:
            self._finish_browser_tts(s, sentences, s._wait_sentences)
            return

        # 4. 合成 -> 電話音質 -> チャンク
        self._set_step(s, "tts")
        tcfg = cfg["tts"]
        unit = tcfg.get("chunk_unit", "auto")
        if unit not in ("part", "sentence", "group"):
            eng_name = tcfg.get("engine")
            unit = "part" if eng_name == "gemini_openvoice" else "group" if eng_name == "chatterbox" else "sentence"
        # chunks: (テキスト, パート番号)。part_last[pi] = そのパートの最後のチャンク番号(元の番号)
        chunks: list[tuple[str, int]] = []
        for pi, (sents, text, _w) in enumerate(units):
            if unit == "part":
                chunks.append((text, pi))
            elif unit == "group":
                chunks.extend((x, pi) for x in group_sentences(sents, int(tcfg.get("chunk_chars", 100))))
            else:
                chunks.extend((x, pi) for x in sents)
        waits = {pi for pi, u in enumerate(units) if u[2]}
        with s.lock:
            s.chunks_total = len(chunks)
        rac = cfg["pipeline"].get("ring_after_chunks", "all")
        if str(rac).lower() == "all":  # 全部できてから着信(ローカル合成が遅く、通話中の途切れを防ぐ)
            ring_after = len(chunks)
        else:
            ring_after = 1 if unit == "part" else int(rac)
        fx_cfg = cfg["phone_fx"]
        fx_on = bool(fx_cfg.get("enabled", True)) and phone_fx is not None
        ready = 0
        last_ok: dict[int, int] = {}  # パート番号 -> そのパートで最後に成功した出力チャンク番号
        for i, (text, pi) in enumerate(chunks):
            self._check(s)
            t0 = time.monotonic()
            raw, tmp = s.path(f"raw_{i}.wav"), s.path(f"chunk_tmp_{i}.wav")
            ok = False
            try:
                # tts_lock は合成中のみ保持する(FX・ファイル操作・状態更新は外)
                with eng.tts_lock:
                    self._check(s)
                    if style:
                        eng.tts.synthesize(ctx, text, raw, style=style)
                    else:
                        eng.tts.synthesize(ctx, text, raw)
                self._check(s)
                out = raw
                if fx_on:
                    try:
                        phone_fx.apply_phone_effect(raw, tmp, fx_cfg)
                        out = tmp
                    except Exception as e:  # noqa: BLE001
                        log.warning("phone_fx failed: %s", type(e).__name__)
                self._check(s)
                os.replace(out, s.path(f"chunk_{ready}.wav"))
                ok = True
            except _Stop:
                raise
            except Exception as e:  # noqa: BLE001
                if s.cancelled.is_set():
                    raise _Stop()
                log.warning("synthesize failed idx=%d: %s", i, type(e).__name__)
            finally:
                for p in (raw, tmp):
                    try:
                        os.remove(p)
                    except OSError:
                        pass
            part_end = i + 1 >= len(chunks) or chunks[i + 1][1] != pi
            with s.lock:
                if s.timed_out:
                    raise _Stop()
                if ok:
                    last_ok[pi] = ready
                    ready += 1
                    s.chunks_ready = ready
                    if s.phase != "ready" and ready >= ring_after:
                        s.phase = "ready"
                # パート末尾で、返事待ちならその位置(失敗時は同パートの直前の成功チャンク)を登録
                if part_end and pi in waits and pi in last_ok and last_ok[pi] not in s.wait_after:
                    s.wait_after = sorted(s.wait_after + [last_ok[pi]])
            if ok:
                log.info("step=tts_chunk idx=%d ms=%d chars=%d", i, (time.monotonic() - t0) * 1000, len(text))

        self._check(s)
        if ready == 0:
            self._finish_browser_tts(s, sentences, s._wait_sentences)
            return
        with s.lock:
            if s.timed_out:
                return
            s.chunks_total = ready
            s.wait_after = [i for i in s.wait_after if i < ready - 1]  # 最後のチャンクの後は待たない
            s.step = "done"
            s.phase = "ready"
            s.all_done = True
