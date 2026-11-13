"""Safety rules: custom vehicle files stay in their folders, mission names stay plain, the local server
only answers its own page."""
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from wtftd import cdk, mission, server


class CustomVehicleFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.game = Path(self.tmp.name) / "War Thunder"
        self.user = Path(self.tmp.name) / "user"
        (self.game / "content").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_refuses_paths_outside_its_folders(self):
        for rel in ("../aces.vromfs.bin", "../../evil.blk", "../pkg_main/x.blk"):
            with self.assertRaises(cdk.CdkError):
                cdk.write_files(self.game, self.user, {rel: "x"})

    def test_writes_lists_and_cleans_up(self):
        rel = "gameData/units/tankModels/userVehicles/us_m2a4.blk"
        cdk.write_files(self.game, self.user, {rel: "// WTFTD\n"})
        target = self.game / "content" / "pkg_local" / rel
        self.assertTrue(target.exists())
        self.assertIn(f"pkg_local/{rel}", cdk.read_manifest(self.user))
        self.assertGreaterEqual(cdk.cleanup(self.game, self.user), 1)
        self.assertFalse(target.exists())


class MissionNames(unittest.TestCase):
    def test_safe_name(self):
        self.assertEqual(mission.safe_name("T-80BVM / Fulda: test"), "T-80BVM_Fulda_test")
        self.assertEqual(mission.safe_name("../../x"), "x")
        self.assertEqual(mission.safe_name("///"), "mission")
        self.assertLessEqual(len(mission.safe_name("a" * 300)), 80)


class FakeHandler:
    local_origin = server.Handler.local_origin

    def __init__(self, host, origin=None):
        self.headers = {"Host": host, **({"Origin": origin} if origin else {})}


class LocalServer(unittest.TestCase):
    def test_own_page_is_allowed(self):
        self.assertTrue(FakeHandler("127.0.0.1:8777").local_origin())
        self.assertTrue(FakeHandler("localhost:8777", "http://localhost:8777").local_origin())

    def test_other_sites_are_refused(self):
        self.assertFalse(FakeHandler("evil.example.com").local_origin())  # DNS rebinding
        self.assertFalse(FakeHandler("127.0.0.1:8777", "https://evil.example.com").local_origin())  # cross-site request


if __name__ == "__main__":
    unittest.main()


class ThePage(unittest.TestCase):
    def test_it_runs_only_the_apps_own_scripts(self):
        self.assertIn("script-src 'self';", server.CSP)
        self.assertIn("connect-src 'self';", server.CSP)

    def test_nothing_inline_for_the_policy_to_stop(self):
        web = Path(server.__file__).parent.parent / "web"
        for f in [*web.glob("*.html"), *web.glob("*.js")]:
            text = f.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"""\son[a-z]+=["']""", f.name)
            self.assertNotRegex(text, r"<script(?![^>]*\ssrc=)", f.name)

    def test_network_paths_are_refused(self):
        for p in (r"\\host\share\oo2core_9_win64.dll", "//host/share/a.dll", r"\\host@80\s\a.dll", r"\\?\UNC\host\s\a.dll", r"/\host\s\a.dll"):
            self.assertTrue(server.on_network(p), p)
        for p in (r"C:\Games\oo2core_9_win64.dll", "D:/War Thunder", "~/oodle.dylib", "/Applications/x", "", None):
            self.assertFalse(server.on_network(p), p)


class UnbreakableAirframe(unittest.TestCase):
    def test_breaking_limits_raised(self):
        from wtftd import cdk
        fm = {"Vne": 760.0, "VneMach": 0.82, "VneControl": 600.0,
              "Mass": {"WingCritOverload": [-87500.0, 150000.0], "GearDestructionIndSpeed": 270.0,
                       "AirbrakeDestructionIndSpeed": -1.0, "FlapsDestructionIndSpeedP1": [0.5, 290.0]},
              "Aerodynamics": {"WingPlaneSweep0": {"Strength": {"VNE": 1021.0, "MNE": 0.96, "CritOverload": [-6.0, 13.0]}}}}
        tree = cdk._structural_overrides(fm)
        self.assertEqual(tree[("Vne",)], ("r", cdk.NO_BREAK_SPEED))
        self.assertEqual(tree[("VneMach",)], ("r", 100.0))
        self.assertEqual(tree[("Aerodynamics", "WingPlaneSweep0", "Strength", "MNE")], ("r", 100.0))  # wings' Mach limit
        self.assertNotIn(("VneControl",), tree)  # control stiffness, not a breaking limit
        self.assertEqual(tree[("Mass", "WingCritOverload")], ("p2", [-8750000.0, 15000000.0]))
        self.assertNotIn(("Mass", "AirbrakeDestructionIndSpeed"), tree)  # -1: never breaks already
        self.assertEqual(tree[("Mass", "FlapsDestructionIndSpeedP1")], ("p2", [0.5, cdk.NO_BREAK_SPEED]))
        self.assertEqual(tree[("Aerodynamics", "WingPlaneSweep0", "Strength", "CritOverload")], ("p2", [-600.0, 1300.0]))
        b = cdk.Blk()
        cdk._write_tree(b, tree)
        text = str(b)
        self.assertEqual(text.count('"@override:Mass"{'), 1)
        self.assertIn('"@override:Aerodynamics"{', text)


class JetThrust(unittest.TestCase):
    def test_thrust_table_base_scaled(self):
        from wtftd import cdk
        det = {"st": {"fm": "fm/x.blk", "thrust": 6000.0}}
        fm = {"EngineType0": {"Main": {"Thrust": 6000.0, "ThrustMax": {"ThrustMax0": 6260.0, "ThrustMaxCoeff_0_0": 0.99}}},
              "Engine0": {"Main": {"FuelSystemNum": 0}}}
        files = cdk.build_files("x", "air", det, {"thrustMul": 3}, "", None, "custom", None, {}, fm_data=fm)[0]
        text = files[f"{cdk.game_data_root()}/flightModels/fm/wtftd_x.blk"]
        self.assertIn('"@override:ThrustMax0":r=18780', text)  # what the game uses for a jet's maximum thrust
        self.assertNotIn("Engine0", text)


class SuperMobility(unittest.TestCase):
    def test_aircraft_engines_and_mass(self):
        from wtftd import cdk
        fm = {"EngineType0": {"Main": {"Type": "Jet", "Power": 1122.0, "ThrustMax": {"ThrustMax0": 6000.0}}},
              "Engine0": {"Main": {"Type": "Inline", "Power": 900.0},
                          "Compressor": {"Power0": 1020.0, "PowerConstRPM0": 200.0, "PowerAtCeiling0": 500.0,
                                         "PowerConstRPMCurvature0": 0.5}}}
        tree = cdk._power_overrides(fm, 3.0)
        self.assertEqual(tree, {("EngineType0", "Main", "ThrustMax", "ThrustMax0"): ("r", 18000.0),
                                ("Engine0", "Main", "Power"): ("r", 2700.0),
                                ("Engine0", "Compressor", "Power0"): ("r", 3060.0),
                                ("Engine0", "Compressor", "PowerConstRPM0"): ("r", 600.0),
                                ("Engine0", "Compressor", "PowerAtCeiling0"): ("r", 1500.0)})
        det = {"st": {"fm": "fm/x.blk", "mass": 1000.0}}
        files = cdk.build_files("x", "air", det, {"superMobility": True}, "", None, "custom", None, {}, fm_data=fm)[0]
        self.assertIn('"@override:EmptyMass":r=600', files[f"{cdk.game_data_root()}/flightModels/fm/wtftd_x.blk"])  # 40 % lighter


class CustomPylonWeapons(unittest.TestCase):
    def test_modified_copy_of_the_weapon(self):
        aim = {"p": "gameData/Weapons/rocketguns/us_aim9l_sidewinder.blk", "c": "aam_ir", "g": "ir", "t": "aam"}
        text = cdk._custom_weapon(aim, {"e": 50, "force": 54000, "g": 100, "gReq": 100}, "x")
        self.assertIn('include "#/develop/gameBase/gameData/Weapons/rocketguns/us_aim9l_sidewinder.blk"', text)
        self.assertIn('"@override:rocket"{', text)
        self.assertIn('"@override:explosiveMass":r=50', text)
        self.assertIn('"@override:loadFactorMax":r=100', text)
        self.assertIn('"@override:reqAccelMax":r=100', text)
        bomb = {"p": "gameData/Weapons/bombguns/us_500lb_mk_82_ldgp.blk", "c": "bombs", "g": "", "t": "bombs"}
        text = cdk._custom_weapon(bomb, {"e": 10000, "g": 100}, "x")
        self.assertIn('"@override:bomb"{', text)
        self.assertIn('"@override:explosionFx":t="bomb_expl_5000kg"', text)  # the explosion of a bomb that size
        text = cdk._custom_weapon(aim, {"e": 500}, "x")
        self.assertIn('"@override:explosionEffect":t="explosion_midair_rocket_big"', text)
        self.assertIn('explosionFx:t="bomb_expl_1000kg"', text)
        self.assertNotIn("loadFactorMax", text)  # unguided: no autopilot to override
        text = cdk._custom_weapon(bomb, {"kt": 20}, "x")
        self.assertIn("yield:r=20", text)  # a nuclear charge: new values, the Mk 82 has none
        self.assertIn("splashFallBySquare:b=yes", text)
        self.assertIsNone(cdk._custom_weapon(bomb, {}, "x"))
        self.assertIsNone(cdk._custom_weapon(dict(bomb, pod=6), {"e": 1}, "x"))  # launchers: not yet
        with self.assertRaises(cdk.CdkError):
            cdk._custom_weapon(bomb, {"e": -1}, "x")


class CustomAssetRoot(unittest.TestCase):
    def test_linux_uses_the_case_sensitive_asset_root(self):
        with mock.patch.object(cdk.sys, "platform", "linux"):
            self.assertEqual(cdk.game_data_root(), "gamedata")
            files = cdk.build_files("x", "air", {"st": {"fm": "fm/x.blk"}}, {}, "", None, "custom")[0]
        self.assertIn("gamedata/flightModels/wtftd_x.blk", files)
        self.assertIn("gamedata/flightModels/fm/wtftd_x.blk", files)

    def test_other_platforms_keep_cdk_spelling(self):
        for platform in ("win32", "darwin"):
            with self.subTest(platform=platform), mock.patch.object(cdk.sys, "platform", platform):
                self.assertEqual(cdk.game_data_root(), "gameData")


class MyWeapons(unittest.TestCase):
    def test_pylons_take_the_weapons_current_changes(self):
        saved = [{"id": "a1", "w": "us_aim9l_sidewinder", "mod": {"e": 500}}]
        real = server.read_json
        server.read_json = lambda path, default: saved if path.name == "weapons.json" else real(path, default)
        try:
            out = server.custom_weapons({"1": {"w": "us_aim9l_sidewinder", "n": 1, "cw": "a1", "mod": {"e": 50}},
                                         "2": {"w": "x", "n": 1, "cw": "gone", "mod": {"e": 7}}, "3": "aim_9l"})
        finally:
            server.read_json = real
        self.assertEqual(out["1"]["mod"], {"e": 500})  # edited since: the current changes
        self.assertEqual(out["2"]["mod"], {"e": 7})    # deleted: the changes saved with the pylon
        self.assertEqual(out["3"], "aim_9l")

    def test_value_tree_of_a_weapon_file(self):
        tree = server.weapon_tree({"rocket": {"mass": 84.5, "bullets": 1, "on": True, "fx": "a_b", "bad": "x\"y",
                                              "p": [1.0, 2.0], "ints": [1, 2], "rep": [{"a": 1}], "guidance": {"workTime": 20.0}}})
        self.assertIn(["rocket/mass", "r", 84.5], tree)
        self.assertIn(["rocket/bullets", "i", 1], tree)
        self.assertIn(["rocket/on", "b", True], tree)
        self.assertIn(["rocket/p", "p2", [1.0, 2.0]], tree)
        self.assertIn(["rocket/guidance/workTime", "r", 20.0], tree)
        paths = {p for p, _, _ in tree}
        self.assertFalse({"rocket/bad", "rocket/ints", "rocket/rep"} & paths)  # unsafe text, int points, repeated blocks


class AircraftHandling(unittest.TestCase):
    def test_roll_pitch_turn_drag(self):
        from wtftd import cdk
        fm = {"MomentOfInertia": [5500.0, 15500.0, 10000.0], "AileronEffectiveSpeed": 450.0,
              "ElevatorsEffectiveSpeed": [450.0, 450.0], "Areas": {"Aileron": 0.89, "Wing": 16.0},
              "Aerodynamics": {"NoFlaps": {"ClCritHigh": 1.2, "CdMin": 0.01}, "Fuselage": {"ClCritHigh": 0.2, "CdMin": 0.01},
                               "WingPlane": {"FlapsPolar0": {"ClCritHigh": 1.7}}, "HorStabPlane": {"Areas": {"Elevator": 12.0}}}}
        t = cdk._handling_overrides(fm)
        self.assertEqual(t[("MomentOfInertia",)], ("p3", [2200.0, 6200.0, 4000.0]))
        self.assertEqual(t[("ElevatorsEffectiveSpeed",)], ("p2", [900.0, 900.0]))
        self.assertEqual(t[("Areas", "Aileron")], ("r", 0.89 * 1.5))
        self.assertNotIn(("Areas", "Wing"), t)
        self.assertEqual(t[("Aerodynamics", "NoFlaps", "ClCritHigh")], ("r", 1.2 * 1.3))
        self.assertNotIn(("Aerodynamics", "Fuselage", "ClCritHigh"), t)  # the wing's lift only
        self.assertEqual(t[("Aerodynamics", "Fuselage", "CdMin")], ("r", 0.005))
        self.assertIn(("Aerodynamics", "WingPlane", "FlapsPolar0", "ClCritHigh"), t)
        self.assertIn(("Aerodynamics", "HorStabPlane", "Areas", "Elevator"), t)


class AppWindowLifetime(unittest.TestCase):
    """WTFTD serves while its page lives, even when the browser process it started ended at once (Edge handing
    its window to another of its processes)."""

    def test_waits_for_the_page(self):
        import time
        from unittest import mock
        from wtftd import server
        with mock.patch.dict(server.PAGE, {"seen": 0.0, "bye": 0.0}):
            t0 = time.time()
            server.wait_page_gone(first=0.2, silence=60)  # the page never loaded
            self.assertLess(time.time() - t0, 3)
            server.PAGE.update(seen=time.time() - 0.5, bye=time.time() - 0.4)  # it said bye
            with mock.patch.object(server, "page_closed", lambda: True):
                server.wait_page_gone(first=0.2, silence=60)
            server.PAGE.update(seen=time.time() - 120, bye=0.0)  # silent for 2 minutes
            server.wait_page_gone(first=0.2, silence=60)


class FirstDownloadConsent(unittest.TestCase):
    def test_no_data_waits_for_the_user(self):
        from unittest import mock
        from wtftd import server
        started = []
        with mock.patch.object(server, "remote_version", lambda: "2.59.0.61"), \
                mock.patch.object(server, "read_json", lambda p, d=None: {}), \
                mock.patch.object(server.threading, "Thread", lambda **kw: started.append(kw) or mock.Mock()), \
                mock.patch.dict(server.STATE.update, {"running": False}):
            available = server.check_for_update(start=True)["available"]
        self.assertTrue(available)
        self.assertEqual(started, [])  # first install: the welcome screen's button starts it
