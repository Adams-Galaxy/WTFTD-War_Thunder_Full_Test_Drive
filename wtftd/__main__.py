"""Entry point: python -m wtftd [--browser] [--port N]

Opens the UI in a chromeless Edge/Chrome app window when available and stops the
server when that window is closed. --browser uses the default browser instead.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

from .alarms import available, game_running
from .paths import CACHE, FROZEN, USER, WEB, prepare
from .server import ROOT, STATE, WATCH, page_closed, read_json, serve, wait_page_gone, write_json

GAME_CHECK_S = 5
FIND_WINDOW_S = 20
PLACE_S = 2  # how often the window's place is looked at, kept when it changes
PLACE = USER / "window.json"  # a file of its own: the settings are written by the page too
# a window hidden, minimized or on another screen keeps its pings, curves and battle log going
STAY_AWAKE = ("--disable-background-timer-throttling", "--disable-renderer-backgrounding", "--disable-backgrounding-occluded-windows")
# macOS: Chromium browsers that support app windows (--app), executable inside the bundle
MAC_BROWSERS = ("Google Chrome.app/Contents/MacOS/Google Chrome", "Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                "Chromium.app/Contents/MacOS/Chromium", "Brave Browser.app/Contents/MacOS/Brave Browser")


def find_app_browser() -> str | None:
    if sys.platform == "darwin":
        for apps in (Path("/Applications"), Path.home() / "Applications"):
            for rel in MAC_BROWSERS:
                if (apps / rel).is_file():
                    return str(apps / rel)
        return None
    pf = [os.environ.get(k) for k in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA")]
    candidates = []
    for base in filter(None, pf):
        candidates += [
            Path(base) / "Microsoft/Edge/Application/msedge.exe",
            Path(base) / "Google/Chrome/Application/chrome.exe",
        ]
    for c in candidates:
        if c.exists():
            return str(c)
    return shutil.which("msedge") or shutil.which("chrome") or shutil.which("chromium")


def window_args() -> list[str]:
    """Where the window was closed (user/window.json), so that it opens there rather than somewhere it then leaves; else
    1500x920, or maximized when the screen's work area is smaller (laptops, 1366x768...). keep_place then puts it exactly
    (shortcut: the browser's pixels are taken as the main screen's, a screen of another scale ends a little off until then)."""
    w, h = 1500, 920
    if sys.platform == "win32":
        from . import tray
        place = read_json(PLACE, None)
        if tray.usable(place):
            s = tray.primary_scale()
            # maximized: as big as its screen from the start (the browser drops --start-maximized given a place), keep_place
            # then maximizes it, which only hides its edges
            box = (tray.work_area(place) or place) if place["max"] else place
            return [f"--window-position={round(box['x'] / s)},{round(box['y'] / s)}", f"--window-size={round(box['w'] / s)},{round(box['h'] / s)}"]
        try:
            import ctypes
            from ctypes import wintypes
            area = wintypes.RECT()
            ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(area), 0)  # SPI_GETWORKAREA
            if area.right - area.left < w + 40 or area.bottom - area.top < h + 40:
                return ["--start-maximized"]
        except (OSError, AttributeError):
            pass
    return [f"--window-size={w},{h}"]


def no_translate(profile: Path):
    """Turns off "Translate this page?" in our app-window profile (Edge ignores --disable-features=Translate)."""
    prefs_file = profile / "Default" / "Preferences"
    try:
        prefs = json.loads(prefs_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        prefs = {}
    if not isinstance(prefs, dict):
        prefs = {}
    tr = prefs.get("translate") if isinstance(prefs.get("translate"), dict) else {}
    if tr.get("enabled") is False:
        return
    prefs["translate"] = dict(tr, enabled=False)
    try:
        prefs_file.parent.mkdir(parents=True, exist_ok=True)
        prefs_file.write_text(json.dumps(prefs), encoding="utf-8")
    except OSError:
        pass


def keep_place(tray, wanted, path: Path = PLACE):
    """The window where it was closed. Edge keeps an app window's place under its address, and 127.0.0.1's dots lose
    it (it writes 127 -> 0 -> 0 -> 1_/ and reads 127.0.0.1_/), so WTFTD keeps it, then minimizes if asked."""
    window = None
    for _ in range(FIND_WINDOW_S * 2):
        time.sleep(0.5)
        window = tray.find_window()
        if window:
            break
    if not window:
        return
    last = read_json(path, None)
    if tray.usable(last):
        tray.put(window, last)
    if wanted("startMinimized"):
        tray.minimize()
    while tray.find_window() == window:  # until it's closed
        time.sleep(PLACE_S)
        now = tray.place_of(window)
        if now and now != last and tray.usable(now):
            write_json(path, now)
            last = now


def window_options(tray) -> object | None:
    """What the app window does on Windows, once it's open: start minimized, go to the notification area, close with the game."""
    wanted = lambda key: STATE.settings().get(key) is True

    def close_with_game():
        seen = False
        while True:
            time.sleep(GAME_CHECK_S)
            up = game_running()
            if seen and not up and wanted("closeWithGame"):
                tray.close()
            seen = up

    threading.Thread(target=keep_place, args=(tray, wanted), daemon=True).start()
    threading.Thread(target=close_with_game, daemon=True).start()
    icon = tray.Tray(lambda: wanted("trayMinimize"), WEB / "favicon.ico")
    icon.start()
    return icon


def main():
    if sys.stdout is None or (FROZEN and sys.platform == "darwin"):  # packaged app without a console: keep a log instead
        CACHE.mkdir(parents=True, exist_ok=True)
        sys.stdout = sys.stderr = open(CACHE / "wtftd.log", "w", encoding="utf-8", buffering=1)
    prepare()
    port = 8777
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    size = window_args()  # in logical pixels, like the browser's: before the overlay makes this process DPI-aware
    httpd, url = serve(port)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    print(f"WTFTD running at {url}  (Ctrl+C to quit)")

    exe = None if "--browser" in sys.argv or "--no-window" in sys.argv else find_app_browser()
    icon = None
    try:
        if exe:
            profile = ROOT / ".cache" / "app-window"
            # our dedicated profile: drop its favicon cache so a new app icon shows up in the taskbar
            for name in ("Favicons", "Favicons-journal"):
                try:
                    (profile / "Default" / name).unlink()
                except OSError:
                    pass
            no_translate(profile)
            proc = subprocess.Popen([exe, f"--app={url}", f"--user-data-dir={profile}", *size, *STAY_AWAKE,
                                     "--no-first-run", "--no-default-browser-check", "--disable-features=Translate"])
            if available():
                from . import tray
                icon = window_options(tray)
            if sys.platform == "darwin":
                # the browser outlives its closed window on macOS: quit when the page says bye
                while proc.poll() is None and not page_closed():
                    time.sleep(1)
                if proc.poll() is None:
                    proc.terminate()
            else:
                proc.wait()
                # window closed -> quit. But Edge may hand its window to another of its processes (first launch
                # with a new profile, an Edge already running in the background): the one started here then ends
                # at once while the window lives on, so keep serving while the page does (it says bye on closing)
                wait_page_gone()
        else:
            if "--no-window" not in sys.argv:
                webbrowser.open(url)
            if FROZEN and sys.platform == "darwin" and "--no-window" not in sys.argv:
                while not page_closed():  # WTFTD.app has no Dock icon: quit with the browser tab
                    time.sleep(1)
            else:
                threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        if icon:
            icon.stop()
        WATCH.stop()
        httpd.shutdown()


if __name__ == "__main__":
    main()
