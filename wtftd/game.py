"""War Thunder install detection and launching (Windows and macOS)."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

STEAM_APP_ID = "236390"
# macOS: the game files live inside the launcher's app bundle (Steam and standalone installs)
MAC_GAME = Path("WarThunderLauncher.app/Contents/WarThunder.app/Contents/Resources/game")
MAC_APPS = (Path("/Applications"), Path.home() / "Applications")


def _steam_roots() -> list[Path]:
    roots = []
    if sys.platform == "win32":
        import winreg
        for hive, key in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                          (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam")):
            try:
                with winreg.OpenKey(hive, key) as k:
                    for name in ("SteamPath", "InstallPath"):
                        try:
                            roots.append(Path(winreg.QueryValueEx(k, name)[0]))
                        except OSError:
                            pass
            except OSError:
                pass
        roots.append(Path(r"C:\Program Files (x86)\Steam"))
    elif sys.platform == "darwin":
        roots.append(Path.home() / "Library" / "Application Support" / "Steam")
    else:
        roots += [Path.home() / ".steam" / "steam", Path.home() / ".local" / "share" / "Steam"]
    libs = []
    for r in roots:
        vdf = r / "steamapps" / "libraryfolders.vdf"
        if vdf.exists():
            for m in re.finditer(r'"path"\s+"([^"]+)"', vdf.read_text(encoding="utf-8", errors="ignore")):
                libs.append(Path(m.group(1).replace("\\\\", "\\")))
        libs.append(r)
    seen, out = set(), []
    for p in libs:
        k = str(p).lower()
        if k not in seen:
            seen.add(k)
            out.append(p)
    return out


def is_game_dir(p: Path) -> bool:
    return (p / "aces.vromfs.bin").exists() or (p / "launcher.exe").exists() and (p / "levels").exists()


def _find_inside(p: Path, depth: int, budget: list) -> Path | None:
    """Game folder somewhere under p (macOS app bundles), breadth-limited."""
    if is_game_dir(p):
        return p
    if depth <= 0:
        return None
    try:
        subs = sorted(e.path for e in os.scandir(p) if e.is_dir(follow_symlinks=False))
    except OSError:
        return None
    for sub in subs:
        budget[0] -= 1
        if budget[0] <= 0:
            return None
        found = _find_inside(Path(sub), depth - 1, budget)
        if found:
            return found
    return None


def resolve_game_dir(p: Path) -> Path | None:
    """The folder holding the game files, from the game folder itself or (macOS) the install folder /
    WarThunderLauncher.app / WarThunder.app that contains it."""
    try:
        if is_game_dir(p):
            return p
        for sub in (MAC_GAME, Path("Contents/WarThunder.app/Contents/Resources/game"), Path("Contents/Resources/game")):
            if is_game_dir(p / sub):
                return p / sub
        if sys.platform == "darwin" and p.is_dir():
            return _find_inside(p, 6, [3000])
    except OSError:
        pass
    return None


def _spotlight() -> list[Path]:
    """macOS: game folders Spotlight knows about (installs outside the usual places)."""
    try:
        out = subprocess.run(["mdfind", 'kMDItemFSName == "aces.vromfs.bin"'], capture_output=True, text=True,
                             timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [Path(line).parent for line in out.splitlines() if line.strip()]


def detect_game_dir() -> Path | None:
    candidates = [lib / "steamapps" / "common" / "War Thunder" for lib in _steam_roots()]
    if sys.platform == "darwin":
        for apps in MAC_APPS:
            candidates += [apps / "WarThunderLauncher.app", apps / "WarThunder.app", apps / "WarThunder", apps / "War Thunder"]
        candidates.append(Path.home() / "WarThunder")
    else:
        local = os.environ.get("LOCALAPPDATA")
        if local:
            candidates.append(Path(local) / "WarThunder")
        for drive in "CDEFG":
            for sub in ("WarThunder", "Games/WarThunder", "Program Files/WarThunder", "Program Files (x86)/WarThunder"):
                candidates.append(Path(f"{drive}:/") / sub)
    for c in candidates:
        found = resolve_game_dir(c) if c.exists() else None
        if found:
            return found
    if sys.platform == "darwin":
        return next((p for p in _spotlight() if is_game_dir(p)), None)
    return None


CIRCUIT = re.compile(rb'curCircuit\s*:\s*t\s*=\s*"([A-Za-z0-9_-]{1,32})"')


def circuit(game_dir: Path | None) -> str | None:
    """Which servers this install plays on: "dev" for a dev server client (Gaijin's wiki: a folder of its own with an empty
    matchingdevmode file and curCircuit "dev" in config.blk), else config.blk's own ("production"). Read only, that key alone:
    config.blk holds the player's settings."""
    if not game_dir:
        return None
    if (game_dir / "matchingdevmode").exists():
        return "dev"
    try:
        found = CIRCUIT.search((game_dir / "config.blk").read_bytes())
    except OSError:
        return None
    return found.group(1).decode() if found else None


def is_steam_install(game_dir: Path) -> bool:
    return "steamapps" in str(game_dir).lower()


def installed_levels(game_dir: Path | None) -> set[str]:
    if not game_dir:
        return set()
    out = set()
    for folder in (game_dir / "levels",):
        if folder.exists():
            out.update(p.stem.lower() for p in folder.glob("*.bin"))
    return out


def user_missions_dir(game_dir: Path) -> Path:
    return game_dir / "UserMissions"


def _mac_app(game_dir: Path) -> Path | None:
    """macOS: the outermost app bundle around the game files (WarThunderLauncher.app)."""
    apps = [p for p in game_dir.parents if p.suffix.lower() == ".app"]
    return apps[-1] if apps else None


def _open(target: str):
    if sys.platform == "win32":
        os.startfile(target)  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", target])
    else:
        subprocess.Popen(["xdg-open", target])


def launch(game_dir: Path | None) -> str:
    if game_dir and not is_steam_install(game_dir):
        if (game_dir / "launcher.exe").exists():
            subprocess.Popen([str(game_dir / "launcher.exe")], cwd=str(game_dir))
            return "launcher"
        app = _mac_app(game_dir) if sys.platform == "darwin" else None
        if app:
            subprocess.Popen(["open", str(app)])
            return "launcher"
    _open(f"steam://rungameid/{STEAM_APP_ID}")
    return "steam"


def open_folder(path: Path):
    _open(str(path))
