"""In-flight speed alarms and their overlay (Windows only).

The game's /indicators can answer {"valid": false} even in flight (seen on 2.59, until the game was restarted), so
speeds come from /state. The aircraft comes from what WTFTD generated, else from /indicators' "type", else as a
fallback from its fuel capacity and engines plus the model the game saved in global.blk (read only, and only that key).
Its speed is then compared to the breaking limits of its flight model (st["lim"] in data/details.json, see
builder.flight_limits): in doubt there is no alarm, never a guess.

What is shown and heard is the player's (My overlay tab, settings.json "overlay", see clean): the window's look, each
line's text ("IAS {ias} / {vne} km/h", see FIELDS) and when it shows, the alarms' thresholds and sounds, for all aircraft
or per aircraft or type (settings.json "overlayProfiles", see Watch.pick). The same values go to the Flight data tab's
curves and, on demand, to a CSV log (flightlog.py).

The overlay is a separate click-through window above the game: nothing is injected, nothing touches the game.
"""
from __future__ import annotations

import base64
import contextlib
import gc
import io
import json
import math
import operator
import queue
import re
import sys
import threading
import time
import wave
from array import array
from collections import deque
from functools import lru_cache
from pathlib import Path
from statistics import linear_regression

from . import battle, flightlog, hud, mappaint, minimap, sights, waveout
from .paths import WEB

# the aircraft's limits a line's alarm can follow, % of the limit: default threshold, beep in Hz
ALARMS = {"airframe": (93, 1400), "gear": (90, 1000), "flaps": (90, 700), "load": (90, 1200), "aoa": (90, 500)}
WING_SHARE = 2  # CritOverload is one wing's: a Su-30MKK pulled 11 G whole (2026-10-31) where one wing's would break at 6.6
PARTS = ("name", "value", "unit")  # what of a line can flash with its alarm
FEEDS = ("chat", "log")  # what a text block can show instead of lines: the game's chat, its battle log
FEED_S = 1.0  # read that often
FEED_ROWS = 6
JOY = 256  # keys from this code on are joystick buttons: JOY + 32 x joystick + button
POLL_S = 0.1
HUD_POLL_S = 0.025  # with the HUD: the game sends a new reading about every 22 ms
HUD_FRAME_MS = 16  # and the window draws it between readings, at about 60 images a second
MAP_S = 0.1  # the minimap reads the map's objects 10 times a second, and glides between readings
MAP_FRAME_MS = 33  # and the window draws it about 30 times a second
PICTURE_S = 2.0  # a map's picture not had yet (the game not ready, a battle joined with the app opening): asked again
TRAIL_MAX = 600  # its trail's last places
IDLE_S = 1.0  # not flying: nothing to read fast
TRY_S = 60  # My overlay's Try, left alone this long, stops: the page that started it may be gone
RING_S = 0.5  # what rings, not told again for this long (two readings at least), stops: muted, landed, the app gone
HANGAR_IAS = 1  # km/h: the aircraft on show in the hangar reads 0 or 1
REPEAT_MS = 300  # an alarm whose beeps don't close in, without a repeat of its own
FLASH_MS = 500  # an alarm flashing "with its beeps" that doesn't beep (only red, or muted): this cycle
BEEP_MS = 150
GAP_MS = 700  # a dynamic alarm: the silence between its beeps at its threshold, none left at its break
MAX_RULES = 6  # a line's alarms: an old line's 4 own ones and the aircraft's it followed fit
SAMPLE_S = 1.0  # curves and logs: a reading a second
BENCH_S = 0.2  # a test bench run: a 360° timed on a heading that moves between two readings
TRACE_MAX = 3600  # an hour of curves
VIEW_S = 5  # the Flight data tab asks every second: without it for this long, nobody is looking
BURN_S, BURN_MIN_S, BURN_KG = 30, 5, 10  # fuel burn: the slope over the last 10 kg, 5 to 30 s of them (the game gives whole kg)
ACCEL_S = 2
TURN_G = 1.05  # below, a turn of several minutes is only level flight's noise
RUNNING_RPM = 500  # an engine really running, not one winding down
LOG_EVERY = 3  # readings between two looks at the battle log
BREAK_UP_S = 5  # a break-up in the air: silent this long, the next spawn comes within it
G = 9.80665
SAVED_MODEL = re.compile(r'selectedAir\s*\{\s*current_model:t="([^"]+)"')

# what an overlay line can show: {name} -> field of /state or /indicators, decimals; "{mach:3}" sets the decimals.
# Any other field the game sends works under its own name: "{RPM 2}", "{bank}"
FIELDS = {"ias": ("IAS, km/h", 0), "tas": ("TAS, km/h", 0), "mach": ("M", 2), "alt": ("H, m", 0), "vy": ("Vy, m/s", 1),
          "aoa": ("AoA, deg", 1), "aos": ("AoS, deg", 1), "g": ("Ny", 1), "g_max": ("g_meter_max", 1),
          "roll": ("Wx, deg/s", 0), "heading": ("compass", 0), "pitch": ("nose_up", 1),
          "bank": ("aviahorizon_roll", 1), "fuel": ("Mfuel, kg", 0), "fuel_max": ("Mfuel0, kg", 0),
          "throttle": ("throttle 1, %", 0), "rpm": ("RPM 1", 0), "thrust": ("thrust 1, kgs", 0),
          "power": ("power 1, hp", 0), "oil": ("oil temp 1, C", 0), "gear": ("gear, %", 0), "flaps": ("flaps, %", 0),
          "airbrake": ("airbrake, %", 0), "speed": ("speed", 0)}
COMPUTED = {"vne": 0, "mne": 2, "gear_max": 0, "flaps_max": 0, "margin": 0, "airframe_pct": 0, "gear_pct": 0,
            "flaps_pct": 0, "fuel_pct": 0, "hspeed": 0, "turn": 1, "turn_rate": 1, "turn_radius": 0, "accel": 1, "sep": 1,
            "burn": 0, "range": 0, "mass": 0, "thrust_total": 0, "twr": 2, "g_lim": 1, "g_neg": 1, "load_pct": 0,
            "aoa_crit": 1, "aoa_low": 1, "aoa_pct": 0, "wep_s": 0}  # see computed(): name -> decimals
SERIES = [*FIELDS, *COMPUTED]  # the numbers curves and logs follow
# their columns in a log, when the game's field name isn't one
COLUMNS = {"speed": "Speed, km/h", "heading": "Heading, deg", "g_max": "Max G", "pitch": "Pitch, deg", "bank": "Bank, deg", "vne": "Max speed, km/h",
           "mne": "Max Mach", "gear_max": "Gear max speed, km/h", "flaps_max": "Flaps max speed, km/h",
           "margin": "Speed left, km/h", "airframe_pct": "Airframe limit, %", "gear_pct": "Gear limit, %",
           "flaps_pct": "Flaps limit, %", "fuel_pct": "Fuel, %", "hspeed": "Horizontal speed, km/h", "turn": "Turn, s",
           "turn_rate": "Turn rate, deg/s", "turn_radius": "Turn radius, m", "accel": "Acceleration, m/s2", "sep": "SEP, m/s",
           "burn": "Fuel consumption, kg/min", "range": "Range, km", "mass": "Mass without weapons, kg",
           "thrust_total": "Thrust, kgf", "twr": "Thrust/weight", "g_lim": "G limit", "g_neg": "Negative G limit", "load_pct": "G load, % of limit",
           "aoa_crit": "Critical AoA, deg", "aoa_low": "Critical negative AoA, deg", "aoa_pct": "AoA limit, %", "wep_s": "WEP left, s"}
POSITION = ["East, m", "North, m", "Map heading, deg"]  # only in the logs, for the Tacview export
FIELD = re.compile(r"\{([^{}:]+)(?::(\d))?\}")
NO_VALUE = "N/A"  # what the game doesn't send, what the aircraft doesn't have

# shown if on; alarm: any line's alarm, own: one of its own alarms
WHEN = {"always": None, "alarm": None, "own": None, "gear": "gear, %", "flaps": "flaps, %", "airbrake": "airbrake, %", "log": "rec"}
MAX_LINES = 30
MAX_TEXT = 120
MAX_BLOCKS = 3  # text blocks besides the main one
MAX_TESTS = 4  # conditions on a line's showing or its alert
STIPPLE = {100: "", 75: "gray75", 50: "gray50", 25: "gray25"}  # a block's background opacities, % (the names: Tk's, before GDI+)
OPS = {">": operator.gt, "<": operator.lt}
SOUND = re.compile(r"[\w.\- ]{1,80}\.wav", re.I)  # the player's sounds, in user/sounds
SOUND_RATE = 22050
STALE_S = 0.5  # a sound that waited longer than this, through a long one, is no longer news
OUTPUT = {"device": ""}  # the sound output picked in My overlay, "" = Windows' default
FADE_MS = 2  # a beep's edges: no click
PROFILE = re.compile(r"(type:)?[\w.\-]{1,120}")  # the overlay of an aircraft (its id) or a type (type:fighter)
COLOR = re.compile(r"#[0-9a-fA-F]{6}")
FONT = re.compile(r"[\w .+-]{1,64}")

# fills the preview when the game isn't flying: every line shows, with an alarm on
SAMPLE_LIM = {"v": 1540, "m": 2.1, "gear": 700, "flaps": [[0.2, 1018], [1, 600]], "fuel": [9400], "eng": 2, "mass": 17520,
              "load": [-550000, 1450000], "aoa": [[-20, 28], [-22, 29]]}
SAMPLE_STATE = {"IAS, km/h": 640, "TAS, km/h": 790, "M": 0.75, "H, m": 3200, "Vy, m/s": 12.5, "AoA, deg": 4.2,
                "AoS, deg": 0.1, "Ny": 3.1, "Wx, deg/s": 20, "Mfuel, kg": 6200, "Mfuel0, kg": 9400, "throttle 1, %": 100,
                "RPM 1": 13300, "thrust 1, kgs": 12500, "power 1, hp": 0, "oil temp 1, C": 79, "gear, %": 100,
                "flaps, %": 33, "airbrake, %": 20}
SAMPLE_VEHICLE = "su_30mkk"
SAMPLE_ATTITUDE = {"compass": 322, "nose_up": 6.0, "aviahorizon_roll": -12.0}
SAMPLE_STATS = {"battles": 78, "kills": 159, "deaths": 91, "kd": 1.75, "winrate": 89, "live_kills": 2, "live_deaths": 1, "live_kd": 2}

GAME_WINDOW_CLASS = "DagorWClass"
OVERLAY_KEY = "#010101"  # the colour made see-through
GLOW_SIZE = 18  # how far the glow reaches into the screen, % of its height
GLOW_ALPHA = 180  # its opacity at the very edge, out of 255
GLOW_STEP = 4  # worked out one pixel in 4: a 4K screen has 8 million, too many for Python, and a soft fade doesn't show it


def available() -> bool:
    return sys.platform == "win32"


def column(name: str) -> str:
    return COLUMNS.get(name) or FIELDS[name][0]


def units() -> dict:
    return {name: column(name).rpartition(", ")[2] if ", " in column(name) else "" for name in SERIES}


def screen() -> tuple:
    """Screen size in real pixels, whatever this process' DPI awareness (not Windows: a 4K screen, only for sizes)."""
    try:
        import ctypes
        dc = ctypes.windll.user32.GetDC(0)
        size = ctypes.windll.gdi32.GetDeviceCaps(dc, 118), ctypes.windll.gdi32.GetDeviceCaps(dc, 117)  # DESKTOPHORZRES, VERTRES
        ctypes.windll.user32.ReleaseDC(0, dc)
        return size
    except (AttributeError, OSError):
        return 3840, 2160


def labels(lang: str) -> dict:
    """The overlay's words (keys overlay.*) from the UI translations, English when missing."""
    out = {}
    for code in ("en", lang):
        try:
            words = json.loads((WEB / "locales" / f"{code}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        out.update({k.split(".", 1)[1]: v for k, v in words.items() if k.startswith("overlay.")})
    return out


# the fighter HUD (hud.py): off until the player turns it on (auto: jets and helicopters), in its family's style
HUD_CHOICES = {"hudMode": ("off", "auto", "on"), "hudStyle": ("auto", *hud.STYLES), "hudUnits": ("auto", "metric", "imperial"),
               "hudLang": ("auto", *hud.LANGS)}
HUD_DEFAULTS = {**{k: v[0] for k, v in HUD_CHOICES.items()}, "hudColor": "#43FF7A", "hudKey": [], "hudKeyName": "",
                "hudCockpitX": 0, "hudCockpitY": 0, "hudCockpitScale": 60, "hudOutsideX": 0, "hudOutsideY": 0, "hudOutsideScale": 100,
                **{f"hud{p.title()}": True for p in hud.PARTS}}


def _map(cfg: dict, base: dict) -> dict:
    zoom = cfg.get("mapZoom")
    zoom = int(zoom) if isinstance(zoom, str) and zoom.isdecimal() else zoom  # a select sends text
    return {"mapMode": cfg.get("mapMode") if cfg.get("mapMode") in ("off", "on") else base["mapMode"],
            "mapZoom": zoom if type(zoom) is int and zoom in minimap.ZOOMS else base["mapZoom"],
            "mapSize": _num(cfg.get("mapSize"), base["mapSize"], 80, 3000), "mapX": _num(cfg.get("mapX"), base["mapX"], -20000, 20000),
            "mapY": _num(cfg.get("mapY"), base["mapY"], -20000, 20000), "mapTrail": _flag(cfg.get("mapTrail"), base["mapTrail"]),
            "mapOpacity": _num(cfg.get("mapOpacity"), base["mapOpacity"], 10, 100),
            "mapShape": cfg.get("mapShape") if cfg.get("mapShape") in ("square", "round") else base["mapShape"],
            "mapUp": cfg.get("mapUp") if cfg.get("mapUp") in ("north", "heading") else base["mapUp"],
            "mapAllies": _flag(cfg.get("mapAllies"), base["mapAllies"]), "mapAlliesGround": _flag(cfg.get("mapAlliesGround"), base["mapAlliesGround"]),
            "mapDim": _num(cfg.get("mapDim"), base["mapDim"], 0, 80),
            **{f"mapMark{k}": _num(cfg.get(f"mapMark{k}"), base[f"mapMark{k}"], 50, 400) for k in minimap.MARKS}}


def _hud(cfg: dict) -> dict:
    out = {k: cfg.get(k) if cfg.get(k) in choices else choices[0] for k, choices in HUD_CHOICES.items()}
    out["hudColor"] = _color(cfg.get("hudColor"), HUD_DEFAULTS["hudColor"])
    for place in ("Cockpit", "Outside"):
        for n, lo, hi in (("X", -20000, 20000), ("Y", -20000, 20000), ("Scale", 20, 300)):
            out[f"hud{place}{n}"] = _num(cfg.get(f"hud{place}{n}"), HUD_DEFAULTS[f"hud{place}{n}"], lo, hi)
    return {**out, **{f"hud{p.title()}": _flag(cfg.get(f"hud{p.title()}"), True) for p in hud.PARTS}, **_keys(cfg, "hudKey", "hudKeyName")}


def defaults(words: dict) -> dict:
    """The overlay until the player changes it: lined up with the game's HUD (x, y, size: 4K screen at 150 %)."""
    scale = screen()[1] / 2160
    lines = [_line({"text": limit_text(name, words), "when": when, "rules": [limit_alarm(name)]})
             for name, when in (("airframe", "always"), ("mach", "always"), ("gear", "gear"), ("flaps", "flaps"), ("load", "own"), ("aoa", "own"))]

    return {"x": round(700 * scale), "y": round(55 * scale), "font": "Consolas", "size": round(40 * scale), "bold": False,
            "italic": False, "spacing": 0, "outline": 0, "outlineColor": "#000000", "blocks": [], "valueColor": "", "unitColor": "",
            "pctAlways": False, **_look({}),
            "volume": 100, "soundFocus": False, "soundEngine": False,
            "pollMs": round(POLL_S * 1000), "logMs": round(SAMPLE_S * 1000), "muteKey": [], "muteKeyName": "", "holdKey": [], "holdKeyName": "",
            "color": "#E6E6E6", "alert": "#FF0000", "opacity": 100, "show": True, "hotkey": [], "hotkeyName": "",
            **HUD_DEFAULTS, "mapMode": "off", "mapZoom": 1, "mapTrail": True, "mapOpacity": 85, "mapShape": "square", "mapUp": "north", "mapAllies": False, "mapAlliesGround": False, "mapDim": 30,
            **{f"mapMark{k}": 100 for k in minimap.MARKS},  # the minimap: off until the player turns it on
            "mapSize": round(560 * scale), "mapX": round(40 * scale), "mapY": round(1100 * scale),
            "logKey": [], "logKeyName": "", "hideCrash": False, "hideUnknown": False,
            "sheetKey": [], "sheetKeyName": "", "profileKey": [], "profileKeyName": "",
            "lines": [*lines, _line({"text": "REC", "when": "log", "color": "#FF0000"})]}


def limit_text(name: str, words: dict) -> str:
    """A default line for one of the aircraft's limits ("mach": the airframe's, by its Mach number)."""
    label, text = {"airframe": ("IAS", "{ias} / {vne} km/h {swept}"), "mach": ("MACH", "{mach} / {mne}"),
                   "gear": (words["gear"], "{ias} / {gear_max} km/h"), "flaps": (words["flaps"], "{ias} / {flaps_max} km/h"),
                   "load": ("G", "{g} / {g_lim}"), "aoa": ("AOA", "{aoa} / {aoa_crit}°")}[name]
    width = max(len(w) for w in ("MACH", words["gear"], words["flaps"])) + 2  # the values line up
    return f"{label:<{width}}{text}"


def limit_alarm(name: str, red=None) -> dict:
    """A line's alarm on one of the aircraft's limits (mach: the airframe's), its defaults: beeps closing in up to 100 %."""
    name = "airframe" if name == "mach" else name
    return {"limit": name, "at": ALARMS[name][0], "red": red, "full": 100, "hz": ALARMS[name][1]}


def _glow_moved(cfg: dict) -> list:
    """The overlay's glow (on, size, flashing) given to every alarm of its lines; its colour follows each alarm's now."""
    glow = {"glow": cfg["glow"] is True, "glowSize": cfg.get("glowSize"), "glowFlash": cfg.get("glowFlash") is True}
    out = []
    for line in cfg["lines"]:
        if isinstance(line, dict):
            rules = line.get("rules") if isinstance(line.get("rules"), list) else [line.get("rule")]
            line = {**line, "rules": [{**glow, **r} if isinstance(r, dict) else r for r in rules]}
        out.append(line)
    return out


def _repeat_moved(cfg: dict) -> list:
    """The overlay's repeat, when it wasn't the default, given to the alarms without one of their own."""
    every = _num(cfg["repeat"], REPEAT_MS, 100, 10000)
    out = []
    for line in cfg["lines"]:
        if isinstance(line, dict) and every != REPEAT_MS:
            rules = line.get("rules") if isinstance(line.get("rules"), list) else [line.get("rule")]
            line = {**line, "rules": [{**r, "repeat": r.get("repeat") or every} if isinstance(r, dict) else r for r in rules]}
        out.append(line)
    return out


def _flash_moved(cfg: dict) -> list:
    """The overlay's flash cycle, when it wasn't the default, given to the alarms without one (the default now: with
    their beeps)."""
    every = _num(cfg["flashMs"], FLASH_MS, 200, 4000)
    out = []
    for line in cfg["lines"]:
        if isinstance(line, dict) and every != FLASH_MS:
            rules = line.get("rules") if isinstance(line.get("rules"), list) else [line.get("rule")]
            line = {**line, "rules": [{**r, "flashMs": r.get("flashMs") or every} if isinstance(r, dict) else r for r in rules]}
        out.append(line)
    return out


def _migrated(cfg: dict, words: dict) -> list:
    """Lines saved before 0.27, when the aircraft's alarms had a tab of their own and a line went red "with" one of them:
    each such line gets that alarm, as it was set; an alarm on that no line followed gets a line shown during it, and so do
    the G load and the angle of attack, new then."""
    old, lines = cfg["alarms"], cfg["lines"]

    def alarm(name):
        a = old.get(name) if isinstance(old.get(name), dict) else {}
        at = a.get("at", ALARMS[name][0])
        return {**limit_alarm(name, a.get("red", at)), "at": at, "full": 100 if a.get("dyn", True) else None,
                **{k: a[k] for k in ("hz", "ms", "sound", "gap") if k in a}}

    on = [n for n in ("airframe", "gear", "flaps") if not isinstance(old.get(n), dict) or old[n].get("on", True) is not False]
    out, followed = [], set()
    for line in lines:
        if isinstance(line, dict) and line.get("alarm") in on:
            followed.add(line["alarm"])
            rules = line.get("rules") if isinstance(line.get("rules"), list) else [line.get("rule")]
            line = {**line, "rules": [alarm(line["alarm"]), *rules]}
        out.append(line)
    return out + [{"text": limit_text(n, words), "when": "own", "rules": [alarm(n)]}
                  for n in [*(n for n in on if n not in followed), "load", "aoa"]]


def _num(v, default, lo, hi):
    return min(hi, max(lo, int(v))) if isinstance(v, (int, float)) and not isinstance(v, bool) else default


def _color(v, default):
    return v if isinstance(v, str) and COLOR.fullmatch(v) else default


def _flag(v, default):
    return v if isinstance(v, bool) else default


def _sound(v) -> str:
    return v if isinstance(v, str) and SOUND.fullmatch(v) else ""


def _one(test) -> dict | None:
    """A condition on a value, {value, op, at}, or None if there isn't a whole one."""
    if not isinstance(test, dict) or not isinstance(test.get("value"), str) or not test["value"] or test.get("op") not in OPS:
        return None
    at = test.get("at")
    if not isinstance(at, (int, float)) or isinstance(at, bool) or not math.isfinite(at):
        return None
    return {"value": test["value"][:40], "op": test["op"], "at": at}


def _test(test) -> dict | None:
    """A condition, with more of them joined by AND or OR."""
    first = _one(test)
    more = test.get("more") if first and isinstance(test.get("more"), list) else []
    return first and {**first, "join": "or" if test.get("join") == "or" else "and",
                      "more": [x for x in map(_one, more) if x][:MAX_TESTS - 1]}


def _value_at(v):
    """A threshold that may be left out: a finite number, else None."""
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def _rule(rule) -> dict | None:
    """One of a line's alarms. limit: one of the aircraft's (ALARMS), its values in % of that limit; "": a condition on any
    value (its first one against "at"). at: the beep; red: the line goes red from there (None: with the beep); full: the
    beeps have come closer and closer from "gap" to one continuous sound (None: they keep "repeat", 0 = REPEAT_MS);
    color: the line's in that alarm ("" = the overlay's alert colour); blink: the parts of the line that flash; after: ms
    the alarm must last before it shows and beeps; glow: it lights a glow around the screen, in its colour, glowSize % of
    the screen's height deep, flashing with glowFlash; flashMs: the cycle of its flashing (line and glow), 0 = with its
    beeps."""
    if not isinstance(rule, dict):
        return None
    limit = rule.get("limit") if rule.get("limit") in ALARMS else ""
    test = {"value": "", "op": ">", "at": _num(rule.get("at"), ALARMS[limit][0], 1, 200), "join": "and", "more": []} if limit else _test(rule)
    if not test:
        return None
    blink = rule.get("blink") if isinstance(rule.get("blink"), list) else []
    return {**test, "limit": limit, "hz": _num(rule.get("hz"), ALARMS[limit][1] if limit else 1000, 37, 32767),
            "ms": _num(rule.get("ms"), BEEP_MS, 10, 2000), "sound": _sound(rule.get("sound")), "red": _value_at(rule.get("red")),
            "full": _value_at(rule.get("full")) if "full" in rule or not limit else 100, "gap": _num(rule.get("gap"), GAP_MS, 0, 5000),
            "color": _color(rule.get("color"), ""), "blink": [x for x in PARTS if x in blink],
            "repeat": _num(rule.get("repeat"), 0, 0, 10000), "after": _num(rule.get("after"), 0, 0, 10000),
            "glow": _flag(rule.get("glow"), False), "glowSize": _num(rule.get("glowSize"), GLOW_SIZE, 3, 50), "glowFlash": _flag(rule.get("glowFlash"), False),
            "flashMs": _num(rule.get("flashMs"), 0, 0, 4000) and max(100, _num(rule.get("flashMs"), 0, 0, 4000))}


def _line(line: dict) -> dict:
    rules = line.get("rules") if isinstance(line.get("rules"), list) else [line.get("rule")]  # a line had one ("rule") before
    if line.get("blink") is True:  # before 0.27 the whole line flashed with its alarms
        rules = [{**r, "blink": list(PARTS)} if isinstance(r, dict) and "blink" not in r else r for r in rules]
    return {"text": str(line.get("text", ""))[:MAX_TEXT], "when": line.get("when") if line.get("when") in WHEN else "always",
            "color": _color(line.get("color"), ""),
            "valueColor": _color(line.get("valueColor"), ""), "unitColor": _color(line.get("unitColor"), ""),
            "size": _num(line.get("size"), 0, 0, 400), "hideNA": _flag(line.get("hideNA"), False),
            "block": _num(line.get("block"), 0, 0, MAX_BLOCKS), "if": _test(line.get("if")),
            "rules": [x for x in map(_rule, rules) if x][:MAX_RULES]}


def _look(block: dict) -> dict:
    """What every text block has, the main one (in the overlay itself) like the others."""
    return {"scale": _num(block.get("scale"), 100, 10, 400), "columns": _num(block.get("columns"), 1, 1, 4), "frame": _num(block.get("frame"), 0, 0, 8),
            "frameColor": _color(block.get("frameColor"), "#FFFFFF"), "background": _color(block.get("background"), ""),
            "bgOpacity": block.get("bgOpacity") if block.get("bgOpacity") in STIPPLE else 50,
            "title": str(block.get("title", ""))[:MAX_TEXT], "feed": block.get("feed") if block.get("feed") in FEEDS else "",
            "rows": _num(block.get("rows"), FEED_ROWS, 1, 20)}


def _block(block: dict) -> dict:
    return {"x": _num(block.get("x"), 0, -20000, 20000), "y": _num(block.get("y"), 0, -20000, 20000), **_look(block)}


def _keys(cfg: dict, key: str, name: str) -> dict:
    keys = cfg.get(key)
    if isinstance(keys, list) and 0 < len(keys) < 5 and all(type(k) is int and (0 < k < 255 or JOY <= k < JOY + 16 * 32) for k in keys):
        return {key: keys, name: str(cfg.get(name, ""))[:32]}
    return {key: [], name: ""}


def clean(cfg, words: dict) -> dict:
    """A complete overlay configuration from what was saved or sent by the page: what's missing or odd gets the default."""
    base = defaults(words)
    if not isinstance(cfg, dict):
        return base
    if isinstance(cfg.get("alarms"), dict) and isinstance(cfg.get("lines"), list):  # saved before 0.27 (none saved: the defaults)
        cfg = {**cfg, "lines": _migrated(cfg, words)}
    if "glow" in cfg and isinstance(cfg.get("lines"), list):  # before 0.27 the glow was the overlay's, for every alarm
        cfg = {**cfg, "lines": _glow_moved(cfg)}
    if "repeat" in cfg and isinstance(cfg.get("lines"), list):  # and so was the repeat of the beeps that don't close in
        cfg = {**cfg, "lines": _repeat_moved(cfg)}
    if "flashMs" in cfg and isinstance(cfg.get("lines"), list):  # and its flashing's cycle
        cfg = {**cfg, "lines": _flash_moved(cfg)}
    out = {"x": _num(cfg.get("x"), base["x"], -20000, 20000), "y": _num(cfg.get("y"), base["y"], -20000, 20000),
           "font": cfg["font"] if isinstance(cfg.get("font"), str) and FONT.fullmatch(cfg["font"]) else base["font"],
           "size": _num(cfg.get("size"), base["size"], 6, 400), "bold": _flag(cfg.get("bold"), base["bold"]),
           "color": _color(cfg.get("color"), base["color"]), "alert": _color(cfg.get("alert"), base["alert"]),
           "opacity": _num(cfg.get("opacity"), base["opacity"], 10, 100), "show": _flag(cfg.get("show"), base["show"]),
           "hideCrash": _flag(cfg.get("hideCrash"), base["hideCrash"]), "hideUnknown": _flag(cfg.get("hideUnknown"), base["hideUnknown"]),
           "valueColor": _color(cfg.get("valueColor"), ""), "unitColor": _color(cfg.get("unitColor"), ""), **_look(cfg),
           "pctAlways": _flag(cfg.get("pctAlways"), base["pctAlways"]),
           "italic": _flag(cfg.get("italic"), base["italic"]), "spacing": _num(cfg.get("spacing"), base["spacing"], -50, 200),
           "outline": _num(cfg.get("outline"), base["outline"], 0, 4), "outlineColor": _color(cfg.get("outlineColor"), base["outlineColor"]),
           "volume": _num(cfg.get("volume"), base["volume"], 0, 100),
           "soundFocus": _flag(cfg.get("soundFocus"), base["soundFocus"]), "soundEngine": _flag(cfg.get("soundEngine"), base["soundEngine"]),
           "pollMs": _num(cfg.get("pollMs"), base["pollMs"], 50, 1000), "logMs": _num(cfg.get("logMs"), base["logMs"], 100, 10000),
           **_keys(cfg, "sheetKey", "sheetKeyName"), **_keys(cfg, "profileKey", "profileKeyName"), **_keys(cfg, "hotkey", "hotkeyName"), **_keys(cfg, "logKey", "logKeyName"), **_keys(cfg, "muteKey", "muteKeyName"),
           **_keys(cfg, "holdKey", "holdKeyName"), **_hud(cfg), **_map(cfg, base)}
    lines, blocks = cfg.get("lines"), cfg.get("blocks")
    out["blocks"] = [_block(x) for x in blocks if isinstance(x, dict)][:MAX_BLOCKS] if isinstance(blocks, list) else []
    out["lines"] = [_line(x) for x in lines if isinstance(x, dict)][:MAX_LINES] if isinstance(lines, list) else base["lines"]
    for line in out["lines"]:
        line["block"] = line["block"] if line["block"] <= len(out["blocks"]) else 0
    return out


def flaps_limit(points: list, position: float) -> float:
    """Speed limit at a flap position (0..1): linear between the flight model's points, flat outside them."""
    if position <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if position <= x1:
            return y0 + (y1 - y0) * (position - x0) / (x1 - x0)
    return points[-1][1]


def load_limits(lim: dict, state: dict) -> tuple | None:
    """The load factors (G, negative then positive) that break the wings, at the mass flown: empty + fuel. shortcut: the
    game doesn't tell the weapons' mass, so loaded the limit reads high; upgrade if /state ever gives the mass."""
    if not lim.get("load") or not lim.get("mass"):
        return None
    weight = (lim["mass"] + (state.get("Mfuel, kg") or 0)) * G
    return tuple(WING_SHARE * n / weight for n in lim["load"])


def aoa_limits(lim: dict, state: dict) -> tuple | None:
    """The wing's critical angles of attack (negative, positive), between flaps up and full flaps as they are out."""
    if not lim.get("aoa"):
        return None
    (low0, high0), (low1, high1) = lim["aoa"][0], lim["aoa"][-1]
    out = min(max((state.get("flaps, %") or 0) / 100, 0), 1)
    return low0 + (low1 - low0) * out, high0 + (high1 - high0) * out


def _share(v, limits) -> float | None:
    """v against the limit on its side (both negative below 0), %."""
    if not isinstance(v, (int, float)) or isinstance(v, bool) or not limits:
        return None
    limit = limits[1] if v >= 0 else limits[0]
    return v / limit * 100 if limit else None


def percents(lim: dict, state: dict, always: bool = False) -> dict:
    """{limit: % of it}: the airframe, the G load and the angle of attack always, gear and flaps only when they are out,
    unless always."""
    ias = state.get("IAS, km/h") or 0
    out = {"airframe": max(ias / lim["v"], (state.get("M") or 0) / lim["m"] if lim["m"] else 0) * 100}
    if ((state.get("gear, %") or 0) > 0 or always) and lim.get("gear"):
        out["gear"] = ias / lim["gear"] * 100
    flaps = state.get("flaps, %") or 0
    if (flaps > 0 or always) and lim.get("flaps"):
        out["flaps"] = ias / flaps_limit(lim["flaps"], flaps / 100) * 100
    for name, v, limits in (("load", state.get("Ny"), load_limits(lim, state)), ("aoa", state.get("AoA, deg"), aoa_limits(lim, state))):
        share = _share(v, limits)
        if share is not None:
            out[name] = share
    return out


class Trend:
    """What only shows over time: fuel burn and acceleration."""

    def __init__(self):
        self.points = deque()

    def add(self, now: float, state: dict):
        self.points.append((now, state.get("Mfuel, kg") or 0, (state.get("TAS, km/h") or 0) / 3.6))
        while now - self.points[0][0] > BURN_S:
            self.points.popleft()

    def rates(self) -> dict:
        """burn: kg/min, accel: m/s2 along the flight path."""
        first, last, out = self.points[0], self.points[-1], {}
        if last[0] - first[0] >= BURN_MIN_S:
            start = next((p for p in reversed(self.points) if last[0] - p[0] >= BURN_MIN_S and p[1] - last[1] >= BURN_KG), first)
            times, fuels = zip(*(p[:2] for p in self.points if p[0] >= start[0]))
            out["burn"] = max(-linear_regression(times, fuels).slope, 0) * 60
        recent = next(p for p in self.points if last[0] - p[0] <= ACCEL_S)
        if last[0] > recent[0]:
            out["accel"] = (last[2] - recent[2]) / (last[0] - recent[0])
        return out


def computed(lim: dict | None, state: dict, words: dict, rates: dict | None = None, always: bool = False) -> dict:
    """The values the game doesn't send. Unknown aircraft: none of those from the limits. margin: km/h left to the
    nearest airframe limit. turn (s), turn_rate, turn_radius: a level turn at this load factor and TAS. mass: empty +
    fuel, the game doesn't tell the weapons' (shortcut: so twr reads high when loaded, until /state gives the real mass)."""
    out = {"swept": words["swept"] if lim and "sw" in lim else "", **(rates or {})}
    tas, climb, load, fuel = (state.get("TAS, km/h") or 0) / 3.6, state.get("Vy, m/s") or 0, state.get("Ny") or 0, state.get("Mfuel, kg") or 0
    thrust = [v for k, v in state.items() if k.startswith("thrust ") and isinstance(v, (int, float))]
    if state.get("Mfuel0, kg"):
        out["fuel_pct"] = fuel / state["Mfuel0, kg"] * 100
    if thrust:
        out["thrust_total"] = sum(thrust)
    if tas:
        out["hspeed"] = math.sqrt(max(tas * tas - climb * climb, 0)) * 3.6
    if tas and abs(load) > TURN_G:
        pull = G * math.sqrt(load * load - 1)
        out.update(turn_rate=math.degrees(pull / tas), turn=2 * math.pi * tas / pull, turn_radius=tas * tas / pull)
    if "accel" in out:
        out["sep"] = climb + tas * out["accel"] / G
    if out.get("burn") and fuel:
        left = fuel / out["burn"] * 60
        out.update(fuel_time=f"{int(left) // 60}:{int(left) % 60:02d}", range=tas * left / 1000)
    if not lim:
        return out
    if lim.get("mass"):
        out["mass"] = lim["mass"] + fuel
        if thrust:
            out["twr"] = sum(thrust) / out["mass"]
    ias, mach = state.get("IAS, km/h") or 0, state.get("M") or 0
    out.update({f"{name}_pct": value for name, value in percents(lim, state, always).items()})
    out.update(vne=lim["v"], mne=lim["m"] or None, gear_max=lim.get("gear") or None,
               margin=min(lim["v"] - ias, ias * (lim["m"] / mach - 1) if lim["m"] and mach else lim["v"]))
    if lim.get("flaps"):
        out["flaps_max"] = flaps_limit(lim["flaps"], (state.get("flaps, %") or 0) / 100)
    if load := load_limits(lim, state):
        out.update(g_neg=load[0], g_lim=load[1])
    if aoa := aoa_limits(lim, state):
        out.update(aoa_low=aoa[0], aoa_crit=aoa[1])
    return out


def _meets(test: dict, values: dict) -> bool:
    v = values.get(FIELDS.get(test["value"], (test["value"],))[0])
    return isinstance(v, (int, float)) and not isinstance(v, bool) and OPS[test["op"]](v, test["at"])


def met(test: dict, values: dict) -> bool:
    results = [_meets(x, values) for x in (test, *test.get("more", []))]
    return any(results) if test.get("join") == "or" else all(results)


def watched(rule: dict, values: dict, pct: dict):
    """The number an alarm follows: its limit's %, else its first condition's value."""
    v = pct.get(rule["limit"]) if rule.get("limit") else values.get(FIELDS.get(rule["value"], (rule["value"],))[0])
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def alarm_on(rule: dict, values: dict, pct: dict, red: bool = False) -> bool:
    """Beeping, or with red, turning its line red (from its "red" value when it has one: it stands for its threshold)."""
    rule = {**rule, "at": rule["red"]} if red and rule.get("red") is not None else rule
    if rule.get("limit"):
        v = watched(rule, values, pct)
        return v is not None and v >= rule["at"]
    return met(rule, values)


def own_alerts(cfg: dict, values: dict, pct: dict | None = None, red: bool = False) -> list:
    """The lines' alarms on, as (line, alarm) places. pct: percents(), what's left of it (nothing for an aircraft not
    known, unbreakable or in its wreck; no gear or flaps torn off): the aircraft's limits' alarms follow it."""
    return [(i, j) for i, line in enumerate(cfg["lines"]) for j, rule in enumerate(line.get("rules") or [])
            if alarm_on(rule, values, pct or {}, red)]


def sound_of(cfg: dict, place: tuple) -> dict:
    """An alarm by its (line, alarm) place."""
    return cfg["lines"][place[0]]["rules"][place[1]]


def closeness(cfg: dict, place: tuple, pct: dict, values: dict) -> float | None:
    """Where an alarm on stands from its threshold (0) to its break (1, its "full": 100 % of an aircraft's limit). None
    for one that beeps at its repeat."""
    a = sound_of(cfg, place)
    v = watched(a, values, pct)
    if a.get("full") is None or v is None:
        return None
    if a["full"] == a["at"]:
        return 1.0
    return min(1.0, max(0.0, (v - a["at"]) / (a["full"] - a["at"])))


def pace(cfg: dict, place: tuple, close: float | None, ms: float | None = None) -> float:
    """Seconds from one beep to the next: the gap shrinks as the alarm nears its break, the beeps touch at it. ms: the
    sound's length, when it isn't the beep's (a file)."""
    a = sound_of(cfg, place)
    return (a.get("repeat") or REPEAT_MS) / 1000 if close is None else ((ms or a["ms"]) + a["gap"] * (1 - close)) / 1000


def sound_ms(alarm: dict, folder: Path | None) -> float:
    """How long an alarm's sound lasts, ms: its file's length (a long one played at a beep's pace would start over and
    over), else its beep's."""
    path = folder / alarm["sound"] if folder and alarm.get("sound") else None
    try:
        with wave.open(io.BytesIO(scaled(str(path), path.stat().st_mtime, 100)), "rb") as w:
            return w.getnframes() / w.getframerate() * 1000
    except (AttributeError, OSError, EOFError, wave.Error, ZeroDivisionError):
        return alarm["ms"]


def _value(m: re.Match, values: dict) -> str:
    name, places = m[1].strip(), m[2]
    source, default = FIELDS.get(name, (name, COMPUTED.get(name)))
    v = values.get(source)
    if isinstance(v, str):
        return v
    if v is None or isinstance(v, bool):
        return NO_VALUE
    return f"{v:.{int(places)}f}" if places else f"{v:.{default}f}" if default is not None else f"{v:g}"


def pieces(text: str, values: dict) -> list:
    """A line's text cut for its colours, [(text, kind)]: the name before the first value, the values, the unit after one."""
    out, at = [], 0
    for m in FIELD.finditer(text):
        if m.start() > at:
            out.append((text[at:m.start()], "unit" if out else "name"))
        out.append((_value(m, values), "value"))
        at = m.end()
    return [*out, (text[at:], "unit" if out else "name")] if at < len(text) else out


def fill(text: str, values: dict) -> str:
    """A line's text with its {values}: what isn't there says N/A."""
    return "".join(x for x, _ in pieces(text, values)).rstrip()


def clock(rule: dict):
    """What an alarm's flashing follows: True, its beeps; else its own cycle, ms."""
    return rule.get("flashMs") or True


def shown(line: dict, values: dict, on: list, i: int = -1) -> bool:
    """on: the alarms whose lines are red, by (line, alarm) place; i: this line's place."""
    if line.get("if") and not met(line["if"], values):
        return False
    if line["when"] == "alarm":
        return bool(on)
    if line["when"] == "own":
        return any(x[0] == i for x in on)
    return line["when"] == "always" or (values.get(WHEN[line["when"]]) or 0) > 0


def lines_for(cfg: dict, values: dict, on: list, feeds: dict | None = None) -> list:
    """[(text, colour, size, blinks, block, parts), ...] of the overlay; parts: [(text, colour, blinks[, colour out of its
    turn]), ...], blinks: False, or its clock (see clock). on: the
    alarms whose lines go red, by (line, alarm) place: a line takes the colour of the last of its own that is on, and
    flashes the parts they ask. A block's title comes first; a block of the chat or the battle log shows feeds' lines."""
    blocks = [cfg, *cfg["blocks"]]
    out = []

    def row(text, color, size, block, parts):
        out.append((text, color, round(size * blocks[block]["scale"] / 100), any(x[2] for x in parts), block, parts))

    for block, b in enumerate(blocks):
        if b.get("title"):
            row(b["title"], cfg["color"], cfg["size"], block, [(b["title"], cfg["color"], False)])
        for text in (feeds or {}).get(b.get("feed"), [])[-b.get("rows", FEED_ROWS):] if b.get("feed") else ():
            row(text, cfg["color"], cfg["size"], block, [(text, cfg["color"], False)])
    for i, line in enumerate(cfg["lines"]):
        text, block = fill(line["text"], values), line.get("block", 0)
        if blocks[block].get("feed") or not shown(line, values, on, i) or (line.get("hideNA") and NO_VALUE in text):
            continue
        mine = [line["rules"][j] for x, j in on if x == i]
        color = (mine[-1]["color"] or cfg["alert"]) if mine else line["color"] or cfg["color"]
        tints = {"name": color, "value": color if mine else line.get("valueColor") or cfg["valueColor"] or color,
                 "unit": color if mine else line.get("unitColor") or cfg["unitColor"] or color}
        flash = {part: clock(rule) for rule in mine for part in rule.get("blink", ())}  # the last alarm's, by part
        own = line["color"] or cfg["color"]  # a flashing part out of its turn: the line's colours, still readable
        off = {"name": own, "value": line.get("valueColor") or cfg["valueColor"] or own, "unit": line.get("unitColor") or cfg["unitColor"] or own}
        parts = []
        for piece, kind in pieces(line["text"], values):
            tail = (tints[kind], flash[kind], off[kind]) if kind in flash else (tints[kind], False)
            if parts and parts[-1][1:] == tail:
                parts[-1] = (parts[-1][0] + piece, *tail)
            else:
                parts.append((piece, *tail))
        row(text, color, line["size"] or cfg["size"], block, parts)
    return out


def columns_of(rows: list, columns: int) -> list:
    """A block's lines in its columns, top to bottom then left to right."""
    tall = max(1, math.ceil(len(rows) / columns))
    return [rows[i:i + tall] for i in range(0, len(rows), tall)]


def numbers(values: dict) -> dict:
    """A reading's values for curves and logs, under their names."""
    out = {}
    for name in SERIES:
        source, places = FIELDS.get(name, (name, COMPUTED.get(name)))
        v = values.get(source)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[name] = round(v, places + 1)
    return out


def where(info, objects) -> tuple | None:
    """Your aircraft on the map: (east m, north m, heading deg). The map marker is a share of the map's extent (map_info),
    its direction is the heading (checked against the compass); None when the game has no map or no marker of yours."""
    try:
        me = next(o for o in objects if o.get("icon") == "Player")
        (x0, z0), (x1, z1) = info["map_min"], info["map_max"]
        return (round(x0 + me["x"] * (x1 - x0), 1), round(z1 - me["y"] * (z1 - z0), 1),
                round(math.degrees(math.atan2(me["dx"], -me["dy"])) % 360, 1))
    except (StopIteration, KeyError, TypeError, ValueError, AttributeError):
        return None


def answer(raw: bytes | None) -> dict:
    """A game API answer, {} when there is none or it says it isn't valid: a bad answer is no reason to stop."""
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) and data.get("valid") else {}


def read_indicators(raw: bytes | None) -> dict:
    """/indicators, its pitch the right way round too: the game's reads negative nose up (-7.4 in a 7.4° climb)."""
    data = answer(raw)
    if isinstance(data.get("aviahorizon_pitch"), (int, float)):
        data["nose_up"] = -data["aviahorizon_pitch"]
    return data


def flying(raw: bytes | None, in_mission=lambda: True) -> dict | None:
    """/state while in the air, else None. In the hangar it is valid too, the aircraft on show flickering between 0 and
    1 km/h, mostly without fuel, but not always (the Swiss F/A-18C has 925 kg there, 2026-11-08): standing still or with
    empty tanks, only a loaded map tells a real flight."""
    state = answer(raw)
    if "Mfuel0, kg" not in state or not state.get("IAS, km/h"):
        return None
    hangar_like = state.get("Mfuel, kg") == 0 or state["IAS, km/h"] <= HANGAR_IAS
    return None if hangar_like and not in_mission() else state


def driving(raw: bytes | None) -> dict | None:
    """/indicators in a tank or a ship: their numbers are there, /state is an aircraft's."""
    data = read_indicators(raw)
    return data if data.get("army") in ("tank", "ship") else None


def reported_type(indicators: dict) -> str | None:
    """The vehicle id the game itself names in /indicators."""
    kind = indicators.get("type")
    return kind if isinstance(kind, str) else None


def _engines(state: dict) -> tuple:
    return ([v for k, v in state.items() if k.startswith("RPM ") and isinstance(v, (int, float))],
            [v for k, v in state.items() if k.startswith("throttle ") and isinstance(v, (int, float))])


def crashed(before: dict | None, state: dict) -> bool:
    """A crash, as the game's numbers show it (recorded on real ones): from one reading to the next every engine's RPM and
    throttle fall to 0. /state then stays valid, wreck included, until the next spawn. It takes that drop: a shot or
    stopped engine winds down and keeps its throttle, a hard pull only slows the aircraft."""
    rpm, throttle = _engines(state)
    return bool(before and rpm and max(_engines(before)[0], default=0) >= RUNNING_RPM and not any(rpm) and not any(throttle))


def crash_name(line: str, words: list) -> str | None:
    """Who a battle log line says crashed: "=TAG= Name (aircraft) has crashed." (words: see builder.build_battle_words)."""
    if " (" in line and any("".join(line.split()).endswith(w) for w in words):
        return line.split(" (", 1)[0]
    return None


def matches(lim: dict, state: dict, fuel: float | None = None) -> bool:
    """Do this aircraft's fuel capacity (one of its two values, or the mission's own) and engines fit /state?"""
    capacity = state["Mfuel0, kg"]
    return (lim.get("eng") == sum(k.startswith("throttle ") for k in state)
            and any(abs(x - capacity) < 1 for x in lim.get("fuel", []) + ([fuel] if fuel else [])))


def speeds(lim: dict) -> tuple:
    return lim["v"], lim["m"], lim.get("gear"), str(lim.get("flaps"))


def recognise(planes: dict, state: dict, model: str | None) -> dict | None:
    """The limits of the aircraft flown: the one the game saved if it fits /state, else what every aircraft that fits
    shares; None when they differ (or none fits): the choice would change the limits, so nothing is assumed."""
    found = [vid for vid, lim in planes.items() if matches(lim, state)]
    if model in found:
        return planes[model]
    return planes[found[0]] if len({speeds(planes[v]) for v in found}) == 1 else None


def read_model(path: Path) -> str | None:
    try:
        m = SAVED_MODEL.search(path.read_text(encoding="latin-1"))
    except OSError:
        return None
    return m[1] if m else None


def save_file() -> Path | None:
    for root in sights._saves_roots():
        path = root / "last" / "production" / "global.blk"
        if path.is_file():
            return path
    return None


def _wav(params: tuple, frames: bytes) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setparams(params)
        w.writeframes(frames)
    return out.getvalue()


@lru_cache(maxsize=32)
def tone(freq: int, ms: int, volume: int) -> bytes:
    """A beep as a .wav in memory: the system's own beep has no volume."""
    count, fade, step = SOUND_RATE * ms // 1000, SOUND_RATE * FADE_MS / 1000, 2 * math.pi * freq / SOUND_RATE
    samples = array("h", (int(32767 * volume / 100 * min(1, i / fade, (count - i) / fade) * math.sin(step * i)) for i in range(count)))
    return _wav((1, 2, SOUND_RATE, count, "NONE", "not compressed"), samples.tobytes())


@lru_cache(maxsize=32)
def scaled(path: str, modified: float, volume: int) -> bytes:
    """A sound file at this volume. Only 16-bit PCM can be scaled here: the others play as they are."""
    with wave.open(path, "rb") as w:
        params, frames = w.getparams(), w.readframes(w.getnframes())
    if params.sampwidth == 2 and volume < 100:
        frames = array("h", (x * volume // 100 for x in array("h", frames))).tobytes()
    return _wav(params, frames)


_sounds = queue.Queue(maxsize=3)
_speaker = []


def _speak():
    while True:
        queued, data = _sounds.get()
        if time.monotonic() - queued < STALE_S:
            waveout.play(data, OUTPUT["device"])


def _sound_out(data: bytes):
    """Played apart: a long sound mustn't hold up the readings. No sound device: the alarms still show."""
    if not _speaker:
        _speaker.append(threading.Thread(target=_speak, daemon=True))
        _speaker[0].start()
    with contextlib.suppress(queue.Full):
        _sounds.put_nowait((time.monotonic(), data))


def beep(freq: int, ms: int, volume: int = 100):
    _sound_out(tone(freq, ms, volume))


def play(alarm: dict, volume: int, folder: Path | None = None):
    """An alarm's sound: its own .wav if it's still there, else its beep."""
    path = folder / alarm["sound"] if folder and alarm.get("sound") else None
    try:
        return _sound_out(scaled(str(path), path.stat().st_mtime, volume))
    except (AttributeError, OSError, EOFError, wave.Error):
        beep(alarm["hz"], alarm["ms"], volume)


def sound_list(folder: Path) -> list:
    return sorted(p.name for p in folder.glob("*.wav") if SOUND.fullmatch(p.name))


def save_sound(folder: Path, name: str, data: str) -> str:
    """A .wav the player picked (base64) into folder, under a safe name. ValueError if the game of sounds can't play it."""
    stem = re.sub(r"[^\w.\- ]", "_", Path(name).stem)[:60].strip(" .") or "sound"
    try:
        raw = base64.b64decode(data, validate=True)
        with wave.open(io.BytesIO(raw), "rb"):
            pass
    except (ValueError, EOFError, wave.Error):
        raise ValueError("Pick a .wav sound file.")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{stem}.wav").write_bytes(raw)
    return f"{stem}.wav"


def game_running() -> bool:
    import ctypes
    return bool(ctypes.windll.user32.FindWindowW(GAME_WINDOW_CLASS, None))


def game_focused() -> bool:
    import ctypes
    name = ctypes.create_unicode_buffer(32)
    ctypes.windll.user32.GetClassNameW(ctypes.windll.user32.GetForegroundWindow(), name, len(name))
    return name.value == GAME_WINDOW_CLASS


def tried_state(rule: dict, value: float, text: str = "", base: dict | None = None, lim: dict | None = None) -> tuple:
    """A reading with a tried alarm's value in it, so that every line shows it: a limit's % gives the speed, G or angle of
    attack it means; the airframe's, from a line showing the Mach number (text), the Mach number. base, lim: the flight
    under way and its aircraft's limits, else the sample's. Returns (reading, the limit tried or None, its %)."""
    st, lim = dict(base or SAMPLE_STATE), lim or SAMPLE_LIM
    name = rule.get("limit") or rule["value"]
    limit = name if name in ALARMS else name[:-4] if name.endswith("_pct") and name[:-4] in ALARMS else None
    k = value / 100
    if limit == "airframe" and "{mach}" in text:
        st["M"] = k * lim["m"]
        st["IAS, km/h"] = min(st["IAS, km/h"], 0.9 * k * lim["v"])  # under the Mach number's share: it's what's tried
    elif limit in ("airframe", "gear", "flaps"):
        flaps = (st.get("flaps, %") or 0) / 100
        top = {"airframe": lim["v"], "gear": lim.get("gear"), "flaps": lim.get("flaps") and flaps_limit(lim["flaps"], flaps)}[limit]
        if top:
            ias = st.get("IAS, km/h") or 0
            st["TAS, km/h"] = (st.get("TAS, km/h") or 0) / ias * k * top if ias else k * top
            st["IAS, km/h"] = k * top
            st["M"] = min(st.get("M") or 0, 0.9 * k * lim["m"]) if limit == "airframe" else st.get("M")  # under the IAS's share
            st["gear, %"] = 100 if limit == "gear" else st.get("gear, %")
    elif limit == "load" and load_limits(lim, st):
        st["Ny"] = k * load_limits(lim, st)[1]
    elif limit == "aoa" and aoa_limits(lim, st):
        st["AoA, deg"] = k * aoa_limits(lim, st)[1]
    elif name == "fuel_pct" and st.get("Mfuel0, kg"):
        st["Mfuel, kg"] = k * st["Mfuel0, kg"]
    elif name not in COMPUTED and name != "fuel_time":
        st[FIELDS.get(name, (name,))[0]] = value
        if name == "ias":
            st["TAS, km/h"] = SAMPLE_STATE["TAS, km/h"] / SAMPLE_STATE["IAS, km/h"] * value  # shortcut: the sample's TAS/IAS
    return st, limit, value


SAMPLE_FEEDS = {"chat": ["[All] Pilot_1: o7", "[Team] Pilot_2: gear down, landing"],
                "log": ["Pilot_3 (F-16A) shot down Pilot_4 (MiG-29)", "Pilot_5 (Su-27) has achieved \"Wingman\""]}


class Wep:
    """What's left of the water or methanol that WEP burns (MaxNitro), in seconds of WEP: it runs while a throttle is past
    100 %. shortcut: the game sends no such reading, so this one counts from the spawn (unchecked in game)."""

    def __init__(self):
        self.used, self.t = 0.0, None

    def add(self, now: float, state: dict, lim: dict | None):
        wep = (lim or {}).get("wep")
        if wep and self.t is not None and any(isinstance(v, (int, float)) and v > 100 for k, v in state.items() if k.startswith("throttle ")):
            self.used += min(now - self.t, 1.0) * wep[1]
        self.t = now

    def left(self, lim: dict | None) -> dict:
        wep = (lim or {}).get("wep")
        if not wep:
            return {}
        s = max(wep[0] - self.used, 0) / wep[1]
        return {"wep_s": s, "wep": f"{int(s) // 60}:{int(s) % 60:02d}"}


def sheet(lim: dict, state: dict, words: dict, name: str | None) -> list:
    """The aircraft's sheet, shown while its key is held: its limits, the G load and the angle of attack at this mass."""
    out = [name] if name else []
    out.append(f"Vne {lim['v']:.0f} km/h" + (f"   Mne {lim['m']:.2f}" if lim.get("m") else ""))
    if lim.get("gear"):
        out.append(f"{words['gear']} {lim['gear']:.0f} km/h")
    if lim.get("flaps"):
        out.append(f"{words['flaps']} " + "   ".join(f"{p * 100:.0f} %: {v:.0f}" for p, v in lim["flaps"]) + " km/h")
    if load := load_limits(lim, state):
        out.append(f"G {load[1]:+.1f} / {load[0]:+.1f}")
    if aoa := aoa_limits(lim, state):
        out.append(f"AOA {aoa[1]:.1f}° / {aoa[0]:.1f}°")
    if lim.get("wep"):
        out.append(f"WEP {Wep().left(lim)['wep']}")
    if lim.get("boost"):
        out.append(f"{words['booster']} " + " + ".join(f"{fuel / rate:.0f} s" for fuel, rate in lim["boost"]))
    if lim.get("mass"):
        out.append(f"{words['mass']} {lim['mass'] + (state.get('Mfuel, kg') or 0):.0f} kg")
    return out


def joy_buttons(ids) -> set:
    """The joystick buttons held, as key codes (JOY + 32 x joystick + button), on the joysticks asked: Windows' winmm."""
    import ctypes

    class JOYINFOEX(ctypes.Structure):
        _fields_ = [(n, ctypes.c_uint32) for n in ("size", "flags", "x", "y", "z", "r", "u", "v", "buttons", "number", "pov", "res1", "res2")]

    out = set()
    for joy in ids:
        info = JOYINFOEX(size=ctypes.sizeof(JOYINFOEX), flags=0x80)  # JOY_RETURNBUTTONS
        try:
            if ctypes.windll.winmm.joyGetPosEx(joy, ctypes.byref(info)) == 0:
                out |= {JOY + 32 * joy + b for b in range(32) if info.buttons >> b & 1}
        except (AttributeError, OSError):
            break
    return out


def joy_wait(seconds: float = 5.0) -> int | None:
    """The first joystick button pressed within seconds (one held already doesn't count), for My overlay's key fields."""
    held, end = joy_buttons(range(16)), time.monotonic() + seconds
    while time.monotonic() < end:
        time.sleep(0.05)
        now = joy_buttons(range(16))
        if now - held:
            return min(now - held)
        held &= now
    return None


class Watch:
    """Reads /state and keeps .display, what the overlay shows: see lines_for.

    get: bytes of a game API path; details: () -> data/details.json; mission_on_map: () -> is the map of the mission
    generated last the one loaded in the game?; save: () -> path of global.blk; stats: () -> the player's numbers from
    My battles (replays.summary); log_words: () -> data/battle_words.json; name: vehicle id -> the name the app shows."""

    def __init__(self, get, details, mission_on_map=lambda: False, save=save_file, lang="en", logs=None,
                 kind=lambda vid: None, crash_words=list, sounds=None, stats=dict, log_words=dict, name=lambda vid: vid,
                 nation=lambda vid: None):
        self.get, self.details, self.mission_on_map, self.save, self.kind = get, details, mission_on_map, save, kind
        self.crash_words, self.stats, self.log_words, self.name, self.nation = crash_words, stats, log_words, name, nation
        self.logs, self.sounds = logs, sounds  # folders of the CSV logs and of the player's sounds
        self.words = labels(lang)
        self.base = self.cfg = clean(None, self.words)  # the overlay for all aircraft, the one in use
        self.profiles = {}  # {aircraft id or "type:<class>": its overlay}
        self.profile = ""  # the one in use, "" = base
        self.current = None  # the aircraft flown
        self.enabled = False
        self.preview = None  # My overlay's "show it on my screen": its configuration, shown without the game
        self.hidden = False  # the show / hide key
        self.muted = False  # the mute key
        self.mission = None  # {"id", "fuel", "unbreakable"}: set when a mission is generated
        self.display = []
        self.hud = []  # the HUD's shapes with the sample values, for the preview: see hud.draw
        self.hud_live = None  # (overlay, nation) while flying an aircraft that shows its HUD: see hud_frame
        self.attitude, self.glide = hud.Attitude(), hud.Glide()  # pitch and bank if the game has none; between readings
        self.hud_viewed = -VIEW_S  # when the cockpit window last asked for its HUD
        self.map_live = None  # the overlay while flying with the minimap on
        self.map = self.blank_map()  # what the minimap read last: see read_map
        self.hud_place = "cockpit"  # or outside: the HUD key switches them
        self.preview_key = ""  # the overlay shown by preview: an aircraft's own gives its HUD style
        self.on = []  # the alarms on, for the cockpit window's HUD
        self.flying = False
        self.crash = False  # in the wreck, until the next spawn
        self.warn = False  # an alarm is on
        self.glow = None  # the glow it lights, see glow_of
        self.pilot = None  # the player's name in the battle log, see read_log
        self.past = {}  # the player's numbers from My battles, read at the start of a battle
        self.tally = battle.Tally()  # and this battle's so far
        self.killed_by = deque()  # who shot the player down, until a replay says if it was a teammate: server.battles
        self._looks = 0
        self._before = None  # the last reading in the air
        self._log_id, self._readings, self._silent = None, 0, 0.0
        self.viewed = -VIEW_S  # when the Flight data tab last asked
        self.trace = deque(maxlen=TRACE_MAX)  # the last readings, for the curves: {"n": number, "t": time, values...}
        self.last = {}  # the latest reading (every tick, not one a second), for the cockpit window
        self.log = None
        self.log_lock = threading.Lock()
        self.bench = False  # a test is armed: readings come faster than the player's rate, see bench.py
        self.trend = Trend()
        self._seq, self._sampled, self._flight = 0, 0.0, "flight"
        self.stopping = threading.Event()
        self.overlay = None
        self._details, self._planes = None, {}
        self._saved = (None, None)
        self._key, self._lim, self._unbreakable = None, None, False
        self._last_beep = 0.0
        self.ringing = None  # (until when, seconds between beeps, sounds, volume, seconds a beep lasts): what the bell plays, see ring
        self._bell = threading.Lock()
        self._wake = threading.Event()  # a trial starting: no waiting out a second's sleep
        self.broken = set()  # gear or flaps torn off: their alarms stay silent until the next spawn
        self._since = {}  # {((line, alarm), "beep" or "red"): since when it's on}, for the alarms that must last
        self.wep = Wep()
        self.feeds = {kind: deque(maxlen=20) for kind in FEEDS}  # the game's chat and battle log, for blocks showing them
        self._feed = {"t": -FEED_S, "chat": 0, "event": 0, "damage": 0}
        self.sheet = False  # the sheet key is held
        self.forced = None  # the overlay the profile key picked, until the next spawn
        self.trial = None  # My overlay's Try: {"key": its overlay, "place": (line, alarm), "value", "t", "since"}
        self._real = None  # in flight: (its reading, its aircraft's limits, its values), for a trial

    def start_overlay(self):
        if not self.overlay:
            self.overlay = threading.Thread(target=run_overlay, args=(self,), daemon=True)
            self.overlay.start()

    def set_enabled(self, on: bool):
        self.enabled = on
        if on:
            self.start_overlay()

    def set_preview(self, cfg: dict | None, key: str = ""):
        self.preview, self.preview_key = cfg, key
        if cfg:
            self.start_overlay()
        self.display = self.sample(cfg) if cfg else []
        self.hud = self.sample_hud(cfg, key, self.hud_place) if cfg else []

    def set_config(self, base: dict, profiles: dict):
        self.base, self.profiles = base, profiles
        self.pick()

    def pick(self):
        """The overlay of the aircraft flown: its own, else its type's, else its engine's, else the one for all aircraft."""
        kind = self.kind(self.current)
        engine = "jet" if (self._lim or {}).get("jet") else "prop"
        wanted = (self.current, f"type:{kind}", f"type:{engine}" if self.current and kind != "helicopter" else None)
        self.profile = self.forced if self.forced in ("", *self.profiles) else next((k for k in wanted if k in self.profiles), "")
        self.cfg = self.profiles.get(self.profile, self.base)

    def next_profile(self):
        """The profile key: the next overlay in the list (the one for all aircraft first), until the next spawn."""
        names = ["", *self.profiles]
        self.forced = names[(names.index(self.profile) + 1) % len(names)] if self.profile in names else ""
        self.pick()

    def held(self, cfg: dict, places: list, kind: str, memo: dict | None = None) -> list:
        """The alarms on that have lasted their "after" (ms); kind: "beep" or "red", each counted on its own. memo: when
        each came on (self._since in flight, the trial's own while trying)."""
        memo = self._since if memo is None else memo
        now = time.monotonic()
        since = {(x, kind): memo.get((x, kind), now) for x in places}
        for k in [k for k in memo if k[1] == kind and k not in since]:
            del memo[k]
        memo.update(since)
        return [x for x in places if now - since[x, kind] >= sound_of(cfg, x).get("after", 0) / 1000]

    def set_trial(self, key: str | None, place: tuple | None = None, value: float = 0.0) -> list:
        """My overlay's Try: one alarm's value set by hand, the overlay shown on the screen and heard as in flight. key: the
        overlay (profile) tried, None stops. Returns what the overlay shows."""
        same = self.trial and (self.trial["key"], self.trial["place"]) == (key, place)
        self.trial = {"key": key, "place": place, "value": value, "t": time.monotonic(), "since": self.trial["since"] if same else {}} \
            if key is not None and place else None
        if self.trial:
            self.start_overlay()
            self._wake.set()
        else:
            self.glow = self.ringing = None
        return self.trial_frame(self._real, ring=False)

    def shown_cfg(self) -> dict:
        """The overlay the window draws: the one shown by My overlay, the one tried, or the aircraft's."""
        return self.preview or (self.profiles.get(self.trial["key"], self.base) if self.trial else self.cfg)

    def trial_frame(self, real: tuple | None = None, ring: bool = True) -> list:
        """The trial's overlay: the tried alarm's value set in the sample, or in the flight under way (real: its reading,
        its aircraft's limits, its values); only that alarm turns its line red, beeps (closing in as in flight, after its
        delay) and lights its glow. ring: False from the page's request, the loop rings it at once (one beat, not two)."""
        t = self.trial
        cfg = self.profiles.get(t["key"], self.base) if t else None
        i, j = t["place"] if t else (-1, -1)
        if not t or time.monotonic() - t["t"] > TRY_S or not (0 <= i < len(cfg["lines"]) and 0 <= j < len(cfg["lines"][i]["rules"])):
            self.trial, self.glow = None, None
            return []
        rule = cfg["lines"][i]["rules"][j]
        base, lim, known = real or (SAMPLE_STATE, SAMPLE_LIM, {**SAMPLE_STATS, "vehicle": self.vehicle(SAMPLE_VEHICLE), "wep": "4:32", "wep_s": 272})
        state, limit, value = tried_state(rule, t["value"], cfg["lines"][i]["text"], base, lim)
        rates = self.trend.rates() if real and self.trend.points else {"burn": 95, "accel": 1.2}
        values = {**known, **state, **computed(lim, state, self.words, rates, cfg["pctAlways"])}
        pct = percents(lim, state)
        if limit:
            pct[limit] = values[f"{limit}_pct"] = value
        elif rule["value"] in COMPUTED or rule["value"] == "fuel_time":  # worked out from the readings: set as it is
            values[rule["value"]] = value
        mine = lambda places: [x for x in places if x == (i, j)]
        on = self.held(cfg, mine(own_alerts(cfg, values, pct)), "beep", t["since"])
        red = self.held(cfg, mine(own_alerts(cfg, values, pct, red=True)), "red", t["since"])
        self.warn, self.glow = bool(red or on), glow_of(cfg, red or on)
        if ring:
            self.ring(cfg, [] if self.muted else on, pct, values)
        return lines_for(cfg, values, red, self.feeds if real else SAMPLE_FEEDS)

    def read_feeds(self, cfg: dict):
        """The chat and the battle log, for the blocks that show them, once a second: only what's new."""
        f, now = self._feed, time.monotonic()
        if not any(b.get("feed") for b in (cfg, *cfg["blocks"])) or now - f["t"] < FEED_S:
            return
        f["t"] = now
        got = battle.news(self.get, f["chat"], f["event"], f["damage"])
        if not got["up"]:  # the game numbers them from 1 again next time
            f.update(chat=0, event=0, damage=0)
            return
        for key, lines in (("chat", got["chat"]), ("event", got["events"]), ("damage", got["damage"])):
            f[key] = lines[-1]["id"] if lines else f[key]
        self.feeds["chat"].extend(f"{x['sender']}: {x['text']}" if x["sender"] else x["text"] for x in got["chat"])
        self.feeds["log"].extend(x["text"] for x in sorted(got["events"] + got["damage"], key=lambda x: x["time"]))

    def set_log(self, on: bool):
        with self.log_lock:
            if on and not self.log:
                self.log = flightlog.Log(self.logs, self._flight, [*(column(n) for n in SERIES), *POSITION])
            elif self.log and not on:
                self.log.close()
                self.log = None

    def vehicle(self, vid: str | None) -> str | None:
        """What {vehicle} shows: the name of an id, which the game may give with its folder; None says N/A."""
        vid = vid and vid.rsplit("/", 1)[-1]
        return self.name(vid) if vid else None

    def sample(self, cfg: dict) -> list:
        values = {**SAMPLE_STATE, **SAMPLE_STATS, "vehicle": self.vehicle(SAMPLE_VEHICLE), "wep": "4:32", "wep_s": 272,
                  **computed(SAMPLE_LIM, SAMPLE_STATE, self.words, {"burn": 95, "accel": 1.2}, cfg["pctAlways"])}
        return lines_for(cfg, values, own_alerts(cfg, values, percents(SAMPLE_LIM, SAMPLE_STATE), red=True), SAMPLE_FEEDS)

    def sample_hud(self, cfg: dict, key: str = "", place: str = "cockpit", screen_size: tuple | None = None) -> list:
        """The HUD with the sample values; key: the overlay's aircraft id, if it has one, for its nation's style."""
        if cfg["hudMode"] == "off":
            return []
        values = {**SAMPLE_STATE, **SAMPLE_ATTITUDE, **computed(SAMPLE_LIM, SAMPLE_STATE, self.words, {"burn": 95})}
        nation = self.nation(key) if key and not key.startswith("type:") else None
        on = own_alerts(cfg, values, percents(SAMPLE_LIM, SAMPLE_STATE))
        return hud.draw(numbers(values), cfg, nation, screen_size or screen(), place, [sound_of(cfg, x)["limit"] for x in on])

    @staticmethod
    def blank_map() -> dict:
        return {"t": 0.0, "gen": None, "image": None, "info": {}, "seen": {"me": None, "fixed": [], "allies": []}, "trail": deque(maxlen=TRAIL_MAX),
                "glide": hud.Glide(), "asked": -PICTURE_S}

    def read_map(self):
        """The minimap's reading, 10 times a second: minimap.keep drops every enemy (and the allies unless asked) as soon as
        it's read. The map's picture stays in memory as the game sends it, JPEG or PNG: GDI+ reads it from there."""
        m, now = self.map, time.monotonic()
        if now - m["t"] < MAP_S:
            return
        m["t"] = now
        info = answer(self.get("/map_info.json"))
        if info.get("map_generation") != m["gen"]:  # another map: its picture, and a new trail
            m.update(gen=info.get("map_generation"), image=None, asked=-PICTURE_S, trail=deque(maxlen=TRAIL_MAX), glide=hud.Glide())
        if info and m["image"] is None and now - m["asked"] >= PICTURE_S:  # until the game gives it: it can't come the first time
            m["asked"] = now
            img = self.get(f"/map.img?gen={m['gen'] or 0}")
            m["image"] = img if img and len(img) >= 1000 else None  # outside a battle the game sends a blank of 1.5 kB
        try:
            objects = json.loads(self.get("/map_obj.json")) if info else []
        except (TypeError, ValueError):
            objects = []
        m["info"], m["seen"] = info, minimap.keep(objects, *((self.map_live or {}).get(k, False) for k in ("mapAllies", "mapAlliesGround")))
        me = m["seen"]["me"]
        if me:
            m["glide"].add(now, me)
        if me and (not m["trail"] or math.dist(m["trail"][-1], (me["x"], me["y"])) > 0.002):
            m["trail"].append((me["x"], me["y"]))

    def sample_frame(self, cfg: dict) -> dict | None:
        return None if cfg["mapMode"] == "off" else minimap.draw(minimap.SAMPLE, minimap.SAMPLE_INFO, minimap.SAMPLE_TRAIL, cfg)

    def sample_map(self, cfg: dict) -> list:
        """The sample's shapes, for My overlay's picture of the screen."""
        frame = self.sample_frame(cfg)
        return frame["marks"] + frame["frame"] if frame else []

    def map_frame(self) -> dict | None:
        """The minimap to draw now (minimap.draw's, with "image": (the picture's bytes, its map)), the aircraft gliding between
        readings; the sample while My overlay shows it on the screen."""
        cfg, m = self.map_live, self.map
        if not cfg:
            frame = self.sample_frame(self.preview) if self.preview else None
            return {**frame, "image": (None, None)} if frame else None
        seen = {**m["seen"], "me": m["glide"].at(time.monotonic()) or m["seen"]["me"]}
        return {**minimap.draw(seen, m["info"], list(m["trail"]), cfg), "image": (m["image"], m["gen"])}

    def hud_frame(self, size: tuple | None = None, place: str | None = None, cfg: dict | None = None) -> list:
        """The HUD to draw now: in flight, the readings glide into each other; else the preview's sample, if any.
        The cockpit window passes its size, the place "window" and its overlay."""
        live = (cfg, self.nation(self.current)) if cfg else self.hud_live
        if not live:
            return self.hud
        return hud.draw(self.glide.at(time.monotonic()), live[0], live[1], size or screen(), place or self.hud_place, self.on)

    def record(self, values: dict):
        """A reading a second for the curves and the log."""
        now = time.monotonic()
        if now - self._sampled < (BENCH_S if self.bench else self.cfg["logMs"] / 1000):
            return
        self._sampled = now
        row = numbers(values)
        self._seq += 1
        self.trace.append({"n": self._seq, "t": round(time.time(), 1), **row})
        spot = self.spot() if self.log else None
        with self.log_lock:
            if self.log:
                self.log.write([*(row.get(name, "") for name in SERIES), *(spot or [""] * len(POSITION))])

    def in_mission(self) -> bool:
        return bool(answer(self.get("/map_info.json")))

    def spot(self) -> tuple | None:
        try:
            return where(json.loads(self.get("/map_info.json")), json.loads(self.get("/map_obj.json")))
        except (TypeError, ValueError):  # no game, no answer
            return None

    def planes(self) -> dict:
        details = self.details()
        if details is not self._details:  # new data after an update
            self._details = details
            self._planes = {vid: d["st"]["lim"] for vid, d in details.items() if (d.get("st") or {}).get("lim")}
        return self._planes

    def model(self) -> str | None:
        """The aircraft the game saved, read again only when the file changes."""
        path = self.save()
        try:
            modified = path.stat().st_mtime
        except (OSError, AttributeError):
            return None
        if modified != self._saved[0]:
            self._saved = (modified, read_model(path))
        return self._saved[1]

    def read_log(self):
        """The battle log (/hudmsg), a few times a second: an aircraft breaking up in the air keeps its engines running, only
        this says it's gone. The game's API doesn't give the player's name and the log names everybody: it comes from the
        replays, and from the line that comes with an impact of ours, so that nobody else's crash can ever silence the alarms."""
        self._readings += 1
        if self._readings % LOG_EVERY:
            return
        lines = battle.damage_lines(self.get, self._log_id or 0)
        first, self._log_id = self._log_id is None, lines[-1]["id"] if lines else self._log_id or 0
        words = self.crash_words() if lines and not first else []  # the first look is the past
        for name in filter(None, (crash_name(x["text"], words) for x in lines)):
            if self.crash:
                self.pilot = name
            elif name == self.pilot or battle.named(name, self.past.get("pilot", "")):
                self._silent = time.monotonic() + BREAK_UP_S

    def follow_battle(self):
        """The overlay's numbers: read alive or dead, a new battle starts them over. The name comes from the replays, else
        from read_log; without one the live numbers say N/A: a line can't be told to be ours."""
        self._looks += 1
        if not self.enabled or self._looks % LOG_EVERY:
            return
        if not self.in_mission():
            self.killed_by.extend(self.tally.killers)
            self.tally = battle.Tally()
            if self.killed_by:
                self.past = self.stats()  # through server.battles, which files them once the replay is there
            return
        if self.tally.after is None:
            self.past = self.stats()
        lines = battle.damage_lines(self.get, self.tally.after or 0)
        self.tally.add(lines, self.past.get("pilot") or self.pilot, self.log_words() if lines else {})

    def own_numbers(self) -> dict:
        return {**self.past, **(self.tally.values() if self.past.get("pilot") or self.pilot else {})}

    def aircraft(self, state: dict, reported: str | None):
        """Works out the aircraft when what it depends on changes."""
        model, planes = self.model(), self.planes()
        key = (state["Mfuel0, kg"], sum(k.startswith("throttle ") for k in state), model, reported, id(self.mission))
        if key == self._key:
            return
        self._key = key
        self._flight = reported or model or "flight"
        m, lim = self.mission, None
        if m and m["id"] in planes and matches(planes[m["id"]], state, m.get("fuel")) and self.mission_on_map():
            lim = planes[m["id"]]  # what WTFTD generated first: custom vehicles keep the name of no real aircraft
        self._unbreakable = bool(lim and m.get("unbreakable"))
        self._lim = lim or planes.get(reported) or recognise(planes, state, model)
        self.current = next((vid for vid, x in planes.items() if x is self._lim), None)
        self.pick()
        print(f"Alarms: Mfuel0={key[0]}, reported={reported}, saved model={model}, limits={self._lim}", flush=True)

    def tick(self) -> float:
        """One reading of /state; returns the time until the next one."""
        wanted = self.enabled or self.log or time.monotonic() - self.viewed < VIEW_S
        state = flying(self.get("/state"), self.in_mission) if wanted else None
        vehicle = driving(self.get("/indicators")) if wanted and state is None else None
        self.flying = state is not None or vehicle is not None
        self.follow_battle()
        if vehicle:
            return self.drive(vehicle)
        if state is None:
            self._real = None
            if not self.trial:
                self.glow = self.ringing = None
            self.display = self.trial_frame() if self.trial else self.sample(self.preview) if self.preview else []
            self.hud = self.sample_hud(self.preview, self.preview_key, self.hud_place) if self.preview else []
            self.hud_live, self.attitude, self.glide = None, hud.Attitude(), hud.Glide()
            self.map_live, self.map = None, self.blank_map()
            self.warn = False
            self.last = {}
            self._key = None  # the next spawn may be another aircraft, or the same one elsewhere
            self.trend, self.wep, self.broken, self._since = Trend(), Wep(), set(), {}
            self.current, self.forced = None, None
            self.pick()
            self.crash, self._before, self._log_id = False, None, None  # a game started again numbers its log from 1
            return self.shown_cfg()["pollMs"] / 1000 if self.trial else IDLE_S
        self.crash = crashed(self._before, state) or (self.crash and not any(_engines(state)[0]))
        self._before = state
        self.read_log()
        wreck = self.crash or time.monotonic() < self._silent
        indicators = read_indicators(self.get("/indicators"))  # every time: it may only start answering mid-flight
        reported = reported_type(indicators)
        self.aircraft(state, reported)
        cfg, lim = self.preview or self.cfg, self._lim
        self.trend.add(time.monotonic(), state)
        self.wep.add(time.monotonic(), state, lim)
        values = {**indicators, **state, **computed(lim, state, self.words, self.trend.rates(), cfg["pctAlways"]), **self.wep.left(lim), "rec": 1 if self.log else 0,
                  "vehicle": self.vehicle(self.current or reported), **self.own_numbers()}
        self.last = numbers(values)
        self.record(values)
        self.glide.add(time.monotonic(), self.attitude.fill(time.monotonic(), self.last))
        fast = time.monotonic() - self.hud_viewed < VIEW_S  # the cockpit window's HUD is open
        if not self.enabled:
            self.display = self.sample(self.preview) if self.preview else []
            self.hud = self.sample_hud(self.preview, self.preview_key, self.hud_place) if self.preview else []
            self.hud_live = self.map_live = None
            self.warn, self.ringing = False, None
            return min(cfg["pollMs"] / 1000, HUD_POLL_S) if fast else cfg["pollMs"] / 1000
        pct = {k: v for k, v in percents(lim, state).items() if k not in self.broken} if lim and not self._unbreakable and not wreck else {}
        self.broken |= {k for k in ("gear", "flaps") if pct.get(k, 0) >= 100}  # past its breaking speed: torn off
        on = self.held(cfg, [] if wreck else own_alerts(cfg, values, pct), "beep")
        red = self.held(cfg, [] if wreck else own_alerts(cfg, values, pct, red=True), "red")  # their lines red
        self._real = (state, lim, values) if lim else None
        # My overlay's Try in flight: its alarm, unless one of the flight's is on. Decided first: the window, drawing
        # every 16 ms, would catch the flight's overlay and glow between two of the trial's (text and glow flickering)
        trying = bool(self.trial) and not (on or red)
        self.on = [sound_of(cfg, x)["limit"] for x in on]  # the HUD lights its speed with these
        if not trying:
            self.warn, self.glow = bool(red or on), glow_of(cfg, red + [x for x in on if x not in red])
        note = self.words["unknown"] if not lim else self.words["unbreakable"] if self._unbreakable else None
        tint = cfg["alert"] if not lim else cfg["color"]
        status = [(note, tint, cfg["size"], False, 0, [(note, tint, False)])] if note else []
        hidden = (wreck and cfg["hideCrash"]) or (not lim and cfg["hideUnknown"])
        self.read_feeds(cfg)
        if trying:
            self.display = self.trial_frame(self._real)  # its lines, its glow, its beeps
        elif self.sheet and lim:
            rows = sheet(lim, state, self.words, self.vehicle(self.current))
            self.display = [(x, cfg["color"], cfg["size"], False, 0, [(x, cfg["color"], False)]) for x in rows]
        else:
            self.display = [] if hidden else status + lines_for(cfg, values, red, self.feeds)
        jet = bool(lim.get("jet")) if lim else None
        shown = not (hidden or wreck) and hud.wanted(cfg["hudMode"], self.kind(self.current), jet)
        self.hud, self.hud_live = [], (cfg, self.nation(self.current)) if shown else None
        self.map_live = cfg if cfg["mapMode"] == "on" and not hidden else None
        if self.map_live:
            self.read_map()
        rpm = _engines(state)[0]
        silent = self.muted or (cfg["soundFocus"] and not game_focused()) or (cfg["soundEngine"] and rpm and not any(rpm))
        if not trying:
            self.ring(cfg, [] if silent else on, pct, values)
        return min(cfg["pollMs"] / 1000, HUD_POLL_S) if self.hud_live or fast else cfg["pollMs"] / 1000

    def ring(self, cfg: dict, on: list, pct: dict, values: dict):
        """The alarms on beep together, as often as the one nearest its break asks: a dynamic alarm goes from spaced beeps
        at its threshold to one continuous sound at its break (its beeps then last two readings, so that they touch).
        Tells the bell, which beeps between readings too: at a reading's pace a gap would be rounded up to the next one."""
        close = [(name, closeness(cfg, name, pct, values)) for name in on]
        if not close:
            self.ringing = None
            return
        sounds, played, waits, lasts = [], set(), [], []  # the same alarm on two lines (IAS and Mach) beeps once
        for name, c in close:
            sound = sound_of(cfg, name)
            ms = sound_ms(sound, self.sounds)
            waits.append(pace(cfg, name, c, ms))
            sound = {**sound, "ms": max(sound["ms"], cfg["pollMs"] * 2)} if c == 1 else sound
            lasts.append(max(ms, sound["ms"]) / 1000)
            if (sound["sound"], sound["hz"], sound["ms"]) not in played:
                played.add((sound["sound"], sound["hz"], sound["ms"]))
                sounds.append(sound)
        fresh = max(RING_S, 2 * cfg["pollMs"] / 1000)
        self.ringing = (time.monotonic() + fresh, min(waits), sounds, cfg["volume"], max(lasts))
        self.chime()

    def chime(self) -> float | None:
        """Plays what rings if its time has come. Returns the seconds until it next does, None if nothing rings."""
        with self._bell:
            r, now = self.ringing, time.monotonic()
            if not r or now > r[0]:
                return None
            left = self._last_beep + r[1] - now
            if left > 0:
                return left
            self._last_beep = now
            for sound in r[2]:
                play(sound, r[3], self.sounds)
            return r[1]

    def lit(self, beat=True) -> bool:
        """Whether what flashes on this clock is lit now. True: from each beep, as long as it sounds and half the beat at
        least, while alarms ring (so it closes in with them, and stays lit when they're continuous), else at FLASH_MS (an
        alarm only red, or muted); a number: that cycle, ms."""
        r, now = self.ringing, time.monotonic()
        if beat is True and r and now <= r[0]:  # from each beep, half the beat at least: the alarm's look stays the main one
            return now - self._last_beep < max(r[4], r[1] / 2)
        return int(now * 2000 / (FLASH_MS if beat is True else beat)) % 2 == 0

    def bell(self):
        """The beeps between two readings, each on its time."""
        while not self.stopping.is_set():
            left = self.chime()
            time.sleep(min(left, 0.05) if left else 0.05)

    def drive(self, values: dict) -> float:
        """A tank or a ship: curves, logs and its overlay ("type:tank", "type:ship": an aircraft's lines mean nothing there);
        no limits, so only the lines' own alerts."""
        values = {**values, **self.own_numbers(), "vehicle": self.vehicle(reported_type(values))}
        self.current, self.profile = None, f"type:{values['army']}" if f"type:{values['army']}" in self.profiles else ""
        self.hud, self.hud_live, self.map_live = [], None, None  # an aircraft's: not on a tank or a ship
        self._flight = str(values.get("type") or "vehicle").rsplit("/", 1)[-1]
        self.last = numbers(values)
        self.record(values)
        cfg = self.preview or self.profiles.get(self.profile)
        on = self.held(cfg, own_alerts(cfg, values), "beep") if cfg and self.enabled else []
        red = self.held(cfg, own_alerts(cfg, values, red=True), "red") if cfg and self.enabled else []
        self.warn, self.glow = bool(red or on), glow_of(cfg, red + [x for x in on if x not in red]) if cfg else None
        if cfg and self.enabled:
            self.read_feeds(cfg)
        if self.preview or not self.enabled:
            self.display = self.sample(self.preview) if self.preview else []
        else:
            self.display = lines_for(cfg, values, red, self.feeds) if cfg else []
        if cfg:
            self.cfg = cfg
        self.ring(self.cfg, [] if self.muted else on, {}, values)
        return self.cfg["pollMs"] / 1000

    def run(self):
        threading.Thread(target=self.bell, daemon=True).start()
        while True:
            try:
                wait = self.tick()
            except Exception:  # never let the alarms thread die
                wait = IDLE_S
            self._wake.wait(wait)
            self._wake.clear()

    def stop(self):
        self.set_log(False)
        self.stopping.set()
        if self.overlay:
            self.overlay.join(1)


def glow_of(cfg: dict, places: list) -> tuple | None:
    """The glow to show: the last of these alarms that has one, (colour, depth %, flashes); None if none has."""
    rules = [r for r in (sound_of(cfg, x) for x in places) if r.get("glow")]
    return (rules[-1]["color"] or cfg["alert"], rules[-1]["glowSize"], rules[-1]["glowFlash"] and clock(rules[-1])) if rules else None


def first_glow(cfg: dict) -> tuple | None:
    """The glow of the overlay's first alarm that has one: painted ahead of time, shown in the preview."""
    place = next(((i, j) for i, line in enumerate(cfg["lines"]) for j, r in enumerate(line.get("rules") or []) if r.get("glow")), None)
    return glow_of(cfg, [place]) if place else None


def glow_pixels(size: tuple, color: str, reach: int = GLOW_SIZE) -> bytes:
    """A screen-sized picture for paint_glow, premultiplied BGRA: the colour at the edges, fading to nothing inside."""
    width, height = size
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    levels = [bytes((b * a // 255, g * a // 255, r * a // 255, a)) * GLOW_STEP for a in range(GLOW_ALPHA + 1)]

    def near(n: int, total: int) -> float:  # 1 at the edge, 0 from reach % of the height in
        return max(0.0, 1 - min(n, total - 1 - n) / (height * reach / 100)) ** 2

    across = [near(x, width) for x in range(0, width, GLOW_STEP)]
    rows, made = [], {}
    for y in range(0, height, GLOW_STEP):
        down = near(y, height)
        if down not in made:  # the middle of the screen is a single row
            made[down] = b"".join(levels[int(GLOW_ALPHA * (1 - (1 - x) * (1 - down)))] for x in across)[:width * 4] * GLOW_STEP
        rows.append(made[down])
    return b"".join(rows)[:width * height * 4]


def paint_glow(hwnd: int, size: tuple, pixels: bytes):
    """Gives a layered window its picture, with an opacity per pixel: Tk only has one for a whole window. The window keeps
    its own copy. shortcut: the primary screen only, use the game window's monitor if someone plays on another one."""
    import ctypes
    from ctypes import wintypes as w

    class Blend(ctypes.Structure):
        _fields_ = [("op", ctypes.c_ubyte), ("flags", ctypes.c_ubyte), ("constant", ctypes.c_ubyte), ("format", ctypes.c_ubyte)]

    class Header(ctypes.Structure):  # BITMAPINFOHEADER
        _fields_ = [("size", w.DWORD), ("width", w.LONG), ("height", w.LONG), ("planes", w.WORD), ("bits", w.WORD), ("rest", w.DWORD * 6)]

    gdi, user = ctypes.WinDLL("gdi32", use_last_error=True), ctypes.WinDLL("user32", use_last_error=True)
    gdi.CreateCompatibleDC.argtypes, gdi.CreateCompatibleDC.restype = [w.HDC], w.HDC
    gdi.CreateDIBSection.argtypes = [w.HDC, ctypes.c_void_p, w.UINT, ctypes.POINTER(ctypes.c_void_p), w.HANDLE, w.DWORD]
    gdi.CreateDIBSection.restype = w.HBITMAP
    gdi.SelectObject.argtypes, gdi.SelectObject.restype = [w.HDC, w.HANDLE], w.HANDLE
    gdi.DeleteObject.argtypes, gdi.DeleteDC.argtypes = [w.HANDLE], [w.HDC]
    user.UpdateLayeredWindow.argtypes = [w.HWND, w.HDC, ctypes.POINTER(w.POINT), ctypes.POINTER(w.SIZE), w.HDC,
                                         ctypes.POINTER(w.POINT), w.COLORREF, ctypes.POINTER(Blend), w.DWORD]
    dc, bits, corner = gdi.CreateCompatibleDC(None), ctypes.c_void_p(), w.POINT(0, 0)
    picture = gdi.CreateDIBSection(dc, ctypes.byref(Header(40, size[0], size[1], 1, 32)), 0, ctypes.byref(bits), None, 0)
    done = False
    if picture:
        ctypes.memmove(bits, pixels, len(pixels))
        before = gdi.SelectObject(dc, picture)
        done = user.UpdateLayeredWindow(hwnd, None, ctypes.byref(corner), ctypes.byref(w.SIZE(*size)), dc, ctypes.byref(corner), 0,
                                        ctypes.byref(Blend(0, 0, 255, 1)), 2)  # AC_SRC_ALPHA, ULW_ALPHA
        gdi.SelectObject(dc, before)
        gdi.DeleteObject(picture)
    gdi.DeleteDC(dc)
    if not done:  # only the glow is lost: an exception here would stop the overlay
        print(f"Glow off: {ctypes.WinError(ctypes.get_last_error())}", flush=True)


def run_overlay(watch: Watch):
    """The overlay window. Runs in its own thread, with every Tk call: the main one waits for the app window."""
    try:
        import ctypes
        import tkinter as tk
        from tkinter import font as tkfont
        user32 = ctypes.windll.user32
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # real pixels
        previous = user32.GetForegroundWindow()
        root = tk.Tk()
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-transparentcolor", OVERLAY_KEY)
        root.configure(bg=OVERLAY_KEY)
        canvas = tk.Canvas(root, bg=OVERLAY_KEY, bd=0, highlightthickness=0)  # text with an outline: a Label has none
        canvas.pack()
        glow = tk.Toplevel(root)  # made now, hidden: created during an alarm, it would take the focus from the game
        glow.overrideredirect(True)
        glow.attributes("-topmost", True)
        glow.geometry("1x1+-10000+-10000")
        mapwin = tk.Toplevel(root)  # the minimap: a layered window GDI+ paints (mappaint), with an opacity of its own
        mapwin.overrideredirect(True)
        mapwin.attributes("-topmost", True)
        mapwin.geometry("1x1+-10000+-10000")
        textwin = tk.Toplevel(root)  # the text blocks: a layered window GDI+ paints too, smooth letters with a halo
        textwin.overrideredirect(True)
        textwin.attributes("-topmost", True)
        textwin.geometry("1x1+-10000+-10000")
        root.update()
        hwnd = user32.GetAncestor(root.winfo_id(), 2)  # GA_ROOT
        glow_hwnd = user32.GetAncestor(glow.winfo_id(), 2)
        map_hwnd = user32.GetAncestor(mapwin.winfo_id(), 2)
        text_hwnd = user32.GetAncestor(textwin.winfo_id(), 2)
        WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW, WS_EX_TRANSPARENT, WS_EX_LAYERED, GWL_EXSTYLE = 0x08000000, 0x80, 0x20, 0x80000, -20
        SW_HIDE, SW_SHOWNOACTIVATE = 0, 4
        click_through = WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TRANSPARENT  # clicks go through it
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, user32.GetWindowLongW(hwnd, GWL_EXSTYLE) | click_through)
        for h in (map_hwnd, text_hwnd):
            user32.SetWindowLongW(h, GWL_EXSTYLE, user32.GetWindowLongW(h, GWL_EXSTYLE) | click_through | WS_EX_LAYERED)
            paint_glow(h, (1, 1), bytes(4))  # as the glow's: a picture before it's shown
        user32.SetWindowLongW(glow_hwnd, GWL_EXSTYLE, user32.GetWindowLongW(glow_hwnd, GWL_EXSTYLE) | click_through | WS_EX_LAYERED)
        paint_glow(glow_hwnd, (1, 1), bytes(4))  # a see-through pixel: hidden before its first picture, it would refuse them all
        user32.ShowWindow(hwnd, SW_HIDE)
        user32.ShowWindow(glow_hwnd, SW_HIDE)
        user32.ShowWindow(map_hwnd, SW_HIDE)
        user32.ShowWindow(text_hwnd, SW_HIDE)
        user32.SetForegroundWindow(previous)  # creating the window took the focus
        drawn, map_drawn, text_drawn, painted, fonts, placed, painter, shown_text = None, None, None, None, {}, {}, [], [False]
        anchors = {"w": "w", "m": "center", "e": "e"}

        joy = {"now": set(), "before": set()}  # the joystick buttons held, at this refresh and the one before

        def down(k: int) -> bool:
            return k in joy["now"] if k >= JOY else bool(user32.GetAsyncKeyState(k) & 0x8000)

        def pressed(keys: list) -> bool:
            """Its last key pressed since the last look, the others held; keys, mouse buttons or joystick buttons."""
            if not keys:
                return False
            last = keys[-1]
            hit = last in joy["now"] - joy["before"] if last >= JOY else user32.GetAsyncKeyState(last) & 1
            return bool(hit and game_focused() and all(down(k) for k in keys[:-1]))

        def hud_font(size: float, text: str):
            wide = any(ord(c) > 0x2E80 for c in text)  # Chinese: Consolas has none of it
            key = "hud", round(size), wide
            if key not in fonts:
                fonts[key] = tkfont.Font(root=root, family="Microsoft YaHei" if wide else "Consolas", size=-max(6, round(size)), weight="bold")
            return fonts[key]

        def place(geometry: str, alpha: float, win=root, done: dict = placed):
            """Only when it changes: each move or resize shows the window black for a moment, and with the HUD it was every image."""
            if done.get("geometry") != geometry:
                done["geometry"] = geometry
                win.geometry(geometry)
            if done.get("alpha") != alpha:
                done["alpha"] = alpha
                win.attributes("-alpha", alpha)

        def draw_hud(cfg: dict, shapes: list, lit: bool, canvas=canvas):
            """hud.draw's shapes; an alert shows in the alert colour, flashing with the lines."""
            for s in shapes:  # the minimap's carry their colour
                tint = s[-1] if isinstance(s[-1], str) else cfg["alert"] if s[-1] and lit else cfg["hudColor"]
                if s[0] == "l":
                    canvas.create_line(*s[1:5], fill=tint, width=s[5], tags="hud")
                elif s[0] == "t":
                    canvas.create_text(s[1], s[2], text=s[3], fill=tint, font=hud_font(s[4], s[3]), anchor=anchors[s[5]], tags="hud")
                elif s[0] == "p":
                    canvas.create_polygon(*s[1], outline=tint, fill=tint if s[2] else "", width=1.6, tags="hud")
                else:
                    canvas.create_oval(s[1] - s[3], s[2] - s[3], s[1] + s[3], s[2] + s[3], outline=tint, width=1.8, tags="hud")

        def gdi():
            """The GDI+ painter of the minimap and the text, made the first time; None where GDI+ won't start."""
            if not painter:
                try:
                    painter.append(mappaint.Painter())
                except (OSError, AttributeError) as e:
                    print(f"Minimap and text off: {e}", flush=True)
                    painter.append(None)
            return painter[0]

        def draw_map(frame: dict, opacity: float):
            if gdi():
                painter[0].load(*frame["image"])
                painter[0].paint(map_hwnd, frame, opacity)

        def draw(cfg: dict, lit: bool, shapes: list):
            """The HUD, on a window as big as the screen: it moves at every image, the window mustn't."""
            canvas.delete("all")
            draw_hud(cfg, shapes, lit)
            if shapes:
                width, height = screen()
                canvas.configure(width=width, height=height)
                place(f"{width}x{height}+0+0", cfg["opacity"] / 100)
            root.update_idletasks()  # now: shown before that, a first drawing stays at (0, 0)

        def refresh():
            nonlocal drawn, map_drawn, text_drawn, painted
            if watch.stopping.is_set():
                root.destroy()
                return
            cfg, lines, shapes = watch.shown_cfg(), watch.display, watch.hud_frame()
            frame = watch.map_frame()
            lit = watch.lit()  # the HUD's alert: with the beeps
            state = cfg, shapes, lit if any(s[-1] for s in shapes) else None
            if state != drawn:
                drawn = state
                draw(cfg, lit, shapes)
            clocks = sorted({p[2] for x in lines for p in x[5] if len(p) > 2 and p[2]}, key=str)  # the flashing parts' rhythms
            words = cfg, lines, tuple(watch.lit(c) for c in clocks)
            if words != text_drawn:
                text_drawn = words
                shown_text[0] = bool(lines and gdi() and painter[0].paint_text(text_hwnd, cfg, lines, watch.lit))
            if frame and (frame, cfg["mapOpacity"]) != map_drawn:
                map_drawn = frame, cfg["mapOpacity"]
                draw_map(frame, cfg["mapOpacity"] / 100)
            keys = [k for name in ("hotkey", "logKey", "muteKey", "hudKey", "holdKey", "sheetKey", "profileKey") for k in cfg[name]]
            joy["before"], joy["now"] = joy["now"], joy_buttons({(k - JOY) // 32 for k in keys if k >= JOY})  # only those in use: winmm is slow
            if pressed(cfg["profileKey"]):
                watch.next_profile()
            watch.sheet = bool(cfg["sheetKey"]) and all(down(k) for k in cfg["sheetKey"])
            if pressed(cfg["hotkey"]):
                watch.hidden = not watch.hidden
            if pressed(cfg["logKey"]):
                watch.set_log(not watch.log)
            if pressed(cfg["muteKey"]):
                watch.muted = not watch.muted
            if pressed(cfg["hudKey"]):
                watch.hud_place = "outside" if watch.hud_place == "cockpit" else "cockpit"
            held = cfg["holdKey"] and all(down(k) for k in cfg["holdKey"])
            on_game = (cfg["show"] and not watch.hidden and not held and game_focused()) or watch.trial
            # ShowWindow rather than Tk: Tk would take the focus
            user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE if shapes and (watch.preview or on_game) else SW_HIDE)
            user32.ShowWindow(text_hwnd, SW_SHOWNOACTIVATE if shown_text[0] and (watch.preview or on_game) else SW_HIDE)
            user32.ShowWindow(map_hwnd, SW_SHOWNOACTIVATE if frame and painter and painter[0] and (watch.preview or on_game) else SW_HIDE)
            spec = watch.glow if watch.trial or not watch.preview else first_glow(cfg)
            want = spec or first_glow(cfg)  # ahead of the first alarm: painting takes a moment on a big screen
            if want and want[:2] != painted:
                painted = want[:2]
                paint_glow(glow_hwnd, screen(), glow_pixels(screen(), *painted))
            shown_glow = spec and spec[:2] == painted and (watch.preview or watch.trial or (not watch.hidden and game_focused()))
            user32.ShowWindow(glow_hwnd, SW_SHOWNOACTIVATE if shown_glow and (not spec[2] or watch.lit(spec[2])) else SW_HIDE)
            root.after(HUD_FRAME_MS if shapes or watch.ringing else MAP_FRAME_MS if frame else int(POLL_S * 1000), refresh)  # ringing: flashes on the beat

        refresh()
        root.mainloop()
        root = glow = mapwin = textwin = canvas = draw = draw_map = refresh = None
        painter.clear()
        fonts.clear()
        gc.collect()  # Tk must be freed here: left to Python's exit, in the main thread, it aborts the process
    except Exception as e:  # no Tk in this Python, no display...: the alarms still beep
        print(f"Overlay off: {e}", flush=True)
