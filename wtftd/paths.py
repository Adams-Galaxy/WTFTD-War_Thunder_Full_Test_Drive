"""Where WTFTD reads and writes its files.

From the source tree everything lives next to the code (web/, data/, user/, .cache/).
In the packaged app (WTFTD.exe on Windows, WTFTD.app on macOS, the WTFTD file on Linux, PyInstaller) the program
files are read-only, so the writable folders go to %LOCALAPPDATA%\\WTFTD (Windows), ~/Library/Application Support/WTFTD
(macOS) or $XDG_DATA_HOME/WTFTD, ~/.local/share/WTFTD by default (Linux), and the game data shipped in the app is copied
there on first run (and when a newer app brings newer data).
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))
BUNDLE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))  # read-only app files


def _app_home() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "WTFTD"
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "WTFTD"
    xdg = os.environ.get("XDG_DATA_HOME", "")
    return (Path(xdg) if os.path.isabs(xdg) else Path.home() / ".local" / "share") / "WTFTD"  # XDG rule: a relative one is ignored


HOME = _app_home() if FROZEN else BUNDLE  # writable

WEB = BUNDLE / "web"
DATA = HOME / "data"
USER = HOME / "user"
CACHE = HOME / ".cache"
HOME.mkdir(parents=True, exist_ok=True)


def _built(data_dir: Path) -> int:
    try:
        return int(json.loads((data_dir / "meta.json").read_text(encoding="utf-8")).get("built", 0))
    except (OSError, ValueError, TypeError):
        return -1


def prepare():
    """Packaged app: installs the bundled game data into the writable folder when it is newer."""
    if not FROZEN:
        return
    HOME.mkdir(parents=True, exist_ok=True)
    src = BUNDLE / "data"
    if src.is_dir() and _built(DATA) < _built(src):
        shutil.copytree(src, DATA, dirs_exist_ok=True)
