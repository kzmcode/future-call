#!/usr/bin/env python3
"""モデルのダウンロード・確認スクリプト。

- OpenVoice V2 のチェックポイントを models/OpenVoiceV2 に配置
- faster-whisper のモデル(config.yaml の stt.model_size)を事前取得
- MeloTTS の日本語モデルを事前取得

オプションのパッケージが未インストールでも落ちずに、状況を最後に表示します。
使い方:  python scripts/download_models.py
"""
from __future__ import annotations

import os
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HF_REPO = "myshell-ai/OpenVoiceV2"
HF_BASE = f"https://huggingface.co/{HF_REPO}/resolve/main/"
OV_FILES = [
    "converter/config.json",
    "converter/checkpoint.pth",
    "base_speakers/ses/jp.pth",
]

summary: list[tuple[str, bool, str]] = []


def log(msg: str) -> None:
    print(msg, flush=True)


def load_config() -> dict:
    """config.yaml を読む。PyYAML が無ければ必要なキーだけ簡易抽出。"""
    path = ROOT / "config.yaml"
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        return yaml.safe_load(text) or {}
    except Exception:
        cfg: dict = {}
        m = re.search(r"^stt:\s*\n(?:[ \t]+.*\n)*?[ \t]+model_size:\s*([\w.\-]+)", text, re.M)
        if m:
            cfg["stt"] = {"model_size": m.group(1)}
        m = re.search(r"^tts:\s*\n(?:[ \t]+.*\n)*?[ \t]+checkpoint_dir:\s*(\S+)", text, re.M)
        if m:
            cfg["tts"] = {"checkpoint_dir": m.group(1)}
        return cfg


def download_url(url: str, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".part")
    with urllib.request.urlopen(url, timeout=60) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            buf = r.read(1024 * 1024)
            if not buf:
                break
            f.write(buf)
            done += len(buf)
            if total:
                print(f"\r    {done * 100 // total:3d}% ({done // 1048576} MB)", end="", flush=True)
    print()
    os.replace(tmp, dst)


def setup_openvoice(cfg: dict) -> None:
    ckpt = (cfg.get("tts") or {}).get("checkpoint_dir") or "models/OpenVoiceV2"
    dest = Path(ckpt)
    if not dest.is_absolute():
        dest = ROOT / dest
    log(f"[1/3] OpenVoice V2 チェックポイント -> {dest}")

    def missing() -> list[str]:
        return [f for f in OV_FILES if not (dest / f).exists()]

    if not missing():
        log("    すでに揃っています。スキップします。")
        summary.append(("OpenVoice V2", True, "配置済み"))
        return
    # 不足しているファイルだけを個別に取得(揃っている分は再ダウンロードしない)
    for f in missing():
        try:
            log(f"    取得中: {f}")
            download_url(HF_BASE + f, dest / f)
        except Exception as e:  # noqa: BLE001
            log(f"    失敗: {f} ({type(e).__name__}: {e})")
    m = missing()
    if m:
        summary.append(("OpenVoice V2", False, "不足: " + ", ".join(m) + "(ネット接続を確認して再実行)"))
    else:
        summary.append(("OpenVoice V2", True, "ダウンロード完了"))


def setup_whisper(cfg: dict) -> None:
    size = (cfg.get("stt") or {}).get("model_size") or "small"
    engine = (cfg.get("stt") or {}).get("engine") or "faster_whisper"
    log(f"[2/3] faster-whisper モデル '{size}'")
    if engine == "mock":
        log("    stt.engine が mock のためスキップします。")
        summary.append(("faster-whisper", True, "mock のため不要"))
        return
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError:
        log("    faster_whisper が未インストールです。requirements-models.txt を入れてください。")
        summary.append(("faster-whisper", False, "未インストール(初回起動時にも自動取得されます)"))
        return
    try:
        WhisperModel(size, device="cpu", compute_type=(cfg.get("stt") or {}).get("compute_type") or "int8")
        summary.append(("faster-whisper", True, f"{size} 取得済み"))
    except Exception as e:  # noqa: BLE001
        log(f"    失敗: {type(e).__name__}: {e}")
        summary.append(("faster-whisper", False, f"取得失敗({type(e).__name__})"))


def setup_melo() -> None:
    log("[3/3] MeloTTS 日本語モデル")
    try:
        from melo.api import TTS  # type: ignore
    except ImportError:
        log("    melo が未インストールです。requirements-models.txt を入れてください。")
        summary.append(("MeloTTS(JP)", False, "未インストール"))
        return
    except Exception as e:  # noqa: BLE001
        log(f"    melo の読み込みに失敗: {type(e).__name__}: {e}")
        summary.append(("MeloTTS(JP)", False, f"読み込み失敗({type(e).__name__}) 。docs/07_troubleshooting.md 参照"))
        return
    try:
        TTS(language="JP", device="cpu")
        summary.append(("MeloTTS(JP)", True, "モデル読み込み成功"))
    except Exception as e:  # noqa: BLE001
        log(f"    失敗: {type(e).__name__}: {e}")
        hint = "unidic 辞書が無い可能性: python -m unidic download" if "unidic" in str(e).lower() or "mecab" in str(e).lower() else "docs/07_troubleshooting.md 参照"
        summary.append(("MeloTTS(JP)", False, f"失敗({type(e).__name__}) {hint}"))


def main() -> int:
    log(f"Python {sys.version.split()[0]} / プロジェクト: {ROOT}")
    if sys.version_info[:2] != (3, 10):
        log("注意: Python 3.10 以外です。MeloTTS / OpenVoice は 3.10 を推奨します。")
    cfg = load_config()
    for fn, args in ((setup_openvoice, (cfg,)), (setup_whisper, (cfg,)), (setup_melo, ())):
        try:
            fn(*args)
        except Exception as e:  # noqa: BLE001
            summary.append((fn.__name__, False, f"予期しないエラー {type(e).__name__}"))
    log("\n===== 結果 =====")
    for name, ok, note in summary:
        log(f"  [{'OK' if ok else 'NG'}] {name}: {note}")
    if all(ok for _, ok, _ in summary):
        log("\nすべて準備できました。")
    else:
        log("\n一部が未準備です。モックモードなら動かせます(README 参照)。詳細は docs/07_troubleshooting.md。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
