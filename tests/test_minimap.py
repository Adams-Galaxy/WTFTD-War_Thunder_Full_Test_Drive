"""The minimap: only your aircraft and the map's fixed objects, the picture's cut and size, the way home, its settings and reading."""
import json
import unittest
from unittest import mock

from tests.test_alarms import WORDS, details, state
from wtftd import alarms, minimap

ME = {"type": "aircraft", "icon": "Player", "color": "#FAC81E", "x": 0.5, "y": 0.5, "dx": 0.7, "dy": -0.7}
OBJECTS = [ME,
           {"type": "aircraft", "icon": "Fighter", "color": "#f00C00", "x": 0.52, "y": 0.48},  # an enemy the game spotted
           {"type": "aircraft", "icon": "Bomber", "color": "#174DFF", "x": 0.45, "y": 0.5},  # an ally
           {"type": "ground_model", "icon": "Tank", "color": "#f00C00", "x": 0.4, "y": 0.6},
           {"type": "airfield", "color": "#174DFF", "sx": 0.30, "sy": 0.70, "ex": 0.32, "ey": 0.70},
           {"type": "airfield", "color": "#f00C00", "sx": 0.70, "sy": 0.20, "ex": 0.72, "ey": 0.20},
           {"type": "capture_zone", "icon": "capture_zone", "color": "#fafafa", "x": 0.55, "y": 0.45},
           {"type": "bombing_point", "icon": "bombing_point", "color": "javascript:", "x": 0.6, "y": 0.6}]
INFO = {"valid": True, "map_min": [0, 0], "map_max": [65536, 65536], "map_generation": 3}
CFG = alarms.clean({"mapMode": "on"}, WORDS)


class Kept(unittest.TestCase):
    def test_nobody_but_you(self):
        seen = minimap.keep(OBJECTS)
        self.assertEqual(seen["me"], {"x": 0.5, "y": 0.5, "dx": 0.7, "dy": -0.7})
        self.assertEqual([f["type"] for f in seen["fixed"]], ["airfield", "airfield", "capture_zone", "bombing_point"])
        self.assertEqual(seen["fixed"][3]["color"], minimap.MAP_LINE)  # a colour that isn't one stays out of the drawing

    def test_no_unit_reaches_the_drawing(self):
        shapes, _ = minimap.draw(minimap.keep(OBJECTS), INFO, [], CFG, None)
        drawn = {round(c) for s in shapes if s[0] in "pc" for c in (s[1] if s[0] == "p" else s[1:3])}
        enemy = minimap.draw({"me": None, "fixed": []}, INFO, [], CFG, None)[0]
        self.assertTrue(all(s[-1] != "#f00C00" or s[0] == "l" for s in shapes))  # red only on the enemy's runway
        self.assertGreater(len(shapes), len(enemy))
        self.assertTrue(drawn)

    def test_odd_answers(self):
        self.assertEqual(minimap.keep(None), {"me": None, "fixed": []})
        self.assertEqual(minimap.keep([{"icon": "Player", "x": "a"}, 3]), {"me": None, "fixed": []})


class Picture(unittest.TestCase):
    def test_png_only(self):
        self.assertEqual(minimap.png_size(b"\x89PNG\r\n\x1a\n" + b"\0\0\0\rIHDR" + (2048).to_bytes(4, "big") * 2), (2048, 2048))
        self.assertIsNone(minimap.png_size(b"\xff\xd8\xff\xe0 a jpeg"))

    def test_the_view_follows_and_stays_inside(self):
        self.assertEqual(minimap.view({"x": 0.5, "y": 0.5}, 1), (0.0, 0.0, 1.0))
        self.assertEqual(minimap.view({"x": 0.5, "y": 0.5}, 4), (0.375, 0.375, 0.25))
        self.assertEqual(minimap.view({"x": 0.95, "y": 0.02}, 4), (0.75, 0.0, 0.25))

    def test_whole_numbers_of_tk(self):
        self.assertEqual(minimap.picture(200, (0, 0, 1), (512, 512)), (171, {"box": [0, 0, 512, 512], "n": 3}))
        self.assertEqual(minimap.picture(300, (0.75, 0, 0.25), (512, 512)), (256, {"box": [384, 0, 512, 128], "n": -2}))
        self.assertEqual(minimap.picture(300, (0, 0, 1), None), (300, None))


class Home(unittest.TestCase):
    def test_the_nearest_airfield_of_ours(self):
        km, heading = minimap.home({"x": 0.5, "y": 0.5}, minimap.keep(OBJECTS)["fixed"], (65536, 65536))
        self.assertAlmostEqual(km, 18.08, delta=0.01)  # south-west; the red one, north-east, is the enemy's
        self.assertAlmostEqual(heading, 223.5, delta=0.1)

    def test_due_east(self):
        self.assertAlmostEqual(minimap.bearing({"x": 0.1, "y": 0.5}, {"x": 0.2, "y": 0.5}, (10000, 10000))[1], 90)

    def test_the_way_is_written(self):
        shapes, _ = minimap.draw(minimap.keep(OBJECTS), INFO, [], CFG, None)
        self.assertIn("AF 18.1 km 224°", [s[3] for s in shapes if s[0] == "t"])


class Settings(unittest.TestCase):
    def test_off_until_turned_on(self):
        cfg = alarms.clean({}, WORDS)
        self.assertEqual((cfg["mapMode"], cfg["mapZoom"], cfg["mapTrail"]), ("off", 1, True))

    def test_a_select_sends_text(self):
        self.assertEqual(alarms.clean({"mapZoom": "4"}, WORDS)["mapZoom"], 4)
        self.assertEqual(alarms.clean({"mapZoom": 3}, WORDS)["mapZoom"], 1)
        self.assertEqual(alarms.clean({"mapZoom": True}, WORDS)["mapZoom"], 1)
        self.assertEqual(alarms.clean({"mapSize": 99999}, WORDS)["mapSize"], 3000)


class Read(unittest.TestCase):
    def setUp(self):
        self.objects = list(OBJECTS)
        planes = {"f_15a": {"v": 1480, "m": 2.5, "gear": 460, "fuel": [5945], "eng": 2, "jet": True}}
        png = b"\x89PNG\r\n\x1a\n" + b"\0\0\0\rIHDR" + (1024).to_bytes(4, "big") * 2
        answers = {"/state": lambda: json.dumps(state()).encode(), "/indicators": lambda: json.dumps({"valid": True, "type": "f_15a"}).encode(),
                   "/map_info.json": lambda: json.dumps(INFO).encode(), "/map_obj.json": lambda: json.dumps(self.objects).encode(),
                   "/map.img?gen=3": lambda: png}
        self.watch = alarms.Watch(lambda path: answers.get(path, lambda: None)(), lambda: details(planes), lambda: False, lambda: None)
        self.watch.enabled = True
        self.watch.model = lambda: None
        self.watch.set_config(CFG, {})
        patcher = mock.patch.object(alarms, "beep")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_in_flight(self):
        self.watch.tick()
        shapes, image = self.watch.map_frame()
        self.assertEqual(self.watch.map["seen"], minimap.keep(OBJECTS))
        self.assertEqual((image["gen"], image["box"], image["n"]), (3, [0, 0, 1024, 1024], 2))
        self.assertTrue(shapes)

    def test_the_trail_grows_as_you_move(self):
        for x in (0.5, 0.5, 0.51, 0.52):
            self.objects[0] = {**ME, "x": x}
            self.watch.map["t"] = 0  # no wait between readings here
            self.watch.tick()
        self.assertEqual(list(self.watch.map["trail"]), [(0.5, 0.5), (0.51, 0.5), (0.52, 0.5)])

    def test_off_reads_nothing(self):
        self.watch.set_config(alarms.clean({}, WORDS), {})
        with mock.patch.object(self.watch, "read_map") as read:
            self.watch.tick()
        read.assert_not_called()
        self.assertEqual(self.watch.map_frame(), ([], None))

    def test_the_preview_shows_the_sample(self):
        self.watch.preview = CFG
        self.watch.map_live = None
        shapes, image = self.watch.map_frame()
        self.assertIsNone(image)
        self.assertTrue(shapes)
        self.assertEqual(self.watch.sample_map(alarms.clean({}, WORDS)), [])


if __name__ == "__main__":
    unittest.main()
