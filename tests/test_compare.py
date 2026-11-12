"""What the vehicle comparison shows beyond the stats: radars, warning receivers, optics, protection, gun details. The
summaries follow the game's own X-ray card (gui.vromfs globalscripts/modexraylib.nut); made-up files first, then the
real game files where they have been unpacked (skipped elsewhere, e.g. on GitHub)."""
import json
import re
import unittest
from pathlib import Path
from unittest import mock

from wtftd import builder

ROOT = Path(__file__).resolve().parent.parent
LOCALES = ROOT / "web" / "locales"

# a fighter's radar: searches (addTarget) and tracks (updateActiveTargetOfInterest), pulse-Doppler search, plain search
RADAR = {
    "type": "radar", "name": "Test radar",
    "transivers": {"pd": {"range": 60000.0, "band": 8, "antenna": {"azimuth": {"angleHalfSens": 2.0}, "elevation": {"angleHalfSens": 2.0}}},
                   "plain": {"range": 40000.0, "band": 8}},
    "scanPatterns": {"wide": {"type": "pyramide", "width": 60.0, "barHeight": 3.0, "barsCount": 4, "rowMajor": True},
                     "narrow": {"type": "pyramide", "width": 10.0, "barHeight": 3.0, "barsCount": 2}},
    "signals": {"pdSearch": {"friendFoeId": True, "groundClutter": False, "mainBeamDopplerSpeed": True,
                             "dopplerSpeed": {"presents": True, "minValue": -100.0, "maxValue": 1500.0}},
                "aaSearch": {"dopplerSpeed": {"presents": True, "minValue": -1500.0, "maxValue": 1500.0}},
                "plainSearch": {"distance": {"presents": True}},
                "track": {"track": True, "groundVehiclesAsTarget": True}},
    "fsms": {"main": {"actionsTemplates": {
        "search": {"addTarget": {}, "updateTargetOfInterest": {"limit": 10}},
        "track": {"updateActiveTargetOfInterest": {}, "setIllumination": {}, "setDistGatePos": [{"source": "targetDesignation"}],
                  "designateHelmetTarget": {}}}}},
    "weaponTargetsMax": 2,
}


class Radar(unittest.TestCase):
    def test_a_fighter_radar(self):
        r = builder.radar_summary(RADAR)
        self.assertEqual((r["k"], r["ro"], r["r"], r["b"]), ("radar", "st", 60000, [8]))
        self.assertEqual(r["z"], [120, 12])  # the widest pattern: 2 x 60 deg by 4 bars of 3 deg
        self.assertEqual(r["ld"], ["aa", "ho", "lu"])  # head-on (main beam Doppler), all aspects, and plain search above
        self.assertEqual(r["tws"], ["tws", 10])
        for key in ("iff", "sarh", "bvr", "hms"):
            self.assertEqual(r[key], 1, key)
        self.assertEqual(r["dl"], 2)
        self.assertNotIn("acm", r)
        self.assertNotIn("sf", r)  # a track signal doesn't count while the radar also searches

    def test_a_tank_or_ship_card_shows_all_aspects_only(self):
        self.assertEqual(builder.radar_summary(RADAR, surface_unit=True)["ld"], ["aa"])

    def test_tracking_radar_and_surface_modes(self):
        track = {"transivers": {"t": {"range": 15000.0, "band": 9}},
                 "signals": {"t": {"groundVehiclesAsTarget": True, "shipsAsTarget": True}},
                 "fsms": {"m": {"updateActiveTargetOfInterest": {}, "setDistGatePos": {"source": "constRange"}}}}
        r = builder.radar_summary(track)
        self.assertEqual((r["ro"], r["r"], r["sf"], r["acm"]), ("t", 15000, ["gs"], 1))
        self.assertNotIn("z", r)  # no search zone without a search mode

    def test_irst_and_ram(self):
        irst = {"transivers": {"ir": {"range": 10000.0, "targetSignatureType": "infraRed"}},
                "fsms": {"m": {"addTarget": {}, "ram": {}, "updateTargetOfInterest": {"limit": 4}}}}
        r = builder.radar_summary(irst)
        self.assertEqual((r["k"], r["ro"], r.get("ram")), ("irst", "s", 1))
        self.assertNotIn("tws", r)  # RAM replaces track while scan
        self.assertNotIn("b", r)  # bands are a radio's
        self.assertNotIn("z", r)  # no beam, no pattern: no zone to tell


class Receivers(unittest.TestCase):
    def test_rwr(self):
        groups = {"group": [{"name": "fighters", "detectLaunch": True}, {"name": "sam", "detectLaunch": True}, {"name": "aaa"}]}
        direction = {"targetsDirectionGroup": [{"text": "F", "group": "fighters"}, {"text": "S", "group": "sam"}, {"text": "A", "group": "aaa"}]}
        r = builder.rwr_summary({"range": 50000.0, "band2": True, "band8": True, "band9": False, "groups": groups,
                                 "targetsDirectionGroups": direction, "targetTracking": True, "searchRangeFinder": True})
        self.assertEqual(r, {"r": 50000, "b": [2, 8], "dg": 3, "trk": 16, "lk": 1, "ln": 2, "ss": 1})

    def test_rwr_without_lock_warning(self):
        r = builder.rwr_summary({"range": 30000.0, "detectTracking": False, "detectLaunch": True, "friendFoeId": True})
        self.assertEqual(r, {"r": 30000, "b": [], "ln": 1, "iff": 1})

    def test_automatic_countermeasures(self):
        self.assertTrue(builder._auto_cm({"automaticFlares": True}, "mlws", set()))
        self.assertTrue(builder._auto_cm({"groups": {"group": {"name": "x", "threatFlag": "msl"}}}, "rwr", {"msl"}))
        self.assertTrue(builder._auto_cm({"a": {"b": {"threatFlag": ["x", "msl"]}}}, "mlws", {"msl"}))
        self.assertFalse(builder._auto_cm({"groups": {"group": {"threatFlag": "aaa"}}}, "rwr", {"msl"}))


class Optics(unittest.TestCase):
    def test_night_vision_generations_and_thermal_first(self):
        nv = builder.night_vision({"gunnerIr": {"resolution": [1200, 800]}, "gunnerThermal": {"resolution": [500, 300]},
                                   "commanderViewIr": {"resolution": [800, 600]}, "driverIr": {"resolution": [100, 80]},
                                   "nightVisionDmPart": ["x"], "fpvShellThermal": {"resolution": [800, 600]}})
        self.assertEqual(nv, {"g": ["t", 1], "c": ["ir", 2], "d": ["ir", 1]})

    def test_zoom_as_the_game_card(self):
        self.assertEqual(builder._zoom(80, 80), [1.0])  # the same twice: shown once
        self.assertEqual(builder._zoom(18.5, 6.14), [4.0, 12.0])  # Leopard 2A5's EMES 15
        self.assertEqual(builder._zoom(0, None), [])


# a made-up tank: a laser rangefinder and thermal sights come with modifications, one through the shared table
TANK = {
    "commonWeapons": {"Weapon": [
        {"trigger": "gunner0", "blk": "gun.blk", "bullets": 40, "limits": {"pitch": [-8.0, 18.0]},
         "gunStabilizer": {"hasVertical": True, "hasHorizontal": True, "verticalSpeedLimitKPH": 40.0, "horizontalSpeedLimitKPH": 60.0}},
        {"trigger": "gunner3", "blk": "smoke.blk", "bullets": 4}]},
    "ammoStowages": {"ammo1": {"weaponTrigger": "gunner0", "autoLoad": True}},
    "cockpit": {"zoomOutFov": 18.5, "zoomInFov": 6.14},
    "nightVision": {"driverIr": {"resolution": [800, 600]}},
    "tank_crew": {"changeTimeMult": 1.0, "commander": {"dmPart": "commander_dm", "role": ["tank_gunner", "commander"]},
                  "gunner": {"dmPart": "gunner_dm", "role": "tank_gunner"}, "driver": {"dmPart": "driver_dm"},
                  "loader": {"dmPart": "loader_dm"}, "loader_01": {"dmPart": "loader_01_dm"}},
    "VehiclePhys": {"mechanics": {"gearRatios": {"ratio": [-2.0, -1.0, 0.0, 3.0, 2.0, 1.0]}}},
    "modifications": {"thermal": {"effects": {"nightVision": {"gunnerThermal": {"resolution": [800, 600]}}}}, "laser": {}},
}
GLOBAL = {"laser": {"effects": {"rangefinderMounted": True, "isLaser": True, "sensors": {"sensor": {"blk": "gamedata/sensors/lws.blk"}}}},
          "ess": {"effects": {"smokeScreenCount": 3}}}
FILES = {"lws": {"type": "lws"}, "smoke": {"rocketGun": True, "rocket": {"bulletType": "smoke_grenade_tank"}}, "gun": {}}


class Systems(unittest.TestCase):
    def setUp(self):
        builder._SMOKE.clear()
        for p in (mock.patch.object(builder, "_GLOBAL_MODS", GLOBAL), mock.patch.object(builder, "load", lambda path: FILES.get(path.stem))):
            p.start()
            self.addCleanup(p.stop)

    def test_a_tank_with_its_modifications(self):
        s = builder.vehicle_systems("ground", TANK, {"thermal", "laser", "ess"})
        self.assertEqual(s["se"], [["lws", "lws", {}]])  # a modification's sensors join the vehicle's
        self.assertEqual((s["rf"], s["ess"], s["sg"], s["al"]), ("laser", 3, 4, 1))
        self.assertEqual(s["nv"], {"g": ["t", 2]})  # a modification's night vision replaces the vehicle's
        self.assertEqual((s["stab"], s["el"], s["zg"], s["gr"]), ([1, 1, 40], [-8, 18], [4.0, 12.0], [3, 2]))
        self.assertEqual(s["crew"], {"commander": 1, "gunner": 1, "driver": 1, "loader": 2})

    def test_stock_values_beside(self):
        s = builder.systems_with_stock("ground", TANK, {"thermal", "laser", "ess"})
        self.assertEqual(s["su"], {"ess": None, "nv": {"d": ["ir", 2]}, "rf": None, "se": None})
        self.assertEqual(list(s["su"]), sorted(s["su"]))  # the same file from one build to the next
        self.assertNotIn("su", builder.systems_with_stock("ground", TANK, set()))

    def test_aircraft_countermeasures_and_load(self):
        plane = {"commonWeapons": {"Weapon": {"slot": 0, "preset": "guns"}},
                 "WeaponSlots": {"maxloadMass": 5420.0, "WeaponSlot": {"index": 0, "WeaponPreset": {"name": "guns", "Weapon": [
                     {"trigger": "cannon", "blk": "gun.blk", "bullets": 500},
                     {"trigger": "countermeasures", "blk": "cm.blk", "bullets": 30},
                     {"trigger": "countermeasures", "blk": "cm.blk", "bullets": 15}]}}}}
        self.assertEqual(builder.vehicle_systems("air", plane, set()), {"cm": 45, "ml": 5420})


class Words(unittest.TestCase):
    def test_every_word_of_the_comparison_in_every_language(self):
        src = (ROOT / "web" / "compare.js").read_text(encoding="utf-8")
        used = set(re.findall(r"'(compare\.[A-Za-z0-9_.]+[A-Za-z0-9_])'", src))
        used |= {f"compare.sec.{s}" for s in re.search(r"CMP_SECTIONS = \[([^\]]*)\]", src)[1].replace("'", "").replace(" ", "").split(",")}
        used |= {f"compare.{p}.{x}" for p, xs in (("ld", "aa ho hov lu"), ("sf", "gtm sea gmti gs"), ("rf", "laser optic"),
                                                  ("m", "iff bvr acm hms sarh mg nctr dl"),
                                                  ("seat", "commander gunner loader driver machine_gunner")) for x in xs.split()}
        en = json.loads((LOCALES / "en.json").read_text(encoding="utf-8"))
        self.assertFalse(used - set(en), "missing in en.json")
        for path in LOCALES.glob("*.json"):
            if path.stem != "index":
                words = json.loads(path.read_text(encoding="utf-8"))
                self.assertFalse({k for k in en if k.startswith("compare.") or k == "stat.vert"} - set(words), path.stem)


SENSORS = builder.DM / "aces.vromfs.bin_u" / "gamedata" / "sensors"


@unittest.skipUnless((SENSORS / "us_an_apg_66.blkx").exists(), "game data not downloaded")
class ReferenceVehicles(unittest.TestCase):
    """The real files (2.61.0.9), with every modification of the vehicle."""

    @classmethod
    def setUpClass(cls):
        cls.wpcost = builder.load(builder.DM / "char.vromfs.bin_u" / "config" / "wpcost.blkx") or {}

    def systems(self, vid, cat):
        mods = set((self.wpcost.get(vid) or {}).get("modifications") or {})
        return builder.vehicle_systems(cat, builder.load(builder.unit_file(vid, cat)), mods)

    def sensor(self, s, key):
        return next(x[2] for x in s["se"] if x[0] == key)

    def test_f_16a(self):  # AN/APG-66: no track while scan; AN/ALR-69
        s = self.systems("f_16a_block_10", "air")
        r = self.sensor(s, "us_an_apg_66")
        self.assertEqual((r["k"], r["ro"], r["r"], r["z"], r["ld"]), ("radar", "st", 60000, [60, 14], ["aa", "lu"]))
        self.assertNotIn("tws", r)
        self.assertEqual(self.sensor(s, "us_an_alr_69")["r"], 70000)
        self.assertEqual((s["cm"], s["ml"]), (45, 5420))

    def test_mig_29(self):  # N019 with its IRST in one file, track while scan, semi-active missiles
        r = self.sensor(self.systems("mig_29_9_12", "air"), "su_n_019e")
        self.assertEqual((r["k"], r["tws"], r["sarh"], r["hms"]), ("radar_irst", ["tws", 10], 1, 1))

    def test_leopard_2a5(self):
        s = self.systems("germ_leopard_2a5", "ground")
        self.assertEqual((s["rf"], s["stab"], s["el"], s["sg"]), ("laser", [1, 1, 75], [-9, 20], 16))
        self.assertEqual(s["nv"], {"g": ["t", 1], "c": ["t", 2], "d": ["ir", 2]})
        self.assertEqual(s["crew"], {"gunner": 1, "driver": 1, "loader": 1, "commander": 1})

    def test_t_80u_smoke_launcher_has_no_smoke_in_its_name(self):  # 81mm_tucha_launcher
        self.assertEqual(self.systems("ussr_t_80u", "ground")["sg"], 8)

    def test_iowa(self):  # ships' radars are in sensors/naval
        s = self.systems("us_battleship_iowa_class_iowa", "ship")
        self.assertEqual([x[0] for x in s["se"]], ["us_sk", "us_sc_radar"])
        self.assertEqual(s["fd"], 2)


if __name__ == "__main__":
    unittest.main()
