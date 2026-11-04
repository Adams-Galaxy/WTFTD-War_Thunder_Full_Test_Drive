"""The minimap in the overlay: the game's own map (/map.img), your aircraft and its trail, and what never moves: airfields,
capture zones, bases. Nobody else: /map_obj.json also lists the enemies the game has spotted and your allies, and an overlay
showing enemies can count as ESP for Gaijin (staff, forum thread "Tools using data provided on port 8111", 2024-05-13), so
keep() drops every unit but yours as soon as the answer is read.

draw() returns shapes like hud.draw, with a colour in place of the alert flag (hud.js and the overlay draw both kinds), and
where the map picture goes: {"box": the part of /map.img shown, in its pixels, "n": subsample or -zoom, "at": [x, y]}."""
from __future__ import annotations

import math
import re

FIXED = ("airfield", "capture_zone", "bombing_point", "defending_point")  # the map's own, the same for everybody
COLOR = re.compile(r"#[0-9a-fA-F]{6}")
ME, MAP_LINE, MAP_TEXT = "#FAC81E", "#9AA4B2", "#E6E6E6"
ZOOMS = (1, 2, 4, 8)


# what My overlay's preview shows: an aircraft heading north-east, its airfield behind it, the enemy's, two zones
SAMPLE = {"me": {"x": 0.46, "y": 0.55, "dx": 0.7, "dy": -0.7}, "fixed": [
    {"type": "airfield", "color": "#174DFF", "sx": 0.30, "sy": 0.74, "ex": 0.34, "ey": 0.72},
    {"type": "airfield", "color": "#FA0C00", "sx": 0.70, "sy": 0.22, "ex": 0.74, "ey": 0.20},
    {"type": "capture_zone", "color": "#FAFAFA", "x": 0.52, "y": 0.40}, {"type": "capture_zone", "color": "#174DFF", "x": 0.40, "y": 0.46}]}
SAMPLE_INFO = {"map_min": [0, 0], "map_max": [65536, 65536]}
SAMPLE_TRAIL = [(0.36, 0.68), (0.39, 0.64), (0.42, 0.60), (0.46, 0.55)]


def _num(v) -> float | None:
    return float(v) if type(v) in (int, float) and math.isfinite(v) else None


def _color(v, default: str) -> str:
    return v if isinstance(v, str) and COLOR.fullmatch(v) else default


def keep(objects) -> dict:
    """Your aircraft and the fixed objects of /map_obj.json, nothing else. Positions are shares of the map, 0 to 1."""
    me, fixed = None, []
    for o in objects if isinstance(objects, list) else []:
        if not isinstance(o, dict):
            continue
        if o.get("icon") == "Player":
            x, y, dx, dy = (_num(o.get(k)) for k in ("x", "y", "dx", "dy"))
            if x is not None and y is not None:
                me = {"x": x, "y": y, "dx": dx or 0.0, "dy": dy or -1.0}
        elif o.get("type") in FIXED:
            pts = {k: _num(o.get(k)) for k in ("x", "y", "sx", "sy", "ex", "ey")}
            fixed.append({"type": o["type"], "color": _color(o.get("color"), MAP_LINE), **{k: v for k, v in pts.items() if v is not None}})
    return {"me": me, "fixed": fixed}


def png_size(img: bytes | None) -> tuple | None:
    """A PNG's width and height from its header; None for anything else (Tk can't show a JPEG: then no picture)."""
    if not img or img[:8] != b"\x89PNG\r\n\x1a\n" or len(img) < 24:
        return None
    return int.from_bytes(img[16:20], "big"), int.from_bytes(img[20:24], "big")


def view(me: dict | None, zoom: int) -> tuple:
    """The square of the map shown: (x0, y0, span) in shares of the map, centred on the aircraft and kept inside the map."""
    span = 1 / zoom
    if not me or zoom == 1:
        return 0.0, 0.0, 1.0
    return (min(max(me["x"] - span / 2, 0.0), 1 - span), min(max(me["y"] - span / 2, 0.0), 1 - span), span)


def picture(size: int, crop: tuple, pixels: tuple | None) -> tuple:
    """How the map picture fills about size pixels: Tk only shrinks or grows a picture by whole numbers, so the minimap takes
    the size that comes out (shortcut: up to a third off the size asked; a resampled copy would need more than Tk has)."""
    if not pixels:
        return size, None
    across = max(1, round(crop[2] * pixels[0]))
    n = round(across / size) if across >= size else -round(size / across)  # n < 0: grown -n times
    shown = -(-across // n) if n > 0 else across * -n  # Tk keeps every n-th pixel, the last one included
    x0, y0 = round(crop[0] * pixels[0]), round(crop[1] * pixels[1])
    return shown, {"box": [x0, y0, x0 + across, y0 + across], "n": n}


def bearing(a: dict, b: dict, extent: tuple) -> tuple:
    """Distance in km and heading in degrees from a to b; extent: the map's width and height in metres."""
    east, north = (b["x"] - a["x"]) * extent[0], -(b["y"] - a["y"]) * extent[1]
    return math.hypot(east, north) / 1000, math.degrees(math.atan2(east, north)) % 360


def home(me: dict, fixed: list, extent: tuple) -> tuple | None:
    """The nearest airfield that isn't the enemy's (red): (km, heading)."""
    own = [f for f in fixed if f["type"] == "airfield" and "sx" in f and "ex" in f and not _reddish(f["color"])]
    best = min(({"x": (f["sx"] + f["ex"]) / 2, "y": (f["sy"] + f["ey"]) / 2} for f in own),
               key=lambda p: math.hypot(p["x"] - me["x"], p["y"] - me["y"]), default=None)
    return bearing(me, best, extent) if best else None


def _reddish(color: str) -> bool:
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return r > 150 and r > 2 * max(g, b)


def draw(seen: dict, info: dict, trail: list, cfg: dict, pixels: tuple | None) -> tuple:
    """The minimap's shapes and where its picture goes. seen: keep()'s answer; info: /map_info.json; trail: the
    aircraft's last places [(x, y)...]; pixels: the map picture's size, None without one."""
    me, zoom = seen.get("me"), cfg["mapZoom"]
    crop = view(me, zoom)
    size, image = picture(cfg["mapSize"], crop, pixels)
    left, top = cfg["mapX"], cfg["mapY"]
    out = []

    def at(x, y):
        return [round(left + (x - crop[0]) / crop[2] * size, 1), round(top + (y - crop[1]) / crop[2] * size, 1)]

    def inside(x, y):
        return crop[0] <= x <= crop[0] + crop[2] and crop[1] <= y <= crop[1] + crop[2]

    if image:
        image["at"] = [left, top]
    else:  # no picture: a dark square, so the marks still read
        out.append(["p", [left, top, left + size, top, left + size, top + size, left, top + size], 1, "#141A22"])
    for f in seen.get("fixed", []):
        if f["type"] == "airfield" and {"sx", "sy", "ex", "ey"} <= f.keys():
            if inside(f["sx"], f["sy"]) or inside(f["ex"], f["ey"]):
                out.append(["l", *at(f["sx"], f["sy"]), *at(f["ex"], f["ey"]), 4, f["color"]])
        elif "x" in f and "y" in f and inside(f["x"], f["y"]):
            x, y = at(f["x"], f["y"])
            if f["type"] == "capture_zone":
                out.append(["c", x, y, max(5, size / 40), f["color"]])
            else:
                out.append(["p", [x - 5, y - 5, x + 5, y - 5, x + 5, y + 5, x - 5, y + 5], 0, f["color"]])
    if cfg["mapTrail"]:
        pts = [at(x, y) for x, y in trail if inside(x, y)]
        out += [["l", *a, *b, 1.5, ME] for a, b in zip(pts, pts[1:])]
    if me and inside(me["x"], me["y"]):
        x, y = at(me["x"], me["y"])
        length = math.hypot(me["dx"], me["dy"]) or 1
        ux, uy = me["dx"] / length, me["dy"] / length  # the way the aircraft points, on the map
        r = max(7, size / 30)
        out.append(["p", [x + ux * r, y + uy * r, x - ux * r * 0.6 - uy * r * 0.6, y - uy * r * 0.6 + ux * r * 0.6,
                          x - ux * r * 0.6 + uy * r * 0.6, y - uy * r * 0.6 - ux * r * 0.6], 1, ME])
    out.append(["p", [left, top, left + size, top, left + size, top + size, left, top + size], 0, MAP_LINE])
    try:
        extent = (float(info["map_max"][0]) - float(info["map_min"][0]), float(info["map_max"][1]) - float(info["map_min"][1]))
    except (KeyError, TypeError, ValueError, IndexError):
        extent = None
    way = home(me, seen.get("fixed", []), extent) if me and extent else None
    if way:
        out.append(["t", left, top + size + 14, f"AF {way[0]:.1f} km {way[1]:03.0f}°", 13, "w", MAP_TEXT])
    return out, image
