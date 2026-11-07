"""Test bench: what an aircraft really does, measured in the game. The player flies a guided test in a mission WTFTD wrote,
the recording (flightlog.py) goes through analyse(), which keeps the stretches that make a valid run and says why it
refused the others. Results are in user/bench.json, by aircraft, loadout and game version. UI in web/bench.js.

The player flies: nothing here sends anything to the game, the app only reads port 8111 through alarms.Watch. A number
in a result is read from the game or is plain geometry of what was read (a turn's radius: the distance flown in 360°);
what the flight model says it should be is never a measurement here.

Tests: top speed, climb, sustained turn, acceleration, speed lost in a hard turn, slowest level flight at idle. Helicopters
get the first three that fit them (top, climb, accel): they have no stall, and a hard turn's numbers mean nothing without
a throttle to hold. The stall test measures where level flight stops, not the wing's stall: with the game's instructor
on, the nose never drops, but the aircraft does sink.

The file can be edited by hand and a plan comes from the page: both go through clean()."""
from __future__ import annotations

import json
import math
import re
import statistics
import threading
import time
from pathlib import Path

from . import alarms, flightlog
from .paths import USER

FILE = USER / "bench.json"
MAX_RUNS = 2000
MAX_REJECTED = 20  # the longest ones, in a flight that lasted
SAFE_ID = re.compile(r"[A-Za-z0-9_\-.]{1,120}")
DIFFICULTIES = ("arcade", "realistic", "hardcore")

FULL, IDLE = 99.0, 10.0  # throttle in %. War Emergency Power and afterburner read above 100
WINGS, BANKED = 10.0, 20.0  # degrees of bank
LEVEL_VY, CLIMBING_VY = 4.0, 1.0  # m/s
STEADY, RATE_S = 1.5, 5.0  # km/h per second of IAS, over this long: a speed that is held by hand
GAP_S = 2.5  # no reading for this long: two stretches, whatever they look like
BLIP_S = 1.0  # a bad reading this short is noise inside a stretch
PAUSE_S = 1.5  # every value frozen this long: the game is paused, its time isn't the log's
FROZEN = ("alt", "vy", "tas", "g", "ias", "east", "north", "heading", "bank")  # the game sends whole metres and km/h: settled flight repeats those, not the map marker
BAD_S = 2.0  # refused stretches shorter than this aren't worth a line
TOP_S, TOP_SEP = 20.0, 0.5  # top speed: this long with this little energy gained or lost (m/s): see _top
ALT_BAND = 500  # m: one result per band of altitude
CLIMB_M, CLIMB_S = 300.0, 15.0  # the shortest climb worth a result
LAP, TURN_DV, TURN_DH, SPEED_BIN = 360.0, 15.0, 60.0, 25  # a sustained turn: its speed and height may end this far from where they began
ACCEL_DH = 100.0  # m
HALF, HARD_G, BLEED_DH, BLEED_DV = 180.0, 2.5, 150.0, 30.0  # a hard turn: 180°, this hard, height kept, begun this near the speed asked
STALL_VY, STALL_S, STALL_G, STALL_LEVEL_S = 4.0, 1.5, 1.3, 5.0  # sinking this fast, this long, not pulling, after level flight this long
SLOWING = (0.3, 8.0)  # km/h per second lost on the way to the stall: below it wasn't slowing, above it wasn't gentle
AWAY_S = 5  # out of the flight this long: the run is over


def _median(rows: list, key: str) -> float | None:
    values = [r[key] for r in rows if key in r]
    return round(statistics.median(values), 1) if values else None


def _slope(xs: list, ys: list) -> float:
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    d = sum((x - mx) ** 2 for x in xs)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / d if d else 0.0


def _span(rows: list) -> float:
    return rows[-1]["t"] - rows[0]["t"]


def _no(rows: list, why: str, v=None) -> dict:
    """A refused stretch. v: the number its message says."""
    return {"why": why, "t": rows[0]["t"], "s": round(_span(rows), 1), **({} if v is None else {"v": v})}


def _cross(a: dict, b: dict, key: str, level: float) -> float:
    """When the line from row a to row b reaches this level."""
    return a["t"] + (b["t"] - a["t"]) * ((level - a[key]) / (b[key] - a[key]) if b[key] != a[key] else 0.0)


def _turned(rows: list) -> list | None:
    """Degrees turned since the first row, at each row; None when the game gave no heading. From the compass, else from the
    marker on the map: /indicators can go blank in flight (alarms.py)."""
    out, total, last = [], 0.0, None
    for r in rows:
        h = r.get("heading", r.get("hdg"))
        if h is None:
            return None
        total += 0.0 if last is None else (h - last + 180) % 360 - 180
        last = h
        out.append(total)
    return out


def _up(key: str):
    return lambda r: r.get(key, 0) <= 0


CHECKS = {"full": lambda r: r.get("throttle", FULL) >= FULL, "idle": lambda r: r.get("throttle", IDLE) <= IDLE,
          "gear": _up("gear"), "flaps": _up("flaps"), "airbrake": _up("airbrake"),
          "wings": lambda r: abs(r.get("bank", 0)) <= WINGS, "banked": lambda r: abs(r.get("bank", BANKED)) >= BANKED,
          "level": lambda r: abs(r.get("vy", 0)) <= LEVEL_VY, "climbing": lambda r: r.get("vy", 0) >= CLIMBING_VY,
          "steady": lambda r: abs(r.get("dias", 0)) <= STEADY}
CLEAN = ("gear", "flaps", "airbrake")


def _prepared(rows: list) -> list:
    """Rows with a speed and a height, each with how fast its IAS moves (dias, km/h per second) and whether the game looks
    paused (frozen)."""
    out, back, still = [], 0, None
    for r in rows:
        if not all(k in r for k in ("t", "ias", "alt")):
            continue
        r = dict(r)
        if out and r["t"] - out[-1]["t"] > GAP_S:
            back, still = len(out), None
        same = out and all(r.get(k) == out[-1].get(k) for k in FROZEN)
        still = (still if still is not None else out[-1]["t"]) if same else None
        r["frozen"] = still is not None and r["t"] - still >= PAUSE_S
        while back < len(out) and r["t"] - out[back]["t"] > RATE_S:
            back += 1
        if back < len(out) and r["t"] - out[back]["t"] >= 1:
            r["dias"] = (r["ias"] - out[back]["ias"]) / (r["t"] - out[back]["t"])
        out.append(r)
    return out


def _verdict(r: dict, checks: tuple) -> str | None:
    return "paused" if r["frozen"] else next((k for k in checks if not CHECKS[k](r)), None)


def _split(rows: list, checks: tuple) -> tuple:
    """The rows cut where their verdict changes: (stretches that pass every check, refusals of those that don't)."""
    groups = []
    for r in rows:
        why = _verdict(r, checks)
        if groups and groups[-1][0] == why and r["t"] - groups[-1][1][-1]["t"] <= GAP_S:
            groups[-1][1].append(r)
        else:
            groups.append((why, [r]))
    merged = []
    for why, run in groups:
        before = merged[-1] if merged else None
        near = before and run[0]["t"] - before[1][-1]["t"] <= GAP_S
        if near and before[0] is None and (why is None or _span(run) < BLIP_S):
            before[1].extend(run)
        else:
            merged.append((why, run))
    return [run for why, run in merged if why is None], [_no(run, why) for why, run in merged if why and _span(run) >= BAD_S]


def _top(run: list, plan: dict) -> tuple:
    """A level stretch whose speed has stopped moving: judged on the energy (height + speed), which a few metres of height
    held by hand don't disturb, and the last such window of each band of altitude, the most settled one."""
    if _span(run) < TOP_S:
        return [], [_no(run, "short", round(TOP_S))]
    found, gain, start, end = {}, 0.0, 0, 0
    while start < len(run):
        t0 = run[start]["t"]
        while end < len(run) and run[end]["t"] - t0 < TOP_S:
            end += 1
        if end == len(run):
            break
        window = run[start:end + 1]
        times, tas = [r["t"] for r in window], [r.get("tas", r["ias"]) / 3.6 for r in window]
        gain = _slope(times, [r["alt"] + v * v / (2 * alarms.G) for r, v in zip(window, tas)])
        if abs(gain) <= TOP_SEP:
            wep = _median(window, "throttle") or 0
            found[round(_median(window, "alt") / ALT_BAND), wep > 100.5] = window
        while start < len(run) and run[start]["t"] - t0 < 1:
            start += 1
    points = [{"t": w[0]["t"], "s": round(_span(w), 1), "alt": _median(w, "alt"), "tas": _median(w, "tas") or _median(w, "ias"), "ias": _median(w, "ias"),
               "mach": _median(w, "mach"), "throttle": _median(w, "throttle"),
               "trend": round(_slope([r["t"] for r in w], [r.get("tas", r["ias"]) for r in w]) * 60, 1)} for w in found.values()]
    return points, [] if points else [_no(run, "moving", round(gain, 1))]


def _climb(run: list, plan: dict) -> tuple:
    """A climb at a held speed: its rate by band of altitude and the time to get there from where it began."""
    gain = run[-1]["alt"] - run[0]["alt"]
    if gain < CLIMB_M or _span(run) < CLIMB_S:
        return [], [_no(run, "low", round(gain))]
    bands = {}
    for r in run:
        bands.setdefault(int(r["alt"] // ALT_BAND), []).append(r)
    curve = [[_median(x, "alt"), _median(x, "vy"), round(x[0]["t"] - run[0]["t"], 1), _median(x, "ias")] for _, x in sorted(bands.items())]
    return [{"t": run[0]["t"], "s": round(_span(run), 1), "from": round(run[0]["alt"]), "to": round(run[-1]["alt"]), "vy": max(c[1] for c in curve),
             "ias": _median(run, "ias"), "throttle": _median(run, "throttle"), "curve": curve}], []


def _turn(run: list, plan: dict) -> tuple:
    """Each full circle of a level turn at a held speed, timed on the heading. The radius is what was flown: speed x time / 2 pi."""
    turned = _turned(run)
    if turned is None:
        return [], [_no(run, "heading")]
    if abs(turned[-1] - turned[0]) < LAP and max(turned) - min(turned) < LAP:
        return [], [_no(run, "lap", round(max(turned) - min(turned)))]
    best, j, why = {}, 0, None
    for i, r in enumerate(run):
        j = max(j, i)
        while j < len(run) and abs(turned[j] - turned[i]) < LAP:
            j += 1
        if j == len(run):
            break
        e, before = run[j], abs(turned[j - 1] - turned[i])
        share = (LAP - before) / (abs(turned[j] - turned[i]) - before)
        s = run[j - 1]["t"] + (e["t"] - run[j - 1]["t"]) * share - r["t"]
        if abs(e["ias"] - r["ias"]) > TURN_DV:
            why = "speed"
        elif abs(e["alt"] - r["alt"]) > TURN_DH:
            why = "altitude"
        else:
            key = round(r["ias"] / SPEED_BIN)
            if key not in best or s < best[key][0]:
                best[key] = (s, i, j)
    if not best:
        return [], [_no(run, why or "lap", round(LAP))]
    points = []
    for s, i, j in best.values():
        lap = run[i:j + 1]
        tas = _median(lap, "tas") or _median(lap, "ias")
        points.append({"t": lap[0]["t"], "s": round(s, 1), "ias": _median(lap, "ias"), "tas": tas, "alt": _median(lap, "alt"), "g": _median(lap, "g"),
                       "radius": round(tas / 3.6 * s / (2 * math.pi)), "throttle": _median(lap, "throttle")})
    return points, []


def _accel(run: list, plan: dict) -> tuple:
    """From one speed to the other with the throttle already open, in level flight."""
    low, high = plan.get("from", 0), plan.get("to", 0)
    if run[0]["ias"] > low:
        return [], [_no(run, "late", round(run[0]["ias"]))]
    end = next((j for j, r in enumerate(run) if r["ias"] >= high), None)
    if end is None:
        return [], [_no(run, "slow", round(max(r["ias"] for r in run)))]
    start = max(i for i, r in enumerate(run[:end]) if r["ias"] <= low)
    t0, t1 = _cross(run[start], run[start + 1], "ias", low), _cross(run[end - 1], run[end], "ias", high)
    if abs(run[end]["alt"] - run[start]["alt"]) > ACCEL_DH:
        return [], [_no(run[start:end + 1], "altitude", round(abs(run[end]["alt"] - run[start]["alt"])))]
    lap = run[start:end + 1]
    return [{"t": t0, "s": round(t1 - t0, 1), "from": low, "to": high, "alt": _median(lap, "alt"), "throttle": _median(lap, "throttle")}], []


def _bleed(run: list, plan: dict) -> tuple:
    """Half a circle pulling hard: the speed it costs, height kept."""
    points, refused, i = [], [], 0
    while i < len(run):
        if run[i].get("g", 0) < HARD_G:
            i += 1
            continue
        j = i
        while j < len(run) and run[j].get("g", 0) >= HARD_G:
            j += 1
        pull, i = run[i:j], j
        if _span(pull) < BLIP_S:
            continue
        turned = _turned(pull)
        if turned is None:
            refused.append(_no(pull, "heading"))
            continue
        k = next((n for n, a in enumerate(turned) if abs(a) >= HALF), None)
        if k is None:
            refused.append(_no(pull, "lap", round(max(abs(a) for a in turned))))
            continue
        half = pull[:k + 1]
        v0, v1, height = half[0]["ias"], half[-1]["ias"], half[-1]["alt"] - half[0]["alt"]
        if plan.get("speed") and abs(v0 - plan["speed"]) > BLEED_DV:
            refused.append(_no(half, "entry", round(v0)))
        elif abs(height) > BLEED_DH:
            refused.append(_no(half, "altitude", round(abs(height))))
        else:
            points.append({"t": half[0]["t"], "s": round(_span(half), 1), "v0": v0, "v1": v1, "lost": round(v0 - v1, 1), "g": _median(half, "g"),
                           "gmax": max(r.get("g", 0) for r in half), "alt": _median(half, "alt"), "dh": round(height), "throttle": _median(half, "throttle")})
    return points, refused or ([] if points else [_no(run, "soft")])


def _stall(run: list, plan: dict) -> tuple:
    """The speed where level flight at idle gave way: the last level reading before the aircraft started to sink, after a
    gentle, unpulled slow-down."""
    for i, r in enumerate(run):
        if r.get("vy", 0) >= -STALL_VY:
            continue
        after = [x for x in run[i:] if x["t"] - r["t"] <= STALL_S]
        before = [x for x in run[:i] if r["t"] - x["t"] <= STALL_LEVEL_S]
        if _span(after) < STALL_S * .9 or any(x.get("vy", 0) >= -STALL_VY for x in after):
            continue  # a dip, the aircraft came back
        if len(before) < 2 or _span(before) < STALL_LEVEL_S * .8 or any(not CHECKS["level"](x) for x in before):
            return [], [_no(run[:i + 1], "notLevel")]
        last, lost = before[-1], (before[0]["ias"] - before[-1]["ias"]) / _span(before)
        if not SLOWING[0] <= lost <= SLOWING[1]:
            return [], [_no(before, "rate", round(lost, 1))]
        if last.get("g", 1) > STALL_G:
            return [], [_no(before, "pulled", round(last["g"], 1))]
        return [{"t": last["t"], "s": round(_span(before), 1), "ias": last["ias"], "tas": last.get("tas"), "alt": last["alt"], "aoa": last.get("aoa"),
                 "throttle": _median(before, "throttle")}], []
    return [], [_no(run, "noStall", round(min(r["ias"] for r in run)))] if _span(run) >= STALL_LEVEL_S else []


# checks: what each reading must pass, in the order a refusal names them. find: a stretch that passed them -> (points, refusals).
# key and score: of the points that measure the same thing, the lowest score stays. need: seconds to hold, for the page
TESTS = {
    "top": {"checks": ("full", *CLEAN, "wings", "level"), "find": _top, "need": TOP_S,
            "key": lambda p: (round(p["alt"] / ALT_BAND), (p.get("throttle") or 0) > 100.5), "score": lambda p: -p["tas"]},
    "climb": {"checks": ("full", *CLEAN, "wings", "climbing", "steady"), "find": _climb, "need": CLIMB_S,
              "key": lambda p: 0, "score": lambda p: p["from"] - p["to"]},
    "turn": {"checks": ("full", *CLEAN, "banked", "level", "steady"), "find": _turn, "need": 0,
             "key": lambda p: round(p["ias"] / SPEED_BIN), "score": lambda p: p["s"]},
    "accel": {"checks": ("full", *CLEAN, "wings", "level"), "find": _accel, "need": 0, "key": lambda p: 0, "score": lambda p: p["s"]},
    "bleed": {"checks": ("full", *CLEAN), "find": _bleed, "need": 0, "key": lambda p: 0, "score": lambda p: p["lost"]},
    "stall": {"checks": ("idle", *CLEAN, "wings"), "find": _stall, "need": STALL_LEVEL_S, "key": lambda p: 0, "score": lambda p: p["ias"]},
}


def analyse(test: str, rows: list, plan: dict | None = None) -> dict:
    """{"points": what was measured, "rejected": the stretches refused, the reason of each}. Times count from the first row."""
    spec = TESTS[test]
    rows = _prepared(rows)
    if not rows:
        return {"points": [], "rejected": []}
    good, rejected = _split(rows, spec["checks"])
    points, kept = [], {}
    for run in good:
        found, refused = spec["find"](run, plan or {})
        points += found
        rejected += refused
    for p in points:
        key, old = spec["key"](p), kept.get(spec["key"](p))
        best = p if old is None or spec["score"](p) < spec["score"](old) else old
        kept[key] = {**best, "n": old["n"] + 1 if old else 1}
    rejected = sorted(sorted(rejected, key=lambda x: -x["s"])[:MAX_REJECTED], key=lambda x: x["t"])
    start = rows[0]["t"]
    return {"points": [{**p, "t": round(p["t"] - start, 1)} for p in kept.values()], "rejected": [{**x, "t": round(x["t"] - start, 1)} for x in rejected]}


def live(test: str, rows: list) -> dict:
    """What the page shows while the player flies: each check on the latest reading, and how long they have all passed."""
    spec = TESTS[test]
    rows = _prepared(rows)
    if not rows:
        return {}
    last, held = rows[-1], 0.0
    good = _split(rows, spec["checks"])[0]
    if good and good[-1][-1] is last:
        held = _span(good[-1])
    return {"checks": [{"key": k, "ok": bool(CHECKS[k](last))} for k in spec["checks"]], "held": round(held, 1), "need": spec["need"], "paused": last["frozen"],
            "now": {k: last[k] for k in ("ias", "tas", "alt", "vy", "throttle", "bank", "g") if k in last}}


# ------------------------------------------------------------------ what's kept
def _number(v, lo: float, hi: float, default=0):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and lo <= v <= hi else default


def _numbers(raw: dict) -> dict:
    return {k: v for k, v in raw.items() if isinstance(k, str) and isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)}


def _point(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    out = _numbers(raw)
    curve = raw.get("curve") if isinstance(raw.get("curve"), list) else None
    if curve is not None:
        out["curve"] = [[float(x) for x in c] for c in curve[:200] if isinstance(c, list) and len(c) == 4 and all(_number(x, -1e6, 1e6, None) is not None for x in c)]
    return out


def plan_of(raw) -> dict | None:
    """What a test was flown with, from the page: None if it's not a test."""
    if not isinstance(raw, dict) or raw.get("test") not in TESTS or not isinstance(raw.get("vehicle"), str) or not SAFE_ID.fullmatch(raw["vehicle"]):
        return None
    preset = raw.get("preset")
    return {"vehicle": raw["vehicle"], "test": raw["test"], "preset": preset if isinstance(preset, str) and SAFE_ID.fullmatch(preset) else "",
            "fuel": _number(raw.get("fuel"), 0, 100), "allMods": raw.get("allMods") is not False, "custom": raw.get("custom") is True, "cheats": raw.get("cheats") is True,
            "difficulty": raw["difficulty"] if raw.get("difficulty") in DIFFICULTIES else "realistic", "altitude": _number(raw.get("altitude"), 0, 40000),
            "speed": _number(raw.get("speed"), 0, 5000), "from": _number(raw.get("from"), 0, 5000), "to": _number(raw.get("to"), 0, 5000)}


def _run(raw) -> dict | None:
    plan = plan_of(raw)
    if not plan or not isinstance(raw.get("id"), str) or not SAFE_ID.fullmatch(raw["id"]):
        return None
    points = [x for x in map(_point, raw.get("points") if isinstance(raw.get("points"), list) else []) if x]
    log = raw.get("log")
    return {**plan, "id": raw["id"], "time": int(_number(raw.get("time"), 0, 1e11)), "game": str(raw.get("game") or "")[:32], "log": log if isinstance(log, str) and flightlog.NAME.fullmatch(log) else "",
            "points": points}


def clean(raw) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    return {"runs": [x for x in map(_run, raw.get("runs") if isinstance(raw.get("runs"), list) else []) if x][-MAX_RUNS:]}


def load() -> dict:
    """The runs, oldest first; damaged: the file nothing could read was just kept aside, the page says so once."""
    try:
        with open(FILE, encoding="utf-8") as f:
            return clean(json.load(f))
    except FileNotFoundError:
        return clean(None)
    except ValueError:  # UnicodeDecodeError is one too
        FILE.replace(FILE.with_suffix(".bad.json"))
        return {**clean(None), "damaged": True}


def _write(data: dict) -> dict:
    """In one step: a stopped write leaves the file as it was."""
    FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    tmp.replace(FILE)
    return data


def add(run: dict) -> dict:
    data = load()
    return _write({"runs": clean({"runs": [*data["runs"], run]})["runs"]})


def remove(run_id: str) -> dict:
    return _write({"runs": [x for x in load()["runs"] if x["id"] != run_id]})


class Bench:
    """A test under way: waits for its mission, records it and analyses it when the player leaves. One flight, one result;
    the plan stays armed for the next try, until another mission is generated. watch: alarms.Watch; folder: the logs';
    game: () -> the game version the data comes from."""

    def __init__(self, watch, folder: Path, game=str):
        self.watch, self.folder, self.game = watch, folder, game
        self.plan = None
        self.log = None  # the recording of this flight
        self.mine = False  # started here, not by the player's own Record
        self.since = 0.0  # where this flight starts in a recording the player began earlier
        self.away = None  # since when the flight is over
        self.last = None  # what the last flight gave, with its refusals: only this says why a flight gave nothing
        self.lock = threading.Lock()  # the page and the bench's thread: one flight, one result

    def arm(self, raw):
        """Each generated mission comes through here: a test's plan, or nothing."""
        with self.lock:
            if self.log:
                self.finish()
            self.plan, self.away = plan_of(raw), None
            self.watch.bench = bool(self.plan)

    def rows(self) -> list:
        names = {**{alarms.column(n): n for n in alarms.SERIES}, **dict(zip(alarms.POSITION, ("east", "north", "hdg")))}
        log = flightlog.read_log(self.folder, self.log, names) if self.log else None
        return [r for r in log["rows"] if r.get("t", 0) >= self.since] if log else []

    def step(self):
        """A look a second."""
        w = self.watch
        with self.lock:
            if not self.plan:
                return
            w.viewed = time.monotonic()  # the readings go on with the page closed
            if self.log:
                self.away = None if w.flying else self.away or time.monotonic()
                if self.away and time.monotonic() - self.away >= AWAY_S:
                    self.finish()
            elif w.flying and w.current in (self.plan["vehicle"], None) and w.mission_on_map():
                self.mine = not w.log
                w.set_log(True)
                log = w.log
                if log:
                    self.log, self.since, self.last = log.name, time.monotonic() - log.start, None

    def finish(self):
        rows = self.rows()
        if self.mine:
            self.watch.set_log(False)
        result = analyse(self.plan["test"], rows, self.plan) if self.plan else {"points": [], "rejected": []}
        self.last = {**(self.plan or {}), "id": f"{int(time.time() * 1000):x}", "time": int(time.time()), "game": self.game(), "log": self.log or "", **result}
        self.log, self.away = None, None
        if result["points"]:
            add(self.last)

    def status(self) -> dict:
        with self.lock:
            out = {"plan": self.plan, "flying": self.watch.flying, "recording": self.log, "last": self.last}
            rows = self.rows() if self.log else []
            if rows:
                out.update(live=live(self.plan["test"], rows), found=analyse(self.plan["test"], rows, self.plan))
            return out

    def run(self):
        while True:
            try:
                self.step()
            except Exception:  # never let the bench's thread die
                pass
            time.sleep(1)
