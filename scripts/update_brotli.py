"""Upgrade installed optional Brotli decoders before fetching remote data."""
from __future__ import annotations

from importlib import metadata
from pathlib import Path
import subprocess
import sys


def main() -> None:
    installed = []
    for name in ("Brotli", "brotlicffi"):
        try:
            metadata.version(name)
        except metadata.PackageNotFoundError:
            continue
        installed.append(name)
    if installed:
        constraints = Path(__file__).resolve().parents[1] / "constraints-security.txt"
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade",
             "--constraint", str(constraints), *installed],
            check=True,
        )


if __name__ == "__main__":
    main()
