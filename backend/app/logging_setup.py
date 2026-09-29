"""ログ設定。ファイル(ローテーション)+コンソール。内容(音声・テキスト)は記録しない (S-03)。"""
from __future__ import annotations

import logging
import logging.handlers

from .config import resolve_path

_FMT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def setup_logging(cfg: dict) -> None:
    lc = cfg.get("logging", {})
    level = getattr(logging, str(lc.get("level", "INFO")).upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        if getattr(h, "_futurecall", False):
            root.removeHandler(h)
            h.close()
    fmt = logging.Formatter(_FMT)
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    console._futurecall = True  # type: ignore[attr-defined]
    root.addHandler(console)
    try:
        log_dir = resolve_path(lc.get("dir", "logs"))
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            log_dir / "futurecall.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8")
        fh.setFormatter(fmt)
        fh._futurecall = True  # type: ignore[attr-defined]
        root.addHandler(fh)
    except Exception:
        logging.getLogger(__name__).warning("log file unavailable")
