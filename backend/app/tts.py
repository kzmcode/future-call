"""Speech synthesis: MeloTTS (JP) + OpenVoice V2 tone-color conversion.

All heavy imports are lazy. Text is never logged (S-02); intermediate files
live under the caller's work_dir.
"""
from __future__ import annotations

import base64
import logging
import math
import os
import re
import shutil
import tempfile
import threading
import time
import wave
from dataclasses import dataclass
from typing import Any, Optional

log = logging.getLogger(__name__)

_WARMUP_TEXT = "もしもし。"


@dataclass
class VoiceContext:
    mode: str  # "clone" | "standard"
    target_se: Any = None
    pitch_semitones: float = 0.0   # standard-voice pitch matching
    age_semitones: float = 0.0     # Q-06 final shift
    speaker_id: Optional[int] = None
    voice_name: Optional[str] = None   # Gemini prebuilt voice (None = MeloTTS only)


def _pitch_shift_file(path: str, semitones: float) -> None:
    """In-place pitch shift preserving duration. Skips if librosa is missing."""
    if abs(semitones) < 0.05:
        return
    try:
        import librosa
        import soundfile as sf
    except ImportError:
        log.warning("librosa unavailable; pitch shift skipped")
        return
    y, sr = sf.read(path, dtype="float32")
    if y.ndim > 1:
        y = y.mean(axis=1)
    y2 = librosa.effects.pitch_shift(y, sr=sr, n_steps=float(semitones))
    sf.write(path, y2, sr, subtype="PCM_16")


_GEMINI_RATE = 24000
_QUOTA_COOLDOWN_SEC = 300.0
_FAIL_COOLDOWN_SEC = 60.0
_FAIL_STREAK_LIMIT = 3
_PERDAY_COOLDOWN_SEC = 1800.0
_LATER_MODEL_MIN_SEC = 8.0
_DEFAULT_MODEL = "gemini-3.8-flash-tts"


def _err_code(e: BaseException) -> Optional[int]:
    for attr in ("code", "status_code"):
        v = getattr(e, attr, None)
        if isinstance(v, int):
            return v
    return None


def _is_not_found(e: BaseException) -> bool:
    return _err_code(e) == 404 or str(getattr(e, "status", "") or "").upper() == "NOT_FOUND"


def _is_quota_error(e: BaseException) -> bool:
    for attr in ("code", "status_code", "status"):
        v = getattr(e, attr, None)
        if v == 429 or (isinstance(v, str) and v.upper() == "RESOURCE_EXHAUSTED"):
            return True
    resp = getattr(e, "response", None)
    if getattr(resp, "status_code", None) == 429:
        return True
    return "RESOURCE_EXHAUSTED" in str(e) or type(e).__name__ == "RateLimitError"


def _retry_options(types: Any) -> Any:
    """一時的な 500/502/504 とネットワーク断だけ 1 回再試行(429・503 は再試行しない)。"""
    return types.HttpRetryOptions(
        attempts=2, initial_delay=0.5, max_delay=1.0, jitter=0.2,
        http_status_codes=[500, 502, 504])


def _quota_cooldown_sec(e: BaseException, default: float) -> float:
    """429 本文から待ち時間を決める。PerDay は 30 分以上、PerMinute 系は retryDelay+2 秒(30〜300 秒)。"""
    text = str(e)
    if "perday" in text.lower().replace("_", "").replace(" ", ""):
        return max(default, _PERDAY_COOLDOWN_SEC)
    m = re.search(r"retryDelay\W+(\d+(?:\.\d+)?)s", text)
    if m:
        return min(max(float(m.group(1)) + 2.0, 30.0), 300.0)
    return default


def _write_audio_as_wav(raw: bytes, path: str, mime: str = "") -> None:
    """Gemini output -> WAV file. RIFF data is kept; raw L16 PCM is wrapped."""
    if not raw:
        raise ValueError("empty audio")
    if raw[:4] == b"RIFF":
        with open(path, "wb") as f:
            f.write(raw)
        return
    rate = _GEMINI_RATE
    for part in (mime or "").split(";"):
        part = part.strip().lower()
        if part.startswith("rate="):
            try:
                rate = int(part[5:])
            except ValueError:
                pass
    if len(raw) % 2:
        raw = raw[:-1]
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(raw)  # Gemini raw PCM is 16-bit little-endian


class SpeechSynthesizer:
    def __init__(self, cfg: dict, api_key: Optional[str] = None):
        self.cfg = cfg or {}
        self.api_key = api_key or None
        self._gcfg: dict = self.cfg.get("gemini") or {}
        self._gemini_client: Any = None
        self._voice_se: dict = {}
        self._voice_se_lock = threading.Lock()
        # モデルごとのサーキットブレーカ(story.py と同じ考え方)
        self._cooldown_until: dict = {}   # model -> 再試行解禁時刻(monotonic)
        self._fail_streak: dict = {}      # model -> 連続失敗回数
        self._unavailable: set = set()    # 404(提供なし)のモデル。プロセス内で記憶
        self._breaker_lock = threading.Lock()
        self._lock = threading.Lock()
        self._melo: Any = None
        self._speaker_id: Optional[int] = None
        self._converter: Any = None
        self._src_se: Any = None
        self._device = "cpu"

    # ------------------------------------------------------------------ load
    def _resolve_device(self, torch: Any) -> str:
        dev = str(self.cfg.get("device", "cpu")).lower()
        if dev == "auto":
            mps = getattr(getattr(torch, "backends", None), "mps", None)
            return "mps" if mps is not None and mps.is_available() else "cpu"
        return dev

    def load(self) -> None:
        try:
            import torch
            from melo.api import TTS
        except ImportError as e:
            raise ImportError(
                "MeloTTS / torch is not installed (scripts/setup.sh を実行); "
                f"original error: {type(e).__name__}") from e
        with self._lock:
            self._device = self._resolve_device(torch)
            threads = int(self.cfg.get("torch_threads") or min(4, os.cpu_count() or 1))
            try:
                torch.set_num_threads(max(1, threads))
            except Exception:
                pass
            model = TTS(language="JP", device=self._device)
            self._speaker_id = model.hps.data.spk2id["JP"]
            self._melo = model

            if str(self.cfg.get("engine", "openvoice")).lower() != "melo":
                try:
                    self._load_converter(torch)
                except Exception as e:  # standard voice still works
                    # model loading only: no user data involved, message is safe
                    log.error("OpenVoice load failed (%s: %s); standard voice only",
                              type(e).__name__, e)
                    self._converter = None
                    self._src_se = None
            self._warm_up()

    def _load_converter(self, torch: Any) -> None:
        from openvoice.api import ToneColorConverter

        ck = self.cfg.get("checkpoint_dir", "models/OpenVoiceV2")
        conv = self._build_converter(
            ToneColorConverter, os.path.join(ck, "converter", "config.json"))
        conv.load_ckpt(os.path.join(ck, "converter", "checkpoint.pth"))
        src_se = torch.load(os.path.join(ck, "base_speakers", "ses", "jp.pth"),
                            map_location=self._device)
        self._converter, self._src_se = conv, src_se

    def _build_converter(self, cls: Any, config_path: str) -> Any:
        """Build ToneColorConverter with the wavmark watermark OFF.

        Some OpenVoice revisions forward ``enable_watermark`` to a base class
        that does not accept it (TypeError), while omitting it imports the
        optional ``wavmark`` package. Try the kwarg first, then fall back to
        initialising the base class directly with no watermark model.
        """
        wm = bool(self.cfg.get("enable_watermark", False))
        try:
            return cls(config_path, device=self._device, enable_watermark=wm)
        except TypeError as e:
            log.info("ToneColorConverter rejects enable_watermark (%s); "
                     "initialising without watermark", e)
        if wm:
            raise RuntimeError("enable_watermark is not supported by this OpenVoice")
        base = next((c for c in cls.__mro__[1:] if c is not object), None)
        obj = cls.__new__(cls)
        if base is not None:
            base.__init__(obj, config_path, device=self._device)
        obj.watermark_model = None
        obj.version = getattr(getattr(obj, "hps", None), "_version_", "v1")
        return obj

    def _warm_up(self) -> None:
        d = tempfile.mkdtemp(prefix="tts_warm_")
        try:
            self._melo_to_file(_WARMUP_TEXT, os.path.join(d, "w.wav"))
        except Exception as e:
            log.warning("TTS warm-up failed (%s)", type(e).__name__)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    # --------------------------------------------------------------- prepare
    def prepare_voice(self, reference_wav: Optional[str], work_dir: str,
                      median_f0_hz: Optional[float], is_child: bool) -> VoiceContext:
        try:
            age = self._age_shift(is_child)
            ctx = VoiceContext(mode="standard", age_semitones=age,
                               speaker_id=self._speaker_id)
            if self._gemini_enabled():
                ctx.voice_name = self._choose_voice(median_f0_hz)
            engine = str(self.cfg.get("engine", "openvoice")).lower()
            if engine != "melo" and reference_wav and self._converter is not None \
                    and os.path.exists(reference_wav):
                try:
                    with self._lock:
                        se = self._converter.extract_se([reference_wav])
                    ctx.mode, ctx.target_se = "clone", se
                    return ctx
                except Exception as e:
                    log.error("speaker embedding failed (%s); standard voice",
                              type(e).__name__)
            if self.cfg.get("standard_voice_pitch_match", True) and median_f0_hz \
                    and median_f0_hz > 0:
                base = float(self.cfg.get("standard_base_f0_hz", 220.0))
                st = 12.0 * math.log2(float(median_f0_hz) / base)
                ctx.pitch_semitones = max(-8.0, min(8.0, st))
            return ctx
        except Exception as e:  # never raise
            log.error("prepare_voice failed (%s)", type(e).__name__)
            return VoiceContext(mode="standard")

    def _tau(self) -> float:
        """OpenVoice convert() tau (flow noise scale; measured: 0.1-1.0 ~ same)."""
        try:
            return float(self.cfg.get("tau", 0.5))
        except (TypeError, ValueError):
            return 0.5

    def _age_shift(self, is_child: bool) -> float:
        a = self.cfg.get("age_voice_shift") or {}
        if not a.get("enabled", False):
            return 0.0
        if is_child and a.get("skip_if_child", True):
            return 0.0
        return float(a.get("semitones", -1.0))

    # ---------------------------------------------------------------- gemini
    def _gemini_enabled(self) -> bool:
        """gemini_openvoice engine with an API key; otherwise acts like openvoice."""
        return (str(self.cfg.get("engine", "openvoice")).lower() == "gemini_openvoice"
                and bool(self.api_key))

    def _voice_table(self) -> list:
        """[(name, f0_hz)] from tts.gemini.voices; legacy voice_low/high fallback."""
        rows = []
        for v in self._gcfg.get("voices") or []:
            try:
                rows.append((str(v["name"]), float(v["f0_hz"])))
            except (KeyError, TypeError, ValueError):
                continue
        return rows

    def _choose_voice(self, median_f0_hz: Optional[float]) -> str:
        """Nearest-F0 selection from tts.gemini.voices (log-Hz distance).

        Unknown F0 -> treated as 200 Hz.
        Without a `voices` table: legacy voice_low / voice_high split.
        """
        g = self._gcfg
        rows = self._voice_table()
        if rows:
            f0 = float(median_f0_hz) if median_f0_hz and median_f0_hz > 0 else 200.0
            return min(rows, key=lambda r: abs(math.log(r[1] / f0)))[0]
        low, high = g.get("voice_low", "Charon"), g.get("voice_high", "Kore")
        split = float(g.get("voice_split_f0_hz", 165))
        if median_f0_hz and median_f0_hz > 0 and float(median_f0_hz) < split:
            return str(low)
        return str(high)

    def _get_client(self) -> Any:
        if self._gemini_client is None:
            from google import genai
            from google.genai import types
            ms = int(float(self._gcfg.get("timeout_sec", 25)) * 1000)
            # SDK 既定は 429/5xx を最大 3〜4 回バックオフ再試行する(interactions API)。
            # 429 は即座に呼び出し側へ返してモデルを切り替えたいので、再試行対象から外す。
            self._gemini_client = genai.Client(
                api_key=self.api_key,
                http_options=types.HttpOptions(timeout=ms, retry_options=_retry_options(types)))
        return self._gemini_client

    def _model_chain(self) -> list:
        chain: list = []
        fb = self._gcfg.get("fallback_models") or []
        if isinstance(fb, str):
            fb = [fb]
        for m in [self._gcfg.get("model", _DEFAULT_MODEL)] + list(fb):
            if m and str(m) not in chain:
                chain.append(str(m))
        return chain

    def _is_cooling(self, model: str) -> bool:
        with self._breaker_lock:
            if model in self._unavailable:
                return True
            until = self._cooldown_until.get(model)
            if until is None:
                return False
            if time.monotonic() >= until:
                del self._cooldown_until[model]  # 期限切れ: 次のチャンクで再試行
                return False
            return True

    def _note_failure(self, model: str, e: BaseException) -> None:
        """モデルごとに記録。ログはモデル名とエラーの種類だけ(文章・話し方は出さない)。"""
        with self._breaker_lock:
            if _is_quota_error(e):
                sec = _quota_cooldown_sec(
                    e, float(self._gcfg.get("quota_cooldown_sec", _QUOTA_COOLDOWN_SEC)))
                self._cooldown_until[model] = time.monotonic() + sec
                self._fail_streak[model] = 0
                log.warning("Gemini TTS quota exhausted model=%s -> skip for %.0fs", model, sec)
                return
            if _is_not_found(e):
                self._unavailable.add(model)
                log.warning("Gemini TTS model unavailable model=%s", model)
                return
            if _err_code(e) == 503:  # 一時的な過負荷: 今回だけ次のモデルへ(記憶しない)
                log.warning("Gemini TTS model overloaded model=%s", model)
                return
            n = self._fail_streak.get(model, 0) + 1
            if n >= _FAIL_STREAK_LIMIT:
                self._cooldown_until[model] = time.monotonic() + _FAIL_COOLDOWN_SEC
                n = 0
            self._fail_streak[model] = n

    def _gemini_call(self, text: str, style: Optional[str], voice: str,
                     model: Optional[str] = None) -> Any:
        content: dict = {"type": "text", "text": text}
        st = style or self._gcfg.get("default_style")
        if st:
            content["annotations"] = [{"type": "speech_metadata", "style": st}]
        return self._get_client().interactions.create(
            model=model or self._gcfg.get("model", _DEFAULT_MODEL),
            input=[{"type": "user_input", "content": [content]}],
            response_format={"type": "audio"},
            generation_config={"speech_config": [{"voice": voice}]},
        )

    def _gemini_to_file(self, text: str, style: Optional[str], voice: str,
                        path: str, model: Optional[str] = None,
                        timeout: Optional[float] = None) -> None:
        """Synthesize with Gemini into a WAV at `path`. Raises on any failure."""
        if timeout is None:
            timeout = float(self._gcfg.get("timeout_sec", 25))
        box: dict = {}

        def run() -> None:
            try:
                box["r"] = self._gemini_call(text, style, voice, model)
            except BaseException as e:  # noqa: BLE001
                box["e"] = e

        t = threading.Thread(target=run, daemon=True)
        t.start()
        t.join(timeout)
        if t.is_alive():
            raise TimeoutError("gemini tts timeout")
        if "e" in box:
            raise box["e"]
        audio = getattr(box.get("r"), "output_audio", None)
        data = getattr(audio, "data", None)
        if isinstance(data, str):
            data = base64.b64decode(data)
        if not data:
            raise ValueError("empty audio")
        _write_audio_as_wav(bytes(data), path, getattr(audio, "mime_type", "") or "")

    def _se_for_voice(self, model: str, voice: str, wav_path: str) -> Any:
        """src_se は (モデル, 声) ごと。同じ声名でもモデルが違えば音色が少し違う。"""
        key = (model, voice)
        with self._voice_se_lock:
            if key in self._voice_se:
                return self._voice_se[key]
        with self._lock:
            se = self._converter.extract_se([wav_path])
        with self._voice_se_lock:
            self._voice_se[key] = se
        return se

    def _synth_gemini(self, ctx: VoiceContext, text: str, style: Optional[str],
                      tmp: str) -> Optional[str]:
        """Returns path of the final Gemini-based wav in tmp, or None (use Melo).

        モデルを順に試す。上限中のモデルは呼ばずに飛ばし、全滅なら None(MeloTTS)。
        全体で timeout_sec の予算(後続モデルには残り予算。最小 8 秒)。
        """
        if not (ctx.voice_name and self._gemini_enabled()):
            return None
        gem = os.path.join(tmp, "gemini.wav")
        total = float(self._gcfg.get("timeout_sec", 25))
        deadline = time.monotonic() + total
        used: Optional[str] = None
        first = True
        for model in self._model_chain():
            if self._is_cooling(model):
                continue
            tmo = total if first else max(_LATER_MODEL_MIN_SEC, deadline - time.monotonic())
            first = False
            try:
                self._gemini_to_file(text, style, ctx.voice_name, gem, model, tmo)
                with self._breaker_lock:
                    self._fail_streak[model] = 0
                used = model
                break
            except Exception as e:
                log.error("Gemini TTS failed model=%s (%s)", model, type(e).__name__)
                self._note_failure(model, e)
                if isinstance(e, TimeoutError):
                    break  # 予算を使い切った: 別モデルは試さず MeloTTS へ
        if used is None:
            log.warning("Gemini TTS unavailable on all models; falling back to MeloTTS")
            return None
        if used != self._gcfg.get("model", _DEFAULT_MODEL):
            log.info("Gemini TTS: using fallback model=%s", used)
        if ctx.mode == "clone" and self._converter is not None:
            try:
                src_se = self._se_for_voice(used, ctx.voice_name, gem)
                conv = os.path.join(tmp, "gconv.wav")
                with self._lock:
                    self._converter.convert(
                        audio_src_path=gem, src_se=src_se, tgt_se=ctx.target_se,
                        output_path=conv, tau=self._tau(), message="@MyShell")
                return conv
            except Exception as e:
                log.error("Gemini voice conversion failed (%s); using preset voice",
                          type(e).__name__)
        return gem

    # ------------------------------------------------------------ synthesize
    def _melo_to_file(self, text: str, path: str) -> None:
        if self._melo is None:
            raise RuntimeError("TTS not loaded")
        self._melo.tts_to_file(text, self._speaker_id, path,
                               speed=float(self.cfg.get("speed", 1.0)))

    def synthesize(self, ctx: VoiceContext, text: str, out_wav: str,
                   style: Optional[str] = None) -> None:
        out_dir = os.path.dirname(os.path.abspath(out_wav))
        tmp = tempfile.mkdtemp(prefix="tts_", dir=out_dir)
        try:
            g = self._synth_gemini(ctx, text, style, tmp)
            if g is not None:
                shutil.move(g, out_wav)
                if ctx.age_semitones:
                    try:
                        _pitch_shift_file(out_wav, ctx.age_semitones)
                    except Exception as e:
                        log.warning("age shift failed (%s)", type(e).__name__)
                return
            self._synth_melo(ctx, text, out_wav, tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _synth_melo(self, ctx: VoiceContext, text: str, out_wav: str, tmp: str) -> None:
        with self._lock:
            base = os.path.join(tmp, "base.wav")
            self._melo_to_file(text, base)
            done = False
            if ctx.mode == "clone" and self._converter is not None:
                try:
                    conv = os.path.join(tmp, "conv.wav")
                    self._converter.convert(
                        audio_src_path=base, src_se=self._src_se,
                        tgt_se=ctx.target_se, output_path=conv,
                        tau=self._tau(), message="@MyShell")
                    shutil.move(conv, out_wav)
                    done = True
                except Exception as e:
                    log.error("clone synthesis failed (%s); using standard voice",
                              type(e).__name__)
            if not done:
                shutil.move(base, out_wav)
                try:
                    _pitch_shift_file(out_wav, ctx.pitch_semitones)
                except Exception as e:
                    log.warning("pitch match failed (%s)", type(e).__name__)
            if ctx.age_semitones:
                try:
                    _pitch_shift_file(out_wav, ctx.age_semitones)
                except Exception as e:
                    log.warning("age shift failed (%s)", type(e).__name__)
