"""Weapons page data: stats of every missile, bomb, rocket and torpedo of the game, and who carries it.

data/armament.json = {"items": [...], "carriers": {id: [vehicle ids]}}. Item fields (short keys, missing = n/a):
  id, c category, g guidance, ic icon, nat nations, br lowest carrier BR (RB), nk nuclear
  m mass kg, e explosive kg, tnt TNT equivalent kg, cal caliber mm, v top speed m/s, rng max range m,
  acc launch acceleration G,
  gl max G, burn motor burn s, pen penetration mm, pf proximity fuse radius m,
  IR seeker: lk lock range (rear) m, aa all-aspect lock range m, ob off-boresight lock angle deg,
             trk tracking rate deg/s, ccm flare rejection (IRCCM) 0..1, ccmt its type,
  radar: act active seeker (fire & forget), ins inertial guidance, dl datalink, loft, sr seeker range m,
  ff fire-and-forget, wire wire-guided, beam beam rider; nuclear: yld yield kt, bh burst height m, iw instant win.

data/weapon_values.json = {id: {path: value}}: every number, switch and word of each weapon's file ("dragCx",
"guidance.opticalSeeker.fov", "force1"...), for What changed (wtftd/patches.py) to compare beyond these columns.
"""
from __future__ import annotations

import json
import math
import re

from . import builder
from .builder import DATA, NUKES, ICON_VOTES, Lang, aslist, first_str, humanize, load, log, report

FOLDERS = ("rocketguns", "bombguns", "torpedoes", "groundmodels_weapons", "navalmodels_weapons")
SURFACE = ("groundmodels_weapons", "navalmodels_weapons")
SKIP_TYPES = re.compile(r"^(flare|chaff|smoke|.*grenade)")

# keys of a weapon's file left out of weapon_values.json: how it looks and sounds, not how it flies or hits
LOOKS = ("fx", "effect", "sound", "smoke", "trail", "decal", "mesh", "model", "icon", "visual", "particle", "tracer")

ICONS = {"aam_ir": "missile_air_to_air", "aam_radar": "missile_air_to_air_midrange", "sam": "missile_air_to_air",
         "atgm": "missile_air_to_uni_middle", "agm": "missile_air_to_uni", "gbomb": "guided_bomb_middle_laser",
         "bomb": "bombs_middle", "nuke": "bombs_large_nuke", "rocket": "rockets_he_large", "torpedo": "torpedo"}


def _n(v):
    for x in aslist(v):
        if isinstance(x, (int, float)) and not isinstance(x, bool):
            return float(x)
    return None


def _payloads(o, parent=None, out=None):
    """(kind, merged dict) of every rocket / bomb / torpedo in a weapon file. Ground launchers keep the
    projectile fields (mass, warhead...) on `bullet` and the flight model on `bullet.rocket`: merged."""
    if out is None:
        out = []
    if isinstance(o, dict):
        for k, v in o.items():
            if k in ("rocket", "bomb", "torpedo") and isinstance(v, (dict, list)):
                for x in aslist(v):
                    if isinstance(x, dict):
                        m = {kk: vv for kk, vv in o.items() if kk != k} if parent == "bullet" else {}
                        m.update(x)
                        out.append((k, m))
            else:
                _payloads(v, k, out)
    elif isinstance(o, list):
        for x in o:
            _payloads(x, parent, out)
    return out


def _mesh(o) -> str:
    """The first model a weapon's file names: the weapon itself, or what it fires."""
    if isinstance(o, dict):
        if o.get("mesh") and isinstance(o["mesh"], str):
            return o["mesh"]
        o = list(o.values())
    if isinstance(o, list):
        for x in o:
            found = _mesh(x)
            if found:
                return found
    return ""


def _category(kind: str, p: dict, folder: str, stem: str):
    bt = first_str(p.get("bulletType")).lower()
    gd = p.get("guidance") if isinstance(p.get("guidance"), dict) else None
    gt = first_str(p.get("guidanceType")).lower()
    guided = bool(gt and gt != "none") or gd is not None or bool(p.get("operated"))  # operated = MCLOS
    if folder == "torpedoes" or kind == "torpedo":
        return "torpedo"
    if SKIP_TYPES.match(bt):
        return None
    if kind == "bomb" and (_n(p.get("yield")) or p.get("isInstantWinOnExplode")):
        return "nuke"
    if kind == "bomb":
        if folder != "bombguns":
            return None  # ships' depth charges / ASW mortars
        return "gbomb" if guided else "bomb"
    if folder == "bombguns":
        return "gbomb" if guided else "rocket"
    if bt.startswith("aam") or bt.startswith("sam"):
        if not guided:
            return "rocket"
        if folder in SURFACE or bt.startswith("sam"):
            return "sam"
        return "aam_ir" if gt == "optical" else "aam_radar"
    if bt.startswith("atgm"):
        # heavy air- / ship-launched ones (Maverick, RB 75, GROM...) are air-to-surface missiles
        return "agm" if folder != "groundmodels_weapons" and (_n(p.get("mass")) or 0) >= 150 else "atgm"
    if guided:
        return "agm"
    if bt.startswith(("rocket", "heat", "he", "ap", "frag")) or not bt:
        return "rocket"
    return None


def _guidance(cat: str, p: dict) -> str:
    gt = first_str(p.get("guidanceType")).lower()
    gd = p.get("guidance") if isinstance(p.get("guidance"), dict) else {}
    if cat == "torpedo":
        return "sonar" if gt == "sonar" else ""
    if gt == "optical":
        os_ = gd.get("opticalSeeker") if isinstance(gd.get("opticalSeeker"), dict) else {}
        sig = first_str(os_.get("targetSignatureType")).lower()
        return "tv" if sig == "optic" else "ir"
    if gt == "radar":
        rs = gd.get("radarSeeker") if isinstance(gd.get("radarSeeker"), dict) else {}
        if first_str(rs.get("targetSignatureType")).lower() == "radarintercept":
            return "arm"
        return "arh" if rs.get("active") else "sarh"
    if gt == "saclos":
        return "beam" if gd.get("beamRider") else "saclos"
    if gt == "sns":
        return "gps"
    if gt == "laser":
        return "laser"
    return "mclos" if cat in ("atgm", "sam", "aam_radar", "agm", "gbomb") else ""


def _stages(p: dict) -> list:
    """Motor stages as (thrust N, burn s, mass lost kg). Two formats: force / timeFire / massEnd (+1, 2) or
    propulsion<N>.impulse<K> {force, time, massLost} (newer missiles, e.g. AIM-54)."""
    out, m0 = [], _n(p.get("mass"))
    for i in ("", "1", "2"):
        force, t, m1 = _n(p.get("force" + i)), _n(p.get("timeFire" + i)), _n(p.get("massEnd" + i))
        if not (force and t and m0 and m1 and m0 > m1):
            break
        out.append((force, t, m0 - m1))
        m0 = m1
    if not out:
        for i in range(4):
            pr = p.get(f"propulsion{i}")
            if not isinstance(pr, dict):
                break
            for j in range(8):
                im = pr.get(f"impulse{j}")
                if not isinstance(im, dict):
                    break
                force, t, lost = _n(im.get("force")), _n(im.get("time")), _n(im.get("massLost"))
                if force and t and lost:
                    out.append((force, t, lost))
    return out


def _motor_dv(p: dict) -> float:
    """Speed the motor adds (rocket equation, stage by stage, no drag)."""
    total, m0 = 0.0, _n(p.get("mass")) or 0
    for force, t, lost in _stages(p):
        if m0 <= lost:
            break
        total += force * t / lost * math.log(m0 / (m0 - lost))  # exhaust velocity x ln(mass ratio)
        m0 -= lost
    return total


def _launch_accel(p: dict) -> float:
    """Acceleration off the rail, in G: first-stage thrust / launch mass."""
    st, m = _stages(p), _n(p.get("mass"))
    return st[0][0] / m / 9.81 if st and m else 0


def _stats(cat: str, g: str, p: dict, tnt_eq: dict) -> dict:
    s: dict = {}

    def put(k, v, nd=1):
        if v is not None and v > 0:
            s[k] = round(v, nd) if nd else round(v)

    put("m", _n(p.get("mass")), 1)
    e = _n(p.get("explosiveMass"))
    put("e", e, 2)
    if e:
        put("tnt", e * tnt_eq.get(first_str(p.get("explosiveType")).lower(), 1.0), 2)
    if "napalm" in [first_str(p[k].get("damageType")) for k in ("splash", "fireDamage") if isinstance(p.get(k), dict)]:
        s["nap"] = 1  # napalm / incendiary: hurts a bombing zone through its own multiplier, not by the explosion table
    cal = _n(p.get("caliber"))
    put("cal", cal * 1000 if cal else None, 0)
    if cat == "torpedo":
        put("v", _n(p.get("maxSpeedInWater")) or _n(p.get("speed")), 1)
        put("rng", _n(p.get("distToLive")), 0)
        return s
    if cat == "bomb":
        return s
    if cat == "nuke":
        s.pop("e", None)
        s.pop("tnt", None)  # killstreak nukes carry a 0.01 kg placeholder charge
        put("yld", _n(p.get("yield")), 1)  # kilotons of TNT
        pfz = p.get("proximityFuse") if isinstance(p.get("proximityFuse"), dict) else {}
        put("bh", _n(pfz.get("radius")), 0)  # bursts this high above the ground
        if p.get("isInstantWinOnExplode"):
            s["iw"] = 1  # ground battles' nuclear killstreak: the explosion wins the battle (no physical yield)
        return s
    # speed: what the motor gives on top of the launch speed, capped by the file's limits
    # (maxSpeed, machMax; endSpeed is often a 2000 m/s placeholder)
    mach, vend = _n(p.get("machMax")), _n(p.get("endSpeed"))
    caps = [x for x in (_n(p.get("maxSpeed")), mach * 340 if mach else None, vend if vend and vend < 1500 else None) if x]
    dv = _motor_dv(p)
    v = dv + (_n(p.get("startSpeed")) or 0) if dv else None
    if caps:
        v = min(v, min(caps)) if v else min(caps)
    put("v", v, 0)
    if dv and cat in ("aam_ir", "aam_radar", "sam", "agm"):
        put("acc", _launch_accel(p), 1)
    rng = _n(p.get("maxDistance")) or _n(p.get("rangeMax"))
    put("rng", rng if rng and rng < 400000 else None, 0)
    gd = p.get("guidance") if isinstance(p.get("guidance"), dict) else {}
    ap = gd.get("guidanceAutopilot") if isinstance(gd.get("guidanceAutopilot"), dict) else {}
    put("gl", _n(p.get("loadFactorMax")) or _n(ap.get("reqAccelMax")), 0)
    burn = (_n(p.get("timeFire")) or 0) + (_n(p.get("timeFire1")) or 0) or sum(t for _, t, _ in _stages(p))
    put("burn", burn, 1)
    # penetration: HEAT jet, or kinetic for AP / KE rounds only (HE warheads would show their fragments)
    cd = p.get("cumulativeDamage") if isinstance(p.get("cumulativeDamage"), dict) else {}
    pen = _n(cd.get("armorPower"))
    bt = first_str(p.get("bulletType")).lower()
    if not pen and (bt.startswith(("ap", "atgm_ke", "ke")) or "_ke_" in bt):
        apw = p.get("armorpower") if isinstance(p.get("armorpower"), dict) else {}
        pen = _n(apw.get("ArmorPower0m"))
    if cat in ("atgm", "agm", "rocket"):
        put("pen", pen, 0)
    pfz = p.get("proximityFuse") if isinstance(p.get("proximityFuse"), dict) else {}
    if p.get("hasProximityFuse") or pfz:
        put("pf", _n(pfz.get("radius")), 1)
    if p.get("wireGuidanceEffects") or p.get("wired"):
        s["wire"] = 1
    os_ = gd.get("opticalSeeker") if isinstance(gd.get("opticalSeeker"), dict) else None
    rs = gd.get("radarSeeker") if isinstance(gd.get("radarSeeker"), dict) else None
    if os_ is not None and cat in ("aam_ir", "sam"):
        put("lk", _n(os_.get("rangeBand0")) or _n(os_.get("rangeMax")), 0)
        put("aa", _n(os_.get("rangeBand1")), 0)
        put("ob", _n(os_.get("lockAngleMax")), 0)
        put("trk", _n(os_.get("rateMax")), 0)
        # IRCCM: "reject" = the seeker pauses on flares (AIM-9M), "gate" = narrow tracking gate that ignores
        # what is off the target's axis (R-73, Magic 2); both together are the hardest to flare
        rej = os_.get("bandMaskToReject") is not None or os_.get("signalRelRejectedTreshold") is not None
        gate = os_.get("gateWidth") is not None
        if rej or gate:
            s["ccm"] = 1.0 if rej and gate else (0.8 if rej else 0.5)
            s["ccmt"] = "rg" if rej and gate else ("r" if rej else "g")
    if rs is not None:
        rcv = rs.get("receiver") if isinstance(rs.get("receiver"), dict) else {}
        put("sr", _n(rcv.get("range")) or _n(gd.get("lockDistance")), 0)
        put("ob", _n(rs.get("lockAngleMax")), 0)
        if rs.get("active"):
            s["act"] = 1
    if gd.get("inertialNavigation") or gd.get("inertialGuidance"):
        s["ins"] = 1
    ig = gd.get("inertialGuidance") if isinstance(gd.get("inertialGuidance"), dict) else {}
    if ig.get("datalink"):
        s["dl"] = 1
    if ap.get("loftEnabled"):
        s["loft"] = 1
    if g in ("ir", "tv", "arh", "gps", "arm") and cat in ("agm", "atgm", "gbomb"):
        s["ff"] = 1  # no designation needed once launched
    return s


def values(o, path: str = "", out: dict | None = None) -> dict:
    """Every value of a weapon's merged file by its path: numbers, switches, lists of them, short words (a file name or a path
    isn't one). A list of blocks gets each its index: "propulsion0.impulse1.force", "rangeBand[0]"."""
    out = {} if out is None else out
    if isinstance(o, dict):
        for k, v in o.items():
            if not any(x in k.lower() for x in LOOKS):
                values(v, f"{path}.{k}" if path else k, out)
    elif isinstance(o, list):
        if all(not isinstance(x, (dict, list)) for x in o):
            out[path] = o
        else:
            for i, x in enumerate(o):
                values(x, f"{path}[{i}]", out)
    elif isinstance(o, (bool, int, float)) or (isinstance(o, str) and len(o) < 48 and not any(c in o for c in "/\\")):
        out[path] = o
    return out


def _name(lang: Lang, iid: str, stem: str) -> None:
    """Short game name ("R-73", not "R-73 air-to-air missiles") in the "arm" section."""
    if iid in lang.out["arm"]:
        return
    if not lang.put("arm", iid, f"weapons/{iid}/short", f"{iid}/short", iid, f"weapons/{stem}/short", stem,
                    f"weapons/{iid}", f"weapons/{stem}"):
        known = lang.out["weapons"].get(stem)
        lang.out["arm"][iid] = known if known else {"en": humanize(iid)}


def build_armament(lang: Lang, vehicles: list, progress=None) -> dict:
    log("Building the weapons page...", progress)
    report(progress, 0.88)
    ex = load(builder.DM / "aces.vromfs.bin_u" / "gamedata" / "damage_model" / "explosive.blkx") or {}
    tnt_eq = {k.lower(): _n((v or {}).get("strengthEquivalent")) or 1.0
              for k, v in (ex.get("explosiveTypes") or {}).items() if isinstance(v, dict)}
    items: dict[str, dict] = {}
    by_file: dict[str, set] = {}  # weapon file key -> armament ids it fires
    for folder in FOLDERS:
        for f in sorted((builder.DM / "aces.vromfs.bin_u" / "gamedata" / "weapons" / folder).glob("*.blkx")):
            d = load(f)
            if not isinstance(d, dict):
                continue
            stem = f.stem.lower()
            for kind, p in _payloads(d):
                cat = _category(kind, p, folder, stem)
                if not cat:
                    continue
                iid = (first_str(p.get("bulletName")) or stem).lower()
                by_file.setdefault(stem, set()).add(iid)
                old = items.get(iid)
                if old and not old["_src"].endswith("_default") and not (old["c"] == "rocket" and cat != "rocket"):
                    continue
                g = _guidance(cat, p)
                it = {"id": iid, "c": cat, "g": g, "_src": stem, "_raw": p, **_stats(cat, g, p, tnt_eq)}
                mesh = first_str(p.get("mesh")) or _mesh(d)
                if mesh and mesh != "empty_mesh":  # the id is the projectile's: it doesn't say which file holds the weapon
                    it["md"] = mesh
                icon = first_str(p.get("iconType"))
                votes = ICON_VOTES.get(stem)
                it["ic"] = icon or (max(votes, key=votes.get) if votes else ICONS[cat])
                items[iid] = it
    # carriers: pylon / preset weapons (file keys), launchers (file keys), ammunition (bullet names)
    carriers: dict[str, set] = {}
    for v in vehicles:
        ammo = set(v.get("wa") or [])
        for k in list(v.get("wp") or []) + list(v.get("wg") or []):
            ids = by_file.get(k) or by_file.get(re.sub(r"(_default|_\d+)$", "", k)) or set()
            mine = ids & ammo
            for iid in (mine or ids):
                carriers.setdefault(iid, set()).add(v["id"])
        for b in ammo:
            if b in items:
                carriers.setdefault(b, set()).add(v["id"])
    vmap = {v["id"]: v for v in vehicles}
    out = []
    for iid, it in items.items():
        car = carriers.get(iid, set())
        if not car and not (it["c"] == "nuke" and it["_src"] in NUKES):
            continue  # not carried by any vehicle: test / unused file (WTFTD's nukes can go on any pylon)
        if it["c"] == "bomb" and all(vmap[c]["c"] in ("boat", "ship") for c in car):
            continue  # depth charges, ASW mortars
        _name(lang, iid, it.pop("_src"))
        nats = sorted({vmap[c]["n"] for c in car if vmap[c].get("n")})
        if nats:
            it["nat"] = nats
        brs = [vmap[c]["br"][1] for c in car if not vmap[c].get("h") and isinstance(vmap[c].get("br"), list) and len(vmap[c]["br"]) > 1]
        if brs:
            it["br"] = min(brs)
        it["nv"] = len(car)
        out.append(it)
    # same weapon in several files under different keys: keep one per (name, category)
    names = lang.out["arm"]
    best: dict = {}
    for it in out:
        key = ((names.get(it["id"]) or {}).get("en", it["id"]).strip().lower(), it["c"], round(it.get("m", 0)), round(it.get("tnt", 0)), it.get("yld"))
        cur = best.get(key)
        if cur is None:
            best[key] = it
            continue
        cur.setdefault("alias", []).append(it["id"])
        carriers.setdefault(cur["id"], set()).update(carriers.get(it["id"], set()))
        cur["nv"] = len(carriers[cur["id"]])
        if "br" in it:
            cur["br"] = min(cur.get("br", 99), it["br"])
        cur["nat"] = sorted(set(cur.get("nat", [])) | set(it.get("nat", [])))
    final = list(best.values())
    for it in final:
        it.pop("alias", None)
    raw = {it["id"]: values(it.pop("_raw")) for it in final}
    for it in items.values():
        it.pop("_raw", None)
    data = {"items": final, "carriers": {it["id"]: sorted(carriers[it["id"]]) for it in final}}
    with open(DATA / "armament.json", "w", encoding="utf-8") as fw:
        json.dump(data, fw, separators=(",", ":"))
    with open(DATA / "weapon_values.json", "w", encoding="utf-8") as fw:
        json.dump(raw, fw, ensure_ascii=False, separators=(",", ":"))
    log(f"  {len(final)} weapons", progress)
    return data
