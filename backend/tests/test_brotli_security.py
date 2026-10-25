"""Security updater must cover both optional decoders and stop on failures."""
import importlib.util
from importlib import metadata
from pathlib import Path
import subprocess
from unittest.mock import Mock

import pytest


spec = importlib.util.spec_from_file_location(
    "update_brotli", Path(__file__).resolve().parents[2] / "scripts/update_brotli.py")
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)


@pytest.mark.parametrize("installed", [[], ["Brotli"], ["brotlicffi"], ["Brotli", "brotlicffi"]])
def test_upgrade_only_installed_decoders(monkeypatch, installed):
    def version(name):
        if name not in installed:
            raise metadata.PackageNotFoundError(name)
        return "1.2.0"

    monkeypatch.setattr(updater.metadata, "version", version)
    run = Mock()
    monkeypatch.setattr(updater.subprocess, "run", run)
    updater.main()
    if not installed:
        run.assert_not_called()
    else:
        run.assert_called_once()
        args = run.call_args.args[0]
        assert args[:5] == [updater.sys.executable, "-m", "pip", "install", "--upgrade"]
        assert Path(args[6]).name == "constraints-security.txt"
        assert args[7:] == installed
        assert run.call_args.kwargs == {"check": True}


def test_failed_upgrade_stops_setup(monkeypatch):
    monkeypatch.setattr(updater.metadata, "version", lambda name: "1.2.0")
    monkeypatch.setattr(updater.subprocess, "run", Mock(
        side_effect=subprocess.CalledProcessError(1, "pip")))
    with pytest.raises(subprocess.CalledProcessError):
        updater.main()
