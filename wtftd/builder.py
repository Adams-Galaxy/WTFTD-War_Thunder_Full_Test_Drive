"""Builds the app database from the community War Thunder datamine, or from the installed game's own files.

Source: https://github.com/gszabi99/War-Thunder-Datamine (sparse git clone, ~1 GB on disk),
or the game's .vromfs.bin files, unpacked with the same layout (vromfs.py, needs Python 3.14).
Output (in ./data):
  meta.json          game version + build date
  vehicles.json      compact vehicle list for the browser grid
  details.json       per-vehicle loadouts / ammo (served one vehicle at a time)
  trees.json         in-game research trees per nation and vehicle type
  scenarios.json     official test drive / test flight missions usable as maps
  scenarios/<id>.json  the raw official missions (rebuilt to .blk with your vehicle)
  lang/<code>.json   vehicle / weapon / ammo / map names for every game language

Run:  python -m wtftd.builder            (clone or update the datamine, then build)
      python -m wtftd.builder --no-pull  (build from the existing clone)
      python -m wtftd.builder --game     (unpack the installed game, then build; --no-pull: from the last unpack)
"""
from __future__ import annotations

import csv
import math
import io
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile
from collections import defaultdict
from pathlib import Path

from . import patches, vromfs
from .paths import CACHE, DATA, HOME as ROOT
DM = CACHE / "datamine"
SCHEMA = 34  # bump when data/*.json gains fields the app needs: installed data gets rebuilt
REPO = "https://github.com/gszabi99/War-Thunder-Datamine.git"
SPARSE = [
    "aces.vromfs.bin_u/gamedata/flightmodels",
    "aces.vromfs.bin_u/gamedata/units/tankmodels",
    "aces.vromfs.bin_u/gamedata/units/ships",
    "aces.vromfs.bin_u/gamedata/units/air_defence",
    "aces.vromfs.bin_u/gamedata/units/structures",
    "aces.vromfs.bin_u/gamedata/units/wheeled_vehicles",
    "aces.vromfs.bin_u/gamedata/units/tracked_vehicles",
    "aces.vromfs.bin_u/gamedata/units/radars",
    "aces.vromfs.bin_u/gamedata/units/infantry",
    "aces.vromfs.bin_u/gamedata/objectgroups",
    "aces.vromfs.bin_u/gamedata/sensors",
    "aces.vromfs.bin_u/gamedata/weapons",
    "aces.vromfs.bin_u/gamedata/damage_model",
    "char.vromfs.bin_u/config",
    "lang.vromfs.bin_u/lang",
    "mis.vromfs.bin_u/gamedata/missions",
    "aces.vromfs.bin_u/config",
    "aces.vromfs.bin_u/levels",
]
DATAMINE = DM
GAMEFILES = CACHE / "gamefiles"  # the installed game's files, unpacked with the datamine's layout
DEV = CACHE / "dev"  # the datamine's newest version built apart (build_dev): What changed sets it beside the game's

# CSV column -> short language code used by the app
LANG_COLUMNS = {
    "<English>": "en", "<French>": "fr", "<Italian>": "it", "<German>": "de",
    "<Spanish>": "es", "<Russian>": "ru", "<Polish>": "pl", "<Czech>": "cs",
    "<Turkish>": "tr", "<Chinese>": "zh", "<Japanese>": "ja", "<Portuguese>": "pt",
    "<Ukrainian>": "uk", "<Serbian>": "sr", "<Hungarian>": "hu", "<Korean>": "ko",
    "<Belarusian>": "be", "<Romanian>": "ro", "<TChinese>": "zh-TW", "<Vietnamese>": "vi",
}

COUNTRIES = ["usa", "germany", "ussr", "britain", "japan", "china", "italy", "france", "sweden", "israel"]

Progress = callable


def log(msg: str, progress=None):
    print(msg, flush=True)
    if progress:
        progress(msg)


def report(progress, frac: float):
    """Overall progress of an update, 0..1 (for the UI's progress bar)."""
    if progress is not None and hasattr(progress, "set_frac"):
        progress.set_frac(max(0.0, min(1.0, frac)))


DM_BYTES = 1.2e9  # size of the checked-out datamine folders, to show the first download's progress


def _watch_size(folder: Path, progress, lo: float, hi: float, stop: threading.Event):
    """First download: git first fetches the repository index (nothing written for ~40 s, shown as a slow
    time-based advance up to 'mid'), then writes the files (progress = size on disk)."""
    mid = lo + (hi - lo) * 0.3
    t0 = time.time()
    while not stop.wait(1.5):
        total = 0
        for root, _, files in os.walk(folder):
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(root, name))
                except OSError:
                    pass
        by_time = lo + (mid - lo) * (1 - math.exp(-(time.time() - t0) / 25))
        by_size = mid + (hi - mid) * min(total / DM_BYTES, 1.0) if total > 5e7 else 0.0
        report(progress, max(by_time, by_size))


# --------------------------------------------------------------------------- helpers

def aslist(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def load(path: Path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


if (load(DATA / "meta.json") or {}).get("source") == "game":
    DM = GAMEFILES  # the app reads the files its data was built from: build() changes it when that build succeeds


def build_bullet_icons() -> dict:
    """The game's own bullet type -> icon table (config/gui.blk), so shells, belts and countermeasures
    get the hangar's icons: {"icons": {"apds_fs_long_tank": "apdsfs_tank", "flr": "bullet_flare", ...}}."""
    gui = load(DM / "aces.vromfs.bin_u" / "config" / "gui.blkx") or {}
    icons = gui.get("bullet_icons") if isinstance(gui, dict) else None
    return {"icons": {k: v for k, v in (icons or {}).items() if isinstance(v, str)}}


def build_battle_words() -> dict:
    """The battle log's verbs in every language: the game writes it in its own. crashed, lost: the end of a line, without
    spaces. killed: "A shot down B", killedBy: "B shot down by A", the longest first."""
    try:
        rows = read_lang_csv("ui.csv")
    except OSError:
        return {"crashed": [], "lost": [], "killed": [], "killedBy": []}

    def said(*keys):
        return {v.replace("\\t", "").strip() for k in keys for v in (rows.get(k) or {}).values()}
    killed = said("NET_UNIT_KILLED_FM", "NET_UNIT_KILLED_GM")
    killed_by = said("NET_PLAYER_KILLED_BY_PLAYER", "NET_PLAYER_KILLED_BY_UNIT", "NET_UNIT_KILLED_BY_PLAYER", "NET_PLAYER_GM_KILLED_BY_UNIT")
    return {"crashed": sorted("".join(v.split()) for v in said("NET_PLAYER_HAS_CRASHED")),
            "lost": sorted("".join(v.split()) for v in said("NET_PLAYER_GM_HAS_DESTROYED", "NET_PLAYER_SHOT_BY_AIR_DEFENCE")),
            "killed": sorted(killed, key=lambda v: (-len(v), v)),
            "killedBy": sorted(killed_by - killed, key=lambda v: (-len(v), v))}  # one word for both (Japanese, Serbian): "A word B"


# Bombing a target. The game sets the HP of a bombing area in its mission templates, by the mission's balance level
# (the economic rank of the battle: BR = 1 + level / 3), then x a multiplier in arcade, x the mission's respawns
# otherwise. An explosion takes off the splash damage of its TNT equivalent (explosive.blkx), which isn't proportional:
# many small bombs beat one big one. Checked on what players report: 3 Mk 83 kill a base, 6 one that respawns at
# 25,900 HP; 9 x 60 kg do at 10,000 HP and an 800 kg bomb doesn't; 28 SC50 + 2 SC250 kill a 32,000 HP airfield.
BASE_KINDS = {  # kind: (template, HP variable, arcade multiplier variable, balance level variable, x respawns outside arcade)
    "base": ("destroy_bomb_areas_template", "baseHP", "arcade_HP_mul", "bomb_areas_balance_level", True),
    "respawn": ("enduring_confrontation/bdt_bases_destroy_template", "bdt_base_hp", None, "bdt_balance_level", False),
    "airfield": ("destroy_airfield_zone_template", "dazt_airfield_max_hp", "dazt_arcade_hp_mul", "dazt_balance_level", True),
}


def game_curve(block) -> list:
    """One of the game's tables, {"p0": [x, y], ...}, as [[x, y], ...] by x: a repeated key comes as a list of pairs."""
    out = []
    for v in (block or {}).values():
        out += v if isinstance(v, list) and v and isinstance(v[0], list) else [v]
    return sorted(out)


def hp_bands(doc: dict, hp_var: str, mul_var: str | None, level_var: str) -> list:
    """[[first level, last level (None: and up), HP, arcade multiplier (None: none)], ...] from the triggers of a mission
    template that set hp_var for a range of balance levels."""
    out = []

    def walk(o):
        if isinstance(o, dict):
            sets = [s for s in aslist((o.get("actions") or {}).get("varSetReal")) if isinstance(s, dict)] if isinstance(o.get("actions"), dict) else []
            hp = next((s.get("value") for s in sets if s.get("var") == hp_var), None)
            if isinstance(hp, (int, float)):
                lo, hi = 0, None
                conditions = o.get("conditions") if isinstance(o.get("conditions"), dict) else {}
                for c in aslist(conditions.get("varCompareInt")):
                    if isinstance(c, dict) and c.get("var_value") == level_var and isinstance(c.get("value"), (int, float)):
                        if c.get("comparasion_func") == "less":
                            hi = c["value"] - 1 if hi is None else min(hi, c["value"] - 1)
                        elif c.get("comparasion_func") == "more":
                            lo = max(lo, c["value"] + 1)
                mul = next((s.get("value") for s in sets if s.get("var") == mul_var), None) if mul_var else None
                out.append([int(lo), None if hi is None else int(hi), hp, mul])
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(doc.get("triggers") or {})
    return sorted(out, key=lambda b: b[0])


def build_bases() -> dict:
    """Bombing data for the Weapons page: HP by balance level per kind of target, damage by TNT equivalent (kg) and the
    napalm multiplier of a bombing zone. {} when the game files don't have them."""
    base = DM / "mis.vromfs.bin_u" / "gamedata" / "missions" / "templates"
    kinds = {}
    for kind, (template, hp_var, mul_var, level_var, respawns) in BASE_KINDS.items():
        bands = hp_bands(load(base / f"{template}.blkx") or {}, hp_var, mul_var, level_var)
        if bands:
            kinds[kind] = {"bands": bands, "respawns": respawns}
    model = DM / "aces.vromfs.bin_u" / "gamedata" / "damage_model"
    splash = (load(model / "explosive.blkx") or {}).get("explosiveTypeToSplashParams") or {}
    zone = (load(model / "armor_classes.blkx") or {}).get("bombing_zone") or {}
    damage = game_curve(splash.get("explosiveMassToDamage"))
    if not kinds or not damage:
        return {}
    return {"damage": damage, "napalm": _numval(zone.get("napalmDamageMult")), "kinds": kinds}


def first_str(v) -> str:
    for x in aslist(v):
        if isinstance(x, str) and x:
            return x
    return ""


def num(v, default=0) -> int:
    for x in aslist(v):
        if isinstance(x, (int, float)) and not isinstance(x, bool):
            return int(x)
    return default


def blk_to_path(blk: str) -> Path:
    """'gameData/Weapons/foo/Bar.blk' -> datamine path to the .blkx file."""
    rel = blk.replace("\\", "/").lower()
    if rel.endswith(".blk"):
        rel = rel[:-4] + ".blkx"
    return DM / "aces.vromfs.bin_u" / rel


def basename(blk: str) -> str:
    return blk.replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0].lower()


ZW = re.compile("[\u200b\u200c\u200d\ufeff]")
# War Thunder font glyphs (country-of-origin marks, icons) that render as junk outside the game
GLYPHS = re.compile("[\u2400-\u243f\u2580-\u25ff\u2600-\u26ff\u22e0\ue000-\uf8ff]")


def clean(s: str) -> str:
    s = ZW.sub("", s or "").replace("\u00a0", " ")
    return re.sub(r"\s{2,}", " ", GLYPHS.sub("", s)).strip()


# --------------------------------------------------------------------------- datamine

MINGIT = CACHE / "mingit"
_git_exe: str | None = None


def find_git(progress=None) -> str:
    """Git of this PC, or else the official portable MinGit (git-for-windows), downloaded once."""
    global _git_exe
    if _git_exe:
        return _git_exe
    if sys.platform == "darwin":
        return _mac_git()
    found = shutil.which("git")
    for cand in ([found] if found else []) + [str(MINGIT / "cmd" / "git.exe"),
                                              r"C:\Program Files\Git\cmd\git.exe"]:
        if cand and Path(cand).is_file():
            _git_exe = cand
            return cand
    if sys.platform != "win32":
        raise RuntimeError("Git is required: install it from https://git-scm.com")
    log("Git not found: downloading the portable MinGit (git-for-windows, ~40 MB, once)...", progress)
    req = urllib.request.Request("https://api.github.com/repos/git-for-windows/git/releases/latest",
                                 headers={"User-Agent": "WTFTD", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        assets = json.load(r).get("assets", [])
    url = next((a["browser_download_url"] for a in assets
                if re.fullmatch(r"MinGit-[\d.]+(?:\.windows\.\d+)?-64-bit\.zip", a.get("name", ""))), None)
    if not url:
        raise RuntimeError("Could not find MinGit. Install Git from https://git-scm.com and retry.")
    if not url.startswith("https://github.com/git-for-windows/git/releases/download/"):
        raise RuntimeError("Unexpected MinGit download location")
    CACHE.mkdir(parents=True, exist_ok=True)
    tmp = CACHE / "mingit.zip"
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "WTFTD"}), timeout=120) as r,             open(tmp, "wb") as f:
        shutil.copyfileobj(r, f)
    shutil.rmtree(MINGIT, ignore_errors=True)
    with zipfile.ZipFile(tmp) as z:
        z.extractall(MINGIT)
    tmp.unlink()
    _git_exe = str(MINGIT / "cmd" / "git.exe")
    return _git_exe


def _mac_git() -> str:
    """macOS: Homebrew / MacPorts Git, else Apple's (/usr/bin/git, from the Command Line Tools).
    An app opened from the Finder has a minimal PATH, hence the fixed locations."""
    global _git_exe
    for cand in ("/opt/homebrew/bin/git", "/usr/local/bin/git", "/opt/local/bin/git", shutil.which("git")):
        if cand and cand != "/usr/bin/git" and Path(cand).is_file():
            _git_exe = cand
            return cand
    # /usr/bin/git is only a stub until the Command Line Tools are installed
    if subprocess.run(["xcode-select", "-p"], capture_output=True).returncode == 0:
        _git_exe = "/usr/bin/git"
        return _git_exe
    subprocess.run(["xcode-select", "--install"], capture_output=True)  # opens Apple's installer dialog
    raise RuntimeError("Git is required: accept the Command Line Tools install macOS just offered "
                       "(or run xcode-select --install in Terminal), then retry.")


def git(*args, cwd=None):
    # no console window flashing from the packaged (windowed) app
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.run([find_git(), "-c", "core.longpaths=true", *args], cwd=cwd, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=flags)


def fetch_datamine(progress=None):
    CACHE.mkdir(parents=True, exist_ok=True)
    find_git(progress)
    if not (DM / ".git").exists():
        shutil.rmtree(DM, ignore_errors=True)  # leftover of an interrupted first download
        log("Downloading the War Thunder datamine (community, ~1 GB, first run takes a few minutes)...", progress)
        report(progress, 0.03)
        stop = threading.Event()
        threading.Thread(target=_watch_size, args=(DM, progress, 0.04, 0.45, stop), daemon=True).start()
        try:
            git("clone", "--filter=blob:none", "--no-checkout", "--depth", "1", REPO, str(DM))
            git("sparse-checkout", "init", "--cone", cwd=DM)
            git("sparse-checkout", "set", *SPARSE, cwd=DM)
            git("checkout", "master", cwd=DM)
        finally:
            stop.set()
    else:
        log("Updating the War Thunder datamine...", progress)
        report(progress, 0.05)
        git("sparse-checkout", "set", *SPARSE, cwd=DM)
        git("fetch", "--depth", "1", "origin", "master", cwd=DM)
        git("reset", "--hard", "origin/master", cwd=DM)
    report(progress, 0.45)


def fetch_gamefiles(game_dir: Path | None, progress=None):
    """Unpacks the installed game (read only) next to the last unpack, which it replaces once complete."""
    if not vromfs.available():
        raise RuntimeError(vromfs.NO_ZSTD)
    if not game_dir:
        raise RuntimeError("War Thunder folder not found. Set it in Settings.")
    log(f"Reading the game files (War Thunder {vromfs.version(game_dir)})...", progress)
    report(progress, 0.03)
    tmp = GAMEFILES.with_name("gamefiles.tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    try:
        vromfs.unpack(game_dir, tmp, SPARSE, lambda frac: report(progress, 0.03 + 0.42 * frac))
        shutil.rmtree(GAMEFILES, ignore_errors=True)
        tmp.replace(GAMEFILES)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)  # after a failure: don't leave 650 MB behind
    report(progress, 0.45)


def build_dev(status: Path, source: str = "datamine", game_dir: Path | None = None):
    """In a process of its own (`wtftd --build-dev`): the other source's database, built into DEV / "data" to switch to at the
    top or to set beside the app's in What changed: the datamine's newest version (the dev server's while one is open) when the
    app reads the installed game, or the installed game's when it reads the datamine. The app's data, its game files and its
    history are left alone: DM and DATA are this process's. Progress and the end go to status (JSON), for the app to read."""
    global DM, DATA
    from . import armament
    from .game import circuit
    st = {"running": True, "log": [], "progress": 0.0, "error": None}

    def save():
        tmp = status.with_suffix(".tmp")
        tmp.write_text(json.dumps(st), encoding="utf-8")
        tmp.replace(status)

    class Progress:
        def __call__(self, msg):
            st["log"] = [*st["log"], msg][-50:]
            save()

        def set_frac(self, frac):
            st["progress"] = max(st["progress"], frac)
            save()

    status.parent.mkdir(parents=True, exist_ok=True)
    save()
    out, tmp = DEV / "data", DEV / "data.tmp"
    try:
        if source == "game":  # the app reads the datamine then: the game's files are free to unpack
            DM = GAMEFILES
            fetch_gamefiles(game_dir, Progress())
        else:
            DM = DATAMINE
            fetch_datamine(Progress())
        shutil.rmtree(tmp, ignore_errors=True)
        DATA = armament.DATA = tmp
        _build(Progress(), source, history=False, circuit=circuit(game_dir) if source == "game" else None)
        shutil.rmtree(out, ignore_errors=True)
        tmp.replace(out)
    except Exception as e:  # the app shows it; the dev data of before, if any, stays
        st["error"] = str(e) or type(e).__name__
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        st["running"] = False
        save()


def remove_datamine():
    """Settings: the player no longer wants the datamine copy. Git's own files are read-only."""
    for root, _, files in os.walk(DATAMINE):
        for name in files:
            os.chmod(os.path.join(root, name), 0o700)
    shutil.rmtree(DATAMINE, ignore_errors=True)


# --------------------------------------------------------------------------- languages

def read_lang_csv(name: str) -> dict[str, dict[str, str]]:
    """Returns {key: {lang: text}}."""
    path = DM / "lang.vromfs.bin_u" / "lang" / name
    out: dict[str, dict[str, str]] = {}
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.reader(f, delimiter=";", quotechar='"')
        header = next(reader)
        cols = [(i, LANG_COLUMNS[h]) for i, h in enumerate(header) if h in LANG_COLUMNS]
        for row in reader:
            if not row:
                continue
            key = row[0]
            vals = {}
            for i, code in cols:
                if i < len(row) and row[i]:
                    vals[code] = clean(row[i])
            out[key] = vals
    return out


class Lang:
    def __init__(self):
        self.tables = {}
        for n in ("units.csv", "units_weaponry.csv", "units_modifications.csv", "missions_locations.csv", "menu.csv"):
            try:
                self.tables[n] = read_lang_csv(n)
            except OSError:
                self.tables[n] = {}
        self.all = {}
        for t in self.tables.values():
            for k, v in t.items():
                self.all.setdefault(k, v)
        self.lower = {k.lower(): k for k in self.all}
        # collected output: {section: {key: {lang: text}}}
        self.out: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)

    def get(self, key: str):
        v = self.all.get(key)
        if v is None:
            k = self.lower.get(key.lower())
            v = self.all.get(k) if k else None
        return v

    def put(self, section: str, key: str, *candidates: str, fallback: str | None = None) -> bool:
        for c in candidates:
            v = self.get(c)
            if v and v.get("en"):
                self.out[section][key] = v
                return True
        if fallback:
            self.out[section][key] = {"en": fallback}
        return False

    def write(self):
        (DATA / "lang").mkdir(parents=True, exist_ok=True)
        codes = set()
        for sec in self.out.values():
            for v in sec.values():
                codes.update(v)
        for code in sorted(codes):
            data = {}
            for sec, entries in self.out.items():
                d = {}
                for k, v in entries.items():
                    t = v.get(code)
                    if t and (code == "en" or t != v.get("en")):
                        d[k] = t
                data[sec] = d
            with open(DATA / "lang" / f"{code}.json", "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        return sorted(codes)


def humanize(s: str) -> str:
    s = re.sub(r"[_\-]+", " ", s).strip()
    return " ".join(w.upper() if len(w) <= 3 or any(ch.isdigit() for ch in w) else w.capitalize() for w in s.split())


# --------------------------------------------------------------------------- vehicles

def br_from(er):
    if er is None:
        return None
    return round(1.0 + er / 3.0, 1)


def categorize(move_type: str, unit_class: str) -> str:
    if move_type in ("tank", "heavy_tank", "wheeled_vehicle"):
        return "ground"
    if move_type == "helicopter":
        return "heli"
    if move_type == "air":
        return "air"
    if move_type == "fast_ship":
        return "boat"
    if move_type in ("ship", "slow_ship"):
        return "ship"
    return "other"


UNIT_BLOCK = {"ground": "tankModels", "air": "armada", "heli": "armada", "boat": "ships", "ship": "ships"}


def unit_file(vid: str, cat: str) -> Path:
    base = DM / "aces.vromfs.bin_u" / "gamedata"
    if cat == "ground":
        return base / "units" / "tankmodels" / f"{vid.lower()}.blkx"
    if cat in ("boat", "ship"):
        return base / "units" / "ships" / f"{vid.lower()}.blkx"
    return base / "flightmodels" / f"{vid.lower()}.blkx"


class WeaponCache:
    def __init__(self, lang: Lang):
        self.lang = lang
        self.cache: dict[str, dict | None] = {}
        self.blast = blast_tables()

    def get(self, blk: str):
        key = blk.lower()
        if key not in self.cache:
            self.cache[key] = load(blk_to_path(blk))
        return self.cache[key]

    def weapon_name(self, blk: str) -> str:
        """Registers a localized name for a weapon blk, returns its key."""
        key = basename(blk)
        if key not in self.lang.out["weapons"]:
            if not self.lang.put("weapons", key, f"weapons/{key}", key):
                # containers: name after the inner weapon
                d = self.get(blk) or {}
                inner = None
                for w in aslist(d.get("Weapon")) + aslist((d.get("weapons") or {}).get("Weapon") if isinstance(d.get("weapons"), dict) else None):
                    if isinstance(w, dict) and first_str(w.get("blk")):
                        inner = w
                        break
                if inner:
                    ik = self.weapon_name(first_str(inner["blk"]))
                    n = num(inner.get("bullets"), 1) or 1
                    en = self.lang.out["weapons"].get(ik, {}).get("en", humanize(ik))
                    self.lang.out["weapons"][key] = {"en": f"{n}× {en}" if n > 1 else en}
                else:
                    self.lang.out["weapons"][key] = {"en": humanize(key)}
        return key

    def bullet_sets(self, blk: str):
        """Returns (default_set, {mod_name: set}) where set = {'b': [bulletName], 't': [bulletType]}."""
        d = self.get(blk)
        if not d:
            return None, {}

        def describe(b):
            names, types = [], []
            first = next((x for x in aslist(b.get("bullet")) if isinstance(x, dict)), None)
            for x in aslist(b.get("bullet")):
                if not isinstance(x, dict):
                    continue
                for bn in aslist(x.get("bulletName")):
                    if isinstance(bn, str) and bn and bn not in names:
                        names.append(bn)
                        self.lang.put("bullets", bn, bn, fallback=bn.split("_", 1)[-1].upper())
                for bt in aslist(x.get("bulletType")):
                    if isinstance(bt, str) and bt and bt not in types:
                        types.append(bt)
                        self.lang.put("btypes", bt, f"{bt}/name/short", f"{bt}_ball/name/short", fallback=bt.upper())
            out = {"b": names, "t": types}
            st = shell_stats(first, self.blast)
            belt = [pen_curve(x, self.blast) for x in aslist(b.get("bullet")) if isinstance(x, dict)]
            if len(belt) > 1:  # a belt pierces what its best round does
                rows, computed = max(belt, key=lambda c: c[0][0][1] if c[0] else 0)
                st.pop("pe", None)
                st.update({"pc": rows, **({"pe": 1} if computed else {})} if rows else {})
            if st:
                out["s"] = st
            return out

        default = describe(d) if d.get("bullet") else None
        sets = {}
        for k, v in d.items():
            if isinstance(v, dict) and "bullet" in v:
                sets[k] = describe(v)
        return default, sets


def _numval(v):
    v = v[0] if isinstance(v, list) and v else v
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


# Penetration (mm, flat armor): an armor-piercing shell's own table when the game file has one, else the formulas the
# game uses - Lanz-Odermatt for long rods (APFSDS: working length, density, material), DeMarre for the others (the
# exponents and coefficient are in the shell's file; sub-calibre shells count the core's caliber, and its mass plus a
# part of the rest). At the speed left at a distance, these give the game's own figures: within 1 mm of the
# official wiki's tables on 27 shells (M829A2, 3BM46, PzGr 39, BR-471, M93, BR-365P, PzGr 40, Shot Mk.3, L28A1...).
_LO = {"tungsten": (0.994, 134.5, -0.148), "depletedUranium": (0.825, 90.0, -0.0849)}  # a, c0, c1 (longrods.ch)
_LO_STEEL = (1.104, 9874.0, 0.3598, -0.2342)  # a, c, k, n: steel has its own law, with the rod's hardness
_RHA_BHN, _RHA_DENSITY = 260.0, 7850.0
_DEMARRE_KFBR = 1900.0
_AIR_DENSITY = 1.225  # kg/m3, sea level: the game's penetration figures are there
_DEFAULT_CX = 0.35  # of a shell whose file has none (M79, M318, M74B1 match the wiki with it)
_PEN_AT = (10, 100, 500, 1000, 1500, 2000, 3000, 4000)  # distances of a computed curve (m)
_NO_PEN = ("smoke", "flr", "chff", "napalm", "practice", "snowball", "football")  # bullet types that pierce nothing
# explosive filler (% of the shell's mass) -> penetration factor, linear in between
_FILLER = ((0.65, 1.0), (1.6, 0.93), (2.0, 0.9), (3.0, 0.85), (4.0, 0.75))
# core's share of a sub-calibre shell's mass -> share of the rest that counts (damage_system.blkx, subcaliberDamageMass)
_SUBCALIBRE = ((0.0, 0.25), (0.15, 0.4), (0.3, 0.5), (0.4, 0.75))


def _linear(points: tuple, x: float) -> float:
    if x <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x <= x1:
            return y0 + (x - x0) * (y1 - y0) / (x1 - x0)
    return points[-1][1]


def _is_ap(b: dict) -> bool:
    bt = first_str(b.get("bulletType")).lower()
    return bt.startswith(("ap", "sap")) or "apds" in bt


def _pen_table(b: dict) -> list:
    """The shell's own penetration table, [(distance m, penetration mm)] nearest first; [] when it has none."""
    ap = b.get("armorpower")
    if not isinstance(ap, dict):
        return []
    return sorted((float(v[1]), float(v[0])) for v in ap.values()
                  if isinstance(v, list) and len(v) == 2 and all(isinstance(c, (int, float)) for c in v))


def speed_at(b: dict, d: float) -> float | None:
    """Speed left after d metres: air drag alone, on the ballistic caliber (a dart's own, not the barrel's)."""
    v, m = _numval(b.get("speed")), _numval(b.get("mass"))
    cal = _numval(b.get("ballisticCaliber")) or _numval(b.get("caliber"))
    if not v or not m or not cal:
        return None
    cx = _numval(b.get("Cx")) or _DEFAULT_CX
    return v * math.exp(-_AIR_DENSITY * cx * math.pi * cal * cal / (8.0 * m) * d)


def _formula_pen(b: dict) -> float | None:
    """The formulas alone, at the shell's "speed"; None when its file doesn't give what they need."""
    kin = (b.get("damage") or {}).get("kinetic") if isinstance(b.get("damage"), dict) else None
    v, m = _numval(b.get("speed")), _numval(b.get("mass"))
    if not isinstance(kin, dict) or not v or not m:
        return None
    if kin.get("lanzOdermattWorkingLength") is not None:
        material, hard = str(kin.get("lanzOdermattMaterial")), _numval(kin.get("lanzOdermattBrinellHardnessNumber"))
        length, rho, d = _numval(kin.get("lanzOdermattWorkingLength")), _numval(kin.get("lanzOdermattDensity")), _numval(b.get("damageCaliber"))
        if not length or not rho or not d or not (material in _LO or (material == "steel" and hard)):
            return None
        if material == "steel":
            a, c, ek, en = _LO_STEEL
            resist = c * _RHA_BHN ** ek * hard ** en
        else:
            a, c0, c1 = _LO[material]
            resist = (c0 + c1 * _RHA_BHN) * _RHA_BHN
        vk = v / 1000.0
        p = length * a / math.tanh(0.283 + 0.0656 * length / (d * 1000.0)) * math.sqrt(rho / _RHA_DENSITY) \
            * math.exp(-resist / (rho * vk * vk))
        return round(p)
    k = _numval(kin.get("demarrePenetrationK"))
    core, cal = _numval(b.get("damageMass")), _numval(b.get("damageCaliber"))
    if k is None or (cal and not core):
        return None
    cal = cal or _numval(b.get("caliber"))
    if not cal:
        return None
    hit = core + _linear(_SUBCALIBRE, core / m) * (m - core) if core else m
    sp, mp, cp = (_numval(kin.get(x)) or dflt for x, dflt in (("demarreSpeedPow", 1.43), ("demarreMassPow", 0.71),
                                                                ("demarreCaliberPow", 1.07)))
    p = v ** sp * hit ** mp / (_DEMARRE_KFBR ** sp * (cal * 10.0) ** cp) * 100.0 * k
    return round(p * _linear(_FILLER, 100.0 * (_numval(b.get("explosiveMass")) or 0.0) / m))


def kinetic_pen(b: dict) -> float | None:
    """Penetration of an armor-piercing shell (mm, 0°, at its "speed"); None for other shells."""
    if not _is_ap(b):
        return None
    rows = _pen_table(b)
    return round(rows[0][1]) if rows else _formula_pen(b)


def blast_tables() -> dict:
    """What blast_pen needs from the game's explosive.blkx."""
    e = load(DM / "aces.vromfs.bin_u" / "gamedata" / "damage_model" / "explosive.blkx") or {}
    frag = [(_numval(v.get("fillingRatio")), game_curve(v.get("explosiveMassToPenetration")))
            for v in (e.get("explosiveTypeToShattersParams") or {}).values() if isinstance(v, dict)]
    return {"tnt": {k.lower(): _numval((v or {}).get("strengthEquivalent")) or 1.0 for k, v in (e.get("explosiveTypes") or {}).items()},
            "pen": game_curve((e.get("explosiveTypeToSplashParams") or {}).get("explosiveMassToPenetration")),
            "frag": sorted((f, c) for f, c in frag if f and c)}


def blast_pen(b: dict, blast: dict | None) -> float:
    """What a shell's explosion pierces (mm), from its TNT equivalent: the blast, or its fragments, whose table goes by how
    much of the shell is explosive. The smallest charges, under the blast table's first point, make none that count."""
    e = _numval(b.get("explosiveMass"))
    if not e or not blast or not blast["pen"]:
        return 0.0
    tnt = e * blast["tnt"].get(first_str(b.get("explosiveType")).lower(), 1.0)
    pen, m = _linear(blast["pen"], tnt), _numval(b.get("mass"))
    if m and blast.get("frag") and tnt >= blast["pen"][0][0]:
        pen = max(pen, _linear(next((c for f, c in blast["frag"] if e / m <= f), blast["frag"][-1][1]), tnt))
    return pen


def _heat(b: dict) -> float | None:
    """A shaped charge's penetration (mm), a guided missile's in its "rocket" block: the same at any distance."""
    for x in (b, b.get("rocket")):
        cum = x.get("cumulativeDamage") if isinstance(x, dict) else None
        if isinstance(cum, dict) and _numval(cum.get("armorPower")):
            return _numval(cum.get("armorPower"))
    return None


def _missile_table(rocket: dict) -> list:
    """A kinetic missile's own figures, [(m, mm)...]: it speeds up, so they rise before they fall. guiArmorpower holds the
    first ones as [mm at 0°, 30°, 60°, distance], armorpower the rest."""
    near = rocket.get("guiArmorpower")
    if not isinstance(near, dict):
        return []
    rows = {v[-1]: v[0] for v in near.values() if isinstance(v, list) and len(v) == 4}
    return sorted({**dict(_pen_table(rocket)), **rows}.items())


def pen_curve(b: dict, blast: dict | None = None) -> tuple:
    """Any shell's penetration by distance: ([[m, mm], ...], computed?), ([], False) if it pierces nothing we can tell.
    An armor-piercing shell's table, a shaped charge's one value, else the formulas at the speed left; a shell with explosive
    pierces the better of that and its explosion (3OF26, 3OF11, Sprgr L/4.5 and the MG 151's APHE match the wiki)."""
    ap = _is_ap(b)
    table = _pen_table(b) if ap else []
    if len(table) > 1:
        return [[round(d), round(p)] for d, p in table], False
    heat = _heat(b)
    if heat:
        return [[_PEN_AT[0], round(heat)], [_PEN_AT[-1], round(heat)]], False
    if table or first_str(b.get("bulletType")).lower().startswith(_NO_PEN):
        return [], False
    missile = b.get("rocket") if isinstance(b.get("rocket"), dict) else b  # a missile's warhead is in its "rocket" block
    floor = blast_pen(missile, blast)
    own = _missile_table(missile)
    if own:
        return [[round(d), round(max(p, floor))] for d, p in own], False
    rows = [[d, round(max(_formula_pen({**b, "speed": speed_at(b, d)}) or 0, floor))] for d in _PEN_AT]
    return (rows, True) if rows[0][1] else ([], False)


def shell_stats(b: dict | None, blast: dict | None = None) -> dict:
    """Editable shell values: v speed (m/s), m mass (kg), e explosive mass (kg), h HEAT penetration (mm),
    l APFSDS rod working length (mm); and, shown only, k armor-piercing penetration at 10 m (mm) and pc any shell's
    penetration by distance, [[m, mm], ...] (pen_curve; pe: 1 when computed)."""
    if not isinstance(b, dict):
        return {}
    out = {}
    pen = kinetic_pen(b)
    rows, computed = pen_curve(b, blast)
    if rows:
        out["pc"] = rows
    if computed:
        out["pe"] = 1
        pen = pen and rows[0][1]
    if pen:
        out["k"] = pen
    for key, src in (("v", b.get("speed")), ("m", b.get("mass")), ("e", b.get("explosiveMass"))):
        val = _numval(src)
        if val is not None:
            out[key] = round(val, 4)
    cum = b.get("cumulativeDamage")
    if isinstance(cum, dict) and _numval(cum.get("armorPower")) is not None:
        out["h"] = _numval(cum.get("armorPower"))
    kin = (b.get("damage") or {}).get("kinetic") if isinstance(b.get("damage"), dict) else None
    if isinstance(kin, dict) and _numval(kin.get("lanzOdermattWorkingLength")) is not None:
        out["l"] = _numval(kin.get("lanzOdermattWorkingLength"))
    return out


def weapons_composition(weapons, wc: "WeaponCache") -> list:
    counts: dict[str, int] = {}
    for w in weapons:
        blk = first_str(w.get("blk")) if isinstance(w, dict) else ""
        if not blk or w.get("dummy"):
            continue
        trig = first_str(w.get("trigger")).lower()
        if trig == "countermeasures":
            continue
        n = num(w.get("bullets"), 1) or 1
        cont = wc.get(blk) if "container" in blk.lower() else None
        if isinstance(cont, dict) and cont.get("container") and first_str(cont.get("blk")):
            blk = first_str(cont.get("blk"))
            n = num(cont.get("bullets"), 1) or 1
        k = wc.weapon_name(blk)
        if trig in ("machine gun", "cannon", "gunner0", "gunner1", "additional gun"):
            n = 1
        counts[k] = counts.get(k, 0) + int(n)
    return [[k, v] for k, v in counts.items()]


ICON_VOTES: dict = {}  # weapon key -> {iconType: count}, to give catalog weapons the game's own icon
CATEGORY_ICONS = {"gun": "cannon", "aam_ir": "missile_air_to_air", "aam_radar": "missile_air_to_air_midrange", "sam": "missile_air_to_air_midrange",
                  "agm": "missile_air_to_uni",
                  "atgm": "missile_air_to_uni_middle", "rockets": "rockets_he_large", "bombs": "bombs_middle",
                  "guided_bombs": "guided_bomb_middle_laser", "nuke": "bombs_special", "fuel": "ptb",
                  "pods": "ltc", "torpedoes": "torpedo", "mines": "bombs_special"}


def weapon_slots(udata: dict, wc: "WeaponCache") -> list:
    """Pylons for custom aircraft loadouts: [{"i": slot index, "o": [{"n": preset, "w": composition}]}]."""
    ws = udata.get("WeaponSlots")
    if not isinstance(ws, dict):
        return []
    common = {w.get("slot") for w in aslist((udata.get("commonWeapons") or {}).get("Weapon")) if isinstance(w, dict) and "slot" in w}
    out = []
    for sl in aslist(ws.get("WeaponSlot")):
        if not isinstance(sl, dict) or sl.get("index") in common:
            continue
        opts, emitter = [], ""
        for wp in aslist(sl.get("WeaponPreset")):
            if isinstance(wp, dict) and wp.get("name"):
                comp = weapons_composition(aslist(wp.get("Weapon")), wc)
                if comp:
                    o = {"n": wp["name"], "w": comp}
                    icon = first_str(wp.get("iconType"))
                    if icon:
                        o["ic"] = icon
                        for k, _ in comp:
                            ICON_VOTES.setdefault(k, {}).setdefault(icon, 0)
                            ICON_VOTES[k][icon] += 1
                    opts.append(o)
                for w in aslist(wp.get("Weapon")):
                    if not emitter and isinstance(w, dict) and w.get("external") and first_str(w.get("trigger")) != "countermeasures":
                        emitter = first_str(w.get("emitter"))
        if opts:
            out.append({"i": sl.get("index"), "o": opts, "e": emitter, "t": num(sl.get("tier"), num(sl.get("index")))})
    out.sort(key=lambda x: x["i"] if isinstance(x["i"], int) else 0)
    return out


# real nuclear bombs of the game (the plain us_b61 / su_rn_28 files are inert dummies)
NUKES = ("su_rn_28_nt", "su_rn_40", "us_b61_5kt", "us_b61_30kt", "fr_an52_5kt_nt", "fr_an52_30kt_nt",
         "cn_kb1_5kt", "cn_kb1_30kt", "su_rds4_5kt_nt", "su_rds4_30kt_nt", "su_rds37")


def _natural(s: str):
    return [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", s.lower())]


def legacy_pylons(udata: dict, wc: "WeaponCache") -> tuple[list, dict]:
    """Aircraft without WeaponSlots: their fixed presets are plain Weapon{trigger, blk, emitter, bullets}
    lists. Each emitter (attachment point) becomes a pylon whose options are what the official presets hang
    there: ([{"i", "e": emitter, "o": [{"n", "w": composition, "r": [[trigger, blk, bullets]]}]}],
    {preset name: {pylon index: option name}})."""
    if isinstance(udata.get("WeaponSlots"), dict):
        return [], {}
    points: dict[str, dict] = {}  # emitter -> {signature: option}
    per_preset: dict[str, dict] = {}
    for p in aslist((udata.get("weapon_presets") or {}).get("preset")):
        if not isinstance(p, dict) or not p.get("name") or not p.get("blk"):
            continue
        pdata = load(blk_to_path(first_str(p.get("blk")))) or {}
        by_em: dict[str, list] = {}
        for w in aslist(pdata.get("Weapon")):
            if not isinstance(w, dict) or w.get("dummy"):
                continue
            em, blk, trig = first_str(w.get("emitter")), first_str(w.get("blk")), first_str(w.get("trigger"))
            if not em or not blk or not trig or trig == "countermeasures":
                continue
            by_em.setdefault(em, []).append([trig, blk, num(w.get("bullets"), 1) or 1])
        chosen = {}
        for em, raw in by_em.items():
            sig = repr(sorted(map(tuple, raw)))
            opts = points.setdefault(em, {})
            if sig not in opts:
                comp = weapons_composition([{"trigger": t, "blk": b, "bullets": n} for t, b, n in raw], wc)
                if not comp:
                    continue
                name = "+".join(k for k, _ in comp)
                taken = {o["n"] for o in opts.values()}
                base, i = name, 2
                while name in taken:
                    name, i = f"{base}#{i}", i + 1
                opts[sig] = {"n": name, "w": comp, "r": raw}
            chosen[em] = opts[sig]["n"]
        if chosen:
            per_preset[p["name"]] = chosen
    pylons = [{"i": i + 1, "e": em, "o": list(points[em].values())}
              for i, em in enumerate(sorted((e for e in points if points[e]), key=_natural))]
    index = {s["e"]: s["i"] for s in pylons}
    return pylons, {name: {str(index[em]): n for em, n in ch.items() if em in index} for name, ch in per_preset.items()}


def pylon_emitters(udata: dict) -> list:
    """Emitter nodes where this aircraft carries external stores, bomb points first."""
    bombs, other = [], []
    ws = udata.get("WeaponSlots")
    for sl in aslist(ws.get("WeaponSlot")) if isinstance(ws, dict) else []:
        for wp in aslist(sl.get("WeaponPreset")) if isinstance(sl, dict) else []:
            for w in aslist(wp.get("Weapon")) if isinstance(wp, dict) else []:
                if not isinstance(w, dict):
                    continue
                em = first_str(w.get("emitter"))
                if not em or not w.get("external") or first_str(w.get("trigger")) == "countermeasures":
                    continue
                (bombs if first_str(w.get("trigger")) == "bombs" else other).append(em)
    for p in aslist((udata.get("weapon_presets") or {}).get("preset")):
        pdata = load(blk_to_path(first_str(p.get("blk")))) if isinstance(p, dict) and p.get("blk") else None
        for w in aslist((pdata or {}).get("Weapon")):
            if isinstance(w, dict) and first_str(w.get("emitter")) and first_str(w.get("trigger")) != "countermeasures":
                (bombs if first_str(w.get("trigger")) == "bombs" else other).append(first_str(w["emitter"]))
    out = []
    for em in bombs + other:
        if em not in out:
            out.append(em)
    return out[:3]


def _r1(x, nd=1):
    return round(float(x), nd) if isinstance(x, (int, float)) and not isinstance(x, bool) else None


_CAL_CACHE: dict = {}


def _caliber_mm(blk: str) -> float | None:
    if blk in _CAL_CACHE:
        return _CAL_CACHE[blk]
    _CAL_CACHE[blk] = None
    d = load(blk_to_path(blk)) if blk else None
    for b in aslist((d or {}).get("bullet")):
        if isinstance(b, dict) and isinstance(b.get("caliber"), (int, float)):
            _CAL_CACHE[blk] = round(b["caliber"] * 1000, 1)
            break
    return _CAL_CACHE[blk]


def ground_speeds(udata: dict) -> tuple[float | None, float | None]:
    """Top forward / reverse speed (km/h) from the gearbox: max RPM through the highest gear."""
    try:
        m = udata["VehiclePhys"]["mechanics"]
        rpm = float(udata["VehiclePhys"]["engine"]["maxRPM"])
        gears = [float(g) for g in aslist((m.get("gearRatios") or {}).get("ratio")) if isinstance(g, (int, float))]
        k = rpm * 2 * math.pi * float(m["driveGearRadius"]) * 60 / 1000 / (float(m["mainGearRatio"]) * float(m.get("sideGearRatio", 1)))
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None, None
    fwd = [g for g in gears if g > 0]
    rev = [-g for g in gears if g < 0]
    return (round(k / min(fwd)) if fwd else None), (round(k / min(rev)) if rev else None)


def vehicle_stats(cat: str, udata: dict, wp: dict, tags: dict, st: dict, ammo: list) -> dict:
    """Comparable stats of a vehicle for the list (sort / filter) and the vehicle card. Units: km/h, m,
    m/s, s, deg/s, mm, t, hp/t. Air values are the game's own stat card (unittags Shop block)."""
    shop = (tags or {}).get("Shop") or {}
    out = {}
    if cat in ("air", "heli"):
        if shop.get("maxSpeed"):
            out["spd"] = round(shop["maxSpeed"] * 3.6)
        for key, src in (("alt", "maxSpeedAlt"), ("ceil", "maxAltitude"), ("turn", "turnTime"), ("roll", "rollRate"),
                         ("climb", "climbSpeed"), ("wl", "wingLoading")):
            if isinstance(shop.get(src), (int, float)) and shop[src] > 0.05:
                out[key] = _r1(shop[src])
        if shop.get("thrustToWeightRatio"):
            out["tw"] = _r1(shop["thrustToWeightRatio"], 2)
        elif shop.get("powerToWeightRatio"):
            out["pw"] = _r1(shop["powerToWeightRatio"] * 1000)  # hp / t
    elif cat == "ground":
        fwd, rev = ground_speeds(udata)
        if fwd:
            out["spd"] = fwd
        if rev:
            out["rev"] = rev
        if st.get("hp"):
            out["hp"] = round(st["hp"])
        if st.get("mass"):
            out["t"] = _r1(st["mass"] / 1000)
            if st.get("hp"):
                out["pw"] = _r1(st["hp"] / (st["mass"] / 1000))
        for key, src in (("armT", "armorThicknessTurret"), ("armH", "armorThicknessHull")):
            if isinstance(shop.get(src), list) and any(shop[src][:3]):  # all zeros in some cards: unknown, not 0 mm
                out[key] = [round(x) for x in shop[src][:3]]
        ts = wp.get("turretSpeed")
        if isinstance(ts, list) and ts and isinstance(ts[0], (int, float)) and ts[0] > 0:
            out["trav"] = _r1(ts[0])
        main = next((g for g in ammo if g.get("trig") == "gunner0" or g.get("wi") == 1), ammo[0] if ammo else None)
        if main:
            cal = _caliber_mm(main.get("p", ""))
            if cal:
                out["cal"] = cal
            heat = max((o.get("s", {}).get("h") or 0 for o in main.get("opts", [])), default=0)
            if heat:
                out["heat"] = round(heat)
            kin = max((o.get("s", {}).get("k") or 0 for o in main.get("opts", [])), default=0)
            if kin:
                out["kin"] = round(kin)
        if isinstance(wp.get("reloadTime_cannon"), (int, float)):
            out["rel"] = _r1(wp["reloadTime_cannon"])
    else:  # boats and ships
        if shop.get("maxSpeed"):
            out["spd"] = round(shop["maxSpeed"] * 3.6)
        if shop.get("displacement"):
            out["disp"] = round(shop["displacement"] / 1000)
        main = ammo[0] if ammo else None
        cal = _caliber_mm(main.get("p", "")) if main else None
        if cal:
            out["cal"] = cal
    if isinstance(wp.get("crewTotalCount"), (int, float)) and wp["crewTotalCount"] > 0:
        out["crew"] = int(wp["crewTotalCount"])
    for key, src in (("rp", "reqExp"), ("sl", "value")):  # research cost (RP) and purchase cost (SL)
        if isinstance(wp.get(src), (int, float)) and wp[src] > 0:
            out[key] = int(wp[src])
    return out


ECONOMY_MODES = ("Arcade", "Historical", "Simulation")


def _f32(x: float) -> float:
    return struct.unpack("f", struct.pack("f", x))[0]


def _game_round(x: float, step: float) -> float:
    """round_by_value of the game's scripts, in its 32-bit floats: 1.45 gives 1.5 and 4.95 gives 4.9, as on its own cards."""
    step = _f32(step)
    return _f32(math.floor(_f32(_f32(x) / step + 0.5)) * step)


def vehicle_economy(cat: str, wp: dict, warpoints: dict, ranks: dict) -> tuple[dict, dict]:
    """What a vehicle costs and earns, worked out as the game's own card does (scripts/unit/unit.nut getWpRewardMulList,
    unitInfoType.nut full_repair_cost, wp_bonus, exp_bonus). -> (stats, stock stats), one value per mode where it's a list, None
    for a mode the vehicle doesn't have (ships: no SB). Left out, no script uses them: repairCostFullUpgraded*, up to 3 % off
    the game's cards, battleTime*, avgAward*, battleTimeAward*. repairCostPerMin* is behind a feature that's off.
      rep  repair cost in SL with all modules: base x (1 + what they add); stock in the second dict, when it differs
      slm  Silver Lions reward in %. Premium vehicles: half of it rounded finer, times 2, the part the vehicle brings
      rpm  Research Points reward in %. Premium vehicles: times goldPlaneExpMul
      fr   free repairs after buying the vehicle; a reserve vehicle's repairs are always free"""
    if "repairCostArcade" not in wp:
        return {}, {}
    visual = warpoints.get("rewardMulVisual") or {}
    special = int(wp.get("costGold", 0)) > 0
    part = visual.get("premRewardMulVisualPart", 0.5) if special else 0.0
    mods = wp.get("modifications")
    coef = 1 + sum(m.get("repairCostCoef", 0) for m in mods.values() if isinstance(m, dict)) if isinstance(mods, dict) else 1
    stock, rep, slm = [None] * 3, [None] * 3, [None] * 3
    for i, mode in enumerate(ECONOMY_MODES[:2] if cat in ("boat", "ship") else ECONOMY_MODES):
        base = wp.get(f"repairCost{mode}", 0) * warpoints.get("avgRepairMul", 1.0)
        stock[i], rep[i] = round(base), round(base * coef)
        mul = _f32(_f32(_f32(wp.get(f"rewardMul{mode}", 1.0)) * _f32(visual.get(f"rewardMulVisual{mode}", 1.0))) * _f32(1.0 - part))
        slm[i] = int(_f32(_game_round(mul, 0.05 if special else 0.1) * _game_round(1.0 / (1.0 - part), 0.1)) * 100.0 + 0.5)
    talisman = ranks.get("goldPlaneExpMul", 1.0) if special else 1.0
    out = {"rep": rep, "slm": slm, "rpm": int(_f32(_f32(wp.get("expMul", 1.0)) * _f32(talisman)) * 100.0 + 0.5)}
    if any(stock):
        out["fr"] = int(wp.get("freeRepairs", warpoints.get("freeRepairs", 0)))
    return out, {"rep": stock} if stock != rep else {}


def engine_kinds(fm: dict) -> list:
    """The kind of each Engine<n> of a flight model: Jet, Inline, Radial, Rocket..."""
    engines = [v for k, v in fm.items() if re.fullmatch(r"Engine\d+", k) and isinstance(v, dict)]
    return [((fm.get(f"EngineType{e.get('Type')}") or e).get("Main") or {}).get("Type") for e in engines]


def engine_count(fm: dict) -> int:
    """Engines of a flight model as /state lists them: take-off rockets (A-4, Mirage III...) are Engine<n> too."""
    kinds = engine_kinds(fm)
    return sum(k != "Rocket" for k in kinds) or len(kinds)  # or: rocket planes (Me 163)


def flight_limits(fm: dict, cat: str) -> dict:
    """Breaking limits of an aircraft for the in-flight alarms (speeds: km/h, indicated). v, m: airframe speed and
    Mach; sw: variable sweep [[sweep, v, m], ...], v and m being then the swept-back limits; gear: 0 = none;
    flaps: [[position 0..1, speed], ...]; fuel: MaxFuelMass0 and the tanks' sum, /state's Mfuel0 is one or the other;
    mass: empty, kg; jet: true on jets, for the overlays by kind of engine."""
    aero, mass = fm.get("Aerodynamics") or {}, fm.get("Mass") or {}
    strength = (aero.get("WingPlane") or {}).get("Strength") or {}
    sweeps = [aero[k] for k in aero if re.fullmatch(r"WingPlaneSweep\d+", k)]
    out = {}
    if sweeps:
        out["sw"] = sorted([s.get("Sweep", 0), s["Strength"]["VNE"], s["Strength"]["MNE"]] for s in sweeps)
    out["v"] = fm.get("Vne") or strength.get("VNE") or max((s[1] for s in out.get("sw", ())), default=0)
    out["m"] = fm.get("VneMach") or strength.get("MNE") or max((s[2] for s in out.get("sw", ())), default=0)
    if not out["v"]:
        return {}
    out["gear"] = max(mass.get("GearDestructionIndSpeed") or 0, 0)
    if cat == "air":  # helicopters have flap entries too, with made-up values
        pairs = []
        for k, v in mass.items():
            if re.fullmatch(r"FlapsDestructionIndSpeedP\d*", k):  # P: flat list; P0, P1...: a pair, or pairs when repeated
                v = v if isinstance(v, list) else [0, v]  # a lone speed (I-16): any position
                pairs += v if isinstance(v[0], list) else [v[i:i + 2] for i in range(0, len(v), 2)]
        if pairs:
            out["flaps"] = sorted(pairs)
    tanks = sum(x for k, v in (mass.get("Parts") or {}).items() if k.endswith("_capacity") for x in aslist(v))
    out["fuel"] = [round(x, 2) for x in (mass.get("MaxFuelMass0", 0), tanks) if x]
    out["eng"] = engine_count(fm)
    out["mass"] = _numval(mass.get("EmptyMass")) or 0
    if "Jet" in engine_kinds(fm):
        out["jet"] = True
    return out


def fm_file(fm_path: str) -> Path:
    """'fm/su_30mkk.blk' -> datamine path to the flight model. Also seen: no .blk (F-16 AM), a leading / (Tornado)."""
    return DM / "aces.vromfs.bin_u" / "gamedata" / "flightmodels" / (fm_path.lower().strip("/").removesuffix(".blk") + ".blkx")


def base_stats(vid: str, udata: dict, cat: str) -> dict:
    """Editable vehicle values with their stock value (used by the Modifications step)."""
    st = {}
    if cat == "ground":
        vp = udata.get("VehiclePhys") or {}
        eng, mass, mech = vp.get("engine") or {}, vp.get("Mass") or {}, vp.get("mechanics") or {}
        for key, src in (("hp", eng.get("horsePowers")), ("rpm", eng.get("maxRPM")), ("mass", mass.get("Empty")),
                         ("fuel", mass.get("Fuel")), ("brake", mech.get("maxBrakeForce")), ("gear", mech.get("mainGearRatio"))):
            val = _numval(src)
            if val is not None:
                st[key] = val
    elif cat in ("air", "heli"):
        fm_path = first_str(udata.get("fmFile"))
        fm = load(fm_file(fm_path or f"fm/{vid}")) or {}  # no fmFile: the flight model is named after the aircraft
        limits = flight_limits(fm, cat)
        if limits:
            st["lim"] = limits
        if fm_path:
            st["fm"] = fm_path
            mass = fm.get("Mass") or {}
            for key, src in (("mass", mass.get("EmptyMass")), ("fuel", mass.get("MaxFuelMass0"))):
                val = _numval(src)
                if val is not None:
                    st[key] = val
            main = ((fm.get("EngineType0") or {}).get("Main")) or {}
            if isinstance(main, dict):
                st["etype"] = first_str(main.get("Type"))
                for key, src in (("thrust", main.get("Thrust")), ("tboost", main.get("ThrottleBoost")), ("abboost", main.get("AfterburnerBoost"))):
                    val = _numval(src)
                    if val is not None:
                        st[key] = val
    return st


def preset_composition(preset: dict, fm: dict | None, wc: WeaponCache):
    """Returns [[weaponKey, count], ...] for a weapon preset."""
    blk = first_str(preset.get("blk"))
    pdata = load(blk_to_path(blk)) if blk else None
    counts: dict[str, int] = {}
    if not pdata:
        return []
    slots = {}
    if fm and isinstance(fm.get("WeaponSlots"), dict):
        for s in aslist(fm["WeaponSlots"].get("WeaponSlot")):
            if isinstance(s, dict):
                slots[s.get("index")] = {p.get("name"): p for p in aslist(s.get("WeaponPreset")) if isinstance(p, dict)}

    def add_weapon(w):
        blk = first_str(w.get("blk")) if isinstance(w, dict) else ""
        if not blk:
            return
        trig = first_str(w.get("trigger")).lower()
        if trig in ("countermeasures",) or w.get("dummy"):
            return
        n = num(w.get("bullets"), 1) or 1
        cont = wc.get(blk) if "container" in blk.lower() else None
        if isinstance(cont, dict) and cont.get("container") and first_str(cont.get("blk")):
            # pod / rack: count the munitions it carries
            blk = first_str(cont.get("blk"))
            n = num(cont.get("bullets"), 1) or 1
        k = wc.weapon_name(blk)
        if trig in ("machine gun", "cannon", "gunner0", "gunner1", "additional gun"):
            n = 1  # guns: count barrels not rounds
        counts[k] = counts.get(k, 0) + int(n)

    for w in aslist(pdata.get("Weapon")):
        if isinstance(w, dict) and "slot" in w and "preset" in w:
            sp = slots.get(w["slot"], {}).get(w["preset"])
            if sp:
                for sw in aslist(sp.get("Weapon")):
                    add_weapon(sw)
        else:
            add_weapon(w)
    return [[k, v] for k, v in counts.items()]


def ground_side_weapons(udata: dict) -> list:
    """A ground vehicle's weapons outside commonWeapons, as the game counts them (bulletsinfo.nut): pilons (Pantsir-SM),
    and a SAM battery's launchers: its radar holds their missiles, the load of all of them (wpcost: ammoCount)."""
    out = [w for sl in aslist((udata.get("WeaponPilons") or {}).get("WeaponSlot")) if isinstance(sl, dict)
           for p in aslist(sl.get("WeaponPreset")) if isinstance(p, dict)
           for w in aslist(p.get("Weapon")) if isinstance(w, dict)]
    launchers: dict = {}
    for p in aslist((udata.get("supportPlanes") or {}).get("plane")):
        if isinstance(p, dict) and p.get("isSlave"):
            cls = first_str(p.get("class")).rsplit("/", 1)[-1]
            launchers[cls] = launchers.get(cls, 0) + num(p.get("count"), 1)
    for cls, n in launchers.items():
        for w in aslist(((load(unit_file(cls, "ground")) or {}).get("commonWeapons") or {}).get("Weapon")):
            if isinstance(w, dict) and not w.get("dummy"):
                out.append(dict(w, bullets=num(w.get("bullets")) * n))
    return out


def vehicle_ammo(udata: dict, cat: str, official_mods: set, wc: WeaponCache):
    """Ammo groups: one per distinct gun able to take alternate ammo / belts."""
    groups = []
    seen = set()
    weapons = []
    slots = {}
    if isinstance(udata.get("WeaponSlots"), dict):
        for sl in aslist(udata["WeaponSlots"].get("WeaponSlot")):
            if isinstance(sl, dict):
                slots[sl.get("index")] = {p.get("name"): p for p in aslist(sl.get("WeaponPreset")) if isinstance(p, dict)}
    for wi, w in enumerate(aslist((udata.get("commonWeapons") or {}).get("Weapon")), start=1):
        if isinstance(w, dict) and "slot" in w and "preset" in w:
            # modern aircraft declare their guns through a weapon slot preset
            weapons += [(None, x) for x in aslist(slots.get(w["slot"], {}).get(w["preset"], {}).get("Weapon")) if isinstance(x, dict) and not x.get("dummy")]
        else:
            weapons.append((wi, w))
    if cat == "ground":
        weapons += [(None, w) for w in ground_side_weapons(udata)]
    for wi, w in weapons:
        blk = first_str(w.get("blk")) if isinstance(w, dict) else ""
        if not blk:
            continue
        key = blk.lower()
        if key in seen:
            # several barrels of the same gun share belts
            for g in groups:
                if g["blk"] == key:
                    g["n"] += 1
            continue
        seen.add(key)
        default, sets = wc.bullet_sets(blk)
        if not sets and not default:
            continue
        opts = []
        # ground missiles: the game hides the default set and names one, in its menus and missions (tank_sam_ir_caged_tft)
        named_only = (cat == "ground" and default and first_str(default.get("t")).startswith(("sam", "atgm"))
                      and (wc.get(blk) or {}).get("notUseDefaultBulletInGui")
                      and any(m in official_mods and not m.endswith("_ammo_pack") for m in sets))
        if default and not named_only:
            opts.append({"id": "", **default})
        for mod, s in sets.items():
            if mod.endswith("_ammo_pack"):
                continue
            o = {"id": mod, **s}
            if mod not in official_mods:
                o["x"] = 1  # not normally available on this vehicle
            opts.append(o)
            wc.lang.put("mods", mod, f"modification/{mod}/short", f"modification/{mod}", f"{mod}/name/short")
        if len(opts) <= 1 and cat != "ground":
            continue
        g = {
            "blk": key,
            "p": blk,  # original path, used to build a custom weapon file
            "w": wc.weapon_name(blk),
            "trig": first_str(w.get("trigger")),
            "cap": num(w.get("bullets")),
            "n": 1,
            "opts": opts,
            "rank": len(opts) + bool(named_only),  # saved gun changes go by a weapon's place: it stays where it was
        }
        if wi:
            g["wi"] = wi  # 1-based index of this Weapon block in commonWeapons
            for key2, src in (("yaw", w.get("speedYaw")), ("pitch", w.get("speedPitch"))):
                val = _numval(src)
                if val is not None:
                    g[key2] = val
        sf = _numval((wc.get(blk) or {}).get("shotFreq"))
        if sf:
            g["sf"] = sf
        groups.append(g)
    if cat == "ground":
        # main gun first (gunner0 with the most ammo options)
        groups.sort(key=lambda g: (g["trig"] != "gunner0", -g["rank"]))
    for g in groups:
        del g["blk"], g["rank"]
    return groups[:4]


PREFIX_NATION = {"us": "usa", "germ": "germany", "ger": "germany", "ussr": "ussr", "uk": "britain", "jp": "japan",
                 "cn": "china", "it": "italy", "fr": "france", "sw": "sweden", "il": "israel"}


def guess_nation(vid: str) -> str:
    return PREFIX_NATION.get(vid.lower().split("_", 1)[0], "")


# vehicle roles for the "type" filter, from unittags (localized by the game: menu.csv mainmenu/type_<role>)
ROLES = ("light_tank", "medium_tank", "heavy_tank", "tank_destroyer", "spaa", "missile_tank",
         "fighter", "jet_fighter", "interceptor", "aa_fighter", "assault", "strike_aircraft", "bomber",
         "dive_bomber", "light_bomber", "frontline_bomber", "longrange_bomber", "jet_bomber", "torpedo",
         "naval_aircraft", "hydroplane", "strike_ucav", "drone", "attack_helicopter", "utility_helicopter",
         "boat", "torpedo_boat", "gun_boat", "torpedo_gun_boat", "heavy_boat", "heavy_gun_boat", "armored_boat",
         "submarine_chaser", "minelayer", "barge", "frigate", "destroyer", "light_cruiser", "heavy_cruiser",
         "battlecruiser", "battleship")
CLASS_ROLES = {"tank_destroyer": "tank_destroyer", "SPAA": "spaa", "fighter": "fighter", "assault": "assault",
               "bomber": "bomber", "torpedo_boat": "torpedo_boat", "gun_boat": "gun_boat",
               "torpedo_gun_boat": "torpedo_gun_boat", "submarine_chaser": "submarine_chaser", "destroyer": "destroyer"}


AVIONICS = ("laserDesignator", "havePointOfInterestDesignator", "hasHelmetDesignator", "haveCCIPForGun", "haveCCIPForRocket",
            "haveCCIPForBombs", "haveCCRPForBombs", "haveCCRPForGun")
NOT_UNITS = re.compile(r"(^|_)(test|dummy|fake)(_|$)|_includes$|_destroyed_unit$|searchlight|_test_gun")
OBJECT_BLOCKS = ("air_defence", "structures", "wheeled_vehicles", "tracked_vehicles", "radars", "infantry")  # folder = mission block
DRONES = ("uav_", "ucav_recon")  # drones the player flies (scout / FPV drones), not the strike UCAVs


def vehicle_roles(tags: dict, unit_class: str, lang: "Lang", vid: str = "") -> list:
    tg = (tags or {}).get("tags") or {}
    roles = [k[5:] for k, on in tg.items() if on is True and k.startswith("type_") and k[5:] in ROLES]
    if vid.lower().startswith(DRONES):
        roles = [r for r in roles if r not in ("fighter", "jet_fighter", "drone")] + ["drone"]
    if not roles and CLASS_ROLES.get(unit_class):
        roles = [CLASS_ROLES[unit_class]]
    for r in roles:
        lang.put("roles", r, f"mainmenu/type_{r}", fallback=humanize(r))
    return sorted(roles, key=ROLES.index)


def build_vehicles(lang: Lang, progress=None):
    log("Reading vehicle economy table (wpcost)...", progress)
    report(progress, 0.49)
    wp = load(DM / "char.vromfs.bin_u" / "config" / "wpcost.blkx") or {}
    unittags = load(DM / "char.vromfs.bin_u" / "config" / "unittags.blkx") or {}
    warpoints = load(DM / "char.vromfs.bin_u" / "config" / "warpoints.blkx") or {}
    ranks = load(DM / "char.vromfs.bin_u" / "config" / "rank.blkx") or {}
    arsenal: dict = {}  # every weapon / ammo carried by a vehicle: category + icon / caliber / shell type
    wc = WeaponCache(lang)
    vehicles, details = [], {}

    entries = []
    for vid, v in wp.items():
        if not isinstance(v, dict) or "unitMoveType" not in v:
            continue
        cat = categorize(v.get("unitMoveType", ""), v.get("unitClass", ""))
        if cat == "other":
            continue
        entries.append((vid, cat, v, False))

    # Units that exist in the game files but are not in the shop (AI, event, removed, dev).
    known = {e[0].lower() for e in entries}
    base = DM / "aces.vromfs.bin_u" / "gamedata"
    for folder, cat in ((base / "units" / "tankmodels", "ground"), (base / "units" / "ships", "ship"), (base / "flightmodels", "air")):
        for f in folder.glob("*.blkx"):
            vid = f.stem
            if vid.lower() in known:
                continue
            if not (lang.get(f"{vid}_shop") or lang.get(f"{vid}_0")) and NOT_UNITS.search(vid.lower()):
                continue  # unnamed test and helper files; the other unnamed ones are real: carriers, trains, transports
            entries.append((vid, cat, {}, True))

    for n in NUKES:
        wc.weapon_name(f"gameData/Weapons/bombGuns/{n}.blk")
    catalog = build_weapon_catalog(wc, progress)
    with open(DATA / "weapons.json", "w", encoding="utf-8") as fw:
        json.dump(catalog, fw, separators=(",", ":"))
    log(f"Processing {len(entries)} vehicles...", progress)
    for i, (vid, cat, v, hidden) in enumerate(entries):
        if i % 500 == 0 and i:
            log(f"  {i}/{len(entries)}", progress)
        if i % 40 == 0:
            report(progress, 0.56 + 0.30 * i / max(1, len(entries)))
        udata = load(unit_file(vid, cat))
        if udata is None:
            continue
        if hidden and cat == "air":
            t = str(udata.get("type", "")).lower()
            if "helicopter" in t:
                cat = "heli"
            if not udata.get("fmFile") and "helicopter" not in t:
                continue
        if hidden and cat == "ship":
            ec = str(udata.get("expClass", "") or udata.get("type", "")).lower()
            if "boat" in ec or "fast" in ec:
                cat = "boat"

        lang.put("units", vid, f"{vid}_shop", f"{vid}_0", fallback=humanize(vid))
        if f"{vid}_0" in lang.all:
            lang.put("unitsFull", vid, f"{vid}_0")

        country = (v.get("country") or "").replace("country_", "") or guess_nation(vid)
        rec = {
            "id": vid,
            "c": cat,
            "n": country or "other",
            "r": num(v.get("rank")),
            "br": [br_from(v.get("economicRankArcade")), br_from(v.get("economicRankHistorical")), br_from(v.get("economicRankSimulation"))],
            "k": (v.get("unitClass") or "").replace("exp_", ""),
        }
        if v.get("costGold"):
            rec["p"] = 1
        if v.get("reqAir"):
            rec["rq"] = v["reqAir"]  # the vehicle to research first
        if hidden:
            rec["h"] = 1
        if not v.get("value") and not v.get("costGold") and not hidden:
            rec["g"] = 1  # gift / event / squadron etc.

        mods = set(aslist(v.get("modifications")) if isinstance(v.get("modifications"), list) else (v.get("modifications") or {}).keys())

        presets = []
        for p in aslist((udata.get("weapon_presets") or {}).get("preset")):
            if not isinstance(p, dict) or not p.get("name"):
                continue
            entry = {"id": p["name"], "w": preset_composition(p, udata if cat in ("air", "heli") else None, wc)}
            if cat in ("air", "heli"):
                pdata = load(blk_to_path(first_str(p.get("blk")))) or {}
                smap = {str(w["slot"]): w["preset"] for w in aslist(pdata.get("Weapon"))
                        if isinstance(w, dict) and "slot" in w and "preset" in w}
                if smap:
                    entry["s"] = smap
            if p.get("reqModification"):
                entry["req"] = p["reqModification"]
            presets.append(entry)

        details[vid] = {
            "b": UNIT_BLOCK[cat],
            "pr": presets,
            "am": vehicle_ammo(udata, cat, mods, wc),
            "st": base_stats(vid, udata, cat),
        }
        if cat in ("air", "heli"):
            sl = weapon_slots(udata, wc)
            if sl:
                details[vid]["sl"] = sl
            # fixed presets only: their attachment points, for a custom loadout written as plain weapons
            lp, lmap = legacy_pylons(udata, wc)
            if lp:
                details[vid]["lp"] = lp
                for entry in presets:
                    if lmap.get(entry["id"]):
                        entry["ls"] = lmap[entry["id"]]
            em = pylon_emitters(udata)
            if em:
                details[vid]["em"] = em
            if not sl and not lp:  # no pylon at all: its first gun's muzzle takes what's mounted
                gun = next((first_str(w.get("emitter")) for w in aslist((udata.get("commonWeapons") or {}).get("Weapon"))
                            if isinstance(w, dict) and first_str(w.get("emitter")) and first_str(w.get("trigger")) in ("machine gun", "cannon")), "")
                if gun:
                    lp = details[vid]["lp"] = [{"i": 1, "e": gun, "o": []}]
            own = [first_str(s.get("blk")).replace("\\", "/").rsplit("/", 1)[-1].removesuffix(".blk").lower()
                   for s in aslist((udata.get("sensors") or {}).get("sensor")) if isinstance(s, dict)]
            if own:
                details[vid]["se"] = own
            flags = [k for k in AVIONICS if udata.get(k) is True]
            if flags:
                details[vid]["av"] = flags
            if ((details[vid].get("st") or {}).get("lim") or {}).get("jet"):
                rec["j"] = 1
            keys = {k for s in sl for o in s["o"] for k, _ in o["w"]} | {k for p in presets for k, _ in p["w"]}
            for s in sl + lp:
                for o in s["o"]:
                    o["c"] = next(((catalog.get(k) or {}).get("c") for k, _ in o["w"] if catalog.get(k)), "")
            caps = aircraft_caps(udata, catalog, keys)
            if caps:
                details[vid]["cap"] = caps
        roles = vehicle_roles(unittags.get(vid) or {}, rec["k"], lang, vid)
        if roles:
            rec["ro"] = roles
        stats = vehicle_stats(cat, udata, v, unittags.get(vid) or {}, details[vid]["st"], details[vid]["am"])
        economy, stock_economy = vehicle_economy(cat, v, warpoints, ranks)
        stats.update(economy)
        if stats:
            rec["s"] = stats
            su = {**stock_stats(cat, stats, stock_factors(udata, mods)), **stock_economy}
            if su:
                rec["su"] = su  # stock values (rec["s"] = fully upgraded)
        # what it carries, for "search by weapon": guns, presets / pylon weapons, ammunition
        guns, carried, ammo_names = [], [], []
        for g in details[vid]["am"]:
            if g.get("w"):
                guns.append(g["w"])
                if g["w"] not in arsenal:
                    arsenal[g["w"]] = {"c": "gun", "cal": _caliber_mm(g.get("p", ""))}
            for o in g.get("opts", []):
                if o.get("x"):
                    continue
                for b in o.get("b", []):
                    ammo_names.append(b)
                    if b not in arsenal and o.get("t"):
                        arsenal[b] = {"c": "ammo", "t": o["t"][0]}
        carried += [k for p in presets for k, _ in p["w"]]
        carried += [k for sl_ in details[vid].get("sl", []) for o in sl_["o"] for k, _ in o["w"]]
        for key, lst in (("wg", guns), ("wp", carried), ("wa", ammo_names)):
            if lst:
                rec[key] = list(dict.fromkeys(lst))
        vehicles.append(rec)
    for key, entry in catalog.items():
        votes = ICON_VOTES.get(key)
        entry["ic"] = max(votes, key=votes.get) if votes else CATEGORY_ICONS.get(entry["c"], "bombs_middle")
    with open(DATA / "weapons.json", "w", encoding="utf-8") as fw:
        json.dump(catalog, fw, separators=(",", ":"))
    # pylon / preset weapons: category and game icon from the catalog (variants like "<key>_default" too)
    for v in vehicles:
        for k in v.get("wp", []):
            if k in arsenal:
                continue
            base = catalog.get(k) or catalog.get(re.sub(r"(_default|_\d+)$", "", k))
            votes = ICON_VOTES.get(k)
            arsenal[k] = {"c": (base or {}).get("c", "other"),
                          "ic": max(votes, key=votes.get) if votes else (base or {}).get("ic", "")}
    with open(DATA / "arsenal.json", "w", encoding="utf-8") as fw:
        json.dump(arsenal, fw, separators=(",", ":"))
    return vehicles, details


# --------------------------------------------------------------------------- air weapons catalog

CATALOG_FOLDERS = ("rocketguns", "bombguns", "torpedoes", "mines", "drop_tank", "equipment", "containers")
SURFACE_FOLDERS = ("groundmodels_weapons", "navalmodels_weapons")  # their missiles and rockets go on pylons too: see launched_rockets
GUN_SKIP = re.compile(r"test|tutorial|dummy|event|pony|toon|melee|bayonet|human|grenade|_user_cannon|no_gun")
TRIGGERS = {"aam_ir": "aam", "aam_radar": "aam", "agm": "atgm", "atgm": "atgm", "rockets": "rockets",
            "bombs": "bombs", "guided_bombs": "guided bombs", "nuke": "bombs", "torpedoes": "torpedoes",
            "mines": "bombs", "fuel": "fuel tanks", "pods": "targetingPod"}
GUIDANCE = {"radar": "radar", "laser": "laser", "saclos": "saclos", "sns": "gps", "sonar": ""}


def _payload(d: dict):
    for k in ("rocket", "bomb", "torpedo", "mine"):
        if k in d:
            v = d[k]
            v = v[0] if isinstance(v, list) and v else v
            return k, v if isinstance(v, dict) else {}
    return None, {}


def launched_rockets(d) -> list:
    """What a ground or ship launcher fires, each in one block. Most launchers are guns: `bullet` holds the projectile,
    `bullet.rocket` how it flies. A few have a `rocket` block, as an aircraft's weapon does."""
    if not isinstance(d, dict):
        return []
    out = [x for x in aslist(d.get("rocket")) if isinstance(x, dict)]
    return out + [{**{k: v for k, v in b.items() if k != "rocket"}, **b["rocket"]} for b in aslist(d.get("bullet"))
                  if isinstance(b, dict) and isinstance(b.get("rocket"), dict)]


def launched_missile(d) -> dict | None:
    """The guided one of them, if any."""
    return next((r for r in launched_rockets(d) if isinstance(r.get("guidance"), dict) or first_str(r.get("guidanceType")).lower() not in ("", "none")), None)


def gun_rounds(d) -> int:
    """How many rounds a gun takes on a pylon, by its caliber; 0 when the file isn't a gun's."""
    bullet = next((b for b in aslist(d.get("bullet")) if isinstance(b, dict)), None) if isinstance(d, dict) else None
    if not bullet or isinstance(bullet.get("rocket"), dict):
        return 0
    caliber = _numval(bullet.get("caliber")) or 0.02
    return 500 if caliber < 0.025 else 150 if caliber < 0.06 else 40


def build_sensors(lang) -> dict:
    """{file: kind} of every aircraft sensor of the game (radar, rwr, mlws, lws), for the vehicle panel."""
    out = {}
    for f in sorted((DM / "aces.vromfs.bin_u" / "gamedata" / "sensors").glob("*.blkx")):
        kind = first_str((load(f) or {}).get("type"))
        if kind in ("radar", "rwr", "mlws", "lws"):
            out[f.stem] = kind
            lang.put("sensors", f.stem, f"sensors/{f.stem}", fallback=humanize(f.stem))
    with open(DATA / "sensors.json", "w", encoding="utf-8") as fw:
        json.dump(out, fw, separators=(",", ":"))
    return out


def build_objects(lang) -> list:
    """What the scenario editor can place besides vehicles: AA guns, trucks, buildings, radars... [{"id", "b": mission block}]."""
    out = []
    for block in OBJECT_BLOCKS:
        for f in sorted((DM / "aces.vromfs.bin_u" / "gamedata" / "units" / block).glob("*.blkx")):
            if lang.get(f"{f.stem}_0") or not NOT_UNITS.search(f.stem):
                out.append({"id": f.stem, "b": block})
                lang.put("units", f.stem, f"{f.stem}_shop", f"{f.stem}_0", fallback=humanize(f.stem))
    for f in sorted((DM / "aces.vromfs.bin_u" / "gamedata" / "objectgroups").glob("*.blkx")):
        if not NOT_UNITS.search(f.stem) and json.loads(f.read_text(encoding="utf-8")).get("node"):
            out.append({"id": f.stem, "b": "objectGroups"})
            lang.put("units", f.stem, f"{f.stem}_shop", f"{f.stem}_0", fallback=humanize(f.stem))
    with open(DATA / "objects.json", "w", encoding="utf-8") as fw:
        json.dump(out, fw, separators=(",", ":"))
    return out


def classify_weapon(d: dict, folder: str):
    """-> (category, guidance) for an air-launched weapon file, or None to skip it."""
    if not isinstance(d, dict):
        return None
    if folder == "drop_tank":
        return "fuel", ""
    if folder == "equipment":
        return ("pods", "") if d.get("mesh") or d.get("payload") else None
    kind, p = _payload(d)
    bt = first_str(p.get("bulletType")).lower()
    gt = first_str(p.get("guidanceType")).lower()
    if folder == "torpedoes" or kind == "torpedo":
        return "torpedoes", ""
    if folder == "mines":
        return "mines", ""
    if bt in ("flare", "chaff") or not kind:
        return None
    if bt == "aam":
        return ("aam_radar", "radar") if gt == "radar" else ("aam_ir", "ir")
    if gt and gt != "none":
        g = GUIDANCE.get(gt, "tv" if gt == "optical" else gt)
        if kind == "bomb" or folder == "bombguns":
            return "guided_bombs", g
        return ("atgm", g) if bt.startswith("atgm") else ("agm", g)
    if kind == "bomb":
        return "bombs", ""
    if kind == "rocket":
        return "rockets", ""
    return None


def build_weapon_catalog(wc: "WeaponCache", progress=None) -> dict:
    """Every air-launched weapon of the game: {key: {"p": blk path, "c": category, "g": guidance, "t": trigger,
    "m": mass in kg}}."""
    log("Building the air weapons catalog...", progress)
    report(progress, 0.50)
    base = DM / "aces.vromfs.bin_u" / "gamedata" / "weapons"
    out = {}
    for folder in CATALOG_FOLDERS:
        for f in sorted((base / folder).glob("*.blkx")):
            d = load(f)
            path = f"gameData/Weapons/{folder}/{f.stem}.blk"
            if folder == "containers":
                if not isinstance(d, dict) or not first_str(d.get("blk")):
                    continue
                inner = first_str(d["blk"])
                ifolder = inner.replace("\\", "/").split("/")[-2].lower()
                cl = classify_weapon(load(blk_to_path(inner)), ifolder)
                if not cl:
                    continue
                cat, g = cl
                entry = {"p": path, "c": cat, "g": g, "t": TRIGGERS.get(cat, "bombs"), "pod": num(d.get("bullets"), 1) or 1}
            else:
                cl = classify_weapon(d, folder)
                if not cl:
                    continue
                cat, g = cl
                if f.stem in NUKES:
                    cat = "nuke"
                entry = {"p": path, "c": cat, "g": g, "t": TRIGGERS.get(cat, "bombs")}
                mass = _numval((_payload(d)[1] or {}).get("mass"))
                if mass:
                    entry["m"] = round(mass, 1)  # kg: the game's loadout grid puts the heaviest in the middle
            key = wc.weapon_name(path)
            out[key] = entry
    for folder in SURFACE_FOLDERS:
        seen = set()  # one per missile: launchers share them, the "user_cannon" ones last
        for f in sorted((base / folder).glob("*.blkx"), key=lambda p: ("user_cannon" in p.stem, p.stem)):
            d = load(f)
            missile = launched_missile(d) or next((r for r in launched_rockets(d) if not re.match(r"flare|chaff|smoke|.*grenade", first_str(r.get("bulletType")).lower())), None)
            name = first_str((missile or {}).get("bulletName")).lower()
            if not name or name in seen:
                continue
            seen.add(name)
            bt, gt = first_str(missile.get("bulletType")).lower(), first_str(missile.get("guidanceType")).lower()
            guided, sam = bool(launched_missile(d)), bt.startswith(("sam", "aam"))
            cat = "sam" if guided and sam else "atgm" if guided else "rockets"
            path, entry = f"gameData/Weapons/{folder}/{f.stem}.blk", {"c": cat, "t": {"sam": "aam", "atgm": "atgm"}.get(cat, "rockets"), "air": 1}
            entry.update(p=path, g=("" if not guided else ("ir" if sam else "tv") if gt == "optical" else GUIDANCE.get(gt, gt)))
            mass = _numval(missile.get("mass"))
            if mass:
                entry["m"] = round(mass, 1)
            key = basename(path)
            wc.lang.put("weapons", key, f"weapons/{name}/short", f"{name}/short", name, f"weapons/{name}", f"weapons/{key}", key, fallback=humanize(name))
            out[key] = entry
    for folder in ("", *SURFACE_FOLDERS):  # guns: the aircraft's lie loose in Weapons
        for f in sorted((base / folder).glob("*.blkx")):
            rounds = gun_rounds(load(f))
            if not rounds or GUN_SKIP.search(f.stem):
                continue
            path = f"gameData/Weapons/{folder}/{f.stem}.blk" if folder else f"gameData/Weapons/{f.stem}.blk"
            out[wc.weapon_name(path)] = {"p": path, "c": "gun", "g": "", "t": "machine gun" if rounds == 500 else "cannon", "gun": rounds}
    build_sensors(wc.lang)
    build_objects(wc.lang)
    log(f"  {len(out)} weapons", progress)
    return out


def aircraft_caps(udata: dict, catalog: dict, slot_keys: set) -> list:
    """Guidance systems this aircraft can use: from its official weapons + its own designators."""
    caps = set()
    for k in slot_keys:
        g = (catalog.get(k) or {}).get("g")
        if g:
            caps.add(g)
        if (catalog.get(k) or {}).get("c") == "pods":
            caps.add("laser")
    if udata.get("laserDesignator"):
        caps.add("laser")
    se = udata.get("sensors")
    for s in aslist(se.get("sensor")) if isinstance(se, dict) else []:
        b = first_str((s or {}).get("blk")).lower() if isinstance(s, dict) else ""
        if "laserdesignator" in b or "laserbeamriding" in b:
            caps.add("laser")
            if "beamriding" in b:
                caps.add("saclos")
    return sorted(caps)


# --------------------------------------------------------------------------- research trees

TREE_TYPES = {"army": "ground", "aviation": "air", "helicopters": "heli", "boats": "boat", "ships": "ship"}
TREE_FLAGS = {"gift": "gift", "event": "event", "isClanVehicle": "clan", "showOnlyWhenBought": "removed",
              "hideFeature": "hidden", "marketplaceItemdefId": "market"}


def build_trees(lang: Lang, known: set, progress=None):
    """In-game research trees: {nation: {category: [column: [item]]}}.

    item = {"id", "r"(rank), "f"[flags]} or a folder {"g"(group id), "r", "u": [items]}.
    Columns keep the game's order, so premium / event lines sit on the right like in game.
    """
    log("Reading research trees...", progress)
    report(progress, 0.94)
    shop = load(DM / "char.vromfs.bin_u" / "config" / "shop.blkx") or {}

    def unit(uid, v):
        it = {"id": uid, "r": num(v.get("rank"))}
        flags = [f for k, f in TREE_FLAGS.items() if v.get(k)]
        if flags:
            it["f"] = flags
        return it

    trees = {}
    for ckey, types in shop.items():
        if not isinstance(types, dict):
            continue
        nation = ckey.replace("country_", "")
        for tkey, tv in types.items():
            cat = TREE_TYPES.get(tkey)
            if not cat or not isinstance(tv, dict):
                continue
            columns = []
            for rng in aslist(tv.get("range")):
                if not isinstance(rng, dict):
                    continue
                col = []
                for k, v in rng.items():
                    if not isinstance(v, dict):
                        continue
                    if "rank" in v:
                        if k in known:
                            col.append(unit(k, v))
                    else:  # folder of several vehicles
                        members = [unit(kk, vv) for kk, vv in v.items() if isinstance(vv, dict) and "rank" in vv and kk in known]
                        if members:
                            lang.put("units", k, f"shop/group/{k}", fallback=" / ".join(m["id"] for m in members))
                            col.append({"g": k, "r": min(m["r"] for m in members), "u": members})
                if col:
                    columns.append(col)
            if columns:
                trees.setdefault(nation, {})[cat] = columns
    return trees


# --------------------------------------------------------------------------- hangar scenarios

HANGARS = (("hangar", "regular"), ("hangar_winter", "winter"), ("hangar_halloween", "halloween"),
           ("hangar_lunar_ny", "lunar_ny"), ("hangar_14_years", "anniversary"))
HANGAR_PLACES = {"ground": ("tank", "tank_premium"), "air": ("aircraft", "aircraft_premium"),
                 "heli": ("aircraft_premium", "aircraft"), "boat": ("hydroplane", "ship"), "ship": ("ship", "hydroplane")}


def _hangar_mission(level: str, block: str, pos: list, title: str, rot: list | None = None, speed: float = 0.0) -> dict:
    """A bare mission on a level: the player alone at pos (rot: the 3 axis rows of a game tm), respawned there."""
    from .mission import UNIT_DEFAULTS
    import copy as _copy
    x, y, z = (float(c) for c in pos)
    wing = "t1_player01"
    props = _copy.deepcopy(UNIT_DEFAULTS[block])
    axes = rot or [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    unit = {"name": wing, "tm": [*axes, [x, y, z]], "unit_class": "",
            "objLayer": 1, "closed_waypoints": False, "isShipSpline": False, "shipTurnRadius": 100.0,
            "weapons": "", "bullets0": "", "bullets1": "", "bullets2": "", "bullets3": "",
            "bulletsCount0": 0, "bulletsCount1": 0, "bulletsCount2": 0, "bulletsCount3": 0,
            "crewSkillK": 0.0, "applyAllMods": True, "props": props, "way": {}}
    if block == "armada":
        props["speed"] = speed
    respawn = {
        "is_enabled": True, "comments": "respawn the player where they started",
        "props": {"actionsType": "PERFORM_ONE_BY_ONE", "conditionsType": "ALL", "enableAfterComplete": True},
        "events": {"periodicEvent": {"time": 1.0}},
        "conditions": {"playersWhenStatus": {"players": "isKilled", "check_players": "any"}},
        "actions": {"wait": {"time": 3.0}, "unitRespawn": {"delay": 1.0, "offset": [0.0, 0.0, 0.0], "object": wing, "target": "wtftd_spawn"}},
        "else_actions": {},
    }
    return {
        "selected_tag": "", "bin_dump_file": "",
        "mission_settings": {
            "player": {"army": 1, "wing": wing}, "player_teamB": {"army": 2},
            "mission": {"level": f"levels/{level}.bin", "type": "singleMission", "environment": "Day", "weather": "clear",
                        "locName": title, "restoreType": "attempts", "optionalTakeOff": False},
            "atmosphere": {"pressure": 760.0, "temperature": 15.0},
        },
        "imports": {}, "triggers": {"isCategory": True, "is_enabled": True, "wtftd_respawn": respawn},
        "mission_objectives": {"isCategory": True, "is_enabled": True},
        "variables": {}, "dialogs": {}, "airfields": {}, "effects": {},
        "units": {block: unit},
        "areas": {"wtftd_spawn": {"type": "Sphere", "tm": [[6.0, 0.0, 0.0], [0.0, 6.0, 0.0], [0.0, 0.0, 6.0], [x, y, z]],
                                  "objLayer": 0, "props": {}}},
        "objLayers": {}, "wayPoints": {},
    }


FREE_SKIP = ("hangar_", "menu", "tutorial")
FREE_AIR_ALT = 1500.0  # m above the map's highest official air unit is unknown: a safe start height


def _unit_rot(tm) -> list | None:
    """The heading part of a game tm, levelled (yaw only), or None."""
    try:
        fx, fz = float(tm[0][0]), float(tm[0][2])
    except (TypeError, ValueError, IndexError):
        return None
    n = math.hypot(fx, fz)
    if n < 1e-6:
        return None
    fx, fz = fx / n, fz / n
    return [[fx, 0.0, fz], [0.0, 1.0, 0.0], [-fz, 0.0, fx]]


def build_free_scenarios(out_dir: Path, lang: "Lang", taken: set, levels: dict, progress=None) -> list:
    """The game's other maps (no official test drive): one bare scenario per vehicle kind. Ground and naval
    starts come from where the game's own missions (battles, training…) put tanks / ships on that map
    (the player's side first); air starts above an air unit of those missions, else above the map centre."""
    log("Collecting the game's other maps...", progress)
    root = DM / "mis.vromfs.bin_u" / "gamedata" / "missions"
    spots: dict[str, dict] = {}  # level -> {"ground" | "naval" | "air": (score, pos, rot)}
    for f in root.rglob("*.blkx"):
        d = load(f)
        if not isinstance(d, dict):
            continue
        lvl = ((d.get("mission_settings") or {}).get("mission") or {}).get("level")
        if not isinstance(lvl, str) or not lvl:
            continue
        level = lvl.replace("\\", "/").rsplit("/", 1)[-1].replace(".bin", "").lower()
        if level.startswith(FREE_SKIP):
            continue
        best = spots.setdefault(level, {})
        ext = levels.get(level) or {}
        inside = (lambda p: ext["a0"][0] <= p[0] <= ext["a1"][0] and ext["a0"][1] <= p[2] <= ext["a1"][1]) if "a0" in ext else (lambda p: True)
        for block, key in (("tankModels", "ground"), ("ships", "naval"), ("armada", "air")):
            for u in aslist((d.get("units") or {}).get(block)):
                if not isinstance(u, dict):
                    continue
                pos = tm_pos(u.get("tm"))
                if not pos or not inside(pos):
                    continue  # some missions park units off the map
                if key == "air" and pos[1] < 300:
                    continue  # parked aircraft: not a flying start
                score = 2 if (u.get("props") or {}).get("army") == 1 else 1
                if score > best.get(key, (0,))[0]:
                    best[key] = (score, pos, _unit_rot(u.get("tm")))
    # maps with water (a ship somewhere in the game's missions): the editor drops template ships elsewhere
    with open(DATA / "water.json", "w", encoding="utf-8") as fo:
        json.dump(sorted(lv for lv, sp in spots.items() if sp.get("naval")), fo, separators=(",", ":"))
    blocks = {"ground": "tankModels", "heli": "armada", "air": "armada", "ship": "ships", "boat": "ships"}
    out = []
    for level in sorted({k for k in spots if k not in taken} | {k for k in levels if k not in taken and not k.startswith(FREE_SKIP)}):
        sp = spots.get(level, {})
        ext = levels.get(level) or {}
        air = sp.get("air")
        if not air and "a0" in ext:
            cx = (ext["a0"][0] + ext["a1"][0]) / 2
            cz = (ext["a0"][1] + ext["a1"][1]) / 2
            air = (0, [cx, FREE_AIR_ALT, cz], None)
        starts = {}
        if sp.get("ground"):
            starts["ground"] = (sp["ground"], "ground", 0.0)
            starts["heli"] = (sp["ground"], "ground", 0.0)
        if air:
            pos = [air[1][0], max(air[1][1], FREE_AIR_ALT), air[1][2]]
            starts["air"] = ((air[0], pos, air[2]), "air", 450.0)
        if sp.get("naval"):
            starts["ship"] = (sp["naval"], "ground", 0.0)
            starts["boat"] = (sp["naval"], "ground", 0.0)
        if not starts:
            continue
        lang.put("maps", level, f"location/{level}", f"missions/{level}", level,
                 fallback=humanize(re.sub(r"^(avg|avn|air|hvg|arcade)_", "", level)))
        for kind, ((_, pos, rot), start, speed) in starts.items():
            sid = f"free_{level}_{kind}"
            m = _hangar_mission(level, blocks[kind], pos, "WTFTD", rot, speed)
            with open(out_dir / f"{sid}.json", "w", encoding="utf-8") as fo:
                json.dump(m, fo, ensure_ascii=False, separators=(",", ":"))
            out.append({"id": sid, "map": level, "kind": kind, "nation": "", "tags": [], "start": start,
                        "block": blocks[kind], "wing": "t1_player01", "pos": [round(float(c), 1) for c in pos],
                        "units": 1, "type": "singleMission", "en": {}, "free": 1})
    log(f"  {len({s['map'] for s in out})} other maps", progress)
    return out


# ------------------------------------------------------------------ ground battle maps (Domination layouts)
# The game's Domination missions (gameData/missions/cta/tanks): each side's spawn and the capture zones, read from
# the mission and the templates it imports. WTFTD makes a bare mission of each layout and side - your start at that
# side's spawn facing the zones, the zones and the other side's spawn shown in the editor (no AI, score or capture).
_BATTLE_SKIP = re.compile(r"hardcore|realistic|(^|_)rb_?|_rb\d|air|heli|plane|fighter|bomber|artillery|ucav|naval|ship|boat|bttl|sim", re.I)
_BATTLE_TEAM = re.compile(r"(?:^|_)(?:t([12])|team([ab]))_", re.I)
BATTLE_AIR_ALT = 1000.0  # m above the side's spawn: an air start over it


def _battle_team(name: str) -> int | None:
    m = _BATTLE_TEAM.search(name)
    if not m:
        return None
    return 1 if m.group(1) == "1" or (m.group(2) or "").lower() == "a" else 2


def battle_layout(d: dict) -> dict | None:
    """{spawn: {1: pos, 2: pos}, zones: [(letter, area)], area: battle area or None} of a Domination mission:
    the briefing markers (what the game shows before a battle) first, else its spawn zones / points."""
    areas: dict = {}
    for doc in _import_chain(d):
        for n, a in (doc.get("areas") or {}).items():
            if isinstance(a, dict) and tm_pos(a.get("tm")):
                areas.setdefault(n, a)
    usable = {n: a for n, a in areas.items() if not _BATTLE_SKIP.search(n)}
    spawn = {}
    for team in (1, 2):
        for rule in (lambda n: n.lower().startswith("briefing_") and "spawn" in n.lower(),
                     lambda n: "spawn" in n.lower() and not re.search(r"_pt_\d|spawnpoint|_\d\d_\d\d$|clear", n, re.I),
                     lambda n: "spawn" in n.lower() and "clear" not in n.lower()):
            names = sorted((n for n in usable if rule(n) and _battle_team(n) == team), key=lambda n: (len(n), n))
            if names:
                spawn[team] = tm_pos(usable[names[0]]["tm"])
                break
    caps: dict = {}
    for n in sorted(usable, key=lambda n: (n.lower().startswith("briefing_"), n)):
        m = re.search(r"capture.*?(\d+)", n, re.I)
        if m and "capture" in n.lower() and 1 <= int(m.group(1)) <= 9:
            caps.setdefault(int(m.group(1)), usable[n])
    if len(spawn) < 2 or not caps:
        return None
    area = next((areas[n] for n in ("briefing_battlearea", "briefing_battlearea_arcade") if n in areas), None)
    return {"spawn": spawn, "zones": [("ABCDEFGHI"[i - 1], caps[i]) for i in sorted(caps)], "area": area}


def _facing(frm: list, to: list) -> list:
    """The heading rows of a game tm, from frm towards to (levelled)."""
    dx, dz = to[0] - frm[0], to[2] - frm[2]
    n = math.hypot(dx, dz) or 1.0
    fx, fz = dx / n, dz / n
    return [[fx, 0.0, fz], [0.0, 1.0, 0.0], [-fz, 0.0, fx]]


def build_battle_scenarios(out_dir: Path, lang: "Lang", progress=None) -> list:
    log("Collecting the ground battle maps (Domination)...", progress)
    root = DM / "mis.vromfs.bin_u" / "gamedata" / "missions" / "cta" / "tanks"
    blocks = {"ground": "tankModels", "heli": "armada", "air": "armada"}
    out = []
    for f in sorted(root.rglob("*_dom.blkx")):
        if "template" in f.as_posix().lower() or f.name.startswith(("aaa_", "ctf_")) or "_aslt_" in f.name:
            continue
        d = load(f)
        mission = ((d or {}).get("mission_settings") or {}).get("mission") or {}
        level = str(mission.get("level") or "").replace("\\", "/").rsplit("/", 1)[-1].replace(".bin", "").lower()
        lay = battle_layout(d) if level else None
        if not lay:
            continue
        layout = f.stem.lower()[:-4]  # poland_02_dom -> poland_02
        lang.put("maps", level, f"location/{level}", f"missions/{level}", level,
                 fallback=humanize(re.sub(r"^(avg|avn|air|hvg|arcade)_", "", level)))
        variant = re.search(r"_(\d\d)$", layout)
        night = layout.startswith("night_")
        centre = [sum(tm_pos(a["tm"])[i] for _, a in lay["zones"]) / len(lay["zones"]) for i in range(3)]
        for side, team in (("a", 1), ("b", 2)):
            pos, foe = lay["spawn"][team], lay["spawn"][3 - team]
            rot = _facing(pos, centre)
            for kind, block in blocks.items():
                start = [pos[0], pos[1] + BATTLE_AIR_ALT, pos[2]] if kind == "air" else pos
                sid = f"battle_{layout}_{side}_{kind}"
                m = _hangar_mission(level, block, start, "WTFTD", rot, 450.0 if kind == "air" else 0.0)
                if night:
                    m["mission_settings"]["mission"]["environment"] = "Night"
                areas = m["areas"]
                for letter, a in lay["zones"]:
                    areas[f"wtftd_capture_{letter}"] = {"type": str(a.get("type") or "Sphere"), "tm": a["tm"], "objLayer": 0, "props": {}}
                areas["wtftd_enemy_spawn"] = {"type": "Sphere", "tm": [[40.0, 0.0, 0.0], [0.0, 40.0, 0.0], [0.0, 0.0, 40.0], list(foe)],
                                              "objLayer": 0, "props": {}}
                if lay["area"]:
                    areas["wtftd_battle_area"] = {"type": str(lay["area"].get("type") or "Box"), "tm": lay["area"]["tm"], "objLayer": 0, "props": {}}
                with open(out_dir / f"{sid}.json", "w", encoding="utf-8") as fo:
                    json.dump(m, fo, ensure_ascii=False, separators=(",", ":"))
                out.append({"id": sid, "map": level, "kind": kind, "nation": "", "tags": ["battle"] + (["night"] if night else []),
                            "start": "air" if kind == "air" else "ground", "block": block, "wing": "t1_player01",
                            "pos": [round(float(c), 1) for c in start], "units": 1, "type": "singleMission", "en": {},
                            "free": 1, "battle": {"side": side, "layout": int(variant.group(1)) if variant else 1}})
    log(f"  {len(out) // 6} battle layouts on {len({s['map'] for s in out})} maps", progress)
    return out


def build_hangar_scenarios(out_dir: Path) -> list:
    """Scenarios on the hangar maps (menu background), using the vehicle spots from config/hangar*.blk."""
    blocks = {"ground": "tankModels", "air": "armada", "heli": "armada", "boat": "ships", "ship": "ships"}
    out = []
    for cfg_name, variant in HANGARS:
        cfg = load(DM / "aces.vromfs.bin_u" / "config" / f"{cfg_name}.blkx")
        if not isinstance(cfg, dict) or not cfg.get("level"):
            continue
        level = first_str(cfg["level"]).replace("\\", "/").rsplit("/", 1)[-1].replace(".bin", "")
        places = {}
        for up in aslist(cfg.get("unitPos")):
            if isinstance(up, dict) and up.get("hangarPlace") and isinstance(up.get("modelPos"), list):
                places[up["hangarPlace"]] = up["modelPos"]
        for kind, wanted in HANGAR_PLACES.items():
            pos = next((places[p] for p in wanted if p in places), None)
            if not pos:
                continue
            sid = f"hangar_{variant}_{kind}"
            m = _hangar_mission(level, blocks[kind], pos, f"WTFTD Hangar ({variant})")
            with open(out_dir / f"{sid}.json", "w", encoding="utf-8") as f:
                json.dump(m, f, ensure_ascii=False, separators=(",", ":"))
            out.append({"id": sid, "map": level, "kind": kind, "nation": "", "tags": ["hangar"], "start": "ground",
                        "block": blocks[kind], "wing": "t1_player01", "pos": [round(float(c), 1) for c in pos],
                        "units": 1, "type": "singleMission", "en": {}, "title": f"scenario.hangar.{variant}"})
    return out


# --------------------------------------------------------------------------- official test-drive scenarios

NATIONS = {"ussr": "ussr", "germ": "germany", "germany": "germany", "usa": "usa", "uk": "britain", "britain": "britain",
           "jp": "japan", "japan": "japan", "it": "italy", "italy": "italy", "china": "china", "fr": "france", "sw": "sweden"}
TAGS = ["jet", "navy", "hydroplane", "hydrobase", "heli", "ucav", "me", "in_air", "era", "destroyer", "universal"]


def scenario_kind(rel: str, level: str) -> str:
    n = rel.lower()
    if "/tank/" in n:
        return "ground"
    if "/ship/" in n:
        return "ship" if "destroyer" in n else "boat"
    if "ucav" in n:
        return "ucav"
    if "heli" in n:
        return "heli"
    return "air"


def _mission_path(game_path: str) -> Path:
    """'gameData/missions/x/y.blk' -> datamine .blkx path."""
    rel = game_path.replace("\\", "/").lower()
    if rel.startswith("gamedata/"):
        rel = rel[len("gamedata/"):]
    return DM / "mis.vromfs.bin_u" / "gamedata" / (rel[:-4] + ".blkx" if rel.endswith(".blk") else rel)


def _import_chain(d: dict, depth: int = 0, seen: set | None = None) -> list:
    """The mission and every game template it imports (recursively), mission first."""
    seen = seen if seen is not None else set()
    out = [d] if depth == 0 else []
    if depth > 4 or not isinstance(d, dict):
        return out
    for rec in aslist((d.get("imports") or {}).get("import_record") if isinstance(d.get("imports"), dict) else None):
        path = first_str(rec.get("file")) if isinstance(rec, dict) else ""
        if not path or path.lower() in seen:
            continue
        seen.add(path.lower())
        sub = load(_mission_path(path))
        if isinstance(sub, dict):
            out.append(sub)
            out += _import_chain(sub, depth + 1, seen)
    return out


def save_templates(d: dict, out_dir: Path, saved: set):
    """Writes every game template a mission imports (recursively) to out_dir, once each."""
    from .mission import template_key
    for rec in aslist((d.get("imports") or {}).get("import_record") if isinstance(d.get("imports"), dict) else None):
        path = first_str(rec.get("file")) if isinstance(rec, dict) else ""
        key = template_key(path) if path else ""
        if not key or key in saved:
            continue
        saved.add(key)
        sub = load(_mission_path(path))
        if isinstance(sub, dict):
            with open(out_dir / f"{key}.json", "w", encoding="utf-8") as fo:
                json.dump(sub, fo, ensure_ascii=False, separators=(",", ":"))
            save_templates(sub, out_dir, saved)


def _all_triggers(node):
    """(trigger, actions) of every trigger, inside categories too."""
    if not isinstance(node, dict):
        return
    for t in node.values():
        if not isinstance(t, dict):
            continue
        if isinstance(t.get("actions"), dict):
            yield t, t["actions"]
        elif t.get("isCategory"):
            yield from _all_triggers(t)


def template_placements(d: dict) -> dict:
    """Where the scenario puts template units, from the triggers of the whole import chain:
    {unit: {"area", "x", "y", "z"}} for a teleport / respawn to a known area, {unit: {"runtime": 1}} when the
    scripts choose at runtime (an area held by a variable set later, or asleep from the start)."""
    from .mission import _is_start_trigger
    chain = _import_chain(d)
    variables, areas, squads = {}, {}, {}
    for doc in reversed(chain):  # the mission's own values win
        if isinstance(doc.get("variables"), dict):
            variables.update(doc["variables"])
        if isinstance(doc.get("areas"), dict):
            areas.update(doc["areas"])
        for sq in aslist((doc.get("units") or {}).get("squad")):
            if isinstance(sq, dict) and sq.get("name"):
                squads[sq["name"]] = aslist((sq.get("props") or {}).get("squad_members"))

    def names(v, depth=0):
        """Unit names an action targets; None for a value only known at runtime."""
        for item in aslist(v):
            if not isinstance(item, str) or not item:
                continue
            if item.startswith("@"):
                item = variables.get(item[1:])
                if not isinstance(item, str) or not item:
                    yield None
                    continue
            if item in squads and depth < 3:
                yield from names(squads[item], depth + 1)
            else:
                yield item

    out = {}
    for doc in chain:
        for t, a in _all_triggers(doc.get("triggers")):
            start = _is_start_trigger(t)
            moves = [x for x in aslist(a.get("unitRespawn")) if isinstance(x, dict)]
            moves += [x for x in aslist(a.get("unitMoveTo")) if isinstance(x, dict) and x.get("move_type") == "teleport"]
            for mv in moves:
                target = next(iter(names(mv.get("target"))), None)
                area = areas.get(target) if target else None
                pos = tm_pos(area.get("tm")) if isinstance(area, dict) else None
                for name in names(mv.get("object")):
                    if not name:
                        continue
                    if pos and ("area" not in out.get(name, {}) or start):
                        out[name] = {"area": target, "x": round(pos[0], 1), "y": round(pos[1], 1), "z": round(pos[2], 1)}
                    elif not pos and name not in out:
                        out[name] = {"runtime": 1}
            if start:  # asleep from the start: only appears where a later trigger respawns it
                for sl in aslist(a.get("unitPutToSleep")):  # its units are in "target"
                    for name in names((sl.get("target") or sl.get("object")) if isinstance(sl, dict) else None):
                        if name and name not in out:
                            out[name] = {"runtime": 1}
    return out


def used_zones(d: dict) -> list:
    """The mission's areas its scripts (or the templates it imports) refer to: by name, or by a name prefix
    the scripts complete with a number (bdt_t2_bomb_zone_mid_ + 01)."""
    areas = d.get("areas") if isinstance(d.get("areas"), dict) else {}
    if not areas:
        return []
    text = "".join(json.dumps([doc.get("triggers"), doc.get("variables")]) for doc in _import_chain(d))
    words = set(re.findall(r'"([A-Za-z0-9_]{4,})"', text))
    # names the scripts build: a literal start ending in "_" (bdt_t2_bomb_zone_ + mid_01)
    stems = [w for w in words if w.endswith("_") and len(w) >= 8]
    return [name for name in areas if name in words or any(name.startswith(s) for s in stems)]


def zone_roles(d: dict) -> dict:
    """What the scenario's scripts (whole import chain) put in each of its zones:
    {"spawns": {area: [unit names]}, "player": [areas the player is respawned / teleported into],
     "playerOther": True when a script moves the player somewhere not known before the mission runs}.
    A variable target ("@air_spawn") counts for every zone its values name; a variable the scripts append
    to ("spawn_area0" + 1) for every zone starting with them."""
    chain = _import_chain(d)
    wing = first_str(((d.get("mission_settings") or {}).get("player") or {}).get("wing"))
    areas = d.get("areas") if isinstance(d.get("areas"), dict) else {}
    variables, squads, units = {}, {}, set()
    sets: dict = {}  # var -> [literal values / ("@", other var)]
    appended = set()
    for doc in reversed(chain):
        if isinstance(doc.get("variables"), dict):
            variables.update(doc["variables"])
        for block, entries in (doc.get("units") or {}).items():
            for u in aslist(entries):
                if not isinstance(u, dict) or not u.get("name"):
                    continue
                if block == "squad":
                    squads[u["name"]] = aslist((u.get("props") or {}).get("squad_members"))
                else:
                    units.add(u["name"])

    def walk(n):
        if isinstance(n, dict):
            for k, v in n.items():
                if k in ("varSetString", "varAddString"):
                    for a in aslist(v):
                        if not isinstance(a, dict) or not isinstance(a.get("var"), str):
                            continue
                        if k == "varAddString":
                            appended.add(a["var"])
                        elif a.get("input_var"):
                            sets.setdefault(a["var"], []).append(("@", str(a["input_var"]).lstrip("@")))
                        elif isinstance(a.get("value"), str):
                            sets.setdefault(a["var"], []).append(a["value"])
                walk(v)
        elif isinstance(n, list):
            for x in n:
                walk(x)
    for doc in chain:
        walk(doc.get("triggers"))

    def values(var, depth=0):
        out = [variables[var]] if isinstance(variables.get(var), str) else []
        for v in sets.get(var, []):
            if isinstance(v, tuple):
                out += values(v[1], depth + 1) if depth < 3 else []
            else:
                out.append(v)
        return [v for v in out if v]

    def matches(ref, pool):
        """Names of pool a target / object refers to; None when unknown before the mission runs."""
        found, unknown = set(), False
        for item in aslist(ref):
            if not isinstance(item, str) or not item:
                continue
            if not item.startswith("@"):
                found.add(item)
                continue
            var = item[1:]
            vals = values(var)
            for v in vals:
                if var in appended and len(v) >= 4:
                    found |= {n for n in pool if n.startswith(v)}
                elif v in pool:
                    found.add(v)
            unknown |= not vals
        out = set()
        for n in found:
            out |= set(squads[n]) | {n} if n in squads else {n}
        return out, unknown

    spawns: dict = {}
    player, other = set(), False
    pool_units = units | set(squads)
    for doc in chain:
        for t, a in _all_triggers(doc.get("triggers")):
            moves = [x for x in aslist(a.get("unitRespawn")) if isinstance(x, dict)]
            moves += [x for x in aslist(a.get("unitMoveTo")) if isinstance(x, dict) and x.get("move_type") == "teleport"]
            for mv in moves:
                targets, t_unknown = matches(mv.get("target"), areas)
                objs, _ = matches(mv.get("object"), pool_units)
                is_player = wing in objs or mv.get("object") == "@player"
                for z in targets:
                    if z in areas:
                        spawns.setdefault(z, set()).update(o for o in objs if o != wing and o not in squads)
                if is_player:
                    player |= {z for z in targets if z in areas}
                    other |= t_unknown or not any(z in areas for z in targets)
    out = {"spawns": {z: sorted(v) for z, v in spawns.items()}, "player": sorted(player)}
    if other:
        out["playerOther"] = True
    return out


def imported_units(d: dict, depth: int = 0, seen: set | None = None) -> list:
    """Units defined in the game templates a mission imports (read-only for the editor)."""
    seen = seen if seen is not None else set()
    out = []
    if depth > 4 or not isinstance(d, dict):
        return out
    for rec in aslist((d.get("imports") or {}).get("import_record") if isinstance(d.get("imports"), dict) else None):
        if not isinstance(rec, dict) or rec.get("importUnits") is False:
            continue
        path = first_str(rec.get("file"))
        if not path or path.lower() in seen:
            continue
        seen.add(path.lower())
        sub = load(_mission_path(path))
        if not isinstance(sub, dict):
            continue
        for block, entries in (sub.get("units") or {}).items():
            if block == "squad":
                continue
            for u in aslist(entries):
                if not isinstance(u, dict) or not isinstance(u.get("tm"), list):
                    continue
                try:
                    x, y, z = (float(c) for c in u["tm"][3])
                    yaw = math.degrees(math.atan2(float(u["tm"][0][2]), float(u["tm"][0][0])))
                except (TypeError, ValueError, IndexError):
                    continue
                props = u.get("props") or {}
                out.append({"name": u.get("name"), "block": block, "cls": first_str(u.get("unit_class")),
                            "x": round(x, 1), "y": round(y, 1), "z": round(z, 1), "yaw": round(yaw, 1),
                            "army": props.get("army", 0) if isinstance(props, dict) else 0,
                            "count": props.get("count", 1) if isinstance(props, dict) else 1,
                            "attack": props.get("attack_type", "") if isinstance(props, dict) else ""})
        out += imported_units(sub, depth + 1, seen)
    if depth == 0:  # where the scenario really puts them
        place = template_placements(d)
        for u in out:
            p = place.get(u["name"])
            if p:
                u.update(p)
    return out


def build_levels(progress=None) -> dict:
    """Tactical maps per level: world x/z extents (a0/a1 = full map, t0/t1 = ground battle map) and
    the game textures holding them (am / tm), used as the scenario editor background."""
    out = {}
    for f in (DM / "aces.vromfs.bin_u" / "levels").glob("*.blkx"):
        d = load(f)
        if not isinstance(d, dict):
            continue
        e = {}
        for key, name in (("mapCoord0", "a0"), ("mapCoord1", "a1"), ("tankMapCoord0", "t0"), ("tankMapCoord1", "t1")):
            v = d.get(key)
            if isinstance(v, list) and len(v) == 2 and all(isinstance(c, (int, float)) for c in v):
                e[name] = [float(v[0]), float(v[1])]
        level = f.stem.lower()
        if "a0" in e:
            e["am"] = (first_str(d.get("customLevelMap")) or f"{level}_map*").split("*")[0].lower()
        if "t0" in e:
            e["tm"] = (first_str(d.get("customLevelTankMap")) or f"{level}_tankmap*").split("*")[0].lower()
        if e:
            out[f.stem.lower()] = e
    return out


def build_scenarios(lang: Lang, progress=None):
    log("Collecting official test drive / test flight missions...", progress)
    report(progress, 0.87)
    root = DM / "mis.vromfs.bin_u" / "gamedata" / "missions"
    src = root / "training" / "testflight"
    out_dir = DATA / "scenarios"
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.json"):
        old.unlink()
    # the game templates the missions import, kept so a mission can carry them itself (mission.inline_imports)
    tpl_dir = DATA / "templates"
    tpl_dir.mkdir(parents=True, exist_ok=True)
    for old in tpl_dir.glob("*.json"):
        old.unlink()
    saved: set = set()
    scenarios = []
    for f in sorted(src.rglob("*.blkx")):
        rel = f.relative_to(root).as_posix()
        if "template" in f.stem or "/human/" in rel or "sound_areas" in f.stem:
            continue
        d = load(f)
        if not isinstance(d, dict):
            continue
        ms = d.get("mission_settings") or {}
        mission = ms.get("mission") or {}
        wing = (ms.get("player") or {}).get("wing")
        level = (mission.get("level") or "").replace("\\", "/").rsplit("/", 1)[-1].replace(".bin", "")
        if not level or not isinstance(wing, str):
            continue
        player = None
        for block, units in (d.get("units") or {}).items():
            for u in aslist(units):
                if isinstance(u, dict) and u.get("name") == wing:
                    player = (block, u)
        if not player:
            continue
        block, u = player
        pos = tm_pos(u.get("tm"))
        kind = scenario_kind("/" + rel, level)
        stem = f.stem.lower()
        tokens = stem.replace("testflight_", "").replace("test_flight_", "").replace("_tft", "").replace("_tfs", "").split("_")
        nation = next((NATIONS[t] for t in tokens if t in NATIONS), "")
        tags = [t for t in TAGS if t in stem.split("_") or (t == "in_air" and "in_air" in stem)]
        if kind in ("air", "ucav", "heli"):
            speed = (u.get("props") or {}).get("speed")
            start = "air" if (pos and pos[1] > 600 and speed != 0.0) or "in_air" in stem else "ground"
        else:
            start = "ground"
        sid = stem
        lang.put("maps", level, f"location/{level}", f"missions/{level}", level,
                 fallback=humanize(re.sub(r"^(avg|avn|air|hvg|arcade)_", "", level)))
        with open(out_dir / f"{sid}.json", "w", encoding="utf-8") as fo:
            json.dump(d, fo, ensure_ascii=False, separators=(",", ":"))
        save_templates(d, tpl_dir, saved)
        tpl = imported_units(d)
        if tpl:
            with open(out_dir / f"{sid}.units.json", "w", encoding="utf-8") as fo:
                json.dump(tpl, fo, ensure_ascii=False, separators=(",", ":"))
        zones = used_zones(d)
        if zones or d.get("imports"):  # zones the scripts use, what they put there, where they respawn you
            with open(out_dir / f"{sid}.zones.json", "w", encoding="utf-8") as fo:
                json.dump({"used": zones, **zone_roles(d)}, fo, separators=(",", ":"))
        scenarios.append({
            "id": sid,
            "map": level,
            "kind": kind,
            "nation": nation,
            "tags": tags,
            "start": start,
            "block": block,
            "wing": wing,
            "pos": [round(c, 1) for c in pos] if pos else None,
            "units": sum(len(aslist(v)) for v in (d.get("units") or {}).values()),
            # enemy units defined in the mission itself (those in game templates can't be swapped)
            "en": {blk: n for blk in ("tankModels", "armada", "ships")
                   if (n := sum(1 for x in aslist((d.get("units") or {}).get(blk))
                                if isinstance(x, dict) and (x.get("props") or {}).get("army") == 2))},
            "type": mission.get("type", ""),
        })
    scenarios += build_hangar_scenarios(out_dir)
    log(f"  {len(scenarios)} scenarios", progress)
    scenarios += build_battle_scenarios(out_dir, lang, progress)  # maps with a battle layout get no bare start too
    scenarios += build_free_scenarios(out_dir, lang, {s["map"] for s in scenarios}, build_levels(), progress)
    return scenarios


def tm_pos(tm):
    try:
        return [float(c) for c in tm[3]]
    except (TypeError, IndexError, ValueError):
        return None


# --------------------------------------------------------------------------- stock vs fully upgraded
# Vehicle files describe the fully upgraded vehicle: performance modules carry invertEnableLogic, i.e.
# their effects (power x0.9, traverse x0.85, mass x1.025...) apply while the module is NOT researched.
# Stock values = upgraded values with all those penalties. Exact for engine power / traverse; aircraft
# speed, climb and turn are estimated with simple physics (the game runs a flight model for those).

_GLOBAL_MODS: dict | None = None


def _global_mods() -> dict:
    global _GLOBAL_MODS
    if _GLOBAL_MODS is None:
        d = load(DM / "char.vromfs.bin_u" / "config" / "modifications.blkx") or {}
        _GLOBAL_MODS = d.get("modifications") if isinstance(d.get("modifications"), dict) else {}
    return _GLOBAL_MODS


def stock_factors(udata: dict, mod_names) -> dict:
    """Product of the penalty multipliers a stock vehicle carries (all 1.0 when nothing applies)."""
    f = {"P": 1.0, "M": 1.0, "D": 1.0, "Y": 1.0, "T": 1.0}
    local = udata.get("modifications") if isinstance(udata.get("modifications"), dict) else {}
    for name in mod_names:
        g = _global_mods().get(name)
        lo = local.get(name)
        g = g if isinstance(g, dict) else {}
        lo = lo if isinstance(lo, dict) else {}
        if not (lo.get("invertEnableLogic", g.get("invertEnableLogic"))):
            continue
        eff = lo.get("effects") if isinstance(lo.get("effects"), dict) else g.get("effects")
        if not isinstance(eff, dict):
            continue

        def mul(key):
            x = _numval(eff.get(key))
            return x if x and 0.2 < x < 5 else 1.0

        f["P"] *= mul("mulHorsePowers") * mul("thrustMult")
        f["M"] *= mul("mulMass")
        f["D"] *= mul("mulCdmin")
        f["Y"] *= mul("mulSpeedYaw")
        f["T"] *= mul("mulTransmissionEfficiency")
    return f


def stock_stats(cat: str, s: dict, f: dict) -> dict:
    """Stock value of each stat that modules change (only those that differ)."""
    out = {}
    P, M, D, Y = f["P"], f["M"], f["D"], f["Y"]

    def put(k, val, digits=1):
        if k in s and isinstance(s[k], (int, float)) and val is not None:
            v = round(val, digits) if digits else round(val)
            if abs(v - s[k]) > (10 ** -digits if digits else 0.5):
                out[k] = v

    if cat == "ground":
        put("hp", s.get("hp", 0) * P, 0)
        put("pw", s.get("pw", 0) * P / M)
        put("trav", s.get("trav", 0) * Y)
    elif cat in ("air", "heli"):
        jet = "tw" in s
        put("spd", s.get("spd", 0) * ((P / D) ** (0.5 if jet else 1 / 3)), 0)
        put("climb", s.get("climb", 0) * P / M)
        put("turn", s.get("turn", 0) * (M ** 0.5))
        put("tw", s.get("tw", 0) * P / M, 2)
        put("pw", s.get("pw", 0) * P / M)
        put("wl", s.get("wl", 0) * M, 0)
    return out


RARITY = {"tree": 0, "premium": 1, "squadron": 2, "pack": 3, "event": 4, "removed": 5, "hidden": 6}


def apply_rarity(vehicles: list, trees: dict):
    """ra = 0 tech tree, 1 premium (Golden Eagles), 2 squadron, 3 pack / gift, 4 event / marketplace,
    5 removed / no longer obtainable, 6 not playable (AI, unreleased)."""
    flags: dict = {}
    for nation in trees.values():
        for cols in nation.values():
            for col in cols:
                for it in col:
                    for u in (it.get("u") or [it]):
                        flags.setdefault(u["id"], set()).update(u.get("f") or [])
    for v in vehicles:
        fl = flags.get(v["id"], set())
        if v.get("h"):
            ra = 6
        elif "removed" in fl or "hidden" in fl:
            ra = 5
        elif "event" in fl or "market" in fl:
            ra = 4
        elif "gift" in fl and not v.get("p"):
            ra = 3
        elif "clan" in fl:
            ra = 2
        elif v.get("p") or "gift" in fl:
            ra = 1
        elif v["id"] not in flags:
            ra = 5  # not in any research tree: no longer obtainable
        else:
            ra = 0
        if ra:
            v["ra"] = ra


# --------------------------------------------------------------------------- main

def build(pull: bool = True, progress=None, source: str = "datamine", game_dir: Path | None = None):
    """source: "datamine", or "game" to read the install in game_dir. After a failure, the app keeps reading the
    files of the data it has."""
    global DM
    before, DM = DM, GAMEFILES if source == "game" else DATAMINE
    from .game import circuit
    try:
        if pull:
            fetch_gamefiles(game_dir, progress) if source == "game" else fetch_datamine(progress)
        meta = _build(progress, source, circuit=circuit(game_dir) if source == "game" else None)
    except BaseException:
        DM = before
        raise
    if source == "datamine" and (load(DEV / "data" / "meta.json") or {}).get("source") != "game":
        shutil.rmtree(GAMEFILES, ignore_errors=True)  # made again from the game in a minute or two; kept for the game's other database
    return meta


def _build(progress, source: str, history: bool = True, circuit: str | None = None):
    t0 = time.time()
    if not DM.exists():
        raise RuntimeError("Datamine not found. Run without --no-pull first.")
    DATA.mkdir(exist_ok=True)
    version = (DM / "version").read_text().strip() if (DM / "version").exists() else "?"
    before = patches.snapshot(DATA, version) if history else None  # now: the first files are replaced long before "Writing database"
    log("Loading game localization...", progress)
    report(progress, 0.46)
    lang = Lang()
    vehicles, details = build_vehicles(lang, progress)
    scenarios = build_scenarios(lang, progress)
    trees = build_trees(lang, {v["id"] for v in vehicles}, progress)
    apply_rarity(vehicles, trees)
    from .armament import build_armament
    build_armament(lang, vehicles, progress)
    log("Writing database...", progress)
    report(progress, 0.97)
    with open(DATA / "vehicles.json", "w", encoding="utf-8") as f:
        json.dump(vehicles, f, separators=(",", ":"))
    with open(DATA / "details.json", "w", encoding="utf-8") as f:
        json.dump(details, f, separators=(",", ":"))
    with open(DATA / "levels.json", "w", encoding="utf-8") as f:
        json.dump(build_levels(progress), f, separators=(",", ":"))
    with open(DATA / "trees.json", "w", encoding="utf-8") as f:
        json.dump(trees, f, separators=(",", ":"))
    with open(DATA / "scenarios.json", "w", encoding="utf-8") as f:
        json.dump(scenarios, f, separators=(",", ":"))
    with open(DATA / "bullet_icons.json", "w", encoding="utf-8") as f:
        json.dump(build_bullet_icons(), f, separators=(",", ":"))
    with open(DATA / "battle_words.json", "w", encoding="utf-8") as f:
        json.dump(build_battle_words(), f, ensure_ascii=False, separators=(",", ":"))
    with open(DATA / "bases.json", "w", encoding="utf-8") as f:
        json.dump(build_bases(), f, separators=(",", ":"))
    codes = lang.write()
    meta = {"version": version, "schema": SCHEMA, "source": source, "built": int(time.time()), "vehicles": len(vehicles), "scenarios": len(scenarios), "langs": codes}
    if circuit:  # the installed game's servers: "dev" for a dev server client
        meta["circuit"] = circuit
    with open(DATA / "meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1)
    try:
        entry = patches.record(before, DATA)
    except Exception as e:  # an old database of any shape: the new one stands, without its comparison
        log(f"No comparison with the previous version: {e}", progress)
        entry = None
    if entry and not entry.get("back"):
        meta.update(patch=entry["id"], changes=len(entry["rows"]))
    report(progress, 1.0)
    log(f"Done: {len(vehicles)} vehicles, {len(scenarios)} scenarios, game v{version} ({time.time() - t0:.0f}s)", progress)
    return meta


if __name__ == "__main__":
    from .game import detect_game_dir
    use_game = "--game" in sys.argv
    from . import builder  # not this copy: python -m runs the file as __main__, and the build's other modules read the real module's DM
    builder.build(pull="--no-pull" not in sys.argv, source="game" if use_game else "datamine",
                  game_dir=detect_game_dir() if use_game else None)
