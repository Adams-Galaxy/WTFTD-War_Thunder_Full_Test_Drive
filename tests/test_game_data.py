"""Reference values from the real game files. Runs only where the datamine has been downloaded
(.cache/datamine, after a first build); skipped elsewhere (e.g. on GitHub)."""
import json
import unittest

from wtftd import armament as A
from wtftd import blk
from wtftd import cdk
from wtftd.builder import DM, base_stats, build_battle_words, flight_limits, launched_missile, load, vehicle_economy

W = DM / "aces.vromfs.bin_u" / "gamedata" / "weapons"
FM = DM / "aces.vromfs.bin_u" / "gamedata" / "flightmodels" / "fm"
CONFIG = DM / "char.vromfs.bin_u" / "config"


def item(folder, stem, cat):
    d = json.loads((W / folder / f"{stem}.blkx").read_text(encoding="utf-8"))
    kind, p = A._payloads(d)[0]
    assert A._category(kind, p, folder, stem) == cat
    return A._stats(cat, A._guidance(cat, p), p, {})


@unittest.skipUnless((CONFIG / "wpcost.blkx").exists(), "game data not downloaded")
class ReferenceEconomy(unittest.TestCase):
    """The official wiki's economy block of each vehicle, 2.59.0.92; the same in 2.60.0.21."""
    VEHICLES = (  # id, type, repair stock, repair with all upgrades, Silver Lions %, Research Points %, free repairs
        ("germ_pzkpfw_VI_ausf_h1_tiger", "ground", [1506, 1635, 2265], [1955, 2122, 2940], [80, 130, 140], 148, 10),
        ("us_m4a1_1942_sherman", "ground", [553, 631, 800], [712, 812, 1030], [30, 50, 60], 118, 10),
        ("us_merkava_mk_3d", "ground", [3817, 3755, 4416], [6645, 6537, 7688], [150, 200, 230], 238, 10),  # 2.35 rounds down
        ("p-51d-5", "air", [1022, 2282, 3695], [1298, 2898, 4693], [60, 150, 300], 142, 10),  # 1.45 rounds up
        ("mig_29_9_12b_hungary", "air", [2898, 8371, 9873], [4396, 12699, 14977], [90, 320, 490], 250, 10),  # 4.95 rounds down
        ("ah_6m", "heli", [9599, 4333, 5592], [13189, 5954, 7683], [100, 260, 390], 214, 10),
        ("uk_fairmile_c_332", "boat", [3327, 4344, None], [4269, 5573, None], [130, 200, None], 178, 10),  # no SB for ships
        ("gladiator_mk1_china", "air", [0, 0, 0], [0, 0, 0], [10, 10, 50], 100, None),  # rank I, reserve: free
        ("ussr_kv_122", "ground", [2437, 2587, 3599], [2437, 2587, 3599], [240, 370, 400], 344, 30),  # premium
        ("fw_190a_5_u14", "air", [689, 1610, 2533], [689, 1610, 2533], [130, 330, 680], 296, 30),  # premium
        ("germ_destroyer_class1936_z20_karlgalster", "ship", [2337, 2371, None], [2337, 2371, None], [530, 1200, None], 308, 30),  # premium
        ("cn_oplot_t", "ground", [4375, 4176, 5277], [7162, 6836, 8638], [150, 190, 200], 250, 10),  # squadron
        ("su_22m3", "air", [3213, 8225, 9723], [4707, 12050, 14244], [80, 310, 600], 232, 10),  # squadron, 3.05 rounds up
        ("saab_jas39d", "air", [3013, 8668, 10216], [4462, 12837, 15130], [100, 320, 500], 262, 10),  # squadron, 0.95 rounds up
    )

    def test_as_the_wiki_says(self):
        wp, warpoints, ranks = (load(CONFIG / f"{n}.blkx") for n in ("wpcost", "warpoints", "rank"))
        for vid, cat, stock, full, slm, rpm, free in self.VEHICLES:
            s, su = vehicle_economy(cat, wp[vid], warpoints, ranks)
            self.assertEqual((su.get("rep", s["rep"]), s["rep"], s["slm"], s["rpm"], s.get("fr")), (stock, full, slm, rpm, free), vid)


@unittest.skipUnless(W.exists(), "game data not downloaded")
class ReferenceWeapons(unittest.TestCase):
    def test_r73_tracking_gate(self):
        s = item("rocketguns", "su_r_73", "aam_ir")
        self.assertEqual(s["ccmt"], "g")
        self.assertIn(s["gl"], (40, 60))  # 2.59, 2.60: the data can come from either, the game or the datamine

    def test_magic2_has_irccm(self):
        self.assertIn("ccm", item("rocketguns", "fr_r_550_magic_2", "aam_ir"))

    def test_aim9m_flare_rejection(self):
        self.assertEqual(item("rocketguns", "us_aim9m_sidewinder", "aam_ir")["ccmt"], "r")

    def test_aim54c_is_not_mach_57(self):
        self.assertLess(item("rocketguns", "us_aim_54c", "aam_radar")["v"], 1200)

    def test_s8ko(self):
        s = item("rocketguns", "su_s_8ko_rocket", "rocket")
        self.assertEqual((s["v"], s["pen"]), (650, 420))

    def test_the_s300s_missile_as_an_aircraft_carries_it(self):
        missile = launched_missile(load(W / "groundmodels_weapons" / "508mm_s300ps_5v55_rocket_launcher.blkx"))
        self.assertEqual((missile["bulletName"], missile["mass"]), ("508mm_5v55r", 1664.0))
        text = cdk._air_copy({"p": "gameData/Weapons/groundModels_weapons/508mm_s300ps_5v55_rocket_launcher.blk", "c": "sam"}, "test")
        air = blk.loads(text.split("\n", 1)[1])
        self.assertTrue(air["rocketGun"])
        self.assertEqual((air["mesh"], air["rocket"]["bulletType"], air["rocket"]["mass"]), ("s300ps_missile_5v55r", "aam", 1664.0))
        self.assertIn("radarSeeker", air["rocket"]["guidance"])
        self.assertEqual((air["mesh_deployed"], air["animChar"]), ("s300ps_missile_5v55r_deployed", "s300ps_missile_5v55r_char"))
        self.assertNotIn("mesh", air["rocket"])

    def test_b61_yield(self):
        self.assertEqual(item("bombguns", "us_b61_30kt", "nuke")["yld"], 30.0)


@unittest.skipUnless(FM.exists(), "game data not downloaded")
class ReferenceLimits(unittest.TestCase):
    def test_su_30mkk(self):
        self.assertEqual(flight_limits(load(FM / "su_30mkk.blkx"), "air"),
                         {"v": 1540, "m": 2.1, "gear": 700, "flaps": [[0.2, 1018], [1, 600]], "fuel": [9400, 9400], "eng": 2, "mass": 17520, "jet": True,
                          "load": [-550000, 1450000], "aoa": [[-20, 28], [-22, 29]], "turn": [18.8, 18.3]})

    def test_j_10c(self):
        self.assertEqual(flight_limits(load(FM / "j_10c.blkx"), "air"),
                         {"v": 1543, "m": 2.1, "gear": 620, "flaps": [[0.1, 550], [1, 400]], "fuel": [5945, 6220.02], "eng": 1, "mass": 9045, "jet": True,
                          "load": [-230000, 630000], "aoa": [[-32, 35], [-31, 35]], "turn": [35.0, 31.2]})

    def test_wep_tank_and_take_off_rockets(self):  # A-26B: water injection; A-4B: two take-off rockets
        self.assertEqual(flight_limits(load(FM / "a-26b.blkx"), "air")["wep"], [162.8, 0.18])
        self.assertEqual(flight_limits(load(FM / "a_4b.blkx"), "air")["boost"], [[40.5, 8], [40.5, 8]])

    def test_reference_turn_times(self):  # the game's card: best turn without and with WEP
        self.assertEqual(flight_limits(load(FM / "p-47d.blkx"), "air")["turn"], [26.9, 24.8])
        self.assertNotIn("turn", flight_limits(load(FM / "bf-109f-4.blkx"), "air"))  # none given

    def test_older_flight_model_s_wing_load(self):  # Bf 109 F-4: Mass/WingCritOverload, NoFlaps and FullFlaps
        lim = flight_limits(load(FM / "bf-109f-4.blkx"), "air")
        self.assertEqual((lim["load"], lim["aoa"]), ([-85000, 175100], [[-14, 17.2], [-17, 15.1]]))

    def test_f_14a_variable_sweep(self):
        lim = flight_limits(load(FM / "f_14a_early.blkx"), "air")
        self.assertEqual(lim["sw"], [[0, 1021, 0.96], [0.5, 1360, 2.0], [1, 1555, 2.25]])
        self.assertEqual((lim["v"], lim["m"]), (1555, 2.25))

    def test_propellers_are_no_jets(self):
        self.assertNotIn("jet", flight_limits(load(FM / "il-10.blkx"), "air"))

    def test_a_4_has_one_engine(self):
        self.assertEqual(flight_limits(load(FM / "a_4e_early.blkx"), "air")["eng"], 1)

    def test_helicopter(self):
        lim = flight_limits(load(FM / "ah_1g.blkx"), "heli")
        self.assertEqual((lim["v"], lim["gear"], lim["eng"]), (450, 420, 1))
        self.assertNotIn("flaps", lim)

    def test_flight_model_named_after_the_aircraft(self):  # il-10 has no fmFile
        self.assertIn("lim", base_stats("il-10", {}, "air"))

    def test_fm_file_without_extension(self):
        st = base_stats("f_16a_block_10_norway", {"fmFile": "fm/f_16a_block_10_norway"}, "air")
        self.assertIn("lim", st)
        self.assertIn("mass", st)

    def test_the_battle_log_s_crash_line(self):
        words = build_battle_words()["crashed"]
        self.assertIn("hascrashed.", words)
        self.assertIn("s'est\u00e9cras\u00e9.", words)
        self.assertGreater(len(words), 10)

    def test_every_flight_model_reads(self):
        for path in FM.glob("*.blkx"):
            fm = load(path)
            if isinstance(fm, dict) and fm.get("Mass"):
                self.assertTrue(flight_limits(fm, "air"), path.stem)


if __name__ == "__main__":
    unittest.main()
