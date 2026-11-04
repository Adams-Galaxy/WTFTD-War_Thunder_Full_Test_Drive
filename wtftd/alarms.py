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

from . import battle, flightlog, hud, minimap, sights, waveout
from .paths import WEB

ALARMS = {"airframe": (93, 1400), "gear": (90, 1000), "flaps": (90, 700)}  # default: % of the limit, beep in Hz
POLL_S = 0.1
HUD_POLL_S = 0.025  # with the HUD: the game sends a new reading about every 22 ms
HUD_FRAME_MS = 16  # and the window draws it between readings, at about 60 images a second
MAP_S = 0.25  # the minimap reads the map's objects 4 times a second
TRAIL_MAX = 600  # its trail's last places
IDLE_S = 1.0  # not flying: nothing to read fast
REPEAT_MS = 300
BEEP_MS = 150
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
            "burn": 0, "range": 0, "mass": 0, "thrust_total": 0, "twr": 2}  # see computed(): name -> decimals
SERIES = [*FIELDS, *COMPUTED]  # the numbers curves and logs follow
# their columns in a log, when the game's field name isn't one
COLUMNS = {"speed": "Speed, km/h", "heading": "Heading, deg", "g_max": "Max G", "pitch": "Pitch, deg", "bank": "Bank, deg", "vne": "Max speed, km/h",
           "mne": "Max Mach", "gear_max": "Gear max speed, km/h", "flaps_max": "Flaps max speed, km/h",
           "margin": "Speed left, km/h", "airframe_pct": "Airframe limit, %", "gear_pct": "Gear limit, %",
           "flaps_pct": "Flaps limit, %", "fuel_pct": "Fuel, %", "hspeed": "Horizontal speed, km/h", "turn": "Turn, s",
           "turn_rate": "Turn rate, deg/s", "turn_radius": "Turn radius, m", "accel": "Acceleration, m/s2", "sep": "SEP, m/s",
           "burn": "Fuel consumption, kg/min", "range": "Range, km", "mass": "Mass without weapons, kg",
           "thrust_total": "Thrust, kgf", "twr": "Thrust/weight"}
POSITION = ["East, m", "North, m", "Map heading, deg"]  # only in the logs, for the Tacview export
FIELD = re.compile(r"\{([^{}:]+)(?::(\d))?\}")
NO_VALUE = "N/A"  # what the game doesn't send, what the aircraft doesn't have

WHEN = {"always": None, "alarm": None, "gear": "gear, %", "flaps": "flaps, %", "airbrake": "airbrake, %", "log": "rec"}  # shown if on
MAX_LINES = 30
MAX_TEXT = 120
MAX_BLOCKS = 3  # text blocks besides the main one
MAX_TESTS = 4  # conditions on a line's showing or its alert
STIPPLE = {100: "", 75: "gray75", 50: "gray50", 25: "gray25"}  # a block's background: a window has only one opacity
BLOCK_PAD = 10  # between a block's text and its frame or background
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
SAMPLE_LIM = {"v": 1540, "m": 2.1, "gear": 700, "flaps": [[0.2, 1018], [1, 600]], "fuel": [9400], "eng": 2}
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
            "mapY": _num(cfg.get("mapY"), base["mapY"], -20000, 20000), "mapTrail": _flag(cfg.get("mapTrail"), base["mapTrail"])}


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
    width = max(len(w) for w in ("IAS", "MACH", words["gear"], words["flaps"])) + 2

    def line(label, text, when="always", alarm=""):
        return _line({"text": f"{label:<{width}}{text}", "when": when, "alarm": alarm})

    return {"x": round(700 * scale), "y": round(55 * scale), "font": "Consolas", "size": round(40 * scale), "bold": False,
            "italic": False, "spacing": 0, "outline": 0, "outlineColor": "#000000", "blocks": [], "valueColor": "", "unitColor": "",
            "pctAlways": False, **_look({}),
            "glowSize": GLOW_SIZE, "glowColor": "", "glowFlash": False, "flashMs": 500, "volume": 100, "soundFocus": False, "soundEngine": False,
            "pollMs": round(POLL_S * 1000), "logMs": round(SAMPLE_S * 1000), "muteKey": [], "muteKeyName": "", "holdKey": [], "holdKeyName": "",
            "color": "#E6E6E6", "alert": "#FF0000", "opacity": 100, "show": True, "hotkey": [], "hotkeyName": "",
            **HUD_DEFAULTS, "mapMode": "off", "mapZoom": 1, "mapTrail": True,  # the minimap: off until the player turns it on
            "mapSize": round(560 * scale), "mapX": round(40 * scale), "mapY": round(1100 * scale),
            "logKey": [], "logKeyName": "", "hideCrash": False, "hideUnknown": False, "glow": False, "repeat": REPEAT_MS, "alarms": {n: {"on": True, "at": at, "hz": hz, "ms": BEEP_MS, "sound": ""} for n, (at, hz) in ALARMS.items()},
            "lines": [line("IAS", "{ias} / {vne} km/h {swept}", alarm="airframe"), line("MACH", "{mach} / {mne}", alarm="airframe"),
                      line(words["gear"], "{ias} / {gear_max} km/h", "gear", "gear"),
                      line(words["flaps"], "{ias} / {flaps_max} km/h", "flaps", "flaps"),
                      _line({"text": "REC", "when": "log", "color": "#FF0000"})]}


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


def _rule(rule) -> dict | None:
    """A line's own alert: its condition and its sound."""
    test = _test(rule)
    return test and {**test, "hz": _num(rule.get("hz"), 1000, 37, 32767), "ms": _num(rule.get("ms"), BEEP_MS, 10, 2000),
                     "sound": _sound(rule.get("sound"))}


def _line(line: dict) -> dict:
    return {"text": str(line.get("text", ""))[:MAX_TEXT], "when": line.get("when") if line.get("when") in WHEN else "always",
            "alarm": line.get("alarm") if line.get("alarm") in ALARMS else "", "color": _color(line.get("color"), ""),
            "valueColor": _color(line.get("valueColor"), ""), "unitColor": _color(line.get("unitColor"), ""),
            "size": _num(line.get("size"), 0, 0, 400), "blink": _flag(line.get("blink"), False), "hideNA": _flag(line.get("hideNA"), False),
            "block": _num(line.get("block"), 0, 0, MAX_BLOCKS), "if": _test(line.get("if")), "rule": _rule(line.get("rule"))}


def _look(block: dict) -> dict:
    """What every text block has, the main one (in the overlay itself) like the others."""
    return {"scale": _num(block.get("scale"), 100, 10, 400), "columns": _num(block.get("columns"), 1, 1, 4), "frame": _num(block.get("frame"), 0, 0, 8),
            "frameColor": _color(block.get("frameColor"), "#FFFFFF"), "background": _color(block.get("background"), ""),
            "bgOpacity": block.get("bgOpacity") if block.get("bgOpacity") in STIPPLE else 50}


def _block(block: dict) -> dict:
    return {"x": _num(block.get("x"), 0, -20000, 20000), "y": _num(block.get("y"), 0, -20000, 20000), **_look(block)}


def _keys(cfg: dict, key: str, name: str) -> dict:
    keys = cfg.get(key)
    if isinstance(keys, list) and 0 < len(keys) < 5 and all(type(k) is int and 0 < k < 255 for k in keys):
        return {key: keys, name: str(cfg.get(name, ""))[:32]}
    return {key: [], name: ""}


def clean(cfg, words: dict) -> dict:
    """A complete overlay configuration from what was saved or sent by the page: what's missing or odd gets the default."""
    base = defaults(words)
    if not isinstance(cfg, dict):
        return base
    alarms = cfg.get("alarms") if isinstance(cfg.get("alarms"), dict) else {}
    out = {"x": _num(cfg.get("x"), base["x"], -20000, 20000), "y": _num(cfg.get("y"), base["y"], -20000, 20000),
           "font": cfg["font"] if isinstance(cfg.get("font"), str) and FONT.fullmatch(cfg["font"]) else base["font"],
           "size": _num(cfg.get("size"), base["size"], 6, 400), "bold": _flag(cfg.get("bold"), base["bold"]),
           "color": _color(cfg.get("color"), base["color"]), "alert": _color(cfg.get("alert"), base["alert"]),
           "opacity": _num(cfg.get("opacity"), base["opacity"], 10, 100), "show": _flag(cfg.get("show"), base["show"]),
           "hideCrash": _flag(cfg.get("hideCrash"), base["hideCrash"]), "hideUnknown": _flag(cfg.get("hideUnknown"), base["hideUnknown"]),
           "glow": _flag(cfg.get("glow"), base["glow"]),
           "valueColor": _color(cfg.get("valueColor"), ""), "unitColor": _color(cfg.get("unitColor"), ""), **_look(cfg),
           "pctAlways": _flag(cfg.get("pctAlways"), base["pctAlways"]),
           "italic": _flag(cfg.get("italic"), base["italic"]), "spacing": _num(cfg.get("spacing"), base["spacing"], -50, 200),
           "outline": _num(cfg.get("outline"), base["outline"], 0, 4), "outlineColor": _color(cfg.get("outlineColor"), base["outlineColor"]),
           "glowSize": _num(cfg.get("glowSize"), base["glowSize"], 3, 50), "glowColor": _color(cfg.get("glowColor"), ""), "glowFlash": _flag(cfg.get("glowFlash"), base["glowFlash"]),
           "flashMs": _num(cfg.get("flashMs"), base["flashMs"], 200, 4000), "volume": _num(cfg.get("volume"), base["volume"], 0, 100),
           "soundFocus": _flag(cfg.get("soundFocus"), base["soundFocus"]), "soundEngine": _flag(cfg.get("soundEngine"), base["soundEngine"]),
           "pollMs": _num(cfg.get("pollMs"), base["pollMs"], 50, 1000), "logMs": _num(cfg.get("logMs"), base["logMs"], 100, 10000),
           "repeat": _num(cfg.get("repeat"), base["repeat"], 100, 10000), "alarms": {},
           **_keys(cfg, "hotkey", "hotkeyName"), **_keys(cfg, "logKey", "logKeyName"), **_keys(cfg, "muteKey", "muteKeyName"),
           **_keys(cfg, "holdKey", "holdKeyName"), **_hud(cfg), **_map(cfg, base)}
    for name, std in base["alarms"].items():
        a = alarms.get(name) if isinstance(alarms.get(name), dict) else {}
        out["alarms"][name] = {"on": _flag(a.get("on"), std["on"]), "at": _num(a.get("at"), std["at"], 1, 200),
                               "hz": _num(a.get("hz"), std["hz"], 37, 32767), "ms": _num(a.get("ms"), std["ms"], 10, 2000),
                               "sound": _sound(a.get("sound"))}
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


def percents(lim: dict, state: dict, always: bool = False) -> dict:
    """{alarm: % of its limit}: the airframe always, gear and flaps only when they are out, unless always."""
    ias = state.get("IAS, km/h") or 0
    out = {"airframe": max(ias / lim["v"], (state.get("M") or 0) / lim["m"] if lim["m"] else 0) * 100}
    if ((state.get("gear, %") or 0) > 0 or always) and lim.get("gear"):
        out["gear"] = ias / lim["gear"] * 100
    flaps = state.get("flaps, %") or 0
    if (flaps > 0 or always) and lim.get("flaps"):
        out["flaps"] = ias / flaps_limit(lim["flaps"], flaps / 100) * 100
    return out


def active(values: dict, alarms: dict) -> list:
    return [name for name, value in values.items() if alarms[name]["on"] and value >= alarms[name]["at"]]


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
    return out


def _meets(test: dict, values: dict) -> bool:
    v = values.get(FIELDS.get(test["value"], (test["value"],))[0])
    return isinstance(v, (int, float)) and not isinstance(v, bool) and OPS[test["op"]](v, test["at"])


def met(test: dict, values: dict) -> bool:
    results = [_meets(x, values) for x in (test, *test.get("more", []))]
    return any(results) if test.get("join") == "or" else all(results)


def own_alerts(cfg: dict, values: dict) -> list:
    """The lines whose own alert is on, by their place in the list."""
    return [i for i, line in enumerate(cfg["lines"]) if line.get("rule") and met(line["rule"], values)]


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


def shown(line: dict, values: dict, on: list) -> bool:
    if line.get("if") and not met(line["if"], values):
        return False
    if line["when"] == "alarm":
        return bool(on)
    return line["when"] == "always" or (values.get(WHEN[line["when"]]) or 0) > 0


def lines_for(cfg: dict, values: dict, on: list) -> list:
    """[(text, colour, size, blinks, block, parts), ...] of the overlay; parts: [(text, colour), ...]. on: alarms by name, a
    line's own alert by its place: the whole line goes to the alert colour with the alarm it follows or its own."""
    out = []
    for i, line in enumerate(cfg["lines"]):
        text = fill(line["text"], values)
        if not shown(line, values, on) or (line.get("hideNA") and NO_VALUE in text):
            continue
        alert, block = line["alarm"] in on or i in on, line.get("block", 0)
        color = cfg["alert"] if alert else line["color"] or cfg["color"]
        tints = {"name": color, "value": color if alert else line.get("valueColor") or cfg["valueColor"] or color,
                 "unit": color if alert else line.get("unitColor") or cfg["unitColor"] or color}
        parts = []
        for piece, kind in pieces(line["text"], values):
            if parts and parts[-1][1] == tints[kind]:
                parts[-1] = (parts[-1][0] + piece, tints[kind])
            else:
                parts.append((piece, tints[kind]))
        out.append((text, color, round((line["size"] or cfg["size"]) * [cfg, *cfg["blocks"]][block]["scale"] / 100),
                    bool(alert and line.get("blink")), block, parts))
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
    """/state while in the air, else None. In the hangar it is valid too, without fuel, and the aircraft on show flickers
    between 0 and 1 km/h: with empty tanks, only a loaded map tells a real flight."""
    state = answer(raw)
    if "Mfuel0, kg" not in state or not state.get("IAS, km/h"):
        return None
    return None if state.get("Mfuel, kg") == 0 and not in_mission() else state


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
        self.warn = False  # an alarm is on: the glow around the screen
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
        self.profile = next((k for k in wanted if k in self.profiles), "")
        self.cfg = self.profiles.get(self.profile, self.base)

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
        values = {**SAMPLE_STATE, **SAMPLE_STATS, "vehicle": self.vehicle(SAMPLE_VEHICLE), **computed(SAMPLE_LIM, SAMPLE_STATE, self.words, {"burn": 95, "accel": 1.2}, cfg["pctAlways"])}
        return lines_for(cfg, values, active(percents(SAMPLE_LIM, SAMPLE_STATE), cfg["alarms"]) + own_alerts(cfg, values))

    def sample_hud(self, cfg: dict, key: str = "", place: str = "cockpit", screen_size: tuple | None = None) -> list:
        """The HUD with the sample values; key: the overlay's aircraft id, if it has one, for its nation's style."""
        if cfg["hudMode"] == "off":
            return []
        values = {**SAMPLE_STATE, **SAMPLE_ATTITUDE, **computed(SAMPLE_LIM, SAMPLE_STATE, self.words, {"burn": 95})}
        nation = self.nation(key) if key and not key.startswith("type:") else None
        on = active(percents(SAMPLE_LIM, SAMPLE_STATE), cfg["alarms"])
        return hud.draw(numbers(values), cfg, nation, screen_size or screen(), place, on)

    @staticmethod
    def blank_map() -> dict:
        return {"t": 0.0, "gen": None, "image": None, "info": {}, "seen": {"me": None, "fixed": []}, "trail": deque(maxlen=TRAIL_MAX)}

    def read_map(self):
        """The minimap's reading, 4 times a second: minimap.keep drops every unit but yours as soon as it's read."""
        m, now = self.map, time.monotonic()
        if now - m["t"] < MAP_S:
            return
        m["t"] = now
        info = answer(self.get("/map_info.json"))
        if info.get("map_generation") != m["gen"]:  # another map: its picture, and a new trail
            img = self.get(f"/map.img?gen={info.get('map_generation', 0)}") if info else None
            m.update(gen=info.get("map_generation"), image=img if minimap.png_size(img) else None, trail=deque(maxlen=TRAIL_MAX))
        try:
            objects = json.loads(self.get("/map_obj.json")) if info else []
        except (TypeError, ValueError):
            objects = []
        m["info"], m["seen"] = info, minimap.keep(objects)
        me = m["seen"]["me"]
        if me and (not m["trail"] or math.dist(m["trail"][-1], (me["x"], me["y"])) > 0.002):
            m["trail"].append((me["x"], me["y"]))

    def sample_map(self, cfg: dict) -> list:
        return [] if cfg["mapMode"] == "off" else minimap.draw(minimap.SAMPLE, minimap.SAMPLE_INFO, minimap.SAMPLE_TRAIL, cfg, None)[0]

    def map_frame(self) -> tuple:
        """The minimap to draw now: (shapes, picture), picture {data, gen, box, n, at} or None; the sample in the preview."""
        cfg, m = self.map_live, self.map
        if not cfg:
            return (self.sample_map(self.preview), None) if self.preview else ([], None)
        shapes, image = minimap.draw(m["seen"], m["info"], list(m["trail"]), cfg, minimap.png_size(m["image"]))
        if image:
            image.update(data=m["image"], gen=m["gen"])
        return shapes, image

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
            self.display = self.sample(self.preview) if self.preview else []
            self.hud = self.sample_hud(self.preview, self.preview_key, self.hud_place) if self.preview else []
            self.hud_live, self.attitude, self.glide = None, hud.Attitude(), hud.Glide()
            self.map_live, self.map = None, self.blank_map()
            self.warn = False
            self.last = {}
            self._key = None  # the next spawn may be another aircraft, or the same one elsewhere
            self.trend = Trend()
            self.current = None
            self.pick()
            self.crash, self._before, self._log_id = False, None, None  # a game started again numbers its log from 1
            return IDLE_S
        self.crash = crashed(self._before, state) or (self.crash and not any(_engines(state)[0]))
        self._before = state
        self.read_log()
        wreck = self.crash or time.monotonic() < self._silent
        indicators = read_indicators(self.get("/indicators"))  # every time: it may only start answering mid-flight
        reported = reported_type(indicators)
        self.aircraft(state, reported)
        cfg, lim = self.preview or self.cfg, self._lim
        self.trend.add(time.monotonic(), state)
        values = {**indicators, **state, **computed(lim, state, self.words, self.trend.rates(), cfg["pctAlways"]), "rec": 1 if self.log else 0,
                  "vehicle": self.vehicle(self.current or reported), **self.own_numbers()}
        self.last = numbers(values)
        self.record(values)
        self.glide.add(time.monotonic(), self.attitude.fill(time.monotonic(), self.last))
        fast = time.monotonic() - self.hud_viewed < VIEW_S  # the cockpit window's HUD is open
        if not self.enabled:
            self.display = self.sample(self.preview) if self.preview else []
            self.hud = self.sample_hud(self.preview, self.preview_key, self.hud_place) if self.preview else []
            self.hud_live = self.map_live = None
            self.warn = False
            return min(cfg["pollMs"] / 1000, HUD_POLL_S) if fast else cfg["pollMs"] / 1000
        on = active(percents(lim, state), cfg["alarms"]) if lim and not self._unbreakable and not wreck else []
        on += [] if wreck else own_alerts(cfg, values)
        self.warn, self.on = bool(on), on
        note = self.words["unknown"] if not lim else self.words["unbreakable"] if self._unbreakable else None
        tint = cfg["alert"] if not lim else cfg["color"]
        status = [(note, tint, cfg["size"], False, 0, [(note, tint)])] if note else []
        hidden = (wreck and cfg["hideCrash"]) or (not lim and cfg["hideUnknown"])
        self.display = [] if hidden else status + lines_for(cfg, values, on)
        jet = bool(lim.get("jet")) if lim else None
        shown = not (hidden or wreck) and hud.wanted(cfg["hudMode"], self.kind(self.current), jet)
        self.hud, self.hud_live = [], (cfg, self.nation(self.current)) if shown else None
        self.map_live = cfg if cfg["mapMode"] == "on" and not hidden else None
        if self.map_live:
            self.read_map()
        rpm = _engines(state)[0]
        silent = self.muted or (cfg["soundFocus"] and not game_focused()) or (cfg["soundEngine"] and rpm and not any(rpm))
        if on and not silent and time.monotonic() - self._last_beep >= cfg["repeat"] / 1000:
            self._last_beep = time.monotonic()
            for name in on:
                play(cfg["lines"][name]["rule"] if isinstance(name, int) else cfg["alarms"][name], cfg["volume"], self.sounds)
        return min(cfg["pollMs"] / 1000, HUD_POLL_S) if self.hud_live or fast else cfg["pollMs"] / 1000

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
        on = own_alerts(cfg, values) if cfg and self.enabled else []
        self.warn = bool(on)
        if self.preview or not self.enabled:
            self.display = self.sample(self.preview) if self.preview else []
        else:
            self.display = lines_for(cfg, values, on) if cfg else []
        if cfg:
            self.cfg = cfg
        if on and not self.muted and time.monotonic() - self._last_beep >= self.cfg["repeat"] / 1000:
            self._last_beep = time.monotonic()
            for i in on:
                play(self.cfg["lines"][i]["rule"], self.cfg["volume"], self.sounds)
        return self.cfg["pollMs"] / 1000

    def run(self):
        while True:
            try:
                wait = self.tick()
            except Exception:  # never let the alarms thread die
                wait = IDLE_S
            time.sleep(wait)

    def stop(self):
        self.set_log(False)
        self.stopping.set()
        if self.overlay:
            self.overlay.join(1)


def glow_color(cfg: dict) -> str:
    return cfg["glowColor"] or cfg["alert"]


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
        root.update()
        hwnd = user32.GetAncestor(root.winfo_id(), 2)  # GA_ROOT
        glow_hwnd = user32.GetAncestor(glow.winfo_id(), 2)
        WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW, WS_EX_TRANSPARENT, WS_EX_LAYERED, GWL_EXSTYLE = 0x08000000, 0x80, 0x20, 0x80000, -20
        SW_HIDE, SW_SHOWNOACTIVATE = 0, 4
        click_through = WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TRANSPARENT  # clicks go through it
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, user32.GetWindowLongW(hwnd, GWL_EXSTYLE) | click_through)
        user32.SetWindowLongW(glow_hwnd, GWL_EXSTYLE, user32.GetWindowLongW(glow_hwnd, GWL_EXSTYLE) | click_through | WS_EX_LAYERED)
        paint_glow(glow_hwnd, (1, 1), bytes(4))  # a see-through pixel: hidden before its first picture, it would refuse them all
        user32.ShowWindow(hwnd, SW_HIDE)
        user32.ShowWindow(glow_hwnd, SW_HIDE)
        user32.SetForegroundWindow(previous)  # creating the window took the focus
        drawn, painted, fonts, placed, photos = None, None, {}, {}, {}
        anchors = {"w": "w", "m": "center", "e": "e"}

        def pressed(keys: list) -> bool:
            return bool(keys and user32.GetAsyncKeyState(keys[-1]) & 1 and game_focused()
                        and all(user32.GetAsyncKeyState(k) & 0x8000 for k in keys[:-1]))

        def font_for(cfg: dict, size: int):
            key = cfg["font"], size, cfg["bold"], cfg["italic"]
            if key not in fonts:
                fonts[key] = tkfont.Font(root=root, family=cfg["font"], size=-size, weight="bold" if cfg["bold"] else "normal",
                                         slant="italic" if cfg["italic"] else "roman")
            return fonts[key]

        def hud_font(size: float, text: str):
            wide = any(ord(c) > 0x2E80 for c in text)  # Chinese: Consolas has none of it
            key = "hud", round(size), wide
            if key not in fonts:
                fonts[key] = tkfont.Font(root=root, family="Microsoft YaHei" if wide else "Consolas", size=-max(6, round(size)), weight="bold")
            return fonts[key]

        def place(geometry: str, alpha: float):
            """Only when it changes: each move or resize shows the window black for a moment, and with the HUD it was every image."""
            if placed.get("geometry") != geometry:
                placed["geometry"] = geometry
                root.geometry(geometry)
            if placed.get("alpha") != alpha:
                placed["alpha"] = alpha
                root.attributes("-alpha", alpha)

        def draw_hud(cfg: dict, shapes: list, lit: bool):
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

        def map_photo(image: dict):
            """The part of /map.img the minimap shows, shrunk or grown by Tk: made again only when it changes."""
            if photos.get("gen") != image["gen"] or photos.get("data") is not image["data"]:
                photos.clear()
                photos.update(gen=image["gen"], data=image["data"])
                try:
                    photos["src"] = tk.PhotoImage(master=root, data=base64.b64encode(image["data"]))
                except tk.TclError:
                    photos["src"] = None
            if not photos["src"]:
                return None
            key = tuple(image["box"]), image["n"]
            if photos.get("key") != key:
                shown, n = tk.PhotoImage(master=root), image["n"]
                shown.tk.call(shown, "copy", photos["src"], "-from", *image["box"], *(("-subsample", n, n) if n > 0 else ("-zoom", -n, -n)))
                photos.update(key=key, shown=shown)
            return photos["shown"]

        def draw(cfg: dict, lines: list, lit: bool, shapes: list = (), image: dict | None = None):
            """Each block's lines in their columns, its frame and background behind them, then the window around all of it.
            lit: the blinking lines' turn to show."""
            canvas.delete("all")
            ring = [(dx * r, dy * r) for r in range(1, cfg["outline"] + 1) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]
            dark = []
            photo = map_photo(image) if image else None
            if photo:
                canvas.create_image(*image["at"], image=photo, anchor="nw", tags="map")
            draw_hud(cfg, shapes, lit)
            for index, spot in enumerate([cfg, *cfg["blocks"]]):
                rows, left, tag = [x for x in lines if x[4] == index], spot["x"], f"block{index}"
                for column in columns_of(rows, spot["columns"]):
                    y, wide = spot["y"], 0
                    for _, color, size, blinks, _, parts in column:
                        font, x, items = font_for(cfg, size), left, []
                        for part, tint in parts or [(" ", color)]:
                            edge = [canvas.create_text(x + dx, y + dy, text=part, fill=cfg["outlineColor"], font=font, anchor="nw", tags=tag) for dx, dy in ring]
                            item = canvas.create_text(x, y, text=part, fill=tint, font=font, anchor="nw", tags=tag)
                            items += [item, *edge]
                            x += font.measure(part)
                        for item in items[::len(ring) + 1]:  # over the outlines of the parts next to it
                            canvas.tag_raise(item)
                        dark += items if blinks and not lit else []
                        y += font.metrics("linespace") + cfg["spacing"]
                        wide = max(wide, x - left)
                    left += wide + cfg["size"]
                box = canvas.bbox(tag)
                if box and (spot["frame"] or spot["background"]):
                    pad = BLOCK_PAD + spot["frame"]
                    canvas.tag_lower(canvas.create_rectangle(box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad, fill=spot["background"], width=spot["frame"],
                                                             outline=spot["frameColor"] if spot["frame"] else "", tags=tag,
                                                             stipple=STIPPLE[spot["bgOpacity"]] if spot["background"] else ""))
            box = canvas.bbox("all")  # before hiding the dark lines: a blink mustn't move the window
            if shapes:  # the whole screen: the HUD moves at every image, the window mustn't
                width, height = screen()
                canvas.configure(width=width, height=height)
                place(f"{width}x{height}+0+0", cfg["opacity"] / 100)
            elif box:
                canvas.move("all", -box[0], -box[1])
                canvas.configure(width=box[2] - box[0], height=box[3] - box[1])
                place(f"{box[2] - box[0]}x{box[3] - box[1]}+{box[0]}+{box[1]}", cfg["opacity"] / 100)
            for item in dark:
                canvas.itemconfigure(item, state="hidden")
            root.update_idletasks()  # now: shown before that, a first drawing stays at (0, 0)

        def refresh():
            nonlocal drawn, painted
            if watch.stopping.is_set():
                root.destroy()
                return
            cfg, lines, hud_shapes = watch.preview or watch.cfg, watch.display, watch.hud_frame()
            map_shapes, image = watch.map_frame()
            shapes = hud_shapes + map_shapes
            lit = int(time.monotonic() * 2000 / cfg["flashMs"]) % 2 == 0
            state = cfg, lines, shapes, image and image["box"], lit if any(x[3] for x in lines) or any(isinstance(s[-1], int) and s[-1] for s in shapes) else None
            if state != drawn:
                drawn = state
                draw(cfg, lines, lit, shapes, image)
            if pressed(cfg["hotkey"]):
                watch.hidden = not watch.hidden
            if pressed(cfg["logKey"]):
                watch.set_log(not watch.log)
            if pressed(cfg["muteKey"]):
                watch.muted = not watch.muted
            if pressed(cfg["hudKey"]):
                watch.hud_place = "outside" if watch.hud_place == "cockpit" else "cockpit"
            held = cfg["holdKey"] and all(user32.GetAsyncKeyState(k) & 0x8000 for k in cfg["holdKey"])
            on_game = cfg["show"] and not watch.hidden and not held and game_focused()
            # ShowWindow rather than Tk: Tk would take the focus
            user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE if (lines or shapes) and (watch.preview or on_game) else SW_HIDE)
            if cfg["glow"] and (glow_color(cfg), cfg["glowSize"]) != painted:  # ahead of the first alarm: it takes a moment on a big screen
                painted = glow_color(cfg), cfg["glowSize"]
                paint_glow(glow_hwnd, screen(), glow_pixels(screen(), *painted))
            warn = watch.preview or (watch.warn and not watch.hidden and game_focused())
            user32.ShowWindow(glow_hwnd, SW_SHOWNOACTIVATE if cfg["glow"] and warn and (lit or not cfg["glowFlash"]) else SW_HIDE)
            root.after(HUD_FRAME_MS if hud_shapes else int(POLL_S * 1000), refresh)

        refresh()
        root.mainloop()
        root = glow = canvas = draw = refresh = font_for = None
        fonts.clear()
        gc.collect()  # Tk must be freed here: left to Python's exit, in the main thread, it aborts the process
    except Exception as e:  # no Tk in this Python, no display...: the alarms still beep
        print(f"Overlay off: {e}", flush=True)
