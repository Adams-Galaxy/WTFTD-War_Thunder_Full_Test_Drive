"""The minimap in the overlay: the game's own map (/map.img), your aircraft and its trail, what never moves (airfields,
capture zones, bases) and, if you want them, your allies. Never an enemy: /map_obj.json also lists the ones the game has
spotted, and an overlay showing enemies can count as ESP for Gaijin (staff, forum thread "Tools using data provided on
port 8111", 2024-05-13), so keep() drops them as soon as the answer is read. The game doesn't say a unit's team, only
its colour: an ally is one in an ally's colour (blue, or a squadmate's green), anything else is left out.

draw() returns where the minimap goes and its shapes, like hud.draw's with a colour in place of the alert flag (hud.js and
mappaint draw both kinds): marks inside the map, cut to its shape; frame and words around it; and how the map picture
lies under them (its centre, scale and turn), for mappaint. North up, or the aircraft's nose up."""
from __future__ import annotations

import math
import re

FIXED = ("airfield", "capture_zone", "bombing_point", "defending_point")  # the map's own, the same for everybody
UNITS = ("aircraft", "ground_model")
COLOR = re.compile(r"#[0-9a-fA-F]{6}")
ME, MAP_LINE, MAP_TEXT, MAP_DARK = "#FAC81E", "#9AA4B2", "#E6E6E6", "#141A22"
ZOOMS = (1, 2, 4, 8)
MARKS = ("Me", "Allies", "Airfields", "Zones")  # the kinds of marks with a size of their own: mapMarkMe... in %

# what My overlay's preview shows: an aircraft heading north-east, its airfield behind it, the enemy's, two zones, an ally
SAMPLE = {"me": {"x": 0.46, "y": 0.55, "heading": 45.0}, "allies": [{"x": 0.42, "y": 0.6, "heading": 30.0, "color": "#174DFF", "air": True}],
          "fixed": [{"type": "airfield", "color": "#174DFF", "sx": 0.30, "sy": 0.74, "ex": 0.34, "ey": 0.72},
                    {"type": "airfield", "color": "#FA0C00", "sx": 0.70, "sy": 0.22, "ex": 0.74, "ey": 0.20},
                    {"type": "capture_zone", "color": "#FAFAFA", "x": 0.52, "y": 0.40}, {"type": "capture_zone", "color": "#174DFF", "x": 0.40, "y": 0.46}]}
SAMPLE_INFO = {"map_min": [0, 0], "map_max": [65536, 65536]}
SAMPLE_TRAIL = [(0.36, 0.68), (0.39, 0.64), (0.42, 0.60), (0.46, 0.55)]


def _num(v) -> float | None:
    return float(v) if type(v) in (int, float) and math.isfinite(v) else None


def _color(v, default: str) -> str:
    return v if isinstance(v, str) and COLOR.fullmatch(v) else default


def _rgb(color: str) -> tuple:
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def _ally(color: str) -> bool:
    """An ally's blue or a squadmate's green, clearly; red, orange, yellow, white or grey are not."""
    r, g, b = _rgb(color)
    return (b > r + 60 and b >= g) or (g > r + 60 and g > b + 30)


def _heading(dx, dy) -> float:
    return math.degrees(math.atan2(dx or 0.0, -(dy if dy is not None else -1.0))) % 360  # 0 north, clockwise, as the compass


def keep(objects, allies: bool = False, ground: bool = False) -> dict:
    """Your aircraft, the fixed objects of /map_obj.json and, if asked, units in an ally's colour: allies, their aircraft;
    ground, their vehicles and ships, the AI in an air battle (the game doesn't say who's an AI). Nothing else. Positions
    are shares of the map, 0 to 1."""
    me, fixed, friends = None, [], []
    for o in objects if isinstance(objects, list) else []:
        if not isinstance(o, dict):
            continue
        x, y = _num(o.get("x")), _num(o.get("y"))
        if o.get("icon") == "Player":
            if x is not None and y is not None:
                me = {"x": x, "y": y, "heading": _heading(_num(o.get("dx")), _num(o.get("dy")))}
        elif o.get("type") in FIXED:
            pts = {k: _num(o.get(k)) for k in ("x", "y", "sx", "sy", "ex", "ey")}
            fixed.append({"type": o["type"], "color": _color(o.get("color"), MAP_LINE), **{k: v for k, v in pts.items() if v is not None}})
        elif (allies if o.get("type") == "aircraft" else ground) and o.get("type") in UNITS and x is not None and y is not None:
            color = _color(o.get("color"), "")
            if color and _ally(color):
                friends.append({"x": x, "y": y, "heading": _heading(_num(o.get("dx")), _num(o.get("dy"))), "color": color,
                                "air": o["type"] == "aircraft"})
    return {"me": me, "fixed": fixed, "allies": friends}


def view(me: dict | None, zoom: int) -> tuple:
    """North up: the square of the map shown, (x0, y0, span) in shares of the map, centred on the aircraft and kept inside."""
    span = 1 / zoom
    if not me or zoom == 1:
        return 0.0, 0.0, 1.0
    return (min(max(me["x"] - span / 2, 0.0), 1 - span), min(max(me["y"] - span / 2, 0.0), 1 - span), span)


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
    r, g, b = _rgb(color)
    return r > 150 and r > 2 * max(g, b)


def _arrow(x: float, y: float, angle: float, r: float) -> list:
    """A filled arrow head at x, y pointing angle degrees clockwise from up."""
    a = math.radians(angle)
    ux, uy = math.sin(a), -math.cos(a)
    return [x + ux * r, y + uy * r, x - ux * r * 0.6 - uy * r * 0.6, y - uy * r * 0.6 + ux * r * 0.6,
            x - ux * r * 0.6 + uy * r * 0.6, y - uy * r * 0.6 - ux * r * 0.6]


def draw(seen: dict, info: dict, trail: list, cfg: dict) -> dict:
    """seen: keep()'s answer (me with its heading, which may glide between readings); info: /map_info.json; trail: the
    aircraft's last places [(x, y)...]. Screen pixels throughout."""
    me, zoom, size = seen.get("me"), cfg["mapZoom"], cfg["mapSize"]
    left, top, r = cfg["mapX"], cfg["mapY"], size / 2
    mid_x, mid_y = left + r, top + r
    heading_up = cfg["mapUp"] == "heading" and me is not None
    if heading_up:  # around the aircraft, turned with it: the map runs off its edge near the sides of the map
        cx, cy, span, turn = me["x"], me["y"], 1 / zoom, me["heading"]
    else:
        x0, y0, span = view(me, zoom)
        cx, cy, turn = x0 + span / 2, y0 + span / 2, 0.0
    k, c, s = size / span, math.cos(math.radians(turn)), math.sin(math.radians(turn))
    round_ = cfg["mapShape"] == "round"
    mine, ally, field, zone = (cfg[f"mapMark{kind}"] / 100 for kind in MARKS)  # each kind of mark at its own size

    def at(x, y) -> list:
        dx, dy = (x - cx) * k, (y - cy) * k
        return [round(mid_x + dx * c + dy * s, 1), round(mid_y - dx * s + dy * c, 1)]

    def inside(p) -> bool:
        dx, dy = p[0] - mid_x, p[1] - mid_y
        return dx * dx + dy * dy <= r * r if round_ else abs(dx) <= r and abs(dy) <= r

    marks = []
    for f in seen.get("fixed", []):
        if f["type"] == "airfield" and {"sx", "sy", "ex", "ey"} <= f.keys():
            a, b = at(f["sx"], f["sy"]), at(f["ex"], f["ey"])
            if inside(a) or inside(b):
                # a runway is a few pixels on a whole map: drawn at least a tenth of the minimap long, and thick, along its way
                mx, my, dx, dy = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2, b[0] - a[0], b[1] - a[1]
                half = max(math.hypot(dx, dy), size / 10 * field) / 2
                ux, uy = (dx, dy) if dx or dy else (1.0, 0.0)
                n = math.hypot(ux, uy)
                marks.append(["l", round(mx - ux / n * half, 1), round(my - uy / n * half, 1), round(mx + ux / n * half, 1), round(my + uy / n * half, 1),
                              round(max(6, size / 50) * field, 1), f["color"]])
        elif "x" in f and "y" in f:
            p = at(f["x"], f["y"])
            if not inside(p):
                continue
            if f["type"] == "capture_zone":
                marks.append(["c", *p, round(max(5, size / 40) * zone, 1), f["color"]])
            else:
                h = 5 * zone
                marks.append(["p", [p[0] - h, p[1] - h, p[0] + h, p[1] - h, p[0] + h, p[1] + h, p[0] - h, p[1] + h], 0, f["color"]])
    for u in seen.get("allies", []):
        p = at(u["x"], u["y"])
        if inside(p):
            h = max(4, size / 90) * ally  # a vehicle's square, half its side
            marks.append(["p", _arrow(*p, u["heading"] - turn, max(7, size / 38) * ally), 1, u["color"]] if u["air"] else
                         ["p", [p[0] - h, p[1] - h, p[0] + h, p[1] - h, p[0] + h, p[1] + h, p[0] - h, p[1] + h], 1, u["color"]])
    if cfg["mapTrail"]:
        pts = [at(x, y) for x, y in [*trail, *([(me["x"], me["y"])] if me else [])]]
        marks += [["l", *a, *b, 1.5, ME] for a, b in zip(pts, pts[1:]) if inside(a) or inside(b)]
    if me:
        p = at(me["x"], me["y"])
        if inside(p):
            marks.append(["p", _arrow(*p, me["heading"] - turn, max(9, size / 26) * mine), 1, ME])

    frame = [["c", mid_x, mid_y, r, MAP_LINE] if round_ else ["p", [left, top, left + size, top, left + size, top + size, left, top + size], 0, MAP_LINE]]
    if heading_up:  # where north is, on the edge
        frame.append(["t", round(mid_x - s * (r - 12), 1), round(mid_y - c * (r - 12), 1), "N", 13, "m", MAP_TEXT])
    try:
        extent = (float(info["map_max"][0]) - float(info["map_min"][0]), float(info["map_max"][1]) - float(info["map_min"][1]))
    except (KeyError, TypeError, ValueError, IndexError):
        extent = None
    way = home(me, seen.get("fixed", []), extent) if me and extent else None
    if way:
        frame.append(["t", left, top + size + 14, f"AF {way[0]:.1f} km {way[1]:03.0f}°", 13, "w", MAP_TEXT])
    return {"box": [left, top, size], "round": round_, "marks": marks, "frame": frame, "dim": cfg["mapDim"],
            "picture": {"cx": cx, "cy": cy, "k": k, "turn": turn}}
