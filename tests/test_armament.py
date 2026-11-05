"""Weapons page: categories and stats read from weapon files.

Payloads below are minimal dicts with the fields the game files use (no game files are needed).
"""
import unittest

from wtftd import armament as A


def stats(cat, payload, g=""):
    return A._stats(cat, g or A._guidance(cat, payload), payload, {"tnt": 1.0, "rdx": 1.6})


class Values(unittest.TestCase):
    """Every value of a weapon's file for What changed: how it flies and hits, not how it looks or sounds."""

    def test_by_path_without_looks(self):
        p = {"dragCx": 0.018, "hasProximityFuse": True, "bulletType": "aam", "mesh": "aim9l", "fx": {"size": 3}, "rocketSmoke": 1,
             "guidance": {"opticalSeeker": {"fov": 3.6, "rangeBand": [11000, 3000]}, "sound": "beep"},
             "propulsion0": {"impulse0": {"force": 9000}}, "stages": [{"force": 1}, {"force": 2}],
             "model": "x", "shellModel": "path/to/a/file.dds", "explosionEffect": "big"}
        self.assertEqual(A.values(p), {"dragCx": 0.018, "hasProximityFuse": True, "bulletType": "aam", "guidance.opticalSeeker.fov": 3.6,
                                       "guidance.opticalSeeker.rangeBand": [11000, 3000], "propulsion0.impulse0.force": 9000,
                                       "stages[0].force": 1, "stages[1].force": 2})

    def test_a_file_name_is_not_a_value(self):
        self.assertEqual(A.values({"a": "short", "b": "some/file", "c": "x" * 60}), {"a": "short"})


class Categories(unittest.TestCase):
    def test_ir_and_radar_air_to_air(self):
        self.assertEqual(A._category("rocket", {"bulletType": "aam", "guidanceType": "optical", "guidance": {}}, "rocketguns", "x"), "aam_ir")
        self.assertEqual(A._category("rocket", {"bulletType": "aam", "guidanceType": "radar", "guidance": {}}, "rocketguns", "x"), "aam_radar")

    def test_ground_launched_missiles_are_surface_to_air(self):
        p = {"bulletType": "aam", "guidanceType": "optical", "guidance": {}}
        self.assertEqual(A._category("rocket", p, "groundmodels_weapons", "x"), "sam")

    def test_heavy_air_launched_atgm_is_air_to_surface(self):
        maverick = {"bulletType": "atgm_tank", "guidanceType": "optical", "guidance": {}, "mass": 210.5}
        hellfire = {"bulletType": "atgm_tank", "guidanceType": "laser", "guidance": {}, "mass": 45.1}
        self.assertEqual(A._category("rocket", maverick, "rocketguns", "x"), "agm")
        self.assertEqual(A._category("rocket", hellfire, "rocketguns", "x"), "atgm")
        self.assertEqual(A._category("rocket", {**maverick, "mass": 300}, "groundmodels_weapons", "x"), "atgm")

    def test_nuclear_bombs(self):
        self.assertEqual(A._category("bomb", {"bulletType": "he_bomb", "yield": 30.0}, "bombguns", "x"), "nuke")
        self.assertEqual(A._category("bomb", {"bulletType": "he_bomb", "isInstantWinOnExplode": True}, "bombguns", "x"), "nuke")
        self.assertEqual(A._category("bomb", {"bulletType": "he_bomb"}, "bombguns", "x"), "bomb")

    def test_ship_depth_charges_and_flares_are_skipped(self):
        self.assertIsNone(A._category("bomb", {"bulletType": "he_bomb"}, "navalmodels_weapons", "x"))
        self.assertIsNone(A._category("rocket", {"bulletType": "flare"}, "rocketguns", "x"))


class Speed(unittest.TestCase):
    def test_end_speed_placeholder_is_ignored(self):
        # S-8KO: endSpeed 2000 is a placeholder, maxSpeed 650 the real cap
        s8 = {"bulletType": "heat_fs_rocket", "mass": 11.3, "massEnd": 7.25, "timeFire": 0.84, "force": 7300.0,
              "endSpeed": 2000.0, "maxSpeed": 650.0}
        self.assertEqual(stats("rocket", s8)["v"], 650)

    def test_propulsion_blocks(self):
        # AIM-54C: thrust in propulsion0.impulse0, machMax 5.7 is only a cap
        aim54 = {"bulletType": "aam", "guidanceType": "radar", "guidance": {}, "mass": 446.788, "machMax": 5.7,
                 "propulsion0": {"impulse0": {"time": 27.8, "force": 12981.21, "massLost": 163.293}}}
        s = stats("aam_radar", aim54)
        self.assertAlmostEqual(s["v"], 1005, delta=10)
        self.assertAlmostEqual(s["acc"], 3.0, delta=0.1)

    def test_two_stage_motor(self):
        # AIM-120A
        p = {"bulletType": "aam", "guidanceType": "radar", "guidance": {}, "mass": 156.4894, "machMax": 4.0,
             "force": 26687.5, "timeFire": 1.4, "massEnd": 140.3415, "force1": 13346.5, "timeFire1": 5.3, "massEnd1": 109.7694}
        self.assertAlmostEqual(stats("aam_radar", p)["v"], 820, delta=10)


class Motor(unittest.TestCase):
    def test_burn_time_of_both_motor_formats(self):
        self.assertEqual(stats("aam_ir", {"mass": 43.5, "massEnd": 33.5, "force": 9500.0, "timeFire": 3.0})["burn"], 3.0)
        # the R-60 from game 2.60 on: propulsion0 instead of force / timeFire
        self.assertEqual(stats("aam_ir", {"mass": 43.5, "propulsion0": {"impulse0": {"force": 8000.0, "time": 2.4, "massLost": 8.0},
                                                                        "impulse1": {"force": 3000.0, "time": 1.2, "massLost": 2.0}}})["burn"], 3.6)


class Seeker(unittest.TestCase):
    def ir(self, **seeker):
        p = {"bulletType": "aam", "guidanceType": "optical", "guidance": {"opticalSeeker": {"rangeBand0": 11000.0, **seeker}}}
        return stats("aam_ir", p)

    def test_no_irccm(self):  # AIM-9L
        self.assertNotIn("ccm", self.ir())

    def test_flare_rejection(self):  # AIM-9M
        s = self.ir(bandMaskToReject=4, signalRelRejectedTreshold=0.1)
        self.assertEqual((s["ccm"], s["ccmt"]), (0.8, "r"))

    def test_tracking_gate(self):  # R-73, Magic 2
        s = self.ir(gateWidth=0.75)
        self.assertEqual((s["ccm"], s["ccmt"]), (0.5, "g"))

    def test_both(self):  # Mistral, Stinger, Type 81C
        s = self.ir(bandMaskToReject=4, gateWidth=0.75)
        self.assertEqual((s["ccm"], s["ccmt"]), (1.0, "rg"))

    def test_all_aspect_and_lock_angle(self):
        s = self.ir(rangeBand1=3400.0, lockAngleMax=45.0, rateMax=60.0)
        self.assertEqual((s["aa"], s["ob"], s["trk"]), (3400, 45, 60))


class Warheads(unittest.TestCase):
    def test_heat_penetration(self):
        p = {"bulletType": "atgm_tandem_tank", "cumulativeDamage": {"armorPower": 1200.0}, "explosiveMass": 6.7, "explosiveType": "rdx"}
        s = stats("atgm", p)
        self.assertEqual(s["pen"], 1200)
        self.assertAlmostEqual(s["tnt"], 6.7 * 1.6, places=2)

    def test_he_warhead_shows_no_fragment_penetration(self):
        p = {"bulletType": "rocket_tank", "armorpower": {"ArmorPower0m": [28.0, 10.0]}, "explosiveMass": 3.0}
        self.assertNotIn("pen", stats("rocket", p))

    def test_kinetic_penetration(self):
        p = {"bulletType": "ap_tank", "armorpower": {"ArmorPower0m": [120.0, 10.0]}}
        self.assertEqual(stats("rocket", p)["pen"], 120)

    def test_nuke_yield_and_killstreak_bomb(self):
        s = stats("nuke", {"yield": 30.0, "proximityFuse": {"radius": 45.0}, "mass": 350.0})
        self.assertEqual((s["yld"], s["bh"]), (30.0, 45))
        k = stats("nuke", {"isInstantWinOnExplode": True, "explosiveMass": 0.01, "mass": 996.3})
        self.assertEqual(k.get("iw"), 1)
        self.assertNotIn("tnt", k)  # the 0.01 kg placeholder charge is not shown


if __name__ == "__main__":
    unittest.main()
