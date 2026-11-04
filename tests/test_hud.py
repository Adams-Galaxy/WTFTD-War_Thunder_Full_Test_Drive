"""The fighter HUD: its three styles, units, parts and alerts, the overlay's settings for it, and when the watcher draws it."""
import json
import unittest
from unittest import mock

from tests.test_alarms import WORDS, details, state
from wtftd import alarms, hud, server

CFG = alarms.clean({}, WORDS)
READING = {"ias": 574, "alt": 1027, "vy": 34, "g": 1.1, "mach": 0.48, "aoa": 4.2, "aos": 0.8, "pitch": 6, "bank": 0,
           "heading": 322, "throttle": 100, "fuel": 2851, "burn": 99.8}
SCREEN = (1920, 1080)


def texts(shapes) -> list:
    return [s[3] for s in shapes if s[0] == "t"]


def points(shapes):
    for s in shapes:
        if s[0] == "l":
            yield from ((s[1], s[2]), (s[3], s[4]))
        elif s[0] in "tc":
            yield s[1], s[2]
        else:
            yield from zip(s[1][::2], s[1][1::2])


class Styles(unittest.TestCase):
    def test_the_nation_picks_the_family(self):
        self.assertEqual([hud.style_of("auto", n) for n in ("usa", "ussr", "china", "france", None)], ["nato", "russian", "chinese", "nato", "nato"])
        self.assertEqual(hud.style_of("russian", "usa"), "russian")  # an aircraft's own choice wins

    def test_jets_and_helicopters_by_default(self):
        self.assertTrue(hud.wanted("auto", "fighter", True))
        self.assertTrue(hud.wanted("auto", "helicopter", None))
        self.assertTrue(hud.wanted("auto", None, None))  # not recognised: shown
        self.assertFalse(hud.wanted("auto", "fighter", False))
        self.assertTrue(hud.wanted("on", "fighter", False))
        self.assertFalse(hud.wanted("off", "fighter", True))

    def test_each_style_stays_on_the_screen(self):
        for nation in ("usa", "ussr", "china"):
            for place in ("cockpit", "outside"):
                shapes = hud.draw(READING, CFG, nation, SCREEN, place)
                xs, ys = zip(*points(shapes))
                self.assertTrue(0 < min(xs) and max(xs) < SCREEN[0] and 0 < min(ys) and max(ys) < SCREEN[1], (nation, place))

    def test_units_follow_the_style(self):
        self.assertIn("310", texts(hud.draw(READING, CFG, "usa", SCREEN, "outside")))  # 574 km/h in knots
        self.assertIn("3369", texts(hud.draw(READING, CFG, "usa", SCREEN, "outside")))  # 1027 m in feet
        self.assertIn("574", texts(hud.draw(READING, CFG, "ussr", SCREEN, "outside")))
        metric = {**CFG, "hudUnits": "metric"}
        self.assertIn("574", texts(hud.draw(READING, metric, "usa", SCREEN, "outside")))

    def test_hidden_parts_are_not_drawn(self):
        shown = texts(hud.draw(READING, {**CFG, "hudSpeed": False, "hudData": False}, "usa", SCREEN, "outside"))
        self.assertNotIn("310", shown)
        self.assertFalse([t for t in shown if t.startswith(("THR", "FUEL"))])

    def test_a_speed_alarm_lights_the_speed(self):
        quiet = hud.draw(READING, CFG, "usa", SCREEN, "outside", ["log"])
        lit = hud.draw(READING, CFG, "usa", SCREEN, "outside", ["airframe"])
        self.assertFalse(any(s[-1] for s in quiet))
        self.assertIn("310", [s[3] for s in lit if s[0] == "t" and s[-1]])

    def test_the_horizon_turns_with_the_bank(self):
        """bank > 0 is the left wing down (checked on a flight): the horizon's left end rises."""
        def horizon(bank):
            shapes = hud.draw({**READING, "pitch": 0, "bank": bank}, CFG, "usa", SCREEN, "outside")
            return max((s for s in shapes if s[0] == "l"), key=lambda s: abs(s[3] - s[1]))  # the horizon's halves are the longest lines
        flat, left = horizon(0), horizon(20)
        self.assertEqual(flat[2], flat[4])
        self.assertNotEqual(left[2], left[4])
        outer_left = min((left[1], left[2]), (left[3], left[4]))  # the end furthest to the left
        self.assertLess(outer_left[1], max(left[2], left[4]))

    def test_missing_values_draw_what_is_there(self):
        shapes = hud.draw({"ias": 300}, CFG, "ussr", SCREEN, "cockpit")
        self.assertIn("300", texts(shapes))
        self.assertEqual(texts(hud.draw({}, CFG, "china", SCREEN, "cockpit")), [])  # only the aircraft's cross

    def test_the_window_fills_its_own_size(self):
        xs, ys = zip(*points(hud.draw(READING, CFG, "usa", (800, 500), "window")))
        self.assertTrue(max(xs) < 800 and max(ys) < 500)
        self.assertAlmostEqual((min(xs) + max(xs)) / 2, 400, delta=60)


class Languages(unittest.TestCase):
    def test_the_style_speaks_its_language(self):
        self.assertIn("ТОПЛ 2851 кг", texts(hud.draw(READING, CFG, "ussr", SCREEN, "outside")))
        self.assertIn("FUEL 2851 kg", texts(hud.draw(READING, CFG, "usa", SCREEN, "outside")))

    def test_or_the_one_picked(self):
        self.assertIn("燃油 2851 公斤", texts(hud.draw(READING, {**CFG, "hudLang": "zh"}, "usa", SCREEN, "outside")))
        self.assertIn("FUEL 2851 kg", texts(hud.draw(READING, {**CFG, "hudLang": "en"}, "ussr", SCREEN, "outside")))
        self.assertEqual(alarms.clean({"hudLang": "xx"}, WORDS)["hudLang"], "auto")


class Attitude(unittest.TestCase):
    """For aircraft whose /indicators has no artificial horizon (the J-16 on 2.59)."""

    def run_for(self, seconds: float, **v) -> dict:
        att, out, turn = hud.Attitude(), {}, v.pop("turn", 0)
        for i in range(int(seconds * 40)):
            out = att.fill(i / 40, {**v, "heading": (i / 40 * turn) % 360})
        return out

    def test_pitch_is_the_climb_angle_plus_the_angle_of_attack(self):
        out = self.run_for(1, tas=360, vy=10, aoa=3, g=1, roll=0)
        self.assertAlmostEqual(out["pitch"], 5.74 + 3, delta=0.05)

    def test_rolling_right_lowers_the_right_wing(self):
        self.assertLess(self.run_for(1, tas=720, vy=0, aoa=2, g=1, roll=30)["bank"], -20)  # bank > 0 is the left wing down
        self.assertGreater(self.run_for(1, tas=720, vy=0, aoa=2, g=1, roll=-30)["bank"], 20)

    def test_a_steady_turn_settles_on_its_bank(self):
        out = self.run_for(30, tas=720, vy=0, aoa=5, g=2.04, roll=0, turn=5)  # 5°/s at 200 m/s: a level turn at 60.7° to the right
        self.assertAlmostEqual(out["bank"], -60.7, delta=2)

    def test_what_the_game_gives_is_kept(self):
        v = {**READING, "pitch": 3.0, "bank": -40.0}
        self.assertIs(hud.Attitude().fill(0, v), v)


class Glide(unittest.TestCase):
    def test_between_two_readings(self):
        g = hud.Glide()
        self.assertEqual(g.at(0), {})
        g.add(0.0, {"ias": 100, "heading": 350, "bank": 170})
        g.add(1.0, {"ias": 200, "heading": 10, "bank": -170})
        mid = g.at(1.5)
        self.assertAlmostEqual(mid["ias"], 150)
        self.assertAlmostEqual(mid["heading"], 0)  # through north, not round the other way
        self.assertAlmostEqual(abs(mid["bank"]), 180)
        self.assertAlmostEqual(g.at(9)["ias"], 200)


class Settings(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual((CFG["hudMode"], CFG["hudStyle"], CFG["hudUnits"], CFG["hudCockpitScale"]), ("off", "auto", "auto", 60))
        self.assertTrue(all(CFG[f"hud{p.title()}"] for p in hud.PARTS))

    def test_odd_values_get_the_default(self):
        cfg = alarms.clean({"hudStyle": "<b>", "hudMode": 3, "hudColor": "red", "hudOutsideScale": 9999, "hudFpm": "no",
                            "hudKey": [17, 72], "hudKeyName": "Ctrl+H"}, WORDS)
        self.assertEqual((cfg["hudStyle"], cfg["hudMode"], cfg["hudColor"], cfg["hudOutsideScale"], cfg["hudFpm"]),
                         ("auto", "off", alarms.HUD_DEFAULTS["hudColor"], 300, True))
        self.assertEqual((cfg["hudKey"], cfg["hudKeyName"]), ([17, 72], "Ctrl+H"))


class Watched(unittest.TestCase):
    def setUp(self):
        self.planes = {"f_15a": {"v": 1480, "m": 2.5, "gear": 460, "fuel": [5945], "eng": 2, "jet": True},
                       "p_51d": {"v": 800, "m": 0, "gear": 300, "fuel": [600], "eng": 1}}
        self.reply = json.dumps(state()).encode()
        self.indicators = json.dumps({"valid": True, "type": "f_15a", "compass": 90, "aviahorizon_pitch": -5, "aviahorizon_roll": 0}).encode()
        self.watch = alarms.Watch(lambda path: self.indicators if path == "/indicators" else self.reply, lambda: details(self.planes),
                                  lambda: False, lambda: None, kind=lambda vid: "fighter", nation=lambda vid: "usa")
        self.watch.enabled = True
        self.watch.model = lambda: None
        self.watch.set_config(alarms.clean({"hudMode": "auto"}, WORDS), {})
        patcher = mock.patch.object(alarms, "beep")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_jet_gets_its_hud(self):
        self.watch.tick()
        self.assertEqual(self.watch.current, "f_15a")
        self.assertIn("09", texts(self.watch.hud_frame()))  # the heading tape at 090
        self.assertIn("270", texts(self.watch.hud_frame()))  # 500 km/h in knots

    def test_a_propeller_aircraft_has_none_unless_asked(self):
        self.indicators = json.dumps({"valid": True, "type": "p_51d", "compass": 90}).encode()
        self.reply = json.dumps(state(**{"Mfuel0, kg": 600})).encode()
        self.watch.tick()
        self.assertEqual((self.watch.current, self.watch.hud_frame()), ("p_51d", []))
        self.watch.set_config(alarms.clean({"hudMode": "on"}, WORDS), {})
        self.watch._key = None
        self.watch.tick()
        self.assertTrue(self.watch.hud_frame())

    def test_the_preview_shows_the_sample(self):
        watch = alarms.Watch(lambda path: None, dict, save=lambda: None, nation=lambda vid: "china")
        on = {**CFG, "hudMode": "auto"}
        with mock.patch.object(watch, "start_overlay"):
            watch.set_preview(on, "j_10c")
        self.assertIn("640", texts(watch.hud))  # the sample's 640 km/h, in the Chinese style's km/h
        self.assertEqual(watch.sample_hud(on, "type:jet")[0][0], "l")
        self.assertEqual(watch.sample_hud(CFG, "j_10c"), [])  # off by default: no HUD in the preview either


class CockpitWindow(unittest.TestCase):
    def watch(self, **attrs):
        glide = hud.Glide()
        glide.add(0, attrs.get("last", READING))
        values = {"flying": True, "last": READING, "glide": glide, "cfg": CFG, "current": "f_15a", "on": [], "nation": lambda vid: "usa", **attrs}
        return mock.patch.multiple(server.WATCH, **values)

    def test_the_hud_fills_the_window(self):
        with self.watch():
            st = server.hud_status("800x500")
        self.assertTrue(st["flying"])
        self.assertIn("310", texts(st["shapes"]))
        self.assertTrue(max(x for x, _ in points(st["shapes"])) < 800)

    def test_odd_sizes_and_tanks(self):
        with self.watch():
            self.assertTrue(server.hud_status("<x>")["shapes"])  # the window's size by default
        with self.watch(last={"speed": 40}):
            self.assertEqual(server.hud_status("800x500")["shapes"], [])  # a tank has no airspeed: no HUD


if __name__ == "__main__":
    unittest.main()
