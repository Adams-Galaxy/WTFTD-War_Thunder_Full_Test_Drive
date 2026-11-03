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


class Settings(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual((CFG["hudMode"], CFG["hudStyle"], CFG["hudUnits"], CFG["hudCockpitScale"]), ("auto", "auto", "auto", 60))
        self.assertTrue(all(CFG[f"hud{p.title()}"] for p in hud.PARTS))

    def test_odd_values_get_the_default(self):
        cfg = alarms.clean({"hudStyle": "<b>", "hudMode": 3, "hudColor": "red", "hudOutsideScale": 9999, "hudFpm": "no",
                            "hudKey": [17, 72], "hudKeyName": "Ctrl+H"}, WORDS)
        self.assertEqual((cfg["hudStyle"], cfg["hudMode"], cfg["hudColor"], cfg["hudOutsideScale"], cfg["hudFpm"]),
                         ("auto", "auto", alarms.HUD_DEFAULTS["hudColor"], 300, True))
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
        patcher = mock.patch.object(alarms, "beep")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_jet_gets_its_hud(self):
        self.watch.tick()
        self.assertEqual(self.watch.current, "f_15a")
        self.assertIn("09", texts(self.watch.hud))  # the heading tape at 090
        self.assertIn("270", texts(self.watch.hud))  # 500 km/h in knots

    def test_a_propeller_aircraft_has_none_unless_asked(self):
        self.indicators = json.dumps({"valid": True, "type": "p_51d", "compass": 90}).encode()
        self.reply = json.dumps(state(**{"Mfuel0, kg": 600})).encode()
        self.watch.tick()
        self.assertEqual((self.watch.current, self.watch.hud), ("p_51d", []))
        self.watch.set_config(alarms.clean({"hudMode": "on"}, WORDS), {})
        self.watch._key = None
        self.watch.tick()
        self.assertTrue(self.watch.hud)

    def test_the_preview_shows_the_sample(self):
        watch = alarms.Watch(lambda path: None, dict, save=lambda: None, nation=lambda vid: "china")
        with mock.patch.object(watch, "start_overlay"):
            watch.set_preview(CFG, "j_10c")
        self.assertIn("640", texts(watch.hud))  # the sample's 640 km/h, in the Chinese style's km/h
        self.assertEqual(watch.sample_hud(CFG, "type:jet")[0][0], "l")


class CockpitWindow(unittest.TestCase):
    def watch(self, **attrs):
        values = {"flying": True, "last": READING, "cfg": CFG, "current": "f_15a", "on": [], "nation": lambda vid: "usa", **attrs}
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
