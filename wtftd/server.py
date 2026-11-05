"""Local web server: static UI + JSON API + wiki image cache. Binds to 127.0.0.1 only."""
from __future__ import annotations

import copy
import json
import mimetypes
import os
import re
import shutil
import socket
import struct
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import DONATE, REPO, __version__, alarms, battle, bench, builder, cdk, challenges, flightlog, game, hangar, hud, maptex, mission, models, mods, patches, replays, sights, \
    terrain, uninstall, vromfs, waveout
from .paths import CACHE, DATA, HOME, USER, WEB

ROOT = HOME
IMG_CACHE = CACHE / "img"
MISSION_SETUPS = USER / "missions"
UA = "WTFTD/1.0 (local War Thunder test drive tool)"

IMAGE_SOURCES = {
    "unit": ("https://static.encyclopedia.warthunder.com/images/{}.png", ".png"),
    "flag": ("https://wiki.warthunder.com/static/country_svg/country_{}.svg", ".svg"),
    "ammo": ("https://static.encyclopedia.warthunder.com/gui_skin/{}.png", ".png"),
}
SAFE_ID = re.compile(r"^[A-Za-z0-9_\-.]{1,120}$")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("application/manifest+json", ".webmanifest")
mimetypes.add_type("image/x-icon", ".ico")


# --------------------------------------------------------------------------- state

class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.details: dict | None = None
        self.vehicles: dict | None = None
        self.catalog: dict | None = None
        self.units: dict | None = None
        self.update = {"running": False, "log": [], "error": None, "done": False,
                       "remote": None, "checked": 0, "before": None, "after": None}
        USER.mkdir(exist_ok=True)

    # settings -------------------------------------------------------------
    def settings(self) -> dict:
        s = read_json(USER / "settings.json", {})
        return s if isinstance(s, dict) else {}

    def save_settings(self, s: dict):
        write_json(USER / "settings.json", s)

    def game_dir(self) -> Path | None:
        custom = self.settings().get("gameDir")
        if custom and not on_network(custom):
            p = Path(custom).expanduser()
            return (game.resolve_game_dir(p) or p) if p.exists() else None
        return game.detect_game_dir()

    def unit_name(self, vid: str) -> str:
        """A vehicle's name as I18N.unit gives it on the page: the app's language, else English, else its id."""
        with self.lock:
            if self.units is None:
                lang = str(self.settings().get("lang") or "en")
                self.units = {**read_json(DATA / "lang" / "en.json", {}).get("units", {}),
                              **read_json(DATA / "lang" / f"{lang}.json", {}).get("units", {})}
            return self.units.get(vid, vid)

    def get_details(self) -> dict:
        with self.lock:
            if self.details is None:
                self.details = read_json(DATA / "details.json", {})
            return self.details

    def get_vehicles(self) -> dict:
        with self.lock:
            if self.vehicles is None:
                self.vehicles = {v["id"]: v for v in read_json(DATA / "vehicles.json", [])}
            return self.vehicles

    def get_catalog(self) -> dict:
        with self.lock:
            if self.catalog is None:
                self.catalog = read_json(DATA / "weapons.json", {})
            return self.catalog

    def data_source(self) -> str:
        return "game" if self.settings().get("dataSource") == "game" else "datamine"

    def cdk_enabled(self) -> bool:
        return self.settings().get("cdk", True) is not False

    def host_for(self, cat: str) -> str:
        hosts = self.settings().get("hosts") or {}
        return (hosts.get(cat) if isinstance(hosts, dict) else "") or cdk.DEFAULT_HOSTS.get(cat, "")

    def reload(self):
        with self.lock:
            self.details = None
            self.vehicles = None
            self.catalog = None
            self.units = None


STATE = State()


def read_json(path: Path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    tmp.replace(path)


BATTLES = CACHE / "battles.json"  # derived from the game's replays: goes with the cache
TEAMKILLS = USER / "teamkills.json"  # the player's own record: a replay can't rebuild it
CHALLENGES = USER / "challenges.json"
_battles_lock = threading.Lock()  # two pages open: one scan at a time, one writer
_challenges_lock = threading.Lock()  # the page, the game's watch


def battles() -> dict:
    """My battles: the player's own results, from the game's replays."""
    gd = STATE.game_dir()
    with _battles_lock:
        known = read_json(BATTLES, None)
        index = replays.refresh(gd / "Replays" if gd else None, known)
        if index != known:
            try:
                write_json(BATTLES, index)
            except OSError:  # a full disk, a locked file: read again next time
                pass
        listed = replays.listing(index)
        if gd and WATCH.killed_by:
            killers = [WATCH.killed_by.popleft() for _ in range(len(WATCH.killed_by))]
            filed, waiting = replays.teamkills(gd / "Replays", listed["rows"], killers)
            WATCH.killed_by.extend(waiting)
            if filed:
                write_json(TEAMKILLS, read_json(TEAMKILLS, []) + filed)
    with _challenges_lock:
        data = read_challenges()
        if challenges.merge(data, listed["rows"]):
            write_json(CHALLENGES, data)
    return {"game": gd is not None, **listed, "teamkills": read_json(TEAMKILLS, [])}


def read_challenges() -> dict:
    return challenges.clean(read_json(CHALLENGES, None))


def challenge_loop():
    """While the game is there, the objective of a challenge being played. Seconds apart: the game holds the result only for that long."""
    live = challenges.Live()
    while True:
        raw = _wt_get("/mission.json")
        try:
            with _challenges_lock:
                data = read_challenges()
                done = live.tick(raw, data["made"], time.time())
                if done:
                    challenges.add_result(data, done)
                    write_json(CHALLENGES, data)
        except Exception:  # never let the thread die
            pass
        time.sleep(1 if raw else 5)


# --------------------------------------------------------------------------- images

_img_locks: dict[str, threading.Lock] = {}
_img_locks_guard = threading.Lock()


def cached_image(kind: str, ident: str) -> Path | None:
    _, ext = IMAGE_SOURCES[kind]
    folder = IMG_CACHE / kind
    path = folder / f"{ident}{ext}"
    miss = folder / f"{ident}.missing"
    if path.exists():
        return path
    if miss.exists() and time.time() - miss.stat().st_mtime < 7 * 86400:
        return None
    with _img_locks_guard:
        lock = _img_locks.setdefault(f"{kind}/{ident}", threading.Lock())
    with lock:
        if path.exists():
            return path
        folder.mkdir(parents=True, exist_ok=True)
        for url in image_urls(kind, ident):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=15) as r:
                    body = r.read()
                if len(body) < 64:
                    continue
                tmp = path.with_suffix(".part")
                tmp.write_bytes(body)
                tmp.replace(path)
                return path
            except (urllib.error.URLError, OSError, TimeoutError, ValueError):
                continue
        try:
            miss.write_text("")
        except OSError:
            pass
        return None


def warm_weapon_icons():
    """The Weapons tab's icons (≈70, a few KB each) fetched in the background, a few at a time, so the page shows
    them at once: the browser asks 6 at a time, each one waiting for its download (≈4 s for the tab on a new install).
    Only once the game data is there (meta.json is written last): on a first install, after the welcome screen was
    accepted and the download done; run_update starts it again for the weapons of a new patch."""
    while not (DATA / "meta.json").exists():
        time.sleep(5)
    items = read_json(DATA / "armament.json", {}).get("items") or []
    todo = [ic for ic in sorted({it.get("ic") for it in items if isinstance(it, dict) and isinstance(it.get("ic"), str)})
            if SAFE_ID.match(ic) and not (IMG_CACHE / "ammo" / f"{ic}.png").exists()]
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda ic: cached_image("ammo", ic), todo))


def image_urls(kind: str, ident: str) -> list[str]:
    """Wiki image first, then variants and the game's own thumbnails (via the datamine)."""
    url_fmt, _ = IMAGE_SOURCES[kind]
    urls = [url_fmt.format(ident)]
    if kind == "unit":
        low = ident.lower()
        if low.startswith("nt_"):
            urls.append(url_fmt.format(low[3:]))
        tex = "https://raw.githubusercontent.com/gszabi99/War-Thunder-Datamine/master/tex.vromfs.bin_u/{}/{}.png"
        urls += [tex.format(folder, low) for folder in ("aircrafts", "tanks", "ships")]
        if low.startswith("nt_"):
            urls.append(tex.format("aircrafts", low[3:]))
    return urls


# --------------------------------------------------------------------------- app window presence
# macOS keeps the browser running when its last window is closed: the page says "bye" when it goes
# away, and any API call after that (a reload) cancels it. __main__ uses this to quit with the window.
PAGE = {"seen": 0.0, "bye": 0.0}


def page_closed(grace: float = 3.0) -> bool:
    return PAGE["bye"] > PAGE["seen"] and time.time() - PAGE["bye"] > grace


def wait_page_gone(first: float = 30.0, silence: float = 60.0):
    """Returns once the app page has closed (its "bye"), never loaded (first s) or went silent (silence s: it
    pings every 15 s)."""
    start = time.time()
    while True:
        seen = PAGE["seen"]
        if page_closed():
            return
        if not seen and time.time() - start > first:
            return
        if seen and time.time() - seen > silence:
            return
        time.sleep(1)


# --------------------------------------------------------------------------- API

def api_status():
    gd = STATE.game_dir()
    meta = read_json(DATA / "meta.json", {})
    um = game.user_missions_dir(gd) if gd else None
    return {
        "platform": sys.platform,
        "gameDir": str(gd) if gd else None,
        "gameFound": bool(gd),
        "steam": bool(gd and game.is_steam_install(gd)),
        "userMissions": str(um) if um else None,
        "levels": sorted(game.installed_levels(gd)),
        "data": meta,
        "dataReady": (DATA / "vehicles.json").exists(),
        "dataSource": STATE.data_source(),
        "gameSourceIssue": "python" if not vromfs.available() else None if gd else "game",
        "datamineCopy": builder.DATAMINE.is_dir(),
        "home": str(HOME),  # where WTFTD keeps its files (the welcome screen says so before the first download)
        "oodle": oodle_dll(gd),
        "settings": STATE.settings(),
        "alarms": alarms.available(),
        "cdk": {"enabled": STATE.cdk_enabled(), "defaultHosts": cdk.DEFAULT_HOSTS,
                "airMethod": STATE.settings().get("airMethod") or "custom",
                **cdk.status(gd, USER)},
    }


# --------------------------------------------------------------------------- new app version (GitHub releases)
_release = {"checked": 0.0, "latest": None}
RELEASE_CHECK_EVERY = 6 * 3600
APP_ASSET = {"win32": ".exe", "darwin": "-macos.zip"}  # release download of this platform


def _version_tuple(tag: str) -> tuple:
    m = re.match(r"v?(\d+)\.(\d+)(?:\.(\d+))?", tag or "")
    return tuple(int(x or 0) for x in m.groups()) if m else (0, 0, 0)


def app_version() -> dict:
    """This WTFTD's version and the latest published release (checked at most every 6 h)."""
    if time.time() - _release["checked"] > RELEASE_CHECK_EVERY:
        _release["checked"] = time.time()
        try:
            req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/releases?per_page=10",
                                         headers={"User-Agent": UA, "Accept": "application/vnd.github+json"})
            with urllib.request.urlopen(req, timeout=8) as r:
                releases = [x for x in json.load(r) if isinstance(x, dict) and not x.get("draft")]
            top = max(releases, key=lambda x: _version_tuple(x.get("tag_name", "")), default=None)
            if top:
                ext = APP_ASSET.get(sys.platform, ".exe")
                exe = next((a.get("browser_download_url") for a in top.get("assets", []) if str(a.get("name", "")).lower().endswith(ext)), None)
                _release["latest"] = {"tag": top.get("tag_name"), "name": top.get("name"), "url": top.get("html_url"), "exe": exe,
                                      "notes": (top.get("body") or "")[:2000]}
        except (urllib.error.URLError, OSError, ValueError, TimeoutError):
            pass  # offline / private repository: no alert
    latest = _release["latest"]
    newer = bool(latest and _version_tuple(latest["tag"]) > _version_tuple(__version__))
    return {"version": __version__, "repo": f"https://github.com/{REPO}", "latest": latest, "newer": newer}


_oodle_memo: dict = {}


# the page runs nothing but the app's own script files, and loads or sends nothing elsewhere: whatever a shared file holds
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' data: blob:; "
       "font-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


def on_network(path) -> bool:
    """A Windows network path (\\\\host\\share, //host/share): opening one reaches another machine."""
    return str(path or "")[:2] in ("\\\\", "//", "\\/", "/\\")


def oodle_dll(gd: Path | None) -> str | None:
    """Oodle runtime used to read the game's map textures: the one set in Settings, else auto-detected (once)."""
    custom = STATE.settings().get("oodleDll")
    if custom:
        custom = str(Path(custom).expanduser())
        return custom if not on_network(custom) and Path(custom).is_file() else None
    key = str(gd)
    if key not in _oodle_memo:
        _oodle_memo[key] = maptex.find_oodle(gd)
    return _oodle_memo[key]


def api_vehicle(vid: str):
    d = STATE.get_details().get(vid)
    if d is None:
        return None
    return d


def game_up() -> bool:
    """The game is running, where the app can tell (Windows)."""
    return alarms.available() and alarms.game_running()


def vehicle_ids():
    return STATE.get_details().keys()


def mods_status() -> dict:
    gd = STATE.game_dir()
    if not gd:
        return {"game": False, "skins": [], "sounds": [], "sound": {}, "running": False}
    return {"game": True, "skins": mods.skins(gd, vehicle_ids()), "sounds": mods.sounds(gd), "sound": mods.sound_state(gd), "running": game_up(),
            "allowed": {k: sorted(v) for k, v in mods.ALLOWED.items()}}


def list_generated():
    gd = STATE.game_dir()
    if not gd:
        return []
    um = game.user_missions_dir(gd)
    out = []
    if um.exists():
        for p in sorted(um.glob("wtftd_*.blk"), key=lambda p: -p.stat().st_mtime):
            # the vehicle comes from the saved setup: the file name may have been changed in Advanced
            setup = read_json(MISSION_SETUPS / f"{p.stem}.json", None)
            vid = setup.get("vehicle") if isinstance(setup, dict) else None
            out.append({"file": p.name, "mtime": int(p.stat().st_mtime), "size": p.stat().st_size,
                        "vehicle": vid if isinstance(vid, str) else None})
    return out


REMOTE_VERSION_URL = "https://raw.githubusercontent.com/gszabi99/War-Thunder-Datamine/master/version"
AUTO_CHECK_EVERY = 3 * 3600  # seconds


def run_update():
    st = STATE.update
    before = read_json(DATA / "meta.json", {})
    st.update(running=True, log=[], error=None, done=False, before=before.get("version"), after=None, progress=0.0)

    class Progress:
        def __call__(self, msg):
            st["log"].append(msg)
            st["log"] = st["log"][-200:]

        def set_frac(self, frac):
            st["progress"] = max(st.get("progress") or 0.0, frac)  # never goes backwards

    progress = Progress()

    try:
        meta = builder.build(pull=True, progress=progress, source=STATE.data_source(), game_dir=STATE.game_dir())
        STATE.reload()
        # vehicles added since last build may now have a wiki image: retry the ones marked missing
        for miss in (IMG_CACHE / "unit").glob("*.missing"):
            try:
                miss.unlink()
            except OSError:
                pass
        st["after"], st["source"] = meta.get("version"), meta.get("source")
        st["newVehicles"] = max(0, int(meta.get("vehicles", 0)) - int(before.get("vehicles", 0) or 0))
        st["patch"], st["changes"] = meta.get("patch"), meta.get("changes", 0)
        st["done"], st["available"] = True, False
        threading.Thread(target=warm_weapon_icons, daemon=True).start()  # weapons new in this patch
    except Exception as e:  # report any builder failure to the UI
        st["error"] = str(e)
    finally:
        st["running"] = False


def remote_version() -> str | None:
    """The newest game data there is: the installed game's version, or the published datamine's."""
    if STATE.data_source() == "game":
        gd = STATE.game_dir()
        try:
            return vromfs.version(gd) if gd else None
        except vromfs.VromfsError:  # mid-update: the next check sees it
            return None
    try:
        req = urllib.request.Request(REMOTE_VERSION_URL, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=10) as r:
            v = r.read(64).decode("utf-8", "ignore").strip()
        return v if re.fullmatch(r"[0-9.]+", v) else None
    except (urllib.error.URLError, OSError, TimeoutError, ValueError):
        return None


def check_for_update(start: bool = True) -> dict:
    """Compares the game data's version (remote_version) with ours; rebuilds in the background when it changed."""
    st = STATE.update
    remote = remote_version()
    st["remote"], st["checked"] = remote, int(time.time())
    meta = read_json(DATA / "meta.json", {})
    local = meta.get("version")
    # newer game patch, data built by an older WTFTD that lacks fields this version needs, or from the other source
    st["available"] = (bool(remote and remote != local) or (bool(meta) and meta.get("schema", 1) < builder.SCHEMA)
                       or (bool(meta) and meta.get("source", "datamine") != STATE.data_source()))
    # a first install (no data yet) downloads only once the user agreed on the welcome screen (route "update")
    if start and st["available"] and meta and not st["running"]:
        threading.Thread(target=run_update, daemon=True).start()
    return st


def auto_check():
    auto = STATE.settings().get("autoUpdate", True) is not False
    # automatic updates off: the installed game is still looked at (a local read), so the page can offer the update
    if (auto or STATE.data_source() == "game") and not STATE.update["running"]:
        check_for_update(start=auto)


def auto_update_loop():
    time.sleep(4)
    while True:
        auto_check()
        time.sleep(AUTO_CHECK_EVERY)


# --------------------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    server_version = "WTFTD"

    def log_message(self, fmt, *args):  # quiet
        pass

    # helpers --------------------------------------------------------------
    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_game_bytes(self, body: bytes | None):
        """What the viewer reads from the player's install: never stored, by the app or by the page."""
        if body is None:
            return self.send_json({"error": "no model"}, 404)
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path: Path, cache=False):
        try:
            body = path.read_bytes()
        except OSError:
            return self.send_error(HTTPStatus.NOT_FOUND)
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/json", "text/javascript"):
            ctype += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, max-age=2592000, immutable" if cache else "no-cache")
        if ctype.startswith("text/html"):
            self.send_header("Content-Security-Policy", CSP)
        self.end_headers()
        self.wfile.write(body)

    def read_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 2_000_000:
            raise ValueError("Body too large")
        raw = self.rfile.read(n) if n else b"{}"
        return json.loads(raw.decode("utf-8") or "{}")

    def local_origin(self) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0]
        origin = self.headers.get("Origin")
        if host not in ("127.0.0.1", "localhost"):
            return False
        if origin and urlparse(origin).hostname not in ("127.0.0.1", "localhost"):
            return False
        return True

    # GET ------------------------------------------------------------------
    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        if path.startswith("/api/"):
            # reads expose settings, setups and paths: only for this app's own page (blocks DNS rebinding)
            if not self.local_origin():
                return self.send_json({"error": "forbidden"}, 403)
            PAGE["seen"] = time.time()
            return self.get_api(path[5:])
        if path.startswith("/img/levelmap/"):
            meta = captured_map(path.rsplit("/", 1)[-1])
            if meta:
                return self.send_file(MAPS / meta["file"])
            return self.send_error(HTTPStatus.NOT_FOUND)
        if path.startswith("/img/terrain/"):
            level = path.rsplit("/", 1)[-1].removesuffix(".bin")
            if re.fullmatch(r"[a-z0-9_]+", level) and terrain.grid_path(level).exists():
                return self.send_file(terrain.grid_path(level), cache=True)
            return self.send_error(HTTPStatus.NOT_FOUND)
        if path.startswith("/img/mapthumb/"):  # the maps tab's pictures: a small copy of the map
            name = path.rsplit("/", 1)[-1].removesuffix(".png")
            try:
                gd = STATE.game_dir()
                return self.send_file(maptex.thumb_path(gd, name, oodle_dll(gd)), cache=True)
            except (maptex.MapTexError, OSError) as e:
                return self.send_json({"error": str(e)}, 404)
        if path.startswith("/img/maptex/"):
            name = path.rsplit("/", 1)[-1].removesuffix(".png")
            try:
                gd = STATE.game_dir()
                return self.send_file(maptex.png_path(gd, name, oodle_dll(gd)), cache=True)
            except (maptex.MapTexError, OSError) as e:
                return self.send_json({"error": str(e)}, 404)
        if path.startswith("/img/"):
            parts = path.split("/")
            if len(parts) == 4 and parts[2] in IMAGE_SOURCES:
                ident = parts[3].rsplit(".", 1)[0]
                if SAFE_ID.match(ident):
                    p = cached_image(parts[2], ident)
                    if p:
                        return self.send_file(p, cache=True)
            self.send_response(404)
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            return
        if path.startswith("/data/"):
            rel = path[6:]
            target = (DATA / rel).resolve()
            if DATA.resolve() in target.parents and target.suffix == ".json" and "scenarios" not in target.parts:
                return self.send_file(target)
            return self.send_error(HTTPStatus.NOT_FOUND)
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        target = (WEB / rel).resolve()
        if WEB.resolve() not in target.parents or not target.is_file():
            return self.send_error(HTTPStatus.NOT_FOUND)
        return self.send_file(target)

    def get_api(self, route: str):
        if route == "ping":  # the app page is alive (every 15 s)
            return self.send_json({"ok": True})
        if route == "status":
            return self.send_json(api_status())
        if route.startswith("vehicle/"):
            vid = route.split("/", 1)[1]
            d = api_vehicle(vid) if SAFE_ID.match(vid) else None
            return self.send_json(d) if d is not None else self.send_json({"error": "not found"}, 404)
        if route == "sights":  # custom tank sights: the game's UserSights and WTFTD's library
            return self.send_json(sights.list_sights(USER))
        if route == "setups":
            return self.send_json(read_json(USER / "setups.json", []))
        if route == "variants":  # scenario variants saved from the map editor
            return self.send_json(read_json(USER / "variants.json", []))
        if route == "combos":  # saved missions: a vehicle setup + a map
            return self.send_json(read_json(USER / "combos.json", []))
        if route == "overlay":
            return self.send_json(overlay_status())
        if route.startswith("overlay/"):
            return self.send_json(overlay_status(route.split("/", 1)[1]))
        if route.startswith("battle/"):  # battle/<last chat id>/<last event>/<last damage>
            ids = route.split("/")[1:]
            if len(ids) == 3 and all(x.isdecimal() for x in ids):
                seen = battle.news(_wt_get, *map(int, ids))
                if STATE.settings().get("battleLog") is True:
                    ARCHIVE.add(seen)
                return self.send_json(seen)
            return self.send_json({"error": "not found"}, 404)
        if route == "battles":
            return self.send_json(battles())
        if route == "challenges":
            battles()  # the replays' results first
            return self.send_json({"list": challenges.catalog(), "results": read_challenges()["results"]})
        if route == "hangar":
            return self.send_json(hangar.load())
        if route == "mods":
            return self.send_json(mods_status())
        if route.startswith("mods/skin/"):  # a skin's texture, for the 3D view
            folder, _, file = route[len("mods/skin/"):].partition("/")
            gd = STATE.game_dir()
            path = mods.skin_file(gd, folder, file) if gd else None
            return self.send_game_bytes(path.read_bytes() if path else None)
        if route == "changes":
            return self.send_json(patches.index())
        if route.startswith("changes/"):
            rows = patches.rows(route.split("/", 1)[1])
            return self.send_json(rows) if rows is not None else self.send_json({"error": "not found"}, 404)
        if route.startswith("hud/"):  # the cockpit window's HUD, filling a window of that size: hud/<width>x<height>
            return self.send_json(hud_status(route.split("/", 1)[1]))
        if route.startswith("flight/"):
            return self.send_json(flight_status(int(route.split("/", 1)[1]) if route.split("/", 1)[1].isdecimal() else 0))
        if route == "bench":
            return self.send_json({**bench.load(), "game": read_json(DATA / "meta.json", {}).get("version", "")})
        if route == "bench-live":
            return self.send_json(BENCH.status())
        if route == "flight-logs":
            return self.send_json(flightlog.list_logs(LOGS))
        if route.startswith("flight-logs/"):
            name, _, what = route.split("/", 1)[1].partition("/")
            names = {alarms.column(n): n for n in alarms.SERIES}
            if what == "acmi":  # the flight as a Tacview file
                log = flightlog.read_log(LOGS, name, {**names, **dict(zip(alarms.POSITION, ("east", "north", "hdg")))})
                text = log and flightlog.acmi(log["rows"], name.rsplit("-", 1)[0], flightlog.started(LOGS, name))
                if text is None:
                    return self.send_json({"error": "This log has no position: record a new flight."}, 404)
                body = text.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="{name[:-4]}.txt.acmi"')
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                return self.wfile.write(body)
            log = flightlog.read_log(LOGS, name, names)
            if log is None:
                return self.send_json({"error": "not found"}, 404)
            return self.send_json({**log, "report": flightlog.report(log["rows"])})
        if route == "myweapons":  # My weapons: modified copies of the game's pylon weapons
            return self.send_json(read_json(USER / "weapons.json", []))
        if route == "weapon-keys":  # Weapons tab rows -> the pylon weapon they can be modified from
            return self.send_json(weapon_keys())
        if route.startswith("weapon-base/"):  # a pylon weapon's own values, for the weapon editor
            base = weapon_base(route.split("/", 1)[1])
            return self.send_json(base) if base else self.send_json({"error": "Weapon not found in the game data"}, 404)
        if route == "missions":
            return self.send_json(list_generated())
        if route.startswith("terrain/"):
            level = route.split("/", 1)[1]
            gd = STATE.game_dir()
            try:
                meta = terrain.terrain(gd, level, oodle_dll(gd))
            except (terrain.TerrainError, OSError, struct.error) as e:
                return self.send_json({"available": False, "reason": str(e)})
            if not meta:
                return self.send_json({"available": False, "reason": "no heightmap"})
            return self.send_json({**meta, "available": True,
                                   "url": f"/img/terrain/{level}.bin?v={int(terrain.grid_path(level).stat().st_mtime)}"})
        if route == "app-version":
            return self.send_json(app_version())
        if route.startswith("level-map/"):
            meta = level_map(route.split("/", 1)[1])
            return self.send_json(meta) if meta else self.send_json({"error": "no map"}, 404)
        if route.startswith("model/"):  # read from the player's install, for the viewer only (models.py)
            kind, _, ref = route[6:].partition("/")
            gd = STATE.game_dir()
            name = ref if kind in ("name", "ri") else models.vehicle_model(ref)  # a name is only ever looked up in the game's own list
            return self.send_game_bytes(models.read(gd, name, kind == "ri") if gd and name else None)
        if route.startswith(("model-texture/", "model-texture-low/")):
            gd = STATE.game_dir()
            kind, name = route.split("/", 1)
            return self.send_game_bytes(models.texture(gd, name, kind == "model-texture") if gd else None)
        if route.startswith("model-variants/"):
            gd = STATE.game_dir()
            return self.send_json(models.variants(gd, route.split("/", 1)[1]) if gd else [])
        if route.startswith("level-info/"):
            return self.send_json(models.level_info(route.split("/", 1)[1]))
        if route.startswith(("level-objects/", "level-land/", "level-tracer/")):
            gd = STATE.game_dir()
            kind, level = route.split("/", 1)
            read = {"level-objects": models.level_objects, "level-land": models.level_land, "level-tracer": models.level_tracer}[kind]
            return self.send_game_bytes(read(gd, level) if gd else None)
        if route.startswith("asset/"):
            gd = STATE.game_dir()
            return self.send_json(models.asset(gd, route.split("/", 1)[1]) if gd else [])
        if route.startswith("level-ground/"):
            gd = STATE.game_dir()
            return self.send_json((models.level_ground(gd, route.split("/", 1)[1]) if gd else None) or {})
        if route.startswith("scenario-units/"):
            try:
                return self.send_json(mission.scenario_units(route.split("/", 1)[1]))
            except mission.MissionError as e:
                return self.send_json({"error": str(e)}, 404)
        if route.startswith("mission-setup/"):
            f = route.split("/", 1)[1]
            if not re.fullmatch(r"wtftd_[A-Za-z0-9_\-]+", f):
                return self.send_json({"error": "bad name"}, 400)
            return self.send_json(read_json(MISSION_SETUPS / f"{f}.json", None))
        if route == "update":
            return self.send_json(STATE.update)
        if route == "uninstall-info":  # Settings → Uninstall: what WTFTD put on this PC
            return self.send_json(uninstall.info(STATE.game_dir()))
        return self.send_json({"error": "unknown route"}, 404)

    # POST -----------------------------------------------------------------
    def do_POST(self):
        if not self.local_origin():
            return self.send_json({"error": "forbidden"}, 403)
        route = urlparse(self.path).path[5:] if self.path.startswith("/api/") else ""
        if route == "bye":  # the app page is closing (navigator.sendBeacon)
            PAGE["bye"] = time.time()
            return self.send_json({"ok": True})
        PAGE["seen"] = time.time()
        if route == "mods/upload":  # the one body that can be large: a stream with limits of its own, not read_body's
            return self.mods_upload()
        try:
            body = self.read_body()
        except ValueError as e:
            return self.send_json({"error": str(e)}, 400)
        try:
            return self.post_api(route, body)
        except mission.MissionError as e:
            return self.send_json({"error": str(e)}, 400)
        except mods.ModsError as e:
            return self.send_json({"error": e.code, "code": e.code, "name": e.name}, 400)
        except OSError as e:
            return self.send_json({"error": f"File error: {e}"}, 500)

    def mods_action(self, action: str, body: dict):
        """Every step comes from a click of the player: the page sends nothing on its own."""
        gd = STATE.game_dir()
        if action == "forget":
            mods.forget(body.get("token"))
            return self.send_json({"ok": True})
        if not gd:
            raise mods.ModsError("noGame")
        if action == "inspect":
            return self.send_json(mods.inspect(body.get("token"), body.get("kind"), vehicle_ids()))
        if action == "install":
            mods.install(gd, body.get("token"), body.get("kind"), body.get("vehicles"), vehicle_ids(), game_up())
        elif action == "remove":
            mods.remove(gd, body.get("kind"), body.get("name"), game_up())
        elif action == "sound":
            mods.set_sound(gd, body.get("on") is True, game_up())
        elif action == "open":
            target = gd / mods.SKINS if body.get("kind") == "skin" else gd.joinpath(*mods.SOUNDS)
            name = body.get("name")
            if body.get("kind") == "skin" and name:
                target = gd / mods.SKINS / mods.safe_path(name)[0]
            target.mkdir(parents=True, exist_ok=True)
            game.open_folder(target)
        else:
            return self.send_json({"error": "unknown route"}, 404)
        return self.send_json(mods_status())

    def mods_upload(self):
        q = parse_qs(urlparse(self.path).query)
        one = lambda k: (q.get(k) or [""])[0]  # noqa: E731
        try:
            length = int(self.headers.get("Content-Length") or -1)
        except ValueError:
            length = -1
        try:
            mods.receive(one("token"), one("path"), self.rfile, length, one("kind"))
        except mods.ModsError as e:
            while length > 0:  # the page reads an answer only once it has sent all it had; a refusal comes before reading any of it
                chunk = self.rfile.read(min(length, 1 << 20))
                if not chunk:
                    break
                length -= len(chunk)
            return self.send_json({"error": e.code, "code": e.code, "name": e.name}, 400)
        except OSError as e:
            return self.send_json({"error": f"File error: {e}"}, 500)
        return self.send_json({"ok": True})

    def post_api(self, route: str, body: dict):
        if route.startswith("mods/"):
            return self.mods_action(route[5:], body)
        if route == "level-cells":  # the page has read the level's table, the unpacking needs zstd
            gd = STATE.game_dir()
            return self.send_game_bytes(models.level_cells(gd, str(body.get("level")), int(body.get("start") or 0), body.get("cells") or []) if gd else None)
        if route == "generate":
            gd = STATE.game_dir()
            if not gd:
                return self.send_json({"error": "War Thunder folder not found. Set it in Settings."}, 400)
            if body.get("challenge"):
                body = challenges.plan(body, STATE.get_vehicles())
            setup = dict(body)
            body, files = self.prepare_cdk(body)
            name, text = mission.build(body)
            if files:
                cdk.write_files(gd, USER, files, body.get("_pkg", "pkg_local"))
            for pkg, ai_files in (body.get("_aiFiles") or {}).items():  # AI units with loadouts of their own
                cdk.write_files(gd, USER, ai_files, pkg)
            # keep the exact setup next to the mission so "Load" can restore it
            write_json(MISSION_SETUPS / (name[:-4] + ".json"), setup)
            try:
                su = mission.scenario_units(str(body.get("scenario", "")))
                me = next((u for u in su["units"] if u.get("player")), None)
                pl = (body.get("edits") or {}).get("player") or {}
                if me:
                    set_capture_hint(su["level"], float(pl.get("x", me["x"])), float(pl.get("z", me["z"])))
            except (mission.MissionError, ValueError, TypeError):
                pass
            WATCH.mission = {"id": str(body.get("vehicle", "")),  # mods only apply to custom vehicles (files)
                             "fuel": cdk._num(body.get("mods") or {}, "fuel", 0, 1_000_000) if files else None,
                             "unbreakable": bool(files and (body.get("cheats") or {}).get("noOverload"))}
            BENCH.arm(body.get("bench"))
            um = game.user_missions_dir(gd)
            um.mkdir(exist_ok=True)
            out = um / name
            out.write_text(text, encoding="utf-8")
            if body.get("challenge"):
                with _challenges_lock:
                    data = read_challenges()
                    challenges.remember(data, body)
                    write_json(CHALLENGES, data)
            ai_names = [k for f in (body.get("_aiFiles") or {}).values() for k in f]
            sight = install_sight(body)
            return self.send_json({"ok": True, "file": name, "path": str(out), "cdkFiles": sorted(files) + sorted(ai_names),
                                   "host": body.get("unitClass", ""), **({"sight": sight} if sight else {})})
        if route == "preview":
            body, files = self.prepare_cdk(body)
            name, text = mission.build(body)
            pkg = body.get("_pkg", "pkg_local")
            shown = {f"{pkg}/{k}": v for k, v in files.items()}
            for ai_pkg, ai_files in (body.get("_aiFiles") or {}).items():
                shown.update({f"{ai_pkg}/{k}": v for k, v in ai_files.items()})
            return self.send_json({"file": name, "text": text, "files": shown})
        if route == "sight-import":  # a sight file the player picked (.blk text) into WTFTD's library
            try:
                return self.send_json({"id": sights.import_sight(USER, str(body.get("name", "")), body.get("text")),
                                       **sights.list_sights(USER)})
            except sights.SightError as e:
                return self.send_json({"error": str(e)}, 400)
        if route == "cdk-cleanup":
            gd = STATE.game_dir()
            removed = (cdk.cleanup(gd, USER) if gd else 0) + sights.cleanup(USER)
            return self.send_json({"removed": removed, **api_status()})
        if route == "launch":
            how = game.launch(STATE.game_dir())
            return self.send_json({"ok": True, "via": how})
        if route == "open-url":  # release page / issue forms / donation page of this project only
            url = str(body.get("url", ""))
            if url.startswith(f"https://github.com/{REPO}/") or url == DONATE:
                import webbrowser
                webbrowser.open(url)
                return self.send_json({"ok": True})
            return self.send_json({"error": "forbidden"}, 403)
        if route == "open-folder":
            gd = STATE.game_dir()
            if gd:
                um = game.user_missions_dir(gd)
                um.mkdir(exist_ok=True)
                game.open_folder(um)
            return self.send_json({"ok": bool(gd)})
        if route == "settings":
            s = STATE.settings()
            for k in ("gameDir", "lang", "missionType", "theme", "cdk", "hosts", "airMethod", "autoUpdate", "oodleDll", "dataSource",
                      "audioDevice", "battleLog", "startMinimized", "trayMinimize", "closeWithGame"):
                if k in body:
                    s[k] = body[k]
            if on_network(s.get("gameDir")) or on_network(s.get("oodleDll")):  # what the app runs and loads stays on this PC
                return self.send_json({"error": "Pick something on this PC, not on a network path."}, 400)
            if s.get("gameDir") and not game.resolve_game_dir(Path(s["gameDir"]).expanduser()):
                return self.send_json({"error": "This folder does not look like a War Thunder install."}, 400)
            if s.get("oodleDll") and maptex.oodle_version(Path(s["oodleDll"]).name) is None:
                return self.send_json({"error": "Pick an Oodle runtime file: oo2core_<version>_win64.dll (Windows) or liboo2core*.dylib (macOS)."}, 400)
            if s.get("dataSource", "datamine") not in ("datamine", "game"):
                return self.send_json({"error": "Unknown game data source."}, 400)
            if body.get("dataSource") == "game" and not vromfs.available():
                return self.send_json({"error": vromfs.NO_ZSTD}, 400)
            STATE.save_settings(s)
            apply_alarm_settings()
            return self.send_json(api_status())
        if route == "overlay":  # My overlay: every change is saved, the window follows at once; reset: the defaults
            key = str(body.get("profile") or "")
            if key and not alarms.PROFILE.fullmatch(key):
                return self.send_json({"error": "Invalid profile"}, 400)
            s = STATE.settings()
            cfg = None if body.get("reset") else alarms.clean(body.get("cfg"), WATCH.words)
            if key:
                profiles = s["overlayProfiles"] = s.get("overlayProfiles") if isinstance(s.get("overlayProfiles"), dict) else {}
                profiles[key] = cfg or alarms.defaults(WATCH.words)
            elif cfg:
                s["overlay"] = cfg
            else:
                s.pop("overlay", None)
            if "enabled" in body:
                s["alarms"] = body["enabled"] is True
            STATE.save_settings(s)
            apply_alarm_settings()
            if WATCH.preview:
                WATCH.set_preview(WATCH.profiles.get(key, WATCH.base), key)
            return self.send_json(overlay_status(key))
        if route == "overlay-profile-delete":
            s = STATE.settings()
            if isinstance(s.get("overlayProfiles"), dict):
                s["overlayProfiles"].pop(str(body.get("profile")), None)
            STATE.save_settings(s)
            apply_alarm_settings()
            return self.send_json(overlay_status())
        if route == "bench-stop":  # the test ends here: what was flown is analysed
            BENCH.arm(None)
            return self.send_json({**bench.load(), **BENCH.status()})
        if route == "bench-delete":
            return self.send_json(bench.remove(str(body.get("id", ""))))
        if route == "flight-log":  # record the flight data to a CSV file, or stop
            WATCH.set_log(body.get("on") is True)
            return self.send_json(flight_status(10 ** 12))
        if route == "flight-log-delete":
            return self.send_json({"ok": flightlog.delete_log(LOGS, str(body.get("name", ""))),
                                   "logs": flightlog.list_logs(LOGS)})
        if route == "flight-logs-open":
            LOGS.mkdir(parents=True, exist_ok=True)
            game.open_folder(LOGS)
            return self.send_json({"ok": True})
        if route == "overlay-preview":  # show it on the screen now, without the game
            on = alarms.available() and body.get("on") is True
            WATCH.set_preview(WATCH.profiles.get(str(body.get("profile") or ""), WATCH.base) if on else None, str(body.get("profile") or ""))
            return self.send_json(overlay_status(str(body.get("profile") or "")))
        if route == "overlay-test":  # hear an alarm, or a line's own alert
            cfg, line = WATCH.profiles.get(str(body.get("profile") or ""), WATCH.base), body.get("line")
            a = cfg["lines"][line]["rule"] if type(line) is int and 0 <= line < len(cfg["lines"]) else cfg["alarms"].get(str(body.get("alarm")))
            if a and alarms.available():
                alarms.play(a, cfg["volume"], SOUNDS)
            return self.send_json({"ok": bool(a)})
        if route == "sound-import":  # a .wav the player picked, for the alarms
            try:
                return self.send_json({"file": alarms.save_sound(SOUNDS, str(body.get("name", "")), str(body.get("data", ""))),
                                       "sounds": alarms.sound_list(SOUNDS)})
            except ValueError as e:
                return self.send_json({"error": str(e)}, 400)
        if route == "combos":
            if not isinstance(body.get("combos"), list):
                return self.send_json({"error": "combos must be a list"}, 400)
            write_json(USER / "combos.json", [c for c in body["combos"] if isinstance(c, dict)][:500])
            return self.send_json({"ok": True})
        if route == "myweapons":
            if not isinstance(body.get("weapons"), list):
                return self.send_json({"error": "weapons must be a list"}, 400)
            write_json(USER / "weapons.json", [w for w in body["weapons"] if isinstance(w, dict)][:500])
            return self.send_json({"ok": True})
        if route == "variants":
            if not isinstance(body.get("variants"), list):
                return self.send_json({"error": "variants must be a list"}, 400)
            write_json(USER / "variants.json", [v for v in body["variants"] if isinstance(v, dict)][:500])
            return self.send_json({"ok": True})
        if route == "hangar":
            return self.send_json(hangar.save(body))
        if route == "setups":
            if not isinstance(body.get("setups"), list):
                return self.send_json({"error": "setups must be a list"}, 400)
            write_json(USER / "setups.json", body["setups"][:500])
            return self.send_json({"ok": True})
        if route == "delete-mission":
            gd = STATE.game_dir()
            f = str(body.get("file", ""))
            if gd and re.fullmatch(r"wtftd_[A-Za-z0-9_\-]+\.blk", f):
                p = game.user_missions_dir(gd) / f
                if p.exists():
                    p.unlink()
                (MISSION_SETUPS / (f[:-4] + ".json")).unlink(missing_ok=True)
            return self.send_json(list_generated())
        if route == "uninstall":
            parts = [p for p in (body.get("parts") or []) if p in uninstall.PARTS]
            res = uninstall.run(parts, STATE.game_dir(), game_up())
            if res["quit"]:  # the app goes: the page shows its goodbye, then WTFTD closes its window and quits
                def leave():
                    uninstall.close_app_window()  # its files would stay locked in WTFTD's folder
                    os._exit(0)
                threading.Timer(2.5, leave).start()
            elif "data" in parts:
                STATE.reload()
            return self.send_json(res)
        if route == "remove-datamine":  # never on its own: the player asked, and the data no longer comes from it
            if builder.DM == builder.DATAMINE or STATE.update["running"]:
                return self.send_json({"error": "The game data still needs the datamine copy."}, 400)
            builder.remove_datamine()
            return self.send_json(api_status())
        if route == "update-check":
            return self.send_json(check_for_update(start=bool(body.get("start", True))))
        if route == "update":
            if not STATE.update["running"]:
                threading.Thread(target=run_update, daemon=True).start()
            return self.send_json(STATE.update)
        return self.send_json({"error": "unknown route"}, 404)


def _ammo_groups(det: dict) -> list:
    """A vehicle's ammo groups as mission.write_bullets wants them (aircraft: weapon tags too; ground: the set each
    weapon starts on and its load)."""
    keys = {"armada": ("p", "n", "trig"), "tankModels": ("n", "trig", "cap")}.get(det.get("b"), ("n", "trig"))
    out = [{k: g[k] for k in keys if k in g} for g in det.get("am") or [] if isinstance(g, dict)]
    if det.get("b") == "tankModels":
        for e, g in zip(out, det.get("am") or []):
            e["set"] = next((o["id"] for o in g.get("opts") or [] if not o.get("x")), "")
    return out


def _prepare_ai(body: dict) -> tuple[dict, dict]:
    """Loadouts of the map editor's units (AI): their ammo groups, and for an aircraft / helicopter with
    pylons of its own, a custom aircraft of its own (CDK, "custom" method). Returns (mission cfg, {package:
    files})."""
    edits = body.get("edits")
    if not isinstance(edits, dict):
        return body, {}
    edits = copy.deepcopy(edits)  # the saved setup keeps what the app sent
    body = dict(body, edits=edits)
    entries = [e for e in list((edits.get("units") or {}).values()) + list(edits.get("add") or []) if isinstance(e, dict)]
    out: dict = {}
    n = 0
    for e in entries:
        lo = e.get("loadout")
        if not isinstance(lo, dict):
            continue
        vid = str(lo.get("vehicle") or e.get("cls") or "")
        veh, det = STATE.get_vehicles().get(vid), STATE.get_details().get(vid)
        if not veh or not isinstance(det, dict):
            e.pop("loadout")
            continue
        lo["_groups"] = _ammo_groups(det)
        pylons = lo.get("pylons")
        if not (pylons and isinstance(pylons, dict) and STATE.cdk_enabled() and veh["c"] in ("air", "heli")
                and (STATE.settings().get("airMethod") or "custom") == "custom"):
            lo.pop("pylons", None)
            continue
        n += 1
        pylons = custom_weapons(pylons)
        non_std = any(isinstance(v, dict) for v in pylons.values())
        try:
            files, preset, unit_class, pkg = cdk.build_files(
                vid, veh["c"], det, {}, "", pylons, "custom", builder.load(builder.unit_file(vid, veh["c"])) if non_std else None,
                STATE.get_catalog(), tag=f"{vid}_ai{n}")
        except cdk.CdkError:
            lo.pop("pylons", None)
            continue
        out.setdefault(pkg, {}).update(files)
        lo["_unitClass"] = unit_class
        if preset:
            lo["preset"] = preset
    return body, out


def custom_weapons(pylons: dict) -> dict:
    """Pylons holding one of My weapons ({"cw": id}) get its current changes: edited after being put on a pylon,
    the weapon flies as it is now. One deleted since keeps the changes saved with the pylon."""
    mine = {w.get("id"): w for w in read_json(USER / "weapons.json", []) if isinstance(w, dict)}
    out = {}
    for k, v in pylons.items():
        cw = mine.get(v.get("cw")) if isinstance(v, dict) else None
        out[k] = dict(v, w=cw.get("w", v.get("w")), mod=cw.get("mod") or {}) if cw else v
    return out


# the editor's fields: (payload block key, its path in the weapon file's payload block)
WEAPON_BASE_FIELDS = {"e": ("explosiveMass",), "mass": ("mass",), "force": ("force",), "burn": ("timeFire",),
                      "mach": ("machMax",), "fins": ("finsLatAccel",), "range": ("maxDistance",),
                      "g": ("loadFactorMax",), "gReq": ("guidance", "guidanceAutopilot", "reqAccelMax"), "kt": ("yield",)}


def weapon_tree(node: dict, path: str = "") -> list:
    """Every value of a weapon file the advanced editor can change: [[path, type, value]], types as in a .blk
    (r real, i integer, b bool, t text, p2-p4 points). Repeated blocks / values (lists) are left out: an override
    can't tell them apart."""
    out = []
    for k, v in node.items():
        if not cdk.ADV_KEY.match(str(k)):
            continue
        p = f"{path}/{k}" if path else k
        if isinstance(v, dict):
            out += weapon_tree(v, p)
        elif isinstance(v, bool):
            out.append([p, "b", v])
        elif isinstance(v, int):
            out.append([p, "i", v])
        elif isinstance(v, float):
            out.append([p, "r", v])
        elif isinstance(v, str):
            if cdk.ADV_TEXT.match(v):
                out.append([p, "t", v])
        elif (isinstance(v, list) and 2 <= len(v) <= 4 and all(isinstance(x, float) for x in v)):
            out.append([p, f"p{len(v)}", v])
    return out


_weapon_keys: dict = {"for": None, "map": {}}


def weapon_keys() -> dict:
    """{Weapons tab id: pylon catalog key}. A Weapons tab row is named after its projectile (bulletName, e.g.
    "pl_5e2"), the catalog after its file ("su_pl5e2"): read once from the local game files (0.3 s), again after an
    update. Files that aren't "_default" variants win."""
    catalog = STATE.get_catalog()
    if _weapon_keys["for"] is not catalog:
        out: dict = {}
        for key, w in catalog.items():
            folder = str(w.get("p", "")).replace("\\", "/").split("/")[-2].lower()
            payload = "rocket" if w.get("air") else cdk.PAYLOADS.get(folder)
            if w.get("pod") or not payload:
                continue
            d = builder.load(builder.blk_to_path(w["p"]))
            blocks = builder.launched_rockets(d) if w.get("air") else d.get(payload) if isinstance(d, dict) else None
            for b in blocks if isinstance(blocks, list) else [blocks]:
                if not isinstance(b, dict):
                    continue
                name = b.get("bulletName")
                name = name[0] if isinstance(name, list) and name else name
                iid = (name if isinstance(name, str) and name else key).lower()
                cur = out.get(iid)
                if cur is None or (cur.endswith("_default") and not key.endswith("_default")):
                    out[iid] = key
            out.setdefault(key.lower(), key)
        _weapon_keys.update({"for": catalog, "map": out})
    return _weapon_keys["map"]


def weapon_base(key: str) -> dict | None:
    """A pylon weapon's own values (local game files): what My weapons' editor starts from."""
    w = STATE.get_catalog().get(key)
    if not w or not SAFE_ID.match(key) or w.get("pod"):
        return None
    folder = str(w.get("p", "")).replace("\\", "/").split("/")[-2].lower()
    payload = "rocket" if w.get("air") else cdk.PAYLOADS.get(folder)
    d = builder.load(builder.blk_to_path(w["p"])) if payload else None
    if w.get("air"):  # a launcher: the rocket block it will have on a pylon
        d = {"rocket": builder.launched_missile(d) or next(iter(builder.launched_rockets(d)), None)}
    block = d.get(payload) if isinstance(d, dict) else None
    block = block[0] if isinstance(block, list) and block else block
    if not isinstance(block, dict):
        return None
    out = {"key": key, "kind": payload, "c": w.get("c"), "guided": bool(w.get("g") and payload == "rocket"),
           "tree": weapon_tree(d)}
    for name, path in WEAPON_BASE_FIELDS.items():
        node = block
        for part in path:
            node = node.get(part) if isinstance(node, dict) else None
        if isinstance(node, list) and node and isinstance(node[0], (int, float)):
            node = node[0]
        if isinstance(node, (int, float)) and not isinstance(node, bool):
            out[name] = node
    return out


def install_sight(body: dict) -> dict | None:
    """The custom sight chosen for a ground vehicle, copied for the vehicle the game loads (the custom vehicle's
    host) and the vehicle itself: {sight, vehicles} or {error}."""
    sid = body.get("sight")
    veh = STATE.get_vehicles().get(str(body.get("vehicle", "")))
    if not sid or not veh or veh["c"] != "ground":
        return None
    unit_class = str(body.get("unitClass") or "")
    targets = [unit_class.split("/", 1)[1] if unit_class.startswith("userVehicles/") else "", veh["id"]]
    try:
        return {"sight": sid, "vehicles": sights.install(USER, str(sid), targets), "file": sights.SIGHT_FILE[:-4]}
    except (sights.SightError, OSError) as e:
        return {"error": str(e)}


def _prepare_cdk(body: dict) -> tuple[dict, dict]:
    """Custom-vehicle mode: writes nothing, returns (mission cfg, files to write under pkg_local)."""
    body, ai_files = _prepare_ai(body)
    body["_aiFiles"] = ai_files
    # aircraft / helicopters: bullet slots tagged with their weapon, per-launcher countermeasure counts
    det0 = STATE.get_details().get(str(body.get("vehicle", ""))) or {}
    body["_ammoGroups"] = _ammo_groups(det0)
    veh0 = STATE.get_vehicles().get(str(body.get("vehicle", "")))
    if veh0 and isinstance(veh0.get("r"), int):
        body["_rank"] = veh0["r"]  # test flights: targets / airfield of your rank
    if veh0 and veh0.get("n") not in (None, "", "other"):
        crew_units = {f"country_{veh0['n']}": [veh0["id"]]}
        if STATE.cdk_enabled() and veh0["c"] == "ground":
            host0 = STATE.host_for("ground")
            if host0:
                crew_units.setdefault("country_usa" if host0.startswith("us_") else f"country_{veh0['n']}", []).append(host0)
        body["_crewUnits"] = crew_units
    if not STATE.cdk_enabled() or body.get("cdk") is False:
        return body, {}
    vid = str(body.get("vehicle", ""))
    veh = STATE.get_vehicles().get(vid)
    det = STATE.get_details().get(vid)
    if not veh or det is None:
        raise mission.MissionError("Unknown vehicle")
    air_method = STATE.settings().get("airMethod") or "custom"
    if air_method not in cdk.AIR_METHODS:
        air_method = "custom"
    host = STATE.host_for(veh["c"])
    if not host and not (veh["c"] in ("air", "heli") and air_method == "custom"):
        raise mission.MissionError(f"No host vehicle set for {veh['c']}. Pick a vehicle you own in Settings → Custom vehicles.")
    mods = dict(body.get("mods") or {})
    unit_data = None
    if (body.get("cheats") or {}).get("immortal"):
        mods["invulnerable"] = True
    st0 = det.get("st") or {}
    if (body.get("cheats") or {}).get("superMobility") and veh["c"] == "ground":
        # super mobility: engine power x4, top speed x2 (final drive), brakes x3; a value set in the panel wins
        for key, value in (("hp", (st0.get("hp") or 0) * 4), ("speedMul", 2.0 if st0.get("gear") else 0),
                           ("brake", (st0.get("brake") or 0) * 3)):
            if value and mods.get(key) in (None, ""):
                mods[key] = value
    if (body.get("cheats") or {}).get("superMobility") and veh["c"] == "air":
        mods["superMobility"] = True  # aircraft: engine output x3, 40 % lighter (cdk._power_overrides)
    fm_data = None
    if (body.get("cheats") or {}).get("noOverload") and veh["c"] in ("air", "heli"):
        mods["noStructural"] = True  # unbreakable airframe: the flight model's breaking limits raised
    if veh["c"] in ("air", "heli") and (mods.get("noStructural") or mods.get("thrustMul") or mods.get("superMobility") or mods.get("engineFrom")):
        # the flight model itself (local game files): breaking limits, jets' thrust table
        fm = str((det.get("st") or {}).get("fm") or "")
        if fm:
            fm_data = builder.load(builder.fm_file(fm))
    if isinstance(body.get("pylons"), dict):
        body["pylons"] = custom_weapons(body["pylons"])
    non_std = any(isinstance(v, dict) for v in (body.get("pylons") or {}).values())
    if mods.get("invulnerable") or non_std or any(mods.get(k) for k in ("sensors", "sensorsAdd", "avionics", "warningVoice", "crewVoice")):
        # needs the local game files (damage model, pylon layout for non-standard weapons, what the unit has)
        unit_data = builder.load(builder.unit_file(vid, veh["c"]))
    engine = str(mods.get("engineFrom") or "")
    donor = str((STATE.get_details().get(engine, {}).get("st") or {}).get("fm") or "") if SAFE_ID.match(engine) else ""
    try:
        files, preset, unit_class, pkg = cdk.build_files(vid, veh["c"], det, mods, host,
                                                         body.get("pylons"), air_method, unit_data,
                                                         STATE.get_catalog(), fm_data=fm_data,
                                                         engine_fm=builder.load(builder.fm_file(donor)) if donor else None)
    except cdk.CdkError as e:
        raise mission.MissionError(str(e))
    body = dict(body, unitClass=unit_class, _pkg=pkg, crewCountry=mods.get("crewCountry"))
    if any(isinstance(g, dict) and g.get("swap") for g in (mods.get("guns") or {}).values()):
        body["ammo"] = []  # the shells picked were the old gun's
    if preset:
        body["preset"] = preset
    return body, files


Handler.prepare_cdk = staticmethod(_prepare_cdk)


# --------------------------------------------------------------------------- tactical map capture
# While a battle / mission runs, War Thunder serves its tactical map on http://localhost:8111
# (map.img + map_info.json, the API external map tools use). We save it for the level of the
# mission WTFTD generated last, so the scenario editor can draw the real map under the units.

WT_API = "http://127.0.0.1:8111"
MAPS = CACHE / "maps"
_capture = {"key": None, "hint": None}


def _wt_get(path: str, timeout: float = 1.0) -> bytes | None:
    try:
        with urllib.request.urlopen(WT_API + path, timeout=timeout) as r:
            return r.read()
    except (urllib.error.URLError, OSError, TimeoutError, ValueError):
        return None


def set_capture_hint(level: str, x: float, z: float):
    _capture["hint"] = {"level": level, "x": x, "z": z}


def _matches(level_info: dict, mn, mx) -> bool:
    for a, b in (("a0", "a1"), ("t0", "t1")):
        if a in level_info and b in level_info:
            if all(abs(level_info[a][i] - mn[i]) < 2 and abs(level_info[b][i] - mx[i]) < 2 for i in (0, 1)):
                return True
    return False


def mission_on_map() -> bool:
    """Is the map of the mission generated last the one loaded in the game?
    Tells it from a real battle fought in the same aircraft, where "Unbreakable airframe" must not silence the alarms."""
    hint = _capture["hint"]
    try:
        info = json.loads((_wt_get("/map_info.json") or b"{}").decode("utf-8", "ignore"))
        mn, mx = [float(c) for c in info["map_min"]], [float(c) for c in info["map_max"]]
    except (ValueError, KeyError, TypeError):
        return False
    return bool(hint and info.get("valid") and _matches(read_json(DATA / "levels.json", {}).get(hint["level"], {}), mn, mx))


LOGS, SOUNDS = USER / "logs", USER / "sounds"
ARCHIVE = battle.Archive(LOGS)
WATCH = alarms.Watch(_wt_get, STATE.get_details, mission_on_map, logs=LOGS, sounds=SOUNDS,
                     kind=lambda vid: (STATE.get_vehicles().get(vid) or {}).get("k"),
                     nation=lambda vid: (STATE.get_vehicles().get(vid) or {}).get("n"),
                     crash_words=lambda: read_json(DATA / "battle_words.json", {}).get("crashed", []),
                     stats=lambda: replays.summary(battles()["rows"]), log_words=lambda: read_json(DATA / "battle_words.json", {}),
                     name=STATE.unit_name)


BENCH = bench.Bench(WATCH, LOGS, lambda: read_json(DATA / "meta.json", {}).get("version", ""))


def apply_alarm_settings():
    s = STATE.settings()
    WATCH.words = alarms.labels(str(s.get("lang") or "en"))
    STATE.units = None  # the language may have changed
    alarms.OUTPUT["device"] = str(s.get("audioDevice") or "")
    saved = s.get("overlayProfiles") if isinstance(s.get("overlayProfiles"), dict) else {}
    WATCH.set_config(alarms.clean(s.get("overlay"), WATCH.words),
                     {k: alarms.clean(v, WATCH.words) for k, v in saved.items() if alarms.PROFILE.fullmatch(k)})
    WATCH.set_enabled(alarms.available() and s.get("alarms") is True)


def flight_status(after: int) -> dict:
    """The Flight data tab: the readings after this one (the tab asking keeps them coming, see Watch.tick)."""
    WATCH.viewed = time.monotonic()
    return {"rows": [r for r in list(WATCH.trace) if r["n"] > after], "flying": WATCH.flying, "aircraft": WATCH.current,
            "log": WATCH.log.name if WATCH.log else None, "units": alarms.units(), "now": WATCH.last}


def hud_status(size: str) -> dict:
    """The HUD of the aircraft flown, drawn for the cockpit window whatever the overlay's own settings say of showing it."""
    WATCH.viewed = WATCH.hud_viewed = time.monotonic()  # keeps the readings coming, and fast
    w, _, h = size.partition("x")
    width, height = (min(int(n), 20000) for n in (w, h)) if w.isdecimal() and h.isdecimal() else (960, 560)
    cfg, flying = WATCH.cfg, WATCH.flying and "ias" in WATCH.last  # an aircraft: a tank has no airspeed
    shapes = WATCH.hud_frame((width, height), "window", cfg) if flying else []
    return {"shapes": shapes, "color": cfg["hudColor"], "alert": cfg["alert"], "flying": flying, "aircraft": WATCH.current}


def overlay_status(profile: str = "") -> dict:
    """The My overlay tab: an overlay (the one for all aircraft, or a profile), the screen it's placed on, its lines with
    sample values."""
    cfg = WATCH.profiles.get(profile, WATCH.base)
    return {"cfg": cfg, "screen": alarms.screen(), "lines": WATCH.sample(cfg), "onScreen": WATCH.preview is not None,
            "hud": {place: WATCH.sample_hud(cfg, profile, place) for place in hud.PLACES}, "map": WATCH.sample_map(cfg),
            "enabled": STATE.settings().get("alarms") is True, "profile": profile if profile in WATCH.profiles else "",
            "profiles": sorted(WATCH.profiles), "active": WATCH.profile, "aircraft": WATCH.current,
            "sounds": alarms.sound_list(SOUNDS), "devices": waveout.devices(), "device": alarms.OUTPUT["device"]}


def capture_once():
    raw = _wt_get("/map_info.json")
    if not raw:
        return
    try:
        info = json.loads(raw.decode("utf-8", "ignore"))
    except ValueError:
        return
    if not info.get("valid") or not isinstance(info.get("map_min"), list) or not isinstance(info.get("map_max"), list):
        return
    hint = _capture["hint"]
    if not hint:
        return
    mn, mx = [float(c) for c in info["map_min"]], [float(c) for c in info["map_max"]]
    key = (hint["level"], info.get("map_generation"), tuple(mn), tuple(mx))
    if key == _capture["key"]:
        return
    levels = read_json(DATA / "levels.json", {})
    if not _matches(levels.get(hint["level"], {}), mn, mx):
        return  # another map is loaded (not the mission we generated)
    img = _wt_get(f"/map.img?gen={info.get('map_generation', 0)}", timeout=4)
    if not img or len(img) < 1000:
        return
    ext = ".png" if img[:4] == b"\x89PNG" else ".jpg"
    # orientation: compare the player's marker with their known start position (the player has not moved yet)
    z_up = True
    try:
        objs = json.loads((_wt_get("/map_obj.json") or b"[]").decode("utf-8", "ignore"))
        me = next((o for o in objs if isinstance(o, dict) and o.get("icon") == "Player"), None)
        if me and mx[0] > mn[0] and mx[1] > mn[1]:
            ny = (hint["z"] - mn[1]) / (mx[1] - mn[1])
            z_up = abs(float(me["y"]) - (1 - ny)) <= abs(float(me["y"]) - ny)
    except (ValueError, KeyError, TypeError):
        pass
    MAPS.mkdir(parents=True, exist_ok=True)
    for old in MAPS.glob(hint["level"] + ".*"):
        old.unlink()
    (MAPS / (hint["level"] + ext)).write_bytes(img)
    write_json(MAPS / (hint["level"] + ".json"), {"min": mn, "max": mx, "zUp": z_up, "file": hint["level"] + ext,
                                                  "captured": int(time.time())})
    _capture["key"] = key


def map_capture_loop():
    while True:
        try:
            capture_once()
        except Exception:  # never let the capture thread die
            pass
        time.sleep(4)


def captured_map(level: str) -> dict | None:
    if not re.fullmatch(r"[a-z0-9_]+", level or ""):
        return None
    meta = read_json(MAPS / f"{level}.json", None)
    return meta if isinstance(meta, dict) and (MAPS / meta.get("file", "")).exists() else None


def level_map(level: str) -> dict | None:
    """Background layers of the scenario editor for a level, drawn in order:
    the full tactical map, then the (more detailed) ground battle map on top.
    From the game files when possible, else the map captured while playing."""
    if not re.fullmatch(r"[a-z0-9_]+", level or ""):
        return None
    info = read_json(DATA / "levels.json", {}).get(level) or {}
    gd = STATE.game_dir()
    layers, oodle, no_oodle = [], None, False
    for tex, a, b in (("am", "a0", "a1"), ("tm", "t0", "t1")):
        name = info.get(tex)
        if not name or a not in info or not maptex.available(gd, name):
            continue
        if not (maptex.CACHE / f"{name}.png").exists():
            oodle = oodle or oodle_dll(gd)
            if not oodle:
                no_oodle = True
                continue
        layers.append({"url": f"/img/maptex/{name}.png", "thumb": f"/img/mapthumb/{name}.png",
                       "min": info[a], "max": info[b], "zUp": True})
    if layers:
        return {"source": "game", "layers": layers}
    cap = captured_map(level)
    if cap:
        return {"source": "capture", "layers": [{"url": f"/img/levelmap/{level}?v={cap.get('captured', 0)}",
                                                 "min": cap["min"], "max": cap["max"], "zUp": cap.get("zUp", True)}]}
    return {"source": None, "layers": [], "noOodle": no_oodle}


def free_port(preferred: int) -> int:
    for port in [preferred] + list(range(preferred + 1, preferred + 20)):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return 0


def serve(port: int = 8777) -> tuple[ThreadingHTTPServer, str]:
    port = free_port(port)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.daemon_threads = True
    threading.Thread(target=auto_update_loop, daemon=True).start()
    threading.Thread(target=map_capture_loop, daemon=True).start()
    threading.Thread(target=challenge_loop, daemon=True).start()
    threading.Thread(target=warm_weapon_icons, daemon=True).start()
    threading.Thread(target=lambda: models.warm(STATE.game_dir()), daemon=True).start()
    if alarms.available():
        apply_alarm_settings()
        threading.Thread(target=WATCH.run, daemon=True).start()
        threading.Thread(target=BENCH.run, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}/"
