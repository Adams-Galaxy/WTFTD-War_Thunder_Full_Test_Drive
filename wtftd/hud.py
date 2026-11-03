"""The fighter HUD: the aircraft flown drawn the way a real HUD shows it, in the style of a family of real HUDs (NATO,
Russian, Chinese). Only the player's own aircraft: what /state and /indicators say of it, nothing about anybody else.

draw() returns shapes that both windows draw, the overlay (Tk, over the game) and the cockpit window (SVG):
  ["l", x1, y1, x2, y2, width, alert]          a line
  ["t", x, y, text, size, anchor, alert]       text, y its middle, anchor "w", "m" or "e"
  ["p", [x, y, x, y, ...], filled, alert]      a polygon
  ["c", x, y, r, alert]                        a circle
in screen pixels; alert 1 = in the alert colour.

The game's signs, checked on a recorded flight (2026-11-03): pitch > 0 nose up, bank > 0 left wing down."""
from __future__ import annotations

import math

STYLES = ("nato", "russian", "chinese")
NATIONS = {"ussr": "russian", "china": "chinese"}  # every other nation flies the NATO style
PARTS = ("heading", "ladder", "fpm", "speed", "alt", "data")
PLACES = ("cockpit", "outside")
KT, FT = 1.852, 0.3048  # km/h in a knot, metres in a foot
HEIGHT = 700  # HUD units the screen height holds at 100 %
WINDOW = (700, 480)  # HUD units a window of its own holds: all of the HUD, nearly edge to edge
DEG = 9  # HUD units a degree of pitch. shortcut: not conformal, the overlay can't know the game's camera
SPEED_ALERTS = ("airframe", "gear", "flaps")  # alarms that light the speed


def style_of(style: str, nation: str | None) -> str:
    return style if style in STYLES else NATIONS.get(nation or "", "nato")


def wanted(mode: str, kind: str | None, jet: bool | None) -> bool:
    """auto: jets and helicopters, and an aircraft not recognised (jet None); off on propeller aircraft."""
    if mode in ("on", "off"):
        return mode == "on"
    return kind == "helicopter" or jet is not False


class Pen:
    """Shapes in HUD units around the HUD's centre, written out in screen pixels; turned: the pitch ladder's bank."""

    def __init__(self, cx: float, cy: float, k: float):
        self.cx, self.cy, self.k, self.out, self.turn = cx, cy, k, [], 0.0
        self.parts = set(PARTS)  # what the player shows

    def xy(self, x: float, y: float) -> list:
        if self.turn:
            c, s = math.cos(self.turn), math.sin(self.turn)
            x, y = x * c - y * s, x * s + y * c
        return [round(self.cx + x * self.k, 1), round(self.cy + y * self.k, 1)]

    def line(self, x1, y1, x2, y2, w=1.6, a=0):
        self.out.append(["l", *self.xy(x1, y1), *self.xy(x2, y2), round(max(1.0, w * self.k), 1), a])

    def dashed(self, x1, y1, x2, y2, w=1.5, on=6, off=4):
        """Dashes cut here: Tk on Windows draws no dash on a wide line."""
        length = math.hypot(x2 - x1, y2 - y1)
        d = 0.0
        while d < length:
            e = min(d + on, length)
            self.line(x1 + (x2 - x1) * d / length, y1 + (y2 - y1) * d / length, x1 + (x2 - x1) * e / length, y1 + (y2 - y1) * e / length, w)
            d = e + off

    def text(self, x, y, s, size=13, anchor="m", a=0):
        self.out.append(["t", *self.xy(x, y), str(s), round(size * self.k, 1), anchor, a])

    def poly(self, pts, filled=0, a=0):
        self.out.append(["p", [c for i in range(0, len(pts), 2) for c in self.xy(pts[i], pts[i + 1])], filled, a])

    def circle(self, x, y, r, a=0):
        self.out.append(["c", *self.xy(x, y), round(r * self.k, 1), a])


def heading(pen: Pen, y: float, hdg: float, label, below: bool, span: float = 130):
    """A heading tape: ticks every 5°, a label every 10°, the caret on the heading. below: labels under the ticks."""
    sign = -1 if below else 1
    for d in range(math.floor(hdg / 5) * 5 - 25, math.ceil(hdg / 5) * 5 + 30, 5):
        x = (d - hdg) * span / 25
        if abs(x) > span:
            continue
        pen.line(x, y, x, y + sign * (10 if d % 10 == 0 else 6), 1.4)
        if d % 10 == 0:
            pen.text(x, y - sign * 10 if not below else y + 16, label(d % 360), 12)
    tip = y + sign * 14
    pen.poly([-7, tip + sign * 9, 0, tip, 7, tip + sign * 9])


def tape(pen: Pen, x: float, value: float, step: int, label: int, span: float, side: int, half: float = 110):
    """A vertical scale centred on the value; side -1: ticks to the right of its line, labels to the left (speed)."""
    pen.line(x, -half, x, half, 1.4)
    for v in range(math.floor((value - span) / step) * step + step, math.ceil(value + span), step):
        y = -(v - value) * half / span
        pen.line(x, y, x - side * (12 if v % label == 0 else 6), y, 1.4)
        if v % label == 0 and abs(v - value) > span / 6:
            pen.text(x + side * 8, y, v, 11, "w" if side > 0 else "e")


def box(pen: Pen, x: float, y: float, w: float, s, size=15, point=0, a=0):
    """A boxed value; point 1: a tip on its right, -1 on its left."""
    h = size * 1.5
    if point == 1:
        pts = [x, y - h / 2, x + w, y - h / 2, x + w + 10, y, x + w, y + h / 2, x, y + h / 2]
    elif point == -1:
        pts = [x, y, x + 10, y - h / 2, x + w + 10, y - h / 2, x + w + 10, y + h / 2, x + 10, y + h / 2]
    else:
        pts = [x, y - h / 2, x + w, y - h / 2, x + w, y + h / 2, x, y + h / 2]
    pen.poly(pts, a=a)
    pen.text(x + w / 2 + (10 if point == -1 else 0), y, s, size, a=a)


def ladder(pen: Pen, pitch: float, bank: float, every: int, tips: bool, half: float = 80, gap: float = 30):
    """The pitch ladder, turned by the bank: rungs above the horizon solid, below dashed, numbers both sides."""
    pen.turn = math.radians(bank)
    for p in range(-90, 91, every):
        y = (pitch - p) * DEG
        if abs(y) > 125:
            continue
        if p == 0:
            pen.line(-150, y, -40, y, 1.8)
            pen.line(40, y, 150, y, 1.8)
            continue
        draw = pen.line if p > 0 else pen.dashed
        draw(-half, y, -gap, y, 1.5)
        draw(gap, y, half, y, 1.5)
        if tips:
            tip = 7 if p > 0 else -7
            pen.line(-half, y, -half, y + tip, 1.5)
            pen.line(half, y, half, y + tip, 1.5)
        pen.text(-half - 10, y, abs(p), 11, "e")
        pen.text(half + 10, y, abs(p), 11, "w")
    pen.turn = 0.0


def fpm(pen: Pen, aoa: float, aos: float):
    """The flight path marker: where the aircraft really goes, below the nose by the angle of attack."""
    x, y = max(-60.0, min(60.0, aos * DEG)), max(-90.0, min(90.0, aoa * DEG))
    pen.circle(x, y, 7)
    pen.line(x - 20, y, x - 7, y, 1.8)
    pen.line(x + 7, y, x + 20, y, 1.8)
    pen.line(x, y - 7, x, y - 15, 1.8)


def fmt(v: float | None, places: int = 0, plus: bool = False) -> str:
    if v is None:
        return "---"
    return f"{v:+.{places}f}" if plus else f"{v:.{places}f}"


def fuel_time(v: dict) -> str | None:
    fuel, burn = v.get("fuel"), v.get("burn")
    if not fuel or not burn:
        return None
    left = int(fuel / burn * 60)
    return f"{left // 60}:{left % 60:02d}"


def nato(pen: Pen, v: dict, imperial: bool, parts: set, alert: int):
    ias, alt, vy = v.get("ias"), v.get("alt"), v.get("vy")
    if "ladder" in parts and v.get("pitch") is not None:
        ladder(pen, v["pitch"], v.get("bank") or 0, 5, True)
    if "fpm" in parts and v.get("aoa") is not None:
        fpm(pen, v["aoa"], v.get("aos") or 0)
    pen.poly([-18, 0, -12, 0, -6, 8, 0, 0, 6, 8, 12, 0, 18, 0])  # the boresight's W: where the nose points
    if "speed" in parts and ias is not None:
        s = ias / KT if imperial else ias
        tape(pen, -230, s, 10 if imperial else 20, 50 if imperial else 100, 60 if imperial else 120, -1)
        box(pen, -312, 0, 62, round(s), point=1, a=alert)
        pen.text(-312, 140, fmt(v.get("mach"), 2), 13, "w")
        pen.text(-312, 158, f"AOA {fmt(v.get('aoa'), 1)}", 12, "w")
    if "alt" in parts and alt is not None:
        a = alt / FT if imperial else alt
        tape(pen, 230, a, 100 if imperial else 20, 500 if imperial else 100, 1000 if imperial else 300, 1)
        box(pen, 242, 0, 70, fmt(a), point=-1)
        if vy is not None:
            pen.text(252, 140, f"VV {fmt(vy / FT * 60 if imperial else vy, 0, True)}", 12, "w")
    if v.get("g") is not None:
        pen.text(-312, -165, fmt(v["g"], 1), 15, "w")
    if "heading" in parts and v.get("heading") is not None:
        heading(pen, 186, v["heading"], lambda d: f"{d // 10:02d}", below=True)
    data(pen, v, -312, 252, 200)


def russian(pen: Pen, v: dict, imperial: bool, parts: set, alert: int):
    ias, alt = v.get("ias"), v.get("alt")
    if "ladder" in parts and v.get("pitch") is not None:  # a moving horizon with a gap, sparse marks; the aircraft stays put
        pen.turn = math.radians(v.get("bank") or 0)
        y0 = v["pitch"] * 7
        pen.line(-190, y0, -30, y0, 2)
        pen.line(30, y0, 190, y0, 2)
        for p in range(-80, 81, 10):
            y = (v["pitch"] - p) * 7
            if p and abs(y) < 120:
                (pen.line if p > 0 else pen.dashed)(-60, y, -25, y, 1.5)
                (pen.line if p > 0 else pen.dashed)(25, y, 60, y, 1.5)
                pen.text(72, y, abs(p), 11, "w")
        pen.turn = 0.0
    pen.circle(0, 0, 1.5)  # the aircraft: its wings stay put, the horizon moves
    pen.line(-34, 0, -10, 0, 2)
    pen.line(10, 0, 34, 0, 2)
    pen.line(0, -6, 0, -14, 2)
    if "fpm" in parts and v.get("aoa") is not None:
        fpm(pen, v["aoa"], v.get("aos") or 0)
    if "speed" in parts and ias is not None:
        pen.text(-300, -165, round(ias / KT if imperial else ias), 22, "w", alert)
        pen.text(-300, -142, f"М {fmt(v.get('mach'), 2)}", 14, "w")  # Cyrillic М
    if "alt" in parts and alt is not None:
        pen.text(300, -165, fmt(alt / FT if imperial else alt), 22, "e")
        if v.get("vy") is not None:
            pen.text(300, -142, f"Vy {fmt(v['vy'] / FT * 60 if imperial else v['vy'], 0, True)}", 14, "e")
    if "heading" in parts and v.get("heading") is not None:
        heading(pen, -200, v["heading"], lambda d: f"{d // 10}", below=False, span=100)
    for x, lo, hi, step, val, name, side in ((-260, 0, 30, 5, v.get("aoa"), "α", 1), (260, -2, 9, 1, v.get("g"), "n", -1)):
        if val is None:
            continue
        pen.line(x, -60, x, 120, 1.4)
        for n in range(lo, hi + 1, step):
            y = 120 - (n - lo) / (hi - lo) * 180
            pen.line(x - 5, y, x + 5, y, 1.2)
        y = 120 - (max(lo, min(hi, val)) - lo) / (hi - lo) * 180
        pen.poly([x + side * 6, y, x + side * 16, y - 6, x + side * 16, y + 6], filled=1)
        pen.text(x, 138, f"{name} {fmt(val, 1)}", 13)
    if v.get("bank") is not None:  # the bank scale under the aircraft
        for b in (-60, -30, -15, 0, 15, 30, 60):
            r = math.radians(b)
            pen.line(90 * math.sin(r), 60 + 90 * math.cos(r), 98 * math.sin(r), 60 + 98 * math.cos(r), 1.4)
        r = math.radians(max(-70, min(70, v["bank"])))
        pen.circle(84 * math.sin(r), 60 + 84 * math.cos(r), 3.5)
    data(pen, v, -300, 230, 200)


def chinese(pen: Pen, v: dict, imperial: bool, parts: set, alert: int):
    ias, alt = v.get("ias"), v.get("alt")
    if "ladder" in parts and v.get("pitch") is not None:
        ladder(pen, v["pitch"], v.get("bank") or 0, 10, False, half=70)
    if "fpm" in parts and v.get("aoa") is not None:
        fpm(pen, v["aoa"], v.get("aos") or 0)
    pen.line(-14, 0, -6, 0, 1.6)
    pen.line(6, 0, 14, 0, 1.6)
    pen.line(0, -6, 0, -14, 1.6)
    if "heading" in parts and v.get("heading") is not None:
        heading(pen, -190, v["heading"], lambda d: f"{d:03d}", below=False)
    if "speed" in parts and ias is not None:
        box(pen, -300, 0, 70, round(ias / KT if imperial else ias), 17, a=alert)
        pen.text(-265, -26, "kt" if imperial else "km/h", 11)
        pen.text(-300, 40, f"M {fmt(v.get('mach'), 2)}", 13, "w")
        pen.text(-300, 58, f"G {fmt(v.get('g'), 1)}", 13, "w")
        pen.text(-300, 76, f"α {fmt(v.get('aoa'), 1)}", 13, "w")
    if "alt" in parts and alt is not None:
        box(pen, 225, 0, 76, fmt(alt / FT if imperial else alt), 17)
        pen.text(263, -26, "ft" if imperial else "m", 11)
        if v.get("vy") is not None:
            pen.text(225, 40, f"VS {fmt(v['vy'] / FT * 60 if imperial else v['vy'], 0, True)}", 13, "w")
    data(pen, v, -300, 225, 200)


def data(pen: Pen, v: dict, left: float, right: float, y: float):
    """Throttle and fuel at the bottom corners."""
    if "data" not in pen.parts:
        return
    if v.get("throttle") is not None:
        pen.text(left, y, f"THR {fmt(v['throttle'])} %", 12, "w")
    if v.get("gear") or v.get("flaps"):
        pen.text(left, y + 16, f"GEAR {fmt(v.get('gear'))}  FLAPS {fmt(v.get('flaps'))}", 12, "w")
    if v.get("fuel") is not None:
        pen.text(right, y, f"FUEL {fmt(v['fuel'])} kg", 12, "w")
        if fuel_time(v):
            pen.text(right, y + 16, f"{fuel_time(v)}  {fmt(v.get('burn'), 1)} kg/min", 12, "w")


DRAW = {"nato": nato, "russian": russian, "chinese": chinese}


def draw(v: dict, cfg: dict, nation: str | None, screen: tuple, place: str, alerts=()) -> list:
    """The HUD's shapes for a reading v (alarms.numbers: ias, alt, heading, pitch, bank...). place: cockpit or outside,
    over the game where the overlay settings put it, or window: the middle of a window of that size."""
    width, height = screen
    if place == "window":  # the HUD fills the window
        pen = Pen(width / 2, height / 2, min(height / WINDOW[1], width / WINDOW[0]))
    else:
        x, y, scale = (cfg[f"hud{place.title()}{n}"] for n in ("X", "Y", "Scale"))
        pen = Pen(width / 2 + x, height / 2 + y, height * scale / 100 / HEIGHT)
    pen.parts = {p for p in PARTS if cfg[f"hud{p.title()}"]}
    style = style_of(cfg["hudStyle"], nation)
    imperial = cfg["hudUnits"] == "imperial" or (cfg["hudUnits"] == "auto" and style == "nato")
    DRAW[style](pen, v, imperial, pen.parts, int(any(a in alerts for a in SPEED_ALERTS)))
    return pen.out
