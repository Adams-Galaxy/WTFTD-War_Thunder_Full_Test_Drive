"""What changed: each time the game data is rebuilt for another game version, the old database is compared with the new one and
the result is kept in user/patches.json. Old versions can't be rebuilt, so that file isn't derived data: a rebuild or the cache
part of Uninstall leave it, only the user part removes it. UI in web/changes.js.

A comparison takes two game versions: a rebuild at the same version gives none, whatever the data source or the schema. A version
that goes down isn't a patch (the datamine ran ahead of the installed game, then the source changed): it's kept, and marked."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .paths import CACHE, DATA, USER

FILE = USER / "patches.json"
DEV_DATA = CACHE / "dev" / "data"  # builder.DEV's (builder imports this module): the datamine's newest version, built apart
KEEP = 30  # patches, newest first
WEAPON_FLAGS = ("ccm", "act", "ins", "dl", "loft", "ff", "wire", "iw")
NAMED = {"weapon": "weapons", "bullet": "bullets", "sensor": "sensors"}  # a list's unit -> its section of data/lang

# the page's groups, in its order
GROUPS = ("new", "gone", "br", "perf", "cost", "ammo", "arms", "weapon", "map")

# What's compared. A new value takes one line here and nothing else, the page reads this table from the API.
#   key     of the rows
#   group   of GROUPS
#   of      v a vehicle (vehicles.json + details.json), s a shell, w a Weapons tab item (armament.json), m a map; "": no value, added
#           or removed records; x any other value of a weapon's file (weapon_values.json), its path on the row
#   path    of the value in that record. A new field reads as nothing changed: see compare()
#   label   locale key
#   unit    after the number; of a name, or of a list of names, what names it (web/changes.js CH_NAMES)
#   better  1 higher, -1 lower, 0 not known or neither: no colour
#   digits  decimals of the value: a move under half the last one is rounding. None: a list of names, the rows say what came and went
# A key ending in ab, rb or sb is that game mode's: the page's mode filter goes by it.
FIELDS = (
    ("new", "new", "", (), "ch.new", "", 0, 0),
    ("gone", "gone", "", (), "ch.gone", "", 0, 0),
    ("rank", "br", "v", ("r",), "filters.rank", "", 0, 0),
    ("brab", "br", "v", ("br", 0), "ch.brab", "", 0, 1),
    ("brrb", "br", "v", ("br", 1), "ch.brrb", "", 0, 1),
    ("brsb", "br", "v", ("br", 2), "ch.brsb", "", 0, 1),
    ("spd", "perf", "v", ("s", "spd"), "stat.spd", "km/h", 1, 0),
    ("rev", "perf", "v", ("s", "rev"), "stat.rev", "km/h", 1, 0),
    ("pw", "perf", "v", ("s", "pw"), "stat.pw", "hp/t", 1, 1),
    ("hp", "perf", "v", ("s", "hp"), "stat.hp", "hp", 1, 0),
    ("t", "perf", "v", ("s", "t"), "stat.t", "t", 0, 1),
    ("armT", "perf", "v", ("s", "armT"), "stat.armT", "mm", 1, 0),
    ("armH", "perf", "v", ("s", "armH"), "stat.armH", "mm", 1, 0),
    ("trav", "perf", "v", ("s", "trav"), "stat.trav", "°/s", 1, 1),
    ("vert", "perf", "v", ("s", "vert"), "stat.vert", "°/s", 1, 1),
    ("cal", "perf", "v", ("s", "cal"), "stat.cal", "mm", 0, 1),
    ("rel", "perf", "v", ("s", "rel"), "stat.rel", "s", -1, 1),
    ("turn", "perf", "v", ("s", "turn"), "stat.turn", "s", -1, 1),
    ("roll", "perf", "v", ("s", "roll"), "stat.roll", "°/s", 1, 1),
    ("climb", "perf", "v", ("s", "climb"), "stat.climb", "m/s", 1, 1),
    ("alt", "perf", "v", ("s", "alt"), "stat.alt", "m", 0, 0),
    ("ceil", "perf", "v", ("s", "ceil"), "stat.ceil", "m", 1, 0),
    ("tw", "perf", "v", ("s", "tw"), "stat.tw", "", 1, 2),
    ("wl", "perf", "v", ("s", "wl"), "stat.wl", "kg/m²", -1, 1),
    ("disp", "perf", "v", ("s", "disp"), "stat.disp", "t", 0, 0),
    ("crew", "perf", "v", ("s", "crew"), "stat.crew", "", 0, 0),
    ("vne", "perf", "v", ("st", "lim", "v"), "lim.speed", "km/h", 1, 0),
    ("mach", "perf", "v", ("st", "lim", "m"), "lim.mach", "", 1, 2),
    ("gear", "perf", "v", ("st", "lim", "gear"), "lim.gear", "km/h", 1, 0),
    ("fuel", "perf", "v", ("st", "fuel"), "lim.fuel", "kg", 0, 0),
    ("mass", "perf", "v", ("st", "lim", "mass"), "lim.mass", "kg", 0, 0),
    ("rp", "cost", "v", ("s", "rp"), "stat.rp", "RP", -1, 0),
    ("sl", "cost", "v", ("s", "sl"), "stat.sl", "SL", -1, 0),
    ("repab", "cost", "v", ("s", "rep", 0), "ch.repab", "SL", -1, 0),
    ("reprb", "cost", "v", ("s", "rep", 1), "ch.reprb", "SL", -1, 0),
    ("repsb", "cost", "v", ("s", "rep", 2), "ch.repsb", "SL", -1, 0),
    ("slab", "cost", "v", ("s", "slm", 0), "ch.slab", "%", 1, 0),
    ("slrb", "cost", "v", ("s", "slm", 1), "ch.slrb", "%", 1, 0),
    ("slsb", "cost", "v", ("s", "slm", 2), "ch.slsb", "%", 1, 0),
    ("rpm", "cost", "v", ("s", "rpm"), "stat.rpm", "%", 1, 0),
    ("fr", "cost", "v", ("s", "fr"), "stat.fr", "", 1, 0),
    ("wa", "ammo", "v", ("wa",), "step.ammo", "bullet", 0, None),
    ("a.pen", "ammo", "s", ("pen",), "arm.col.pen", "mm", 1, 0),
    ("a.v", "ammo", "s", ("v",), "ch.muzzle", "m/s", 1, 0),
    ("a.m", "ammo", "s", ("m",), "arm.col.m", "kg", 0, 4),
    ("a.e", "ammo", "s", ("e",), "arm.col.e", "kg", 1, 4),
    ("wg", "arms", "v", ("wg",), "compare.guns", "weapon", 0, None),
    ("wp", "arms", "v", ("wp",), "compare.pylons", "weapon", 0, None),
    ("se", "arms", "v", ("se",), "ch.sensors", "sensor", 0, None),
    ("av", "arms", "v", ("av",), "ch.avionics", "avionics", 0, None),
    ("w.new", "weapon", "", (), "ch.new", "", 0, 0),
    ("w.gone", "weapon", "", (), "ch.gone", "", 0, 0),
    ("w.g", "weapon", "w", ("g",), "arm.col.type", "guidance", 0, 0),
    ("w.f", "weapon", "w", ("flags",), "ch.abilities", "flag", 0, None),
    ("w.ccmt", "weapon", "w", ("ccmt",), "ch.irccm", "irccm", 0, 0),
    ("w.v", "weapon", "w", ("v",), "arm.col.v", "m/s", 1, 0),
    ("w.acc", "weapon", "w", ("acc",), "arm.col.acc", "G", 1, 1),
    ("w.gl", "weapon", "w", ("gl",), "arm.col.gl", "G", 1, 0),
    ("w.ob", "weapon", "w", ("ob",), "arm.col.ob", "°", 1, 0),
    ("w.trk", "weapon", "w", ("trk",), "arm.col.trk", "°/s", 1, 0),
    ("w.lk", "weapon", "w", ("lk",), "arm.col.lk", "m", 1, 0),
    ("w.aa", "weapon", "w", ("aa",), "arm.col.aa", "m", 1, 0),
    ("w.rng", "weapon", "w", ("rng",), "arm.col.rng", "m", 1, 0),
    ("w.sr", "weapon", "w", ("sr",), "arm.col.sr", "m", 1, 0),
    ("w.pen", "weapon", "w", ("pen",), "arm.col.pen", "mm", 1, 0),
    ("w.tnt", "weapon", "w", ("tnt",), "arm.col.tnt", "kg", 1, 2),
    ("w.e", "weapon", "w", ("e",), "arm.col.e", "kg", 1, 2),
    ("w.m", "weapon", "w", ("m",), "arm.col.m", "kg", 0, 1),
    ("w.cal", "weapon", "w", ("cal",), "arm.col.cal", "mm", 0, 0),
    ("w.pf", "weapon", "w", ("pf",), "arm.col.pf", "m", 1, 1),
    ("w.burn", "weapon", "w", ("burn",), "arm.col.burn", "s", 1, 1),
    ("w.yld", "weapon", "w", ("yld",), "arm.col.yld", "kt", 1, 1),
    ("w.bh", "weapon", "w", ("bh",), "arm.col.bh", "m", 0, 0),
    ("w.x", "weapon", "x", (), "ch.raw", "", 0, None),  # drag, seeker field of view, fuses, thrust...: rows [id, key, old, new, path]
    ("m.new", "map", "", (), "ch.new", "", 0, 0),
    ("m.gone", "map", "", (), "ch.gone", "", 0, 0),
    ("m.n", "map", "m", ("n",), "ch.scenarios", "", 0, 0),
)
GROUP_OF = {f[0]: f[1] for f in FIELDS}
# the values of a weapon's file that a column above already shows, under its own name
SHOWN = {"mass", "explosiveMass", "caliber", "maxSpeedInWater", "distToLive", "yield", "loadFactorMax", "maxDistance", "rangeMax",
         "proximityFuse.radius", "cumulativeDamage.armorPower", "guidance.opticalSeeker.rangeBand0", "guidance.opticalSeeker.rangeBand1",
         "guidance.opticalSeeker.lockAngleMax", "guidance.opticalSeeker.rateMax", "guidance.radarSeeker.lockAngleMax",
         "guidance.radarSeeker.receiver.range", "guidance.guidanceAutopilot.reqAccelMax"}


def _load(path: Path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def read(folder: Path) -> dict:
    """The part of a database that's compared."""
    return {"meta": _load(folder / "meta.json") or {}, "vehicles": _load(folder / "vehicles.json") or [], "details": _load(folder / "details.json") or {},
            "armament": _load(folder / "armament.json") or {}, "scenarios": _load(folder / "scenarios.json") or [],
            "values": _load(folder / "weapon_values.json"),
            "names": _load(folder / "lang" / "en.json") or {}}


def _version(v) -> tuple:
    return tuple(map(int, v.split("."))) if isinstance(v, str) and re.fullmatch(r"\d+(\.\d+)*", v) else ()


def snapshot(folder: Path, version: str) -> dict | None:
    """The database a build is about to replace, if that build brings another game version: None for nothing to compare."""
    old = _load(folder / "meta.json")
    old = old.get("version") if isinstance(old, dict) else None
    return read(folder) if _version(old) and _version(version) and old != version else None


def _get(record, path: tuple):
    for p in path:
        try:
            record = record[p]
        except (KeyError, IndexError, TypeError):
            return None
    return record


def _same(a, b, digits: int) -> bool:
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_same(x, y, digits) for x, y in zip(a, b))
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) < 0.5 * 10 ** -digits
    return a == b


def _came_went(a, b, unit: str, names: tuple) -> tuple:
    """A list's changes, as the player sees them: another file under the same name is nothing, and what went keeps its name, that the
    new data won't have."""
    old, new = (n.get(NAMED.get(unit), {}) for n in names)
    a, b = set(a or ()), set(b or ())
    went, came = {old.get(k, k): k for k in a - b}, {new.get(k, k): k for k in b - a}
    return sorted(k if k in new else n for n, k in went.items() if n not in came), sorted(k for n, k in came.items() if n not in went)


def _rows(old: dict, new: dict, of: str, both_sides: bool, names: tuple) -> list:
    """What moved in the records of one kind that both sides have. both_sides: a value only one side has isn't a change."""
    fields = [f for f in FIELDS if f[2] == of]
    rows = []
    for rid in sorted(old.keys() & new.keys()):
        for key, _, _, path, _, unit, _, digits in fields:
            a, b = _get(old[rid], path), _get(new[rid], path)
            if (a is None and b is None) or (both_sides and (a is None or b is None)):
                continue
            if digits is None:
                went, came = _came_went(a, b, unit, names)
                if went or came:
                    rows.append([rid, key, went, came])
            elif not _same(a, b, digits):
                rows.append([rid, key, a, b])
    return rows


def _vehicles(db: dict) -> dict:
    return {v["id"]: {**v, **db["details"].get(v["id"], {})} for v in db["vehicles"]}


def _shells(vehicles: dict) -> dict:
    """Every gun's shells and belts: {gun|belt|bullets: record}. Its numbers don't depend on the vehicle, its gun's length does."""
    out: dict = {}
    for vid, v in vehicles.items():
        for gun in v.get("am") or []:
            for o in gun.get("opts") or []:
                s = o.get("s") or {}
                rec = out.setdefault("|".join([gun.get("w", ""), o.get("id", ""), *o.get("b", [])]), {
                    "pen": s["pc"][0][1] if s.get("pc") else None, "v": s.get("v"), "m": s.get("m"), "e": s.get("e"), "by": set()})
                rec["by"].add(vid)
    return out


def _shell_rows(old: dict, new: dict, both_sides: bool, names: tuple) -> list:
    """One row per change whatever the number of vehicles: rows = [shell, key, old, new, vehicles]. The same shell in two guns is one
    row when it changed the same way in both."""
    merged: dict = {}
    for sid, key, a, b in _rows(old, new, "s", both_sides, names):
        gun, belt, *bullets = sid.split("|")
        row = merged.setdefault((tuple(bullets) or (gun, belt), key, str(a), str(b)), [sid, key, a, b, set()])
        row[4] |= new[sid]["by"]
    return [[*r[:4], sorted(r[4])] for r in merged.values()]


def _weapons(db: dict) -> dict:
    return {it["id"]: {**it, "flags": [f for f in WEAPON_FLAGS if it.get(f)]} for it in db["armament"].get("items", [])}


def _close(a, b) -> bool:
    """Equal, but for the last bits of a float."""
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_close(x, y) for x, y in zip(a, b))
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool):
        return abs(a - b) <= 1e-9 * max(abs(a), abs(b), 1)
    return a == b


def _value_rows(old, new) -> list:
    """Every other value of the weapons' files: rows = [id, "w.x", old, new, path], None for one that came or went. Nothing when the
    database replaced didn't keep them (built by a WTFTD before 0.25.3)."""
    if not isinstance(old, dict) or not isinstance(new, dict):
        return []
    rows = []
    for wid in sorted(old.keys() & new.keys()):
        a, b = old[wid] or {}, new[wid] or {}
        rows += [[wid, "w.x", a.get(p), b.get(p), p] for p in sorted(a.keys() | b.keys()) if p not in SHOWN and not _close(a.get(p), b.get(p))]
    return rows


def _maps(db: dict) -> dict:
    out: dict = {}
    for s in db["scenarios"]:
        out.setdefault(s["map"], {"n": 0})["n"] += 1
    return out


def compare(old: dict, new: dict) -> dict:
    """One patch: what read() gives for both sides -> {id, from, to, at, rows}, rows = [id, key, old, new, ...]; back: the version went
    down; schema: the app's reading changed too. Across a schema bump a value only one side has is a field the bump added, or a
    vehicle it now covers: not a change. Between equal schemas it's one: a missile that gains a proximity fuse."""
    frm, to = old["meta"].get("version"), new["meta"].get("version")
    bump = old["meta"].get("schema") != new["meta"].get("schema")
    names = old["names"], new["names"]
    a, b = _vehicles(old), _vehicles(new)
    # a new one's nation, type, class and BRs: the page has them from the new data, but not from a dev server's
    rows = [[i, "new", None, new["names"].get("units", {}).get(i, i), [b[i].get("n"), b[i].get("c"), b[i].get("k"), b[i].get("br")]]
            for i in sorted(b.keys() - a.keys())]
    rows += [[i, "gone", old["names"].get("units", {}).get(i, i), None, [a[i].get("n"), a[i].get("c")]] for i in sorted(a.keys() - b.keys())]
    rows += _rows(a, b, "v", bump, names) + _shell_rows(_shells(a), _shells(b), bump, names)
    a, b = _weapons(old), _weapons(new)
    rows += [[i, "w.new", None, new["names"].get("arm", {}).get(i, i)] for i in sorted(b.keys() - a.keys())]
    rows += [[i, "w.gone", old["names"].get("arm", {}).get(i, i), None] for i in sorted(a.keys() - b.keys())]
    rows += _rows(a, b, "w", bump, names) + _value_rows(old.get("values"), new.get("values"))
    a, b = _maps(old), _maps(new)
    rows += [[i, "m.new", None, new["names"].get("maps", {}).get(i, i)] for i in sorted(b.keys() - a.keys())]
    rows += [[i, "m.gone", old["names"].get("maps", {}).get(i, i), None] for i in sorted(a.keys() - b.keys())]
    rows += _rows(a, b, "m", bump, names)
    entry = {"id": f"{frm}-{to}", "from": frm, "to": to, "at": new["meta"].get("built", 0), "rows": rows}
    if _version(to) < _version(frm):
        entry["back"] = 1
    if bump:
        entry["schema"] = 1
    if new["meta"].get("circuit") == "dev":  # built from a dev server client: the dev server's changes, not the live game's
        entry["circuit"] = "dev"
    return entry


def load() -> list:
    """The patches kept, newest first."""
    try:
        with open(FILE, encoding="utf-8") as f:
            patches = json.load(f)
    except FileNotFoundError:
        return []
    except ValueError:  # nothing can read it any more
        return []
    return patches if isinstance(patches, list) else []


def record(before: dict | None, folder: Path) -> dict | None:
    """Last step of a build that went through: keeps its comparison with the database it replaced. A patch that moved nothing WTFTD
    reads takes no place. Written at once: a build stopped halfway leaves nothing, and a stopped write leaves the file as it was."""
    if not before:
        return None
    entry = compare(before, read(folder))
    if not entry["rows"]:
        return None
    kept = [entry, *(p for p in load() if p.get("id") != entry["id"])][:KEEP]  # the same versions again, after switching source and back
    FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(kept, f, ensure_ascii=False, separators=(",", ":"))
    tmp.replace(FILE)
    return entry


def _counts(rows: list) -> dict:
    out: dict = {}
    for r in rows:
        group = GROUP_OF.get(r[1])
        if group:
            out[group] = out.get(group, 0) + 1
    return out


_DEV: dict = {}  # (both builds) -> their comparison: two databases are read and compared once, not at each visit


def dev(live: Path | None = None, other: Path | None = None) -> dict | None:
    """The game's data beside the dev server's (the datamine's newest version, built apart on request): an entry like a patch's,
    id "dev", from the game's version to the datamine's. None without it, or at the same version. Never kept in FILE."""
    live, other = live or DATA, other or DEV_DATA
    a, b = (_load(f / "meta.json") or {} for f in (live, other))
    if a.get("source") == "datamine" and b.get("source") == "game":  # the app reads the datamine: still the game on the left
        live, other, a, b = other, live, b, a
    same_source = a.get("source") is not None and a.get("source") == b.get("source")  # left from before a source change: not a pair
    if not a.get("version") or not b.get("version") or a["version"] == b["version"] or same_source:
        return None
    key = (str(live), a.get("built"), b.get("built"), a["version"], b["version"])
    if key not in _DEV:
        _DEV.clear()
        _DEV[key] = {**compare(read(live), read(other)), "id": "dev", "dev": 1}
        if _version(b["version"])[:2] > _version(a["version"])[:2]:  # a whole version ahead: the dev server's; a patch ahead isn't
            _DEV[key]["ahead"] = 1
    return _DEV[key]


def index() -> dict:
    """What the page needs before opening a patch: the table, and the patches without their rows; the dev server's first."""
    keys = ("group", "of", "label", "unit", "better", "digits")
    d = dev()
    return {"groups": GROUPS, "fields": {f[0]: dict(zip(keys, (*f[1:3], *f[4:]))) for f in FIELDS},
            "patches": [{**{k: v for k, v in p.items() if k != "rows"}, "counts": _counts(p["rows"])} for p in [*([d] if d else []), *load()]]}


def rows(pid: str) -> list | None:
    if pid == "dev":
        d = dev()
        return d["rows"] if d else None
    return next((p["rows"] for p in load() if p.get("id") == pid), None)
