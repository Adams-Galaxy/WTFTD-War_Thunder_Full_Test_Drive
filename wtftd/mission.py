"""Builds a user mission from an official test drive / test flight scenario.

The official mission is kept as-is (targets, triggers, imports of in-game templates);
only the player unit, its loadout and a few mission settings are changed.
"""
from __future__ import annotations

import copy
import json
import math
import re
from pathlib import Path

from . import blk

from .paths import DATA

ENVIRONMENTS = ["Day", "Morning", "Noon", "Evening", "Dusk", "Dawn", "Night"]
WEATHERS = ["clear", "good", "hazy", "thin_clouds", "cloudy", "cloudy_windy", "overcast", "poor", "rain", "thunder", "blind"]
MISSION_TYPES = ["singleMission", "testFlight"]
DIFFICULTIES = ("arcade", "realistic", "hardcore")  # the game's names (Simulator is "hardcore")

UNIT_DEFAULTS = {
    "tankModels": {"army": 1, "count": 1, "formation_type": "rows", "formation_div": 3,
                   "formation_step": [2.5, 2.0], "formation_noise": [0.1, 0.1], "uniqueName": "",
                   "attack_type": "fire_at_will"},
    "ships": {"army": 1, "count": 1, "formation_type": "rows", "formation_div": 3,
              "formation_step": [2.5, 2.0], "formation_noise": [0.1, 0.1], "uniqueName": "",
              "attack_type": "fire_at_will"},
    "armada": {"army": 1, "count": 1, "free_distance": 70.0, "floating_distance": 50.0,
               "minimum_distance_to_earth": 20.0, "altLimit": 6000.0, "attack_type": "fire_at_will",
               "skill": 4, "plane": {"wing_formation": "Diamond", "row_distances": 3.0, "col_distances": 3.0,
                                     "super_formation": "Diamond", "super_row_distances": 1.5,
                                     "super_col_distances": 1.5, "ai_skill": "NORMAL", "task": "FLY_WAYPOINT"}},
}


class MissionError(Exception):
    pass


def load_scenario(sid: str) -> dict:
    if not re.fullmatch(r"[a-z0-9_]+", sid or ""):
        raise MissionError("Invalid scenario id")
    path = DATA / "scenarios" / f"{sid}.json"
    if not path.exists():
        raise MissionError(f"Unknown scenario: {sid}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _difficulty_data() -> dict | None:
    try:
        return json.loads((DATA / "difficulty.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None  # data built before the file existed: the game's briefing asks as before


def difficulty_block(name: str, changes, kind: str) -> dict | None:
    """The mission's own difficulty (netDifficultyBlk): the game's preset for this kind of vehicle with the player's
    changes, each checked against what the game's Custom window offers. None without the data."""
    data = _difficulty_data() or {}
    preset = ((data.get("presets") or {}).get(kind) or {}).get(name)
    if not isinstance(preset, dict):
        return None
    allowed = {o.get("k"): o.get("n") for o in data.get("options") or [] if isinstance(o, dict)}
    out = dict(preset)
    for k, v in changes.items() if isinstance(changes, dict) else ():
        n, was = allowed.get(k), type(preset.get(k))
        if n == 0 and type(v) in (bool, int) and v in (0, 1):
            out[k] = was(v) if was in (bool, int) else v  # some on/off settings are 0/1 in the game's files: keep its type
        elif n and type(v) is int and 0 <= v < n:
            out[k] = v
    out["setDifficulty"] = 3  # Custom, as the game's own events write it
    return out


def _as_list(v):
    return v if isinstance(v, list) else ([] if v is None else [v])


def _find_player(units: dict, wing: str):
    for block, entries in units.items():
        lst = _as_list(entries)
        for i, u in enumerate(lst):
            if isinstance(u, dict) and u.get("name") == wing:
                return block, i, u
    return None, None, None


def _remove_unit(units: dict, block: str, index: int):
    entries = units[block]
    if isinstance(entries, list):
        entries.pop(index)
        if not entries:
            del units[block]
    else:
        del units[block]


def _append_unit(units: dict, block: str, unit: dict):
    if block not in units:
        units[block] = unit
    elif isinstance(units[block], list):
        units[block].append(unit)
    else:
        units[block] = [units[block], unit]


def _strip_airfield_spawn(node, wing: str):
    """Removes spawnOnAirfield actions for the player (used for air starts)."""
    if isinstance(node, dict):
        for k in list(node):
            v = node[k]
            if k == "spawnOnAirfield":
                kept = [a for a in _as_list(v) if not (isinstance(a, dict) and wing in _as_list(a.get("objects")))]
                if not kept:
                    del node[k]
                else:
                    node[k] = kept if len(kept) > 1 else kept[0]
            else:
                _strip_airfield_spawn(v, wing)
    elif isinstance(node, list):
        for x in node:
            _strip_airfield_spawn(x, wing)


EDITABLE_BLOCKS = ("tankModels", "armada", "ships")
COUNTRIES = ("usa", "germany", "ussr", "britain", "japan", "china", "italy", "france", "sweden", "israel")
OBJECT_BLOCKS = ("air_defence", "structures", "wheeled_vehicles", "tracked_vehicles", "radars", "infantry", "objectGroups")  # placed, not swapped
ATTACK_TYPES = ("fire_at_will", "return_fire", "hold_fire", "dont_aim")
ROUTE_POINTS = 40
WAVE_PAUSE = 5.0  # s between the end of a wave and the next one
_CLASS = re.compile(r"^[A-Za-z0-9_\-.]{1,120}$")


def _area_pos(m: dict, name) -> dict | None:
    a = (m.get("areas") or {}).get(name) if isinstance(name, str) else None
    try:
        x, y, z = (float(c) for c in a["tm"][3])
        return {"x": round(x, 1), "y": round(y, 1), "z": round(z, 1)}
    except (TypeError, KeyError, IndexError, ValueError):
        return None


def _is_start_trigger(t: dict) -> bool:
    """Runs once when the mission starts, whatever the player does."""
    ev = t.get("events") or {}
    return not (t.get("conditions") or {}) and (not ev or "initMission" in ev) and "periodicEvent" not in ev


def _trigger_actions(m: dict):
    for name, t in (m.get("triggers") or {}).items():
        if isinstance(t, dict) and isinstance(t.get("actions"), dict):
            yield name, t, t["actions"]


def player_spawn(m: dict, wing: str) -> dict | None:
    """Where the player really appears when the scenario spawns them on a runway (spawnOnAirfield):
    the airfield's spawn point, heading down the runway."""
    airfields = {}
    for _, _, a in _trigger_actions(m):
        for af in _as_list(a.get("addAirfield")):
            if isinstance(af, dict) and af.get("runwayStart"):
                airfields[af["runwayStart"]] = af
    for _, t, a in _trigger_actions(m):
        if not _is_start_trigger(t):
            continue
        for sp in _as_list(a.get("spawnOnAirfield")):
            if not isinstance(sp, dict) or wing not in _as_list(sp.get("objects")):
                continue
            af = airfields.get(sp.get("runwayName"))
            start, end = _area_pos(m, (af or {}).get("runwayStart")), _area_pos(m, (af or {}).get("runwayEnd"))
            pos = _area_pos(m, (af or {}).get("spawnPoint")) or start
            if not pos:
                return None
            out = {**pos, "airfield": sp.get("runwayName")}
            if start and end:
                out["yaw"] = round(math.degrees(math.atan2(end["z"] - start["z"], end["x"] - start["x"])), 1)
                out["runway"] = [[start["x"], start["z"]], [end["x"], end["z"]]]
            return out
    return None


def teleports(m: dict) -> dict:
    """Units the scenario's triggers move to an area: {unit: {x, y, z, area, start}} where start
    means it happens as soon as the mission starts (else later, e.g. a periodic respawn)."""
    out = {}
    for _, t, a in _trigger_actions(m):
        start = _is_start_trigger(t)
        moves = [x for x in _as_list(a.get("unitMoveTo")) if isinstance(x, dict) and x.get("move_type") == "teleport"]
        moves += [x for x in _as_list(a.get("unitRespawn")) if isinstance(x, dict)]
        for mv in moves:
            pos = _area_pos(m, mv.get("target"))
            if not pos:
                continue
            for obj in _as_list(mv.get("object")):
                if isinstance(obj, str) and (obj not in out or start and not out[obj]["start"]):
                    out[obj] = {**pos, "area": mv.get("target"), "start": start}
    return out


def _strip_unit_moves(node, names: set):
    """Removes the given units from the scenario's teleports / respawns (they were moved in the editor)."""
    if isinstance(node, dict):
        for k in list(node):
            v = node[k]
            if k in ("unitMoveTo", "unitRespawn"):
                kept = []
                for a in _as_list(v):
                    if isinstance(a, dict) and (k == "unitRespawn" or a.get("move_type") == "teleport"):
                        objs = [o for o in _as_list(a.get("object")) if o not in names]
                        if not objs:
                            continue
                        a["object"] = objs if len(objs) > 1 else objs[0]
                    kept.append(a)
                if not kept:
                    del node[k]
                else:
                    node[k] = kept if len(kept) > 1 else kept[0]
            else:
                _strip_unit_moves(v, names)
    elif isinstance(node, list):
        for x in node:
            _strip_unit_moves(x, names)


def scenario_units(sid: str) -> dict:
    """Units of a scenario for the map editor (only those defined in the mission itself)."""
    m = load_scenario(sid)
    wing = ((m.get("mission_settings") or {}).get("player") or {}).get("wing")
    out = []
    for block, entries in (m.get("units") or {}).items():
        if block == "squad":
            continue
        for u in _as_list(entries):
            if not isinstance(u, dict) or not isinstance(u.get("tm"), list):
                continue
            try:
                x, y, z = (float(c) for c in u["tm"][3])
                fx, fz = float(u["tm"][0][0]), float(u["tm"][0][2])
            except (TypeError, ValueError, IndexError):
                continue
            props = u.get("props") or {}
            out.append({
                "name": u.get("name"), "block": block, "cls": u.get("unit_class", ""), "tpl": False,
                "x": round(x, 1), "y": round(y, 1), "z": round(z, 1), "yaw": round(math.degrees(math.atan2(fz, fx)), 1),
                "army": props.get("army", 0), "count": props.get("count", 1), "attack": props.get("attack_type", ""),
                "moves": bool(u.get("way")), "player": u.get("name") == wing,
                "edit": block in EDITABLE_BLOCKS and u.get("name") != wing,
                # delayed: not there at start, the scripts bring it in (or not) while the mission runs
                **({"runtime": 1} if props.get("isDelayed") and u.get("name") != wing else {}),
            })
    # units of the game templates the mission imports: can be removed / frozen / made passive or hunting
    tpl_path = DATA / "scenarios" / f"{sid}.units.json"
    level = (((m.get("mission_settings") or {}).get("mission") or {}).get("level") or "")
    level = level.replace("\\", "/").rsplit("/", 1)[-1].replace(".bin", "").lower()
    try:
        water = set(json.loads((DATA / "water.json").read_text(encoding="utf-8")))
    except (OSError, ValueError):
        water = None  # unknown: keep every unit
    if tpl_path.exists():
        names = {u["name"] for u in out}
        swap = swappable_units(m)  # their vehicle can change (the mission then declares them)
        try:
            tpl = json.loads(tpl_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            tpl = []
        for u in tpl:
            if water is not None and level not in water and u.get("block") == "ships" and u.get("runtime"):
                continue  # template ships the scenario only brings in on maps with water
            if isinstance(u, dict) and u.get("name") and u["name"] not in names:
                out.append({**u, "tpl": True, "moves": False, "player": False,
                            **({"swap": 1} if u["name"] in swap and u.get("block") in EDITABLE_BLOCKS else {}),
                            # real vehicles only (bombing targets / dummies stay scenery)
                            "edit": u.get("block") in EDITABLE_BLOCKS + ("air_defence", "tracked_vehicles", "wheeled_vehicles")
                            and u.get("army") == 2 and not str(u.get("cls", "")).startswith("dummy")})
    level = (((m.get("mission_settings") or {}).get("mission") or {}).get("level") or "")
    level = level.replace("\\", "/").rsplit("/", 1)[-1].replace(".bin", "").lower()
    me = next((u for u in out if u["player"]), None)
    tp = teleports(m)
    for u in out:
        if u["name"] in tp and not u["player"]:
            u["tp"] = tp[u["name"]]
    spawn = player_spawn(m, wing) if wing else None
    if not spawn and wing in tp and tp[wing]["start"]:
        spawn = {k: tp[wing][k] for k in ("x", "y", "z", "area")}
    return {"wing": wing, "units": out, "level": level, "army": (me or {}).get("army") or 1, "spawn": spawn,
            "areas": scenario_zones(sid, m)}


def zone_info(sid: str) -> dict | None:
    """What the scenario's scripts do with its zones (builder.zone_roles + "used"); None when unknown."""
    try:
        z = json.loads((DATA / "scenarios" / f"{sid}.zones.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if isinstance(z, list):  # older data: the used zones only
        return {"used": z}
    return z if isinstance(z, dict) else None


# zones of the battle maps (builder.build_battle_scenarios): capture zones are named by their letter
BATTLE_ZONES = {"wtftd_enemy_spawn": "@editor.enemySpawn", "wtftd_battle_area": "@editor.battleArea"}


def scenario_zones(sid: str, m: dict) -> list:
    """The mission's areas for the editor: centre, size, heading, shape, whether its scripts use it
    (where they spawn / respawn / send units), the units they put there and whether you start there."""
    info = zone_info(sid) or {}
    used = set(info.get("used") or [])
    spawns = info.get("spawns") or {}
    player = set(info.get("player") or [])
    tf = _test_flight_spawn(m)
    if tf:  # test flights: of all their start zones, the mission's air_spawn_point picks one (and its variants)
        player = {n for n in player if n == tf[1] or n.startswith(tf[1] + "_")}
    out = []
    for name, a in (m.get("areas") or {}).items():
        try:
            tm = a["tm"]
            x, y, z = (float(c) for c in tm[3])
            sx = math.hypot(float(tm[0][0]), float(tm[0][2]))
            sy = math.hypot(*(float(c) for c in tm[1]))
            sz = math.hypot(float(tm[2][0]), float(tm[2][2]))
            yaw = math.degrees(math.atan2(float(tm[0][2]), float(tm[0][0])))
        except (TypeError, KeyError, IndexError, ValueError):
            continue
        label = BATTLE_ZONES.get(name) or (name[-1] if name.startswith("wtftd_capture_") else "")
        out.append({"name": name, "type": str(a.get("type", "")), "x": round(x, 1), "y": round(y, 1), "z": round(z, 1),
                    "sx": round(sx, 1), "sy": round(sy, 1), "sz": round(sz, 1), "yaw": round(yaw, 1),
                    "used": name in used or name == "wtftd_spawn" or bool(label), **({"label": label} if label else {}),
                    **({"units": spawns[name][:80]} if spawns.get(name) else {}), **({"player": 1} if name in player else {})})
    return out


def _yaw_tm(deg: float, x: float, y: float, z: float):
    t = math.radians(deg)
    return [[math.cos(t), 0.0, math.sin(t)], [0.0, 1.0, 0.0], [-math.sin(t), 0.0, math.cos(t)], [x, y, z]]


def set_vehicle(u: dict, e: dict):
    """A unit's vehicle and loadout from the map editor: {cls, loadout: {preset, ammo, _groups, _unitClass}}."""
    cls = e.get("cls")
    if cls and _CLASS.match(str(cls)) and cls != u.get("unit_class"):
        u["unit_class"] = cls
        u["weapons"] = ""
        for n in range(4):
            if f"bullets{n}" in u:
                u[f"bullets{n}"] = ""
    lo = e.get("loadout")
    if isinstance(lo, dict):  # the unit's own loadout (AI), set in the app like the player's
        if _CLASS.match(str(lo.get("_unitClass") or "")):
            u["unit_class"] = lo["_unitClass"]  # custom aircraft of its own (pylons)
        preset = str(lo.get("preset") or "")
        if re.fullmatch(r"[A-Za-z0-9_\-.]{0,120}", preset):
            u["weapons"] = preset
        if isinstance(lo.get("ammo"), list):
            write_bullets(u, lo["ammo"], lo.get("_groups"))


# ---------------------------------------------------------------------------- units taken over from game templates
# A scenario that imports the game's templates (test flights: their targets) keeps importing them (their scripts run
# as the game wrote them: the datamine's JSON loses the order of repeated actions, so they are never rewritten), but
# the units of a template the mission imports directly can be declared by the mission itself instead
# (importUnits: no on that import): their vehicle can then change. The scripts find them by name, as they find the
# player's unit, which the mission declares too.
TEMPLATES = DATA / "templates"


def template_key(path: str) -> str:
    """'gameData/missions/training/testFlight/x.blk' -> 'training__testflight__x' (data/templates/<key>.json)."""
    rel = str(path).replace("\\", "/").lower()
    rel = re.sub(r"^gamedata/missions/", "", rel)
    rel = re.sub(r"\.blkx?$", "", rel)
    return re.sub(r"[^a-z0-9_.-]+", "__", rel).strip("_.")


def _template(path: str) -> dict | None:
    try:
        d = json.loads((TEMPLATES / f"{template_key(path)}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def _import_records(doc: dict) -> list:
    imp = doc.get("imports")
    recs = _as_list(imp.get("import_record")) if isinstance(imp, dict) else []
    return [r for r in recs if isinstance(r, dict) and isinstance(r.get("file"), str) and r["file"]]


def _record_units(rec: dict) -> dict | None:
    """{block: [unit]} a direct import brings, when the mission can declare them itself: a template of its own
    (no further imports, whose units would come with it) that WTFTD has; excluded names left out."""
    sub = _template(rec["file"])
    if sub is None or _import_records(sub) or rec.get("importUnits") is False:
        return None
    ex = rec.get("excludes")
    skip = {x for x in _as_list(ex.get("exclude")) if isinstance(x, str)} if isinstance(ex, dict) else set()
    out = {}
    for block, entries in (sub.get("units") or {}).items():
        kept = [u for u in _as_list(entries) if isinstance(u, dict) and u.get("name") and u["name"] not in skip]
        if kept:
            out[block] = kept
    return out


def swappable_units(m: dict) -> set:
    """Names of the template units whose vehicle can change (take_over_units)."""
    out = set()
    for rec in _import_records(m):
        for entries in (_record_units(rec) or {}).values():
            out |= {u["name"] for u in entries}
    return out


def take_over_units(m: dict, names: set) -> set:
    """The mission declares the units of each template it imports directly that holds one of names (that import
    no longer brings units). Returns the names of the units now declared by the mission."""
    units = m.setdefault("units", {})
    have = {u.get("name") for v in units.values() for u in _as_list(v) if isinstance(u, dict)}
    brought = set()
    for rec in _import_records(m):
        got = _record_units(rec)
        if not got or not any(u["name"] in names for entries in got.values() for u in entries):
            continue
        rec["importUnits"] = False
        for block, entries in got.items():
            for u in entries:
                if u["name"] not in have:
                    _append_unit(units, block, copy.deepcopy(u))
                    have.add(u["name"])
                    brought.add(u["name"])
    # editor layers the units sit on
    used = [u.get("objLayer") for v in units.values() for u in _as_list(v) if isinstance(u, dict) and isinstance(u.get("objLayer"), int)]
    layers = m.get("objLayers") if isinstance(m.get("objLayers"), dict) else {}
    lst = _as_list(layers.get("layer"))
    if used and max(used) >= len(lst):
        m["objLayers"] = {**layers, "layer": lst + [{"enabled": True} for _ in range(max(used) + 1 - len(lst))]}
    return brought


def _route(u: dict, e: dict):
    """Points drawn in the editor: the game drives the unit along them by itself, from the start or when it appears."""
    try:
        speed = max(1.0, min(float(e.get("routeSpeed") or 40), 3000.0))
    except (TypeError, ValueError):
        speed = 40.0
    way = {}
    for p in (e.get("route") or [])[:ROUTE_POINTS]:
        try:
            pos = [float(p["x"]), float(p["y"]), float(p["z"])]
        except (KeyError, TypeError, ValueError):
            continue
        way[f"{u['name']}_wp_{len(way) + 1:02d}"] = {
            "type": "normal", "tm": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0], pos],
            "props": {"speed": speed, "moveType": "MOVETO_STRAIGHT", "tas": False, "shouldKeepFormation": False,
                      "canUsePathFinder": False}}
    if way:
        u["way"] = way
        u["closed_waypoints"] = bool(e.get("routeLoop"))


def apply_waves(m: dict, waves: dict, edits: dict, stay: list, passive: list):
    """Enemies by wave (waves: {number: [unit]}): the first is there at the start, each next one comes when the one
    before is destroyed, the way the game's test flights bring their targets in: delayed units, unitRespawn in a zone
    of their own. waveLoop: after the last one, the first again."""
    triggers = m.setdefault("triggers", {"isCategory": True, "is_enabled": True})
    if not isinstance(triggers, dict):
        return
    order = sorted(waves)
    loop = bool(edits.get("waveLoop"))
    text = _clean_text(edits.get("waveText"), "Wave {n}")
    for k, n in enumerate(order):
        _append_unit(m["units"], "squad", {"name": f"wtftd_wave_{n}", "tm": copy.deepcopy(waves[n][0]["tm"]),
                                           "props": {"squad_members": [u["name"] for u in waves[n]]}})
        for u in waves[n]:
            if k:
                u["props"]["isDelayed"] = True
            if k or loop:
                area = {"type": "Sphere", "objLayer": 0, "props": {}}
                _place_area(area, u["tm"])
                m.setdefault("areas", {})[f"wtftd_wave_{u['name']}"] = area

    def bring(k: int) -> dict:
        names = [u["name"] for u in waves[order[k]]]
        actions: dict = {"wait": {"time": WAVE_PAUSE}}
        if loop:  # they were destroyed: back to life first
            actions["unitRestore"] = {"target": names, "fullRestore": True, "ressurectIfDead": True, "ammoRestore": True}
        spawns = [{"delay": 0.0, "offset": [0.0, 0.0, 0.0], "object": x, "target": f"wtftd_wave_{x}"} for x in names]
        actions["unitRespawn"] = spawns if len(spawns) > 1 else spawns[0]
        # lost on coming in: the game's scripts set their targets passive again too
        held = [{"object": [x for x in names if x in group], flag: True} for group, flag in ((stay, "cannotMove"), (passive, "cannotShoot"))
                if set(names) & set(group)]
        if held:
            actions["unitSetProperties"] = held if len(held) > 1 else held[0]
        actions["playHint"] = _hint(text.replace("{n}", str(k + 1)))
        return actions

    for k, n in enumerate(order):
        after = k + 1 if k + 1 < len(order) else 0 if loop else None
        if after is None:
            break
        actions = bring(after)
        if after != k and (after + 1 < len(order) or loop):
            actions["triggerEnable"] = {"target": [f"wtftd_wave_{order[after]}_end"]}
        t = _trigger({"periodicEvent": {"time": 2.0}}, actions, after == k)
        t["is_enabled"] = k == 0
        t["conditions"] = {"unitWhenCountMatches": {"object_type": "isAlive", "object_marking": 0, "func": "less", "value": 1,
                                                    "object": f"wtftd_wave_{n}"}}
        triggers[f"wtftd_wave_{n}_end"] = t


def _wave_units(units: dict) -> set:
    return {n for s in _as_list(units.get("squad")) if isinstance(s, dict) and str(s.get("name")).startswith("wtftd_wave_")
            for n in _as_list((s.get("props") or {}).get("squad_members"))}


def apply_edits(m: dict, wing: str, edits: dict, sid: str | None = None):
    """Map editor changes:
    units: {name: {cls, count, attack, behavior, remove, side, x, y, z}}   existing units of the scenario
    add:   [{block, cls, x, y, z, yaw, count, attack, behavior, speed, side, loadout}]   new units
    loadout: {vehicle, preset, ammo, _groups, _unitClass}   an AI unit's weapons / belts (server._prepare_ai)
    player: {x, y, z, yaw}   moves the player's start
    side:     "ally" | "enemy" (default for added units: enemy)
    behavior: "" | "stay" (cannotMove) | "hunt" (unitAttackTarget on the player)
              | "follow" (unitMoveTo following the player: escort) | "route" (route, routeSpeed, routeLoop: _route)
    wave:     1..9 on enemies (apply_waves; waveLoop, waveText at the top of edits)
    attack:   "" | fire_at_will | return_fire | hold_fire (+ cannotShoot)"""
    units = m.setdefault("units", {})
    stay, hunt, passive, sleep, follow, shoot = [], [], [], [], [], []
    waves: dict = {}
    _, _, pu = _find_player(units, wing)
    my_army = (pu.get("props") or {}).get("army", 1) if pu else 1
    enemy_army = 2 if my_army == 1 else 1

    def apply(u: dict, e: dict):
        name = u["name"]
        set_vehicle(u, e)
        props = u.setdefault("props", {})
        if e.get("count"):
            props["count"] = max(1, min(int(e["count"]), 12))
        attack = e.get("attack")
        if attack in ATTACK_TYPES:
            props["attack_type"] = attack
            if attack == "hold_fire":
                passive.append(name)
        if e.get("side") in ("ally", "enemy"):
            props["army"] = my_army if e["side"] == "ally" else enemy_army
        if "x" in e and "z" in e and isinstance(u.get("tm"), list) and len(u["tm"]) == 4:
            try:
                pos = u["tm"][3]
                u["tm"][3] = [float(e["x"]), float(e.get("y", pos[1])), float(e["z"])]
            except (TypeError, ValueError, IndexError):
                pass
        if e.get("yaw") is not None and isinstance(u.get("tm"), list) and len(u["tm"]) == 4:
            try:
                u["tm"] = _yaw_tm(float(e["yaw"]), *(float(c) for c in u["tm"][3]))
            except (TypeError, ValueError):
                pass
        behavior(name, e)
        if e.get("behavior") == "route":
            _route(u, e)
        if e.get("wave") in range(1, 10) and props.get("army") != my_army:
            waves.setdefault(int(e["wave"]), []).append(u)

    def behavior(name: str, e: dict):
        b = e.get("behavior")
        if b == "stay":
            stay.append(name)
        elif b == "hunt":
            hunt.append(name)
        elif b == "follow":
            follow.append(name)

    edits_units = edits.get("units") or {}
    own = {u.get("name") for entries in units.values() for u in _as_list(entries) if isinstance(u, dict)}
    for name, e in edits_units.items():
        if name in own or not isinstance(e, dict) or not _CLASS.match(str(name).replace(" ", "_")):
            continue
        if e.get("remove"):  # unit from an imported game template
            sleep.append(name)
            continue
        behavior(name, e)
        if e.get("attack") == "hold_fire":
            passive.append(name)
        elif e.get("attack") == "fire_at_will":  # a template unit: made to fire by a start trigger
            shoot.append(name)
    for block, entries in units.items():
        if block not in EDITABLE_BLOCKS:
            continue
        for u in _as_list(entries):
            if not isinstance(u, dict) or u.get("name") == wing:
                continue
            e = edits_units.get(u.get("name"))
            if not isinstance(e, dict):
                continue
            if e.get("remove"):
                sleep.append(u["name"])
                continue
            apply(u, e)

    moved = {n for n, e in edits_units.items() if isinstance(e, dict) and "x" in e and "z" in e and not e.get("remove")}
    if isinstance(edits.get("player"), dict):
        moved.add(wing)
    if moved:  # placed on the map: drop the scenario's teleports at mission start (respawns later are kept)
        for _, t, a in _trigger_actions(m):
            if _is_start_trigger(t):
                _strip_unit_moves(a, moved)

    for i, a in enumerate((edits.get("add") or [])[:300]):
        if not isinstance(a, dict) or a.get("block") not in EDITABLE_BLOCKS + OBJECT_BLOCKS or not _CLASS.match(str(a.get("cls", ""))):
            continue
        block = a["block"]
        try:
            x, y, z = float(a.get("x", 0)), float(a.get("y", 0)), float(a.get("z", 0))
            yaw = float(a.get("yaw", 0))
        except (TypeError, ValueError):
            continue
        army = my_army if a.get("side") == "ally" else enemy_army
        if block == "objectGroups":  # an asset, as the game's own missions place them: no crew, no orders
            _append_unit(units, block, {"name": f"wtftd_unit_{i + 1:02d}", "tm": _yaw_tm(yaw, x, y, z), "unit_class": a["cls"], "objLayer": 2,
                                        "props": {"army": army, "active": True}})
            continue
        props = copy.deepcopy(UNIT_DEFAULTS.get(block, UNIT_DEFAULTS["tankModels"]))
        props["army"] = army
        props["attack_type"] = "fire_at_will"
        u = {"name": f"wtftd_unit_{i + 1:02d}", "tm": _yaw_tm(yaw, x, y, z), "unit_class": a["cls"], "objLayer": 1,
             "closed_waypoints": False, "isShipSpline": False, "shipTurnRadius": 100.0,
             "weapons": "", "bullets0": "", "bullets1": "", "bullets2": "", "bullets3": "",
             "bulletsCount0": 0, "bulletsCount1": 0, "bulletsCount2": 0, "bulletsCount3": 0,
             "crewSkillK": 0.0, "applyAllMods": False, "props": props, "way": {}}
        if block == "armada":
            try:
                props["speed"] = float(a.get("speed", 400))
            except (TypeError, ValueError):
                props["speed"] = 400.0
        _append_unit(units, block, u)
        apply(u, a)

    for name, e in (edits.get("areas") or {}).items():  # zones moved in the editor
        a = (m.get("areas") or {}).get(name)
        try:
            pos = a["tm"][3]
            a["tm"][3] = [float(e["x"]), float(e.get("y", pos[1])), float(e["z"])]
        except (TypeError, KeyError, IndexError, ValueError):
            continue
    player = edits.get("player")
    if isinstance(player, dict):
        _strip_airfield_spawn(m.get("triggers"), wing)  # the start was placed on the map: no runway spawn
        if pu:
            try:
                pu["tm"] = _yaw_tm(float(player.get("yaw", 0)), float(player["x"]), float(player["y"]), float(player["z"]))
            except (KeyError, TypeError, ValueError):
                pass
            else:
                _hold_start(m, wing, pu["tm"], player, zone_info(sid) if sid else None)

    if waves:
        apply_waves(m, waves, edits, stay, passive)
    actions: dict = {}
    if sleep:
        actions["unitPutToSleep"] = {"target": sleep}
    props_actions = []
    if stay:
        props_actions.append({"object": stay, "cannotMove": True})
    if passive:
        props_actions.append({"object": passive, "cannotShoot": True})
    if props_actions:
        actions["unitSetProperties"] = props_actions if len(props_actions) > 1 else props_actions[0]
    if follow:
        actions["unitMoveTo"] = {"target": wing, "follow_target": True, "object": follow, "shouldKeepFormation": False,
                                 "teleportHeightType": "absolute", "useUnitHeightForTele": True, "teleportHeightValue": 0.0,
                                 "horizontalDirectionForTeleport": True, "object_marking": 0, "target_marking": 0,
                                 "waypointReachedDist": 10.0, "recalculatePathDist": -1.0, "follow_radius": 60.0,
                                 "follow_offset": [-60.0, 0.0, 40.0]}
    triggers = m.setdefault("triggers", {"isCategory": True, "is_enabled": True}) if actions or shoot or hunt else None
    if actions and isinstance(triggers, dict):
        triggers["wtftd_editor"] = _trigger({"initMission": {}}, actions, False)
    if shoot and isinstance(triggers, dict):
        # template units made to attack: the templates' scripts set their targets passive again when they
        # (re)spawn them (cannotShoot), so this holds every 3 s
        triggers["wtftd_attack"] = _trigger({"periodicEvent": {"time": 3.0}}, {"unitSetProperties": {
            "object": shoot, "attack_type": "fire_at_will", "cannotShoot": False}}, True)
    if hunt and isinstance(triggers, dict):
        # units hunting you: the order is given again every 10 s. At start you may not be there yet (test flights: the
        # templates' scripts spawn you a moment later, the order is lost), template units come in later on a route
        # of their own (aircraft on it engage no one)
        attacks = [{"playerAttracted": True, "object": n, "target": wing, "fireRandom": False} for n in hunt]
        triggers["wtftd_hunt"] = _trigger({"periodicEvent": {"time": 10.0}},
                                          {"unitAttackTarget": attacks if len(attacks) > 1 else attacks[0]}, True)


def _test_flight_spawn(m: dict) -> tuple[dict, str] | None:
    """Test flights (the game's test_flight_template): (mission settings, base name of the air start zone)."""
    mission = (m.get("mission_settings") or {}).get("mission") or {}
    try:
        base = f"spawn_area0{int(mission['air_spawn_point'])}"
    except (KeyError, TypeError, ValueError):
        return None
    return (mission, base) if base in (m.get("areas") or {}) else None


def _place_area(a: dict, tm: list):
    """Puts an area at tm (position and heading), keeping the size of each of its axes."""
    try:
        old = a["tm"]
        sx, sy, sz = (math.hypot(*(float(c) for c in old[k])) or 10.0 for k in range(3))
    except (KeyError, TypeError, ValueError, IndexError):
        sx = sy = sz = 10.0
    a["tm"] = [[c * sx for c in tm[0]], [0.0, sy, 0.0], [c * sz for c in tm[2]], list(tm[3])]


def _move_air_spawn(m: dict, tm: list) -> bool:
    """Test flights: the player spawns in the air in zone "spawn_area0" + the mission's air_spawn_point
    (+ "_high" / "_low" / "_heli" variants), unless the mission asks for an airfield / carrier / water
    start. Asks for an air start and puts that zone (all its variants) at the start set in the editor,
    turned the same way: the game spawns the player right there, after a crash too (checked in game
    2026-10-09). False when the mission doesn't work that way."""
    tf = _test_flight_spawn(m)
    if not tf:
        return False
    mission, base = tf
    areas = m["areas"]
    for flag in ("is_airfield_spawn", "is_ship_spawn", "is_water_spawn"):
        if flag in mission:
            mission[flag] = False
    for n in [n for n in areas if n == base or n.startswith(base + "_")]:
        _place_area(areas[n], tm)
    return True


def _ground_airfield(m: dict, wing: str, tm: list) -> bool:
    """Test flights, ground start: the template spawns the player on the runway its variable airfield_spawn
    names (spawnOnAirfield, after a crash too). A runway of WTFTD's own (addAirfield, as the template
    itself does for seaplanes) at the start set in the editor, heading its way, and that variable kept on
    it: the game parks the player right there."""
    tf = _test_flight_spawn(m)
    if not tf:
        return False
    triggers = m.setdefault("triggers", {"isCategory": True, "is_enabled": True})
    if not isinstance(triggers, dict):
        return False
    mission, _ = tf
    mission["is_airfield_spawn"] = True
    mission["is_ship_spawn"] = False
    mission["is_water_spawn"] = False
    x, y, z = tm[3]
    fx, fz = float(tm[0][0]), float(tm[0][2])
    areas = m.setdefault("areas", {})
    for name, pos in (("wtftd_runway", [x, y, z]), ("wtftd_runway_end", [x + fx * 600.0, y, z + fz * 600.0]),
                      ("wtftd_runway_spawn", [x, y, z])):
        areas[name] = {"type": "Point", "tm": [list(tm[0]), [0.0, 1.0, 0.0], list(tm[2]), pos], "objLayer": 0, "props": {}}
    _, _, pu = _find_player(m.get("units") or {}, wing)
    army = ((pu or {}).get("props") or {}).get("army", 1)
    triggers["wtftd_runway"] = _trigger({"initMission": {}}, {"addAirfield": {
        "runwayStart": "wtftd_runway", "runwayEnd": "wtftd_runway_end", "runwayWidth": 50.0, "army": army,
        "spawnPoint": "wtftd_runway_spawn", "visibleOnHud": True}}, False)
    # the template picks its runway over its first ticks (rank, seaplane, helicopter): ours wins every time
    triggers["wtftd_runway_use"] = _trigger({"periodicEvent": {"time": 0.01}}, {"varSetString": [
        {"value": "wtftd_runway", "var": "airfield_spawn"},
        {"value": "wtftd_runway_spawn", "var": "airfield_spawn_reload"}]}, True)
    triggers["wtftd_runway_use"]["conditions"] = {
        "varCompareString": {"var_value": "airfield_spawn", "value": "wtftd_runway", "comparasion_func": "notEqual"}}
    return True


def _move_player_zones(m: dict, tm: list, info: dict) -> bool:
    """Zones the scenario's scripts respawn / teleport the player into (after a crash: tank test drives'
    spawn01): put at the start set in the editor. Only when no other unit uses them."""
    areas = m.get("areas") or {}
    zones = [z for z in info.get("player") or [] if z in areas]
    if not zones or info.get("playerOther") or any((info.get("spawns") or {}).get(z) for z in zones):
        return False
    for z in zones:
        _place_area(areas[z], tm)
    return True


def _hold_start(m: dict, wing: str, tm: list, player: dict, info: dict | None = None):
    """The game templates a scenario imports may respawn the player in a zone of their own (test flights:
    @player -> @air_spawn as the mission starts, tank test drives: spawn01 after a crash). Their own zones /
    runway are moved to the start set in the editor when WTFTD knows them (no jump); else a WTFTD zone and a
    respawn into it once their scripts have run (1 s in, and after a crash). An air start gets its speed."""
    if not m.get("imports"):
        return  # nothing else places the player: the unit's own position is the start
    x, y, z = tm[3]
    air = player.get("mode") == "air"
    actions = {}
    if air and _move_air_spawn(m, tm):
        pass  # the scenario itself now spawns the player there: only the speed is left to set
    elif player.get("mode") == "ground" and _ground_airfield(m, wing, tm):
        return  # parked on WTFTD's runway by the template itself
    elif info is not None and _move_player_zones(m, tm, info):
        pass
    elif info is not None and not info.get("player") and not info.get("playerOther"):
        return  # the templates never move the player
    else:
        m.setdefault("areas", {})["wtftd_start"] = {
            "type": "Sphere", "tm": [[c * 10.0 for c in tm[0]], [0.0, 10.0, 0.0], [c * 10.0 for c in tm[2]], [x, y, z]],
            "objLayer": 0, "props": {}}
        actions["unitRespawn"] = {"delay": 0.0, "offset": [0.0, 0.0, 0.0], "object": wing, "target": "wtftd_start",
                                  "resetFormation": True}
    if air:
        try:
            speed = max(0.0, min(float(player.get("speed") or 450), 3000.0))
        except (TypeError, ValueError):
            speed = 450.0
        actions["unitSetProperties"] = {"object": wing, "speed": speed}
    triggers = m.setdefault("triggers", {"isCategory": True, "is_enabled": True})
    if not isinstance(triggers, dict) or not actions:
        return
    triggers["wtftd_start"] = _trigger({"periodicEvent": {"time": 1.0}}, actions, False)
    # after a crash the scripts respawn the player in their zone again: once back alive (and placed by them,
    # 1 s), back to the WTFTD start
    if isinstance(m.setdefault("variables", {}), dict):
        m["variables"]["wtftd_dead"] = False
    triggers["wtftd_start_killed"] = _trigger(
        {"periodicEvent": {"time": 0.5}}, {"varSetBool": {"value": True, "var": "wtftd_dead"}}, True)
    triggers["wtftd_start_killed"]["conditions"] = {"playersWhenStatus": {"players": "isKilled", "check_players": "any"}}
    triggers["wtftd_start_back"] = _trigger(
        {"periodicEvent": {"time": 0.5}}, {"varSetBool": {"value": False, "var": "wtftd_dead"}, "wait": {"time": 1.0}, **actions}, True)
    triggers["wtftd_start_back"]["conditions"] = {
        "playersWhenStatus": {"players": "isAlive", "check_players": "any"},
        "varCompareBool": {"var_value": "wtftd_dead", "value": True, "comparasion_func": "equal"}}


def _trigger(event: dict, actions: dict, repeat: bool) -> dict:
    return {
        "is_enabled": True, "comments": "WTFTD",
        "props": {"actionsType": "PERFORM_ONE_BY_ONE", "conditionsType": "ALL", "enableAfterComplete": repeat},
        "events": event, "conditions": {}, "actions": actions, "else_actions": {},
    }


def _enemy_units(units: dict) -> list[str]:
    names = []
    for block, entries in units.items():
        if block == "squad":
            continue
        for u in _as_list(entries):
            if isinstance(u, dict) and (u.get("props") or {}).get("army") == 2 and u.get("name"):
                names.append(u["name"])
    return names


def make_hostile(m: dict, edits: dict) -> list[str]:
    """"Targets shoot": the scenario's enemies set to hold fire (the test-drive targets) fire at will,
    except units whose fire setting was chosen in the map editor. Returns the units changed."""
    chosen = {n for n, e in (edits.get("units") or {}).items() if isinstance(e, dict) and e.get("attack")}
    changed = []
    for block, entries in (m.get("units") or {}).items():
        if block not in EDITABLE_BLOCKS:
            continue
        for u in _as_list(entries):
            if not isinstance(u, dict) or u.get("name") in chosen:
                continue
            props = u.get("props")
            if isinstance(props, dict) and props.get("army") == 2 and props.get("attack_type") in ("hold_fire", "dont_aim"):
                props["attack_type"] = "fire_at_will"
                changed.append(u["name"])
    return changed


def apply_cheats(m: dict, wing: str, ch: dict, air: bool = False):
    """Game-rule options, built only from actions the official missions use, and stacked so
    that one working mechanism is enough:
      immortal    unitSetProperties isImmortal (re-applied every 1 s); no invulnerabilityTimer any more: that is
                  the spawn protection, and AI aircraft leave a protected player alone (checked in game 2026-10-09)
                  + unitRestore full repair / resurrect every 1 s as a fallback (not for aircraft /
                  helicopters: the repair restarts the engines, the MiG-29SMT's never got going; checked
                  in game 2026-10-08. Custom aircraft also get raised hit points.)
      infAmmo     mission isLimitedAmmo:no + unitRestore ammoRestore every 1 s (not a SAM battery's launchers, units of
                  their own: supportPlanesRestore on the radar doesn't refill them either, checked in game 2026-11-01)
      noReload    unitForceRearmSpeed x1000 + ammo restore every 1 s (+ gun shotFreq in custom vehicles)
      infFuel     mission isLimitedFuel:no
      repairEvery unitRestore full repair every N s
      passiveEnemies / ghost  unitSetProperties cannotShoot / ignoreCollisions
      hostileEnemies  enemies on hold fire set to fire at will (make_hostile) + cannotShoot:no
    A hint shows the active options when the mission starts, to confirm the triggers run."""
    mission = m["mission_settings"]["mission"]
    if ch.get("infAmmo"):
        mission["isLimitedAmmo"] = False
    if ch.get("infFuel"):
        mission["isLimitedFuel"] = False

    keys = bool(ch.get("hotkeys"))  # invulnerable / no reload switched by keys: kept on by apply_hotkeys' triggers
    props = {"object": wing}
    if ch.get("immortal") and not keys:
        props["isImmortal"] = True
    if ch.get("ghost"):
        props["ignoreCollisions"] = True

    active = [label for key, label in (("immortal", "invulnerable"), ("infAmmo", "unlimited ammo"), ("noReload", "no reload"),
                                       ("infFuel", "unlimited fuel"), ("passiveEnemies", "passive targets"), ("hostileEnemies", "targets shoot"),
                                       ("ghost", "no collisions"), ("noOverload", "unbreakable airframe"),
                                       ("superMobility", "super mobility")) if ch.get(key)]
    every = float(ch.get("repairEvery") or 0)
    if every > 0:
        active.append(f"repair every {int(every)} s")

    init: dict = {}
    if len(props) > 1:
        init["unitSetProperties"] = [dict(props)]
    if ch.get("noReload") or float(ch.get("rearmSpeed") or 0) > 0:
        rearm = 1000.0 if ch.get("noReload") else float(ch.get("rearmSpeed"))
        init["unitForceRearmSpeed"] = {"rearmSpeedK": min(rearm, 1000.0), "target": wing}
    if ch.get("passiveEnemies"):
        enemies = _enemy_units(m.get("units") or {})
        if enemies:
            init.setdefault("unitSetProperties", []).append({"object": enemies, "cannotShoot": True})
    elif ch.get("_hostile"):  # undo a cannotShoot the scenario may set on them
        init.setdefault("unitSetProperties", []).append({"object": ch["_hostile"], "cannotShoot": False})
    if "unitSetProperties" in init and len(init["unitSetProperties"]) == 1:
        init["unitSetProperties"] = init["unitSetProperties"][0]
    if active:
        init["playHint"] = {"hintType": "standard", "name": "WTFTD cheats: " + ", ".join(active), "action": "show",
                            "shouldFadeOut": True, "time": 8.0, "priority": 0, "isOverFade": False, "target_marking": 0,
                            "object_var_name": "", "object_var_comp_op": "equal", "object_var_value": 0, "team": "Both"}

    triggers = m.setdefault("triggers", {"isCategory": True, "is_enabled": True})
    if not isinstance(triggers, dict):
        return
    if init:
        triggers["wtftd_rules_init"] = _trigger({"initMission": {}}, init, False)

    # every second: keep the player immortal / topped up
    fast: dict = {}
    restore = {}
    if ch.get("immortal") and not air and not keys:
        restore.update({"fullRestore": True, "ressurectIfDead": True, "partRestore": True})
    if ch.get("infAmmo") or ch.get("noReload") and not keys:
        restore["ammoRestore"] = True
    if restore:
        fast["unitRestore"] = {"target": wing, "fullRestore": restore.get("fullRestore", False),
                               "ressurectIfDead": restore.get("ressurectIfDead", False), **restore}
    if len(props) > 1:
        fast["unitSetProperties"] = dict(props)  # re-apply after the scenario respawns the player
    if fast:
        triggers["wtftd_rules_fast"] = _trigger({"periodicEvent": {"time": 1.0}}, fast, True)

    if every > 0 and not ch.get("immortal"):
        repair = {"unitRestore": {"target": wing, "fullRestore": True, "ammoRestore": True, "ressurectIfDead": False}}
        triggers["wtftd_rules_repair"] = _trigger({"periodicEvent": {"time": max(1.0, every)}}, repair, True)


# ---------------------------------------------------------------------------- in-mission keys
# The game's "Quick radio message #n" controls (ID_FAST_VOICE_MESSAGE_n, set in the game's controls) are read by
# the mission's triggers (playerShortcutPressed, as the game's own tutorials read keys). A key either runs an
# action (repair, targets back, back to the start) or switches an option: the key's trigger asks a second,
# disabled one to check its conditions (triggerActivate), which turns the option on (actions) or off
# (else_actions) by a mission variable; while an option is on, a third trigger keeps it applied.
HOTKEYS = {"immortal": 1, "reload": 2, "passive": 3, "repair": 4, "targets": 5, "start": 6, "restart": 7, "help": 9}
HOTKEY_TEXTS = {  # English fallback; the app sends them in the player's language
    "on": "{what}: on", "off": "{what}: off",
    "immortal": "Invulnerable", "reload": "No reload", "passive": "Passive targets", "repair": "Repaired",
    "targets": "Targets back", "start": "Back to the start",
    "help": "WTFTD keys (Quick radio messages): #1 invulnerable · #2 no reload · #3 passive targets · #4 repair · "
            "#5 targets back · #6 back to the start · #9 this help",
    "intro": "WTFTD keys: Quick radio message #9 shows them",
}
TARGETS_BACK_EVERY = 20.0  # s, "Targets come back"


def _key_cond(name: str) -> dict:
    return {"playerShortcutPressed": {"control": f"ID_FAST_VOICE_MESSAGE_{HOTKEYS[name]}"}}


def _hint(text: str, time: float = 4.0) -> dict:
    return {"hintType": "standard", "name": text, "action": "show", "shouldFadeOut": True, "time": time,
            "priority": 0, "isOverFade": False, "target_marking": 0, "object_var_name": "",
            "object_var_comp_op": "equal", "object_var_value": 0, "team": "Both"}


def _clean_text(s, default: str) -> str:
    s = " ".join(str(s or "").replace('"', "'").split())[:300]
    return s or default


def apply_hotkeys(m: dict, wing: str, ch: dict, air: bool, texts: dict | None, start_tm: list | None):
    """In-mission keys (cheat "hotkeys") and "Targets come back" (cheat "targetsBack"): see HOTKEYS."""
    triggers = m.setdefault("triggers", {"isCategory": True, "is_enabled": True})
    variables = m.setdefault("variables", {})
    if not isinstance(triggers, dict) or not isinstance(variables, dict):
        return
    enemies = _enemy_units(m.get("units") or {})
    waves = _wave_units(m.get("units") or {})
    revive = [n for n in enemies if n not in waves]  # a wave only ends with its units destroyed, the next ones wait for that
    if ch.get("targetsBack") and revive:
        triggers["wtftd_targets_back"] = _trigger({"periodicEvent": {"time": TARGETS_BACK_EVERY}}, {"unitRestore": {
            "target": revive, "fullRestore": True, "ressurectIfDead": True, "ammoRestore": True}}, True)
    if not ch.get("hotkeys"):
        return
    tx = {k: _clean_text((texts or {}).get(k), v) for k, v in HOTKEY_TEXTS.items()}
    on = lambda what: tx["on"].replace("{what}", tx[what])  # noqa: E731
    off = lambda what: tx["off"].replace("{what}", tx[what])  # noqa: E731

    def toggle(name: str, initial: bool, on_actions: dict, off_actions: dict, hold: dict | None = None):
        var = f"wtftd_hk_{name}"
        variables[var] = initial
        triggers[f"wtftd_key_{name}"] = _trigger({"periodicEvent": {"time": 0.1}}, {
            "wait": {"time": 0.3},
            "triggerActivate": {"target": f"wtftd_key_{name}_switch", "activate_type": "checkConidtions",
                                "check_trigger_status": False, "after_activation": "doNotChange"}}, True)
        triggers[f"wtftd_key_{name}"]["conditions"] = _key_cond(name)
        sw = _trigger({"periodicEvent": {"time": 1.0}}, {"varSetBool": {"value": True, "var": var}, **on_actions,
                                                         "playHint": _hint(on(name))}, False)
        sw["is_enabled"] = False
        sw["conditions"] = {"varCompareBool": {"var_value": var, "value": False, "comparasion_func": "equal"}}
        sw["else_actions"] = {"varSetBool": {"value": False, "var": var}, **off_actions, "playHint": _hint(off(name))}
        triggers[f"wtftd_key_{name}_switch"] = sw
        if hold:
            h = _trigger({"periodicEvent": {"time": 1.0}}, hold, True)
            h["conditions"] = {"varCompareBool": {"var_value": var, "value": True, "comparasion_func": "equal"}}
            triggers[f"wtftd_key_{name}_hold"] = h

    def action(name: str, actions: dict):
        t = _trigger({"periodicEvent": {"time": 0.1}}, {**actions, "playHint": _hint(tx[name]), "wait": {"time": 1.0}}, True)
        t["conditions"] = _key_cond(name)
        triggers[f"wtftd_key_{name}"] = t

    restore = {"target": wing, "fullRestore": True, "ressurectIfDead": True, "partRestore": True, "ammoRestore": True}
    immortal_hold = {"unitSetProperties": {"object": wing, "isImmortal": True}}
    if not air:  # aircraft: a full repair restarts the engines (apply_cheats)
        immortal_hold["unitRestore"] = dict(restore)
    toggle("immortal", bool(ch.get("immortal")), {"unitSetProperties": {"object": wing, "isImmortal": True}},
           {"unitSetProperties": {"object": wing, "isImmortal": False}}, immortal_hold)
    toggle("reload", bool(ch.get("noReload")), {"unitForceRearmSpeed": {"rearmSpeedK": 1000.0, "target": wing}},
           {"unitForceRearmSpeed": {"rearmSpeedK": 1.0, "target": wing}},
           {"unitRestore": {"target": wing, "fullRestore": False, "ressurectIfDead": False, "ammoRestore": True}})
    if enemies:
        toggle("passive", bool(ch.get("passiveEnemies")), {"unitSetProperties": {"object": enemies, "cannotShoot": True}},
               {"unitSetProperties": {"object": enemies, "cannotShoot": False}})
        if revive:
            action("targets", {"unitRestore": {"target": revive, "fullRestore": True, "ressurectIfDead": True, "ammoRestore": True}})
    action("repair", {"unitRestore": restore})
    if start_tm:
        m.setdefault("areas", {})["wtftd_key_start"] = {
            "type": "Sphere", "tm": [[c * 5.0 for c in start_tm[0]], [0.0, 5.0, 0.0], [c * 5.0 for c in start_tm[2]], list(start_tm[3])],
            "objLayer": 0, "props": {}}
        back = {"unitRespawn": {"delay": 0.0, "offset": [0.0, 0.0, 0.0], "object": wing, "target": "wtftd_key_start",
                                "resetFormation": True}}
        _, _, pu = _find_player(m.get("units") or {}, wing)
        speed = ((pu or {}).get("props") or {}).get("speed")
        if air and isinstance(speed, (int, float)) and speed > 0:
            back["unitSetProperties"] = {"object": wing, "speed": float(speed)}
        action("start", back)
    action("help", {})
    triggers["wtftd_key_help"]["actions"]["playHint"] = _hint(tx["help"], 12.0)
    intro = _trigger({"periodicEvent": {"time": 3.0}}, {"playHint": _hint(tx["intro"], 8.0)}, False)
    triggers["wtftd_key_intro"] = intro


# ---------------------------------------------------------------------------- challenges
# A scored mission (wtftd/challenges.py makes the units, this the rules): one objective, a countdown, a real end. Block
# shapes as in the game's own single missions: malta_s02 (timer, end), free_flight_preset01 (points to fly through),
# aircraft_countermeasures_flares (an aircraft told to fire at the player), aircraft_aam_mclos (restart).
CH_END_WAIT = 3.0  # s between the objective's result and the end: the app reads the result then
CH_TIME, CH_NO_TIME = "wtftd_ch_time", "wtftd_ch_no_time"  # s left; a variable at 0 hides the game's timer
CH_TEXTS = {"goal": "Challenge", "start": "", "gate": "Gate {n} of {total}"}  # English fallback; the app sends them in the player's language


def _ch_objective(m: dict, goal: str):
    """The game shows an objective's name as its text: a name no language file knows shows as it is written."""
    m.setdefault("mission_objectives", {"isCategory": True, "is_enabled": True})[goal] = {
        "is_enabled": False, "comments": "WTFTD", "type": "abstractMissionObjective",
        "props": {"isPrimary": True, "timeLimit": 1800, "scoreConst": 100, "scoreTime": 400}, "onSuccess": {}, "onFailed": {}}


def _ch_end(goal: str, won: bool, others: list) -> dict:
    """The objective's result, the timer gone, the game's own end of mission."""
    end = {"missionCompleted": {"timer": False, "debriefingTimer": 2}} if won else {"missionFailed": {"timer": False, "debriefingTimer": 5}}
    return {"triggerDisable": {"target": others}, "moSetObjectiveStatus": {"target": goal, "status": 2 if won else 3},
            "missionSetTimeIndicator": {"var": CH_NO_TIME}, "wait": {"time": CH_END_WAIT}, **end}


def _ch_mark(area: str, visible: bool) -> dict:
    return {"visible": visible, "primary": False, "scale": 1.0, "oriented": False, "ignoreDifficulty": True, "target": area}


def _ch_gates(m: dict, gates: list, radius: float, text: str) -> list:
    """Points to fly through in order, the next one marked on the map and the HUD. -> their triggers, first enabled."""
    names = [f"wtftd_ch_gate_{i + 1}" for i in range(len(gates))]
    out = []
    for i, name in enumerate(names):
        m.setdefault("areas", {})[name] = {"type": "Point", "tm": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0], list(gates[i])], "objLayer": 0, "props": {}}
        following = names[i + 1:i + 2]
        t = _trigger({"periodicEvent": {"time": 0.25}}, {
            "missionMarkAsWaypoint": [_ch_mark(name, False), *(_ch_mark(x, True) for x in following)],
            "playHint": _hint(text.replace("{n}", str(i + 1)).replace("{total}", str(len(gates))), 2.0)}, False)
        t["is_enabled"] = i == 0
        t["conditions"] = {"playersDistanceBetween": {"value": float(radius), "math": "3D", "players": "isAlive", "target_type": "isAlive",
                                                      "check_players": "any", "check_targets": "any", "target": name}}
        if following:
            t["actions"]["triggerEnable"] = {"target": [f"{following[0]}_passed"]}
        out.append((f"{name}_passed", t))
    return out


def apply_challenge(m: dict, wing: str, ch: dict):
    """ch (challenges.plan): limit (s), rule, texts (see CH_TEXTS), and by rule
      destroy  targets: units to destroy
      waves    the enemies of apply_waves: the last wave destroyed wins
      gates    gates: [[x, y, z]], radius
      survive  the timer running out wins; attackers: aircraft told to fire at the player
    Time out and death end it. A bare map's respawn goes: a death is the end here."""
    triggers = m.setdefault("triggers", {"isCategory": True, "is_enabled": True})
    tx = {k: _clean_text((ch.get("texts") or {}).get(k), v) for k, v in CH_TEXTS.items()}
    triggers.pop("wtftd_respawn", None)
    goal, rule = tx["goal"], ch["rule"]
    _ch_objective(m, goal)
    m.setdefault("variables", {}).update({CH_TIME: int(ch["limit"]), CH_NO_TIME: 0})
    units = m.setdefault("units", {})
    start: dict = {"moAddMissionObjective": {"target": goal, "object_var_comp_op": "equal", "object_var_name": ""},
                   "missionSetTimeIndicator": {"var": CH_TIME}}
    clock: dict = {"varModify": {"var": CH_TIME, "operator": "subAB", "value": 1.0}, "missionSetTimeIndicator": {"var": CH_TIME}}
    won = None  # the trigger that wins, when it isn't the timer
    squad = None
    if rule == "destroy":
        squad = "wtftd_ch_targets"
        first = next(u for v in units.values() for u in _as_list(v) if isinstance(u, dict) and u.get("name") == ch["targets"][0])
        _append_unit(units, "squad", {"name": squad, "tm": copy.deepcopy(first["tm"]), "props": {"squad_members": list(ch["targets"])}})
        start["unitSetIndication"] = {"set": True, "target": squad, "target_marking": 0, "object_var_name": "", "object_var_comp_op": "equal", "object_var_value": 0}
        clock["missionSetTargetsIndicator"] = {"target_type": "isAlive", "target_marking": 0, "delta": 0, "icon": ch.get("icon", "tank"), "icon army": 2,
                                               "set": True, "object_var_name": "", "object_var_comp_op": "equal", "object_var_value": 0, "target": squad}
    elif rule == "waves":
        numbers = sorted(int(s["name"].rsplit("_", 1)[1]) for s in _as_list(units.get("squad")) if str(s.get("name")).startswith("wtftd_wave_"))
        squad = f"wtftd_wave_{numbers[-1]}"
        triggers[f"wtftd_wave_{numbers[-2]}_end"]["actions"]["triggerEnable"] = {"target": ["wtftd_ch_won"]}  # absent at the start: it'd count as destroyed
    if squad:
        won = _trigger({"periodicEvent": {"time": 1.0}}, {}, False)
        won["is_enabled"] = rule == "destroy"
        won["conditions"] = {"unitWhenCountMatches": {"object_type": "isAlive", "object_marking": 0, "func": "less", "value": 1, "object": squad}}
    gates = []
    if rule == "gates":
        gates = _ch_gates(m, ch["gates"], ch["radius"], tx["gate"])
        start["missionMarkAsWaypoint"] = _ch_mark("wtftd_ch_gate_1", True)
        won = gates[-1][1]
    triggers["wtftd_ch_start"] = _trigger({"initMission": {}}, start, False)
    triggers.update(gates)
    triggers["wtftd_ch_clock"] = _trigger({"periodicEvent": {"time": 1.0}}, clock, True)
    if tx["start"]:
        triggers["wtftd_ch_hint"] = _trigger({"periodicEvent": {"time": 3.0}}, {"playHint": _hint(tx["start"], 10.0)}, False)
    if ch.get("attackers"):  # lost when they turn or lose sight: given again
        attacks = [{"playerAttracted": False, "object": n, "attack_type": "attack_target", "target": wing, "weaponType": "all"} for n in ch["attackers"]]
        triggers["wtftd_ch_attack"] = _trigger({"periodicEvent": {"time": 10.0}}, {"unitAttackTarget": attacks if len(attacks) > 1 else attacks[0]}, True)

    time_up = _trigger({"periodicEvent": {"time": 1.0}}, {}, False)
    time_up["conditions"] = {"varCompareInt": {"var_value": CH_TIME, "value": 1, "comparasion_func": "less"}}
    dead = _trigger({"periodicEvent": {"time": 0.5}}, {}, False)
    dead["conditions"] = {"playersWhenStatus": {"players": "isKilled", "check_players": "any"}}
    ending = {"wtftd_ch_time_up": (time_up, rule == "survive"), "wtftd_ch_dead": (dead, False)}
    if won:
        ending[gates[-1][0] if gates else "wtftd_ch_won"] = (won, True)
    stop = ["wtftd_ch_clock", *ending]
    for name, (t, result) in ending.items():
        t["actions"].update(_ch_end(goal, result, [x for x in stop if x != name]))
        triggers[name] = t
    restart = _trigger({"periodicEvent": {"time": 0.1}}, {"missionRestart": {}}, False)
    restart["conditions"] = _key_cond("restart")
    triggers["wtftd_ch_restart"] = restart


def safe_name(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_\-]+", "_", s).strip("_")[:80] or "mission"


def _count(v) -> int:
    try:
        return max(0, min(int(v or 0), 100000))
    except (TypeError, ValueError):
        return 0


def write_bullets(unit: dict, ammo: list, groups: list | None = None):
    """The player's bullet slots: belt / shell set id and count per slot.

    groups: the vehicle's ammo groups (details.json "am", same order as ammo). For aircraft and
    helicopters, slots are written the way the game itself spawns them (respawn.nut): one after the other,
    each tagged with its weapon (bulletsWeapon<i> = weapon blk name), a countermeasure launcher as two sets
    (flares, then chaff), counts per launcher. Without the weapon tag the game binds slots in an order of its
    own that differs between aircraft (checked in game, 2026-10-08).
    Without groups (tanks, ships): 4 slots, slot = ammo index, chaff in the first slot no weapon uses.
    Ground groups with a "set": a second weapon that only fires that named set takes a free slot, full (the game's
    slots run one after the other; the panel's are the main gun's)."""
    groups = [g if isinstance(g, dict) else {} for g in groups or []]
    tagged = any(g.get("p") for g in groups)
    for i in range(6 if tagged else 4):
        unit[f"bullets{i}"] = ""
        unit[f"bulletsCount{i}"] = 0
        if tagged:
            unit[f"bulletsWeapon{i}"] = ""
    sets = []  # (slot index or None, id, count, weapon)
    for i, a in enumerate(ammo):
        a = a if isinstance(a, dict) else {}
        g = groups[i] if i < len(groups) else {}
        # countermeasures: the mission gives each launcher its count (n launchers share the total)
        n = max(1, int(g.get("n", 1) or 1)) if g.get("trig") == "countermeasures" else 1
        weapon = re.sub(r"\.blk$", "", str(g.get("p", "")).rsplit("/", 1)[-1], flags=re.I)
        count = _count(a.get("count"))
        ch = a.get("chaff")
        cid = str(ch.get("id", "")) if isinstance(ch, dict) else ""
        if not re.fullmatch(r"[A-Za-z0-9_\-]+", cid):
            sets.append((i, str(a.get("id", "") or ""), -(-count // n), weapon))
            continue
        # flares + chaff on one launcher: two linked sets; a set left at 0 is not written (as the game does)
        if count:
            sets.append((i if not tagged else None, "", count // n, weapon))
        sets.append((None, cid, _count(ch.get("count")) // n, weapon))
    if tagged:
        for s, (_, sid, cnt, weapon) in enumerate(sets[:6]):
            unit[f"bullets{s}"] = sid
            unit[f"bulletsCount{s}"] = cnt
            unit[f"bulletsWeapon{s}"] = weapon
        return
    free = list(range(len(ammo), 4))
    for slot, sid, cnt, _ in sets:
        if slot is None:
            if not free:
                continue
            slot = free.pop(0)
        if slot < 4:
            unit[f"bullets{slot}"] = sid
            unit[f"bulletsCount{slot}"] = cnt
    unused = [i for i in range(4) if not unit[f"bulletsCount{i}"]]
    for g in groups[1:]:
        if g.get("set") and unused:
            slot = unused.pop(0)
            unit[f"bullets{slot}"] = g["set"]
            unit[f"bulletsCount{slot}"] = _count(g.get("cap"))


def build(cfg: dict) -> tuple[str, str]:
    """Returns (file_name, blk_text)."""
    sid = cfg.get("scenario", "")
    vid = cfg.get("vehicle", "")
    block = cfg.get("block", "")
    if not vid or not re.fullmatch(r"[A-Za-z0-9_\-.]+", vid):
        raise MissionError("Invalid vehicle id")
    if block not in UNIT_DEFAULTS:
        raise MissionError("Invalid unit block")

    m = copy.deepcopy(load_scenario(sid))
    ms = m.setdefault("mission_settings", {})
    mission = ms.setdefault("mission", {})
    wing = (ms.get("player") or {}).get("wing")
    units = m.setdefault("units", {})
    old_block, idx, unit = _find_player(units, wing)
    if unit is None:
        raise MissionError("Scenario has no player unit")

    # ---- player unit
    if old_block != block:
        _remove_unit(units, old_block, idx)
        props = copy.deepcopy(UNIT_DEFAULTS[block])
        props["army"] = (unit.get("props") or {}).get("army", 1)
        unit = {
            "name": wing, "tm": unit["tm"], "unit_class": vid, "objLayer": 1,
            "closed_waypoints": False, "isShipSpline": False, "shipTurnRadius": 100.0,
            "weapons": "", "bullets0": "", "bullets1": "", "bullets2": "", "bullets3": "",
            "bulletsCount0": 0, "bulletsCount1": 0, "bulletsCount2": 0, "bulletsCount3": 0,
            "crewSkillK": 0.0, "applyAllMods": False, "props": props, "way": {},
        }
        _append_unit(units, block, unit)

    unit_class = cfg.get("unitClass") or vid
    if not re.fullmatch(r"(userVehicles/)?[A-Za-z0-9_\-.]+", unit_class):
        raise MissionError("Invalid unit class")
    unit["unit_class"] = unit_class
    unit["weapons"] = cfg.get("preset", "") or ""
    write_bullets(unit, cfg.get("ammo") or [], cfg.get("_ammoGroups"))
    unit["applyAllMods"] = bool(cfg.get("allMods", True))
    ch = cfg.get("cheats") or {}
    crew = ch.get("crew") or ("expert" if ch.get("expertCrew") else "")
    if crew in ("expert", "ace"):
        unit["crewSkillK"] = 1.0  # 0..1, 1 = fully trained crew
        # same block official event missions use to hand out fully trained crews (2 = ace, 1 = expert)
        slot = {"crewSkillsPercent": 100, "crewSpecialization": 2 if crew == "ace" else 1}
        edit = {"keepOwnUnits": True}
        for country, unit_ids in (cfg.get("_crewUnits") or {}).items():
            if re.fullmatch(r"country_[a-z]+", country):
                edit[country] = {uid: dict(slot) for uid in unit_ids if re.fullmatch(r"[A-Za-z0-9_\-.]+", uid)}
        if len(edit) > 1:
            mission["editSlotbar"] = edit

    # ---- start position
    start = cfg.get("start", "scenario")
    if start == "air" and block == "armada":
        tm = unit["tm"]
        alt = float(cfg.get("altitude", 1500))
        speed = float(cfg.get("speed", 450))
        start_y = float(tm[3][1])
        # absolute altitude (ASL); keep a margin above ground starts on high airfields
        tm[3][1] = alt if start_y >= 300 else max(alt, start_y + 100.0)
        unit.setdefault("props", {})["speed"] = speed
        _strip_airfield_spawn(m.get("triggers"), wing)
    fuel = cfg.get("fuel")
    if block == "armada" and fuel not in (None, ""):
        pct = max(1.0, min(float(fuel), 100.0))
        unit.setdefault("props", {})["fuel"] = pct  # % of the tanks, as official missions set it on AI aircraft
        mission["fuelAmount"] = round(pct / 100.0, 3)
        if not (cfg.get("cheats") or {}).get("infFuel"):
            mission["isLimitedFuel"] = True
    if cfg.get("heading") not in (None, ""):
        yaw = math.radians(float(cfg["heading"]))
        x, y, z = unit["tm"][3]
        unit["tm"] = [[math.cos(yaw), 0.0, math.sin(yaw)], [0.0, 1.0, 0.0], [-math.sin(yaw), 0.0, math.cos(yaw)], [x, y, z]]

    # a bare map's air start (no game script places the player): at the speed the app picked for the aircraft
    if block == "armada" and not m.get("imports") and not (cfg.get("edits") or {}).get("player"):
        props = unit.get("props") or {}
        try:
            if float(props.get("speed") or 0) > 0 and cfg.get("speed"):
                props["speed"] = max(50.0, min(float(cfg["speed"]), 3000.0))
        except (TypeError, ValueError):
            pass

    start_y = float(unit["tm"][3][1])
    apply_edits(m, wing, cfg.get("edits") or {}, sid)
    pl = (cfg.get("edits") or {}).get("player")
    if block == "armada" and isinstance(pl, dict):
        # the start set in the editor: in the air at its speed, or parked on the ground
        mode = pl.get("mode") or ("air" if float(unit["tm"][3][1]) > start_y + 50 else "")
        if mode == "air":
            try:
                speed = float(pl.get("speed") or cfg.get("speed") or 450)
            except (TypeError, ValueError):
                speed = 450.0
            unit.setdefault("props", {})["speed"] = max(0.0, min(speed, 3000.0))
        elif mode == "ground":
            unit.setdefault("props", {})["speed"] = 0.0
    cheats = dict(cfg.get("cheats") or {})
    if cheats.get("hostileEnemies") and not cheats.get("passiveEnemies"):
        cheats["_hostile"] = make_hostile(m, cfg.get("edits") or {})
    else:
        cheats.pop("hostileEnemies", None)
    apply_cheats(m, wing, cheats, air=block == "armada")
    apply_hotkeys(m, wing, cheats, block == "armada", cfg.get("hotkeyTexts"), unit.get("tm"))
    if isinstance(cfg.get("_challenge"), dict):
        apply_challenge(m, wing, cfg["_challenge"])

    # ---- template units given another vehicle in the editor: the mission declares them itself
    eu = (cfg.get("edits") or {}).get("units") or {}
    swaps = {n: e for n, e in eu.items() if isinstance(e, dict) and not e.get("remove")
             and (e.get("cls") or isinstance(e.get("loadout"), dict))}
    brought = take_over_units(m, set(swaps)) if swaps else set()
    for blk_name in EDITABLE_BLOCKS if brought else ():
        for u in _as_list(units.get(blk_name)):
            if isinstance(u, dict) and u.get("name") in brought and u["name"] in swaps:
                set_vehicle(u, swaps[u["name"]])
                if swaps[u["name"]].get("attack") in ATTACK_TYPES:
                    u.setdefault("props", {})["attack_type"] = swaps[u["name"]]["attack"]

    # ---- mission settings
    mtype = cfg.get("missionType") or "singleMission"
    if mtype in MISSION_TYPES:
        mission["type"] = mtype
    title = (cfg.get("title") or f"Test Drive: {vid}")[:120]
    mission["locName"] = title
    # shown under the mission in the game's list (else it shows the missing key "missions//objective")
    desc = " ".join(str(cfg.get("description") or "").split())[:1000]
    if desc:
        mission["locDesc"] = desc
    if cfg.get("crewCountry") in COUNTRIES:  # what the crew's language follows, with the game's Crew language on Auto or Crew country
        mission["country_allies"] = mission["country_axis"] = cfg["crewCountry"]
    if cfg.get("environment") in ENVIRONMENTS:
        mission["environment"] = cfg["environment"]
    if cfg.get("weather") in WEATHERS:
        mission["weather"] = cfg["weather"]
    if cfg.get("difficulty") in DIFFICULTIES:
        kind = "air" if block == "armada" else "ship" if block == "ships" else "tank"
        own = difficulty_block(cfg["difficulty"], cfg.get("difficultySettings"), kind)
        # the game's briefing would put the player's pick over it: it no longer asks, and the engine takes the block
        # (checked in game 2026-11-07: Realistic with aim prediction and the cockpit view locked)
        mission.update({"difficulty": "custom", "openDiffLevels": False, "netDifficultyBlk": own} if own else {"difficulty": cfg["difficulty"]})
    # test flights: their templates pick targets and airfield by the rank the hangar passes them (a user mission keeps
    # the file's value, 1: low, a dirt strip and old targets); from rank V (jets) on, the high ones
    if "target_rank_index" in mission and isinstance(cfg.get("_rank"), int):
        mission["target_rank_index"] = 2 if cfg["_rank"] >= 5 else 1

    header = {"selected_tag": "", "bin_dump_file": ""}
    body = {k: v for k, v in m.items() if k not in header}
    text = blk.dumps({**header, **body})
    fname = cfg.get("fileName") or f"wtftd_{vid}"
    return safe_name(fname) + ".blk", text
