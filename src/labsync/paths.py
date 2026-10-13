"""Per-platform locations for configuration, data, logs and bundled resources.

Windows keeps the historical ``%LOCALAPPDATA%\\LabSync`` folder so existing
installations are picked up and migrated. macOS uses ``~/Library/Application
Support/LabSync`` and Linux follows the XDG base directory spec.

``LABSYNC_HOME`` overrides everything (useful for portable installs, services
and tests).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from . import APP_NAME


def app_home() -> Path:
    override = os.environ.get("LABSYNC_HOME")
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / APP_NAME.lower()


def _ensure(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_file() -> Path:
    return _ensure(app_home()) / "config.json"


def data_dir() -> Path:
    return _ensure(app_home() / "data")


def database_file() -> Path:
    return data_dir() / "labsync.db"


def log_dir() -> Path:
    if sys.platform == "darwin" and not os.environ.get("LABSYNC_HOME"):
        return _ensure(Path.home() / "Library" / "Logs" / APP_NAME)
    return _ensure(app_home() / "logs")


def export_dir() -> Path:
    return _ensure(app_home() / "exports")


def updates_dir() -> Path:
    return _ensure(app_home() / "updates")


def resource_path(name: str) -> Path:
    """Locate a bundled resource both from source and inside a PyInstaller bundle."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        candidate = base / "labsync" / "resources" / name
        if candidate.exists():
            return candidate
    return Path(__file__).resolve().parent / "resources" / name
