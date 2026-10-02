"""config.yaml + .env の読み込み。リポジトリ直下を基準にパスを解決する。"""
from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULTS: dict[str, Any] = {
    "server": {"host": "127.0.0.1", "port": 8000, "open_browser": False,
               "allowed_hosts": ["127.0.0.1", "localhost", "[::1]"]},
    "experience": {
        "future_years": 10, "caller_name": None, "record_min_sec": 20,
        "record_max_sec": 90, "ring_timeout_sec": 30, "missed_call_display_sec": 4,
        "end_screen_sec": 15, "consent_idle_sec": 60, "low_volume_threshold": 0.02,
        "staff_reset_hold_ms": 3000, "status_poll_ms": 1000,
        "reply_wait": {"enabled": True, "no_speech_sec": 5, "silence_end_sec": 1.2,
                       "max_reply_sec": 15, "min_pause_sec": 0.6, "speech_threshold": 0.03},
    },
    "audio": {"ringtone_volume": 0.8, "call_volume": 1.0,
              "ambient_enabled": True, "ambient_volume": 0.12, "ambient_file": None},
    "pipeline": {"total_timeout_sec": 180, "ring_after_chunks": 2, "work_dir": None},
    "reference": {"max_sec": 30, "min_voiced_sec": 8, "denoise": False},
    "stt": {"engine": "faster_whisper", "model_size": "small", "compute_type": "int8",
            "beam_size": 1, "language": "ja"},
    "llm": {"engine": "gemini", "model": "gemini-3.5-flash-lite", "timeout_sec": 35,
            "fallback_models": ["gemini-3.1-flash-lite", "gemini-3.8-flash"],
            "temperature": 0.9, "min_transcript_chars": 10,
            "target_chars_min": 300, "target_chars_max": 480, "reply_pauses": 1},
    "tts": {"engine": "gemini_chatterbox", "chunk_unit": "auto", "device": "cpu", "checkpoint_dir": "models/OpenVoiceV2",
            "speed": 1.0, "tau": 0.5, "standard_voice_pitch_match": True,
            "chatterbox": {"device": None, "cfm_steps": 6},
            "age_voice_shift": {"enabled": False, "semitones": -1.0, "skip_if_child": True},
            "gemini": {"model": "gemini-3.8-flash-tts",
                       "fallback_models": ["gemini-3.8-flash-lite-tts"],
                       "quota_cooldown_sec": 300, "timeout_sec": 40, "voice_low": "Charon",
                       "voice_high": "Kore", "voice_split_f0_hz": 165,
                       "voices": [{"name": "Charon", "f0_hz": 100}, {"name": "Puck", "f0_hz": 120},
                                  {"name": "Kore", "f0_hz": 160}],
                       "default_style": "電話口で、少し照れくさそうに笑いながら話す、親しい相手への自然な日本語。テンポはゆったり、言いよどみや間をそのまま活かす。外国人のような抑揚や不自然なアクセントは避ける。",
                       "style_suffix": "親しい相手への自然な日本語。テンポはゆったり、言いよどみや間をそのまま活かす。外国人のような抑揚や不自然なアクセントは避ける。"}},
    "phone_fx": {"enabled": True, "low_hz": 250, "high_hz": 3800, "noise_db": -45,
                 "compress": True, "sample_rate": 16000},
    "logging": {"dir": "logs", "level": "INFO"},
}


def deep_merge(base: dict, over: dict | None) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str | os.PathLike | None = None, overrides: dict | None = None) -> dict:
    """デフォルト <- config.yaml <- overrides の順にマージした dict を返す。"""
    try:
        from dotenv import load_dotenv
        load_dotenv(REPO_ROOT / ".env")
    except Exception:
        pass
    p = Path(path or os.environ.get("FUTURECALL_CONFIG") or REPO_ROOT / "config.yaml")
    data: dict = {}
    if p.exists():
        with open(p, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    return deep_merge(deep_merge(DEFAULTS, data), overrides)


def get_api_key() -> str | None:
    key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    return key or None


def resolve_path(p: str | os.PathLike) -> Path:
    path = Path(p)
    return path if path.is_absolute() else REPO_ROOT / path


def frontend_config(cfg: dict) -> dict:
    """GET /api/config のレスポンスを作る。"""
    ex, au, pl = cfg["experience"], cfg["audio"], cfg["pipeline"]
    years = int(ex["future_years"])
    rw = ex.get("reply_wait") or {}
    return {
        "future_years": years,
        "caller_name": ex.get("caller_name") or f"{years}年後の自分",
        "record_min_sec": ex["record_min_sec"],
        "record_max_sec": ex["record_max_sec"],
        "ring_timeout_sec": ex["ring_timeout_sec"],
        "missed_call_display_sec": ex["missed_call_display_sec"],
        "end_screen_sec": ex["end_screen_sec"],
        "consent_idle_sec": ex["consent_idle_sec"],
        "low_volume_threshold": ex["low_volume_threshold"],
        "ringtone_volume": au["ringtone_volume"],
        "call_volume": au["call_volume"],
        "staff_reset_hold_ms": ex["staff_reset_hold_ms"],
        "status_poll_ms": ex["status_poll_ms"],
        "max_wait_sec": int(pl["total_timeout_sec"]) + 20,
        "reply_wait_enabled": bool(rw.get("enabled", True)),
        "reply_no_speech_sec": rw.get("no_speech_sec", 5),
        "reply_silence_end_sec": rw.get("silence_end_sec", 1.2),
        "reply_max_sec": rw.get("max_reply_sec", 15),
        "reply_min_pause_sec": rw.get("min_pause_sec", 0.6),
        "reply_speech_threshold": rw.get("speech_threshold", 0.03),
        "ambient_enabled": bool(au.get("ambient_enabled", True)),
        "ambient_volume": au.get("ambient_volume", 0.12),
        "ambient_file": au.get("ambient_file"),
    }
