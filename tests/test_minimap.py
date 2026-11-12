"""The minimap: your aircraft, the map's fixed objects and allies on request, never an enemy; round or square, north or nose
up; gliding between readings; painted by GDI+ (Windows) or cairo (Linux), and its settings."""
import json
import math
import sys
import unittest
from unittest import mock

from tests.test_alarms import WORDS, details, setUpModule, state  # setUpModule: one reading flies, as there
from tests.test_overlay_text import PAINTER, painter
from wtftd import alarms, minimap

ME = {"type": "aircraft", "icon": "Player", "color": "#FAC81E", "x": 0.5, "y": 0.5, "dx": 0.7, "dy": -0.7}
OBJECTS = [ME,
           {"type": "aircraft", "icon": "Fighter", "color": "#f00C00", "x": 0.52, "y": 0.48},  # an enemy the game spotted
           {"type": "aircraft", "icon": "Bomber", "color": "#174DFF", "x": 0.45, "y": 0.5, "dx": 0, "dy": -1},  # an ally
           {"type": "ground_model", "icon": "Tank", "color": "#fa0C00", "x": 0.4, "y": 0.6},
           {"type": "ground_model", "icon": "SPAA", "color": "#FAC81E", "x": 0.41, "y": 0.6},  # a colour that says nothing
           {"type": "airfield", "color": "#174DFF", "sx": 0.30, "sy": 0.70, "ex": 0.32, "ey": 0.70},
           {"type": "airfield", "color": "#f00C00", "sx": 0.70, "sy": 0.20, "ex": 0.72, "ey": 0.20},
           {"type": "capture_zone", "icon": "capture_zone", "color": "#fafafa", "x": 0.55, "y": 0.45},
           {"type": "bombing_point", "icon": "bombing_point", "color": "javascript:", "x": 0.6, "y": 0.6}]
INFO = {"valid": True, "map_min": [0, 0], "map_max": [65536, 65536], "map_generation": 3}
CFG = alarms.clean({"mapMode": "on", "mapX": 100, "mapY": 100, "mapSize": 400}, WORDS)


def colours(frame: dict) -> set:
    return {s[-1] for s in frame["marks"]}


class Kept(unittest.TestCase):
    def test_no_enemy_and_no_ally_unless_asked(self):
        seen = minimap.keep(OBJECTS)
        self.assertEqual((seen["me"]["x"], seen["me"]["y"], round(seen["me"]["heading"])), (0.5, 0.5, 45))  # north-east
        self.assertEqual([f["type"] for f in seen["fixed"]], ["airfield", "airfield", "capture_zone", "bombing_point"])
        self.assertEqual(seen["fixed"][3]["color"], minimap.MAP_LINE)  # a colour that isn't one stays out of the drawing
        self.assertEqual(seen["allies"], [])

    def test_allies_by_their_colour_only(self):
        allies = minimap.keep(OBJECTS, allies=True)["allies"]
        self.assertEqual([(a["color"], a["air"], round(a["heading"])) for a in allies], [("#174DFF", True, 0)])
        for colour, ally in (("#174DFF", True), ("#18D25A", True), ("#f00C00", False), ("#fa0C00", False), ("#FAC81E", False),
                             ("#FFFFFF", False), ("#808080", False), ("#FF8800", False)):
            self.assertEqual(minimap._ally(colour), ally, colour)

    def test_aircraft_and_ai_units_each_their_own_switch(self):
        ai = {"type": "ground_model", "icon": "Artillery", "color": "#043FFF", "x": 0.3, "y": 0.3}  # an allied AI in an air battle
        squad = {"type": "aircraft", "icon": "Fighter", "color": "#39D921", "x": 0.31, "y": 0.3}  # as seen 2026-11-04
        kept = lambda **on: sorted(a["air"] for a in minimap.keep([*OBJECTS, ai, squad], **on)["allies"])
        self.assertEqual(kept(allies=True), [True, True])
        self.assertEqual(kept(ground=True), [False])
        self.assertEqual(kept(allies=True, ground=True), [False, True, True])
        self.assertEqual(kept(), [])

    def test_odd_answers(self):
        self.assertEqual(minimap.keep(None), {"me": None, "fixed": [], "allies": []})
        self.assertEqual(minimap.keep([{"icon": "Player", "x": "a"}, 3], allies=True), {"me": None, "fixed": [], "allies": []})


class Drawn(unittest.TestCase):
    def frame(self, **cfg):
        return minimap.draw(minimap.keep(OBJECTS, allies=True), INFO, [(0.48, 0.52)], {**CFG, **cfg})

    def test_never_an_enemy_unit(self):
        frame = self.frame()
        red_units = [s for s in frame["marks"] if s[-1].lower() in ("#f00c00", "#fa0c00") and s[0] != "l"]
        self.assertEqual(red_units, [])  # red only on the enemy's runway, a line

    def test_north_up_keeps_the_aircraft_pointing_its_way(self):
        me = self.frame()["marks"][-1]
        tip, back = me[1][:2], me[1][2:4]
        self.assertGreater(tip[0], back[0])  # north-east: to the right
        self.assertLess(tip[1], back[1])  # and up

    def test_nose_up_turns_the_map(self):
        frame = self.frame(mapUp="heading", mapZoom=2)
        me = frame["marks"][-1][1]
        self.assertAlmostEqual(me[0], 300, delta=0.2)  # in the middle, pointing straight up
        self.assertLess(me[1], 300)
        self.assertEqual(frame["picture"]["turn"], 45)
        north = [s for s in frame["frame"] if s[0] == "t" and s[3] == "N"][0]
        self.assertLess(north[1], 300)  # north is up and to the left when flying north-east
        self.assertLess(north[2], 300)

    def test_round_cuts_the_corners(self):
        square, round_ = self.frame(mapZoom=4), self.frame(mapZoom=4, mapShape="round")
        self.assertEqual(round_["frame"][0][0], "c")
        self.assertTrue(round_["round"])
        self.assertLessEqual(len(round_["marks"]), len(square["marks"]))
        for s in round_["marks"]:
            if s[0] == "c":
                self.assertLessEqual(math.hypot(s[1] - 300, s[2] - 300), 200)

    def test_a_runway_big_enough_to_see(self):
        runway = [s for s in self.frame()["marks"] if s[0] == "l" and s[-1] == "#174DFF"][0]  # 0.02 of the map: 8 px on 400
        self.assertGreaterEqual(math.hypot(runway[3] - runway[1], runway[4] - runway[2]), 39.9)  # a tenth of the minimap
        self.assertGreaterEqual(runway[5], 8)
        self.assertAlmostEqual(runway[2], runway[4], delta=0.2)  # still along its way: east-west here

    def test_each_kind_of_mark_its_own_size(self):
        def sizes(frame):
            runway = [s for s in frame["marks"] if s[0] == "l" and s[-1] == "#174DFF"][0]
            zone = [s for s in frame["marks"] if s[0] == "c"][0]
            ally, me = [math.dist(s[1][:2], s[1][2:4]) for s in frame["marks"] if s[0] == "p" and s[2] == 1]
            return runway[5], math.dist(runway[1:3], runway[3:5]), zone[3], ally, me
        usual = sizes(self.frame())
        bigger = sizes(self.frame(mapMarkAirfields=200, mapMarkZones=300, mapMarkAllies=150, mapMarkMe=50))
        for a, b, k in zip(usual, bigger, (2, 2, 3, 1.5, 0.5)):
            self.assertAlmostEqual(b, a * k, delta=0.2)

    def test_the_way_home(self):
        frame = self.frame()
        self.assertIn("AF 18.1 km 224°", [s[3] for s in frame["frame"] if s[0] == "t"])

    def test_the_view_stays_inside_north_up(self):
        self.assertEqual(minimap.view({"x": 0.5, "y": 0.5}, 1), (0.0, 0.0, 1.0))
        self.assertEqual(minimap.view({"x": 0.95, "y": 0.02}, 4), (0.75, 0.0, 0.25))


class Home(unittest.TestCase):
    def test_the_nearest_airfield_of_ours(self):
        km, heading = minimap.home({"x": 0.5, "y": 0.5}, minimap.keep(OBJECTS)["fixed"], (65536, 65536))
        self.assertAlmostEqual(km, 18.08, delta=0.01)  # south-west; the red one, north-east, is the enemy's
        self.assertAlmostEqual(heading, 223.5, delta=0.1)

    def test_due_east(self):
        self.assertAlmostEqual(minimap.bearing({"x": 0.1, "y": 0.5}, {"x": 0.2, "y": 0.5}, (10000, 10000))[1], 90)


class Settings(unittest.TestCase):
    def test_off_until_turned_on(self):
        cfg = alarms.clean({}, WORDS)
        self.assertEqual((cfg["mapMode"], cfg["mapZoom"], cfg["mapTrail"], cfg["mapShape"], cfg["mapUp"], cfg["mapAllies"], cfg["mapAlliesGround"], cfg["mapOpacity"]),
                         ("off", 1, True, "square", "north", False, False, 85))

    def test_odd_values(self):
        cfg = alarms.clean({"mapZoom": "4", "mapShape": "star", "mapUp": "<x>", "mapAllies": "yes", "mapSize": 99999, "mapOpacity": 2}, WORDS)
        self.assertEqual((cfg["mapZoom"], cfg["mapShape"], cfg["mapUp"], cfg["mapAllies"], cfg["mapSize"], cfg["mapOpacity"]),
                         (4, "square", "north", False, 3000, 10))
        self.assertEqual(alarms.clean({"mapZoom": True}, WORDS)["mapZoom"], 1)
        marks = alarms.clean({"mapMarkMe": 10, "mapMarkAllies": 9999, "mapMarkAirfields": "big", "mapMarkZones": 250}, WORDS)
        self.assertEqual([marks[f"mapMark{k}"] for k in minimap.MARKS], [50, 400, 100, 250])


class Read(unittest.TestCase):
    def setUp(self):
        self.objects = list(OBJECTS)
        self.picture = b"\xff\xd8 a map" * 200
        planes = {"f_15a": {"v": 1480, "m": 2.5, "gear": 460, "fuel": [5945], "eng": 2, "jet": True}}
        climb = iter(range(10 ** 6))  # in flight every reading differs (alarms.Watch.moving)
        answers = {"/state": lambda: json.dumps(state(**{"Vy, m/s": next(climb)})).encode(), "/indicators": lambda: json.dumps({"valid": True, "type": "f_15a"}).encode(),
                   "/map_info.json": lambda: json.dumps(INFO).encode(), "/map_obj.json": lambda: json.dumps(self.objects).encode(),
                   "/map.img?gen=3": lambda: self.picture}
        self.watch = alarms.Watch(lambda path: answers.get(path, lambda: None)(), lambda: details(planes), lambda: False, lambda: None)
        self.watch.enabled = True
        self.watch.model = lambda: None
        self.watch.set_config(CFG, {})
        patcher = mock.patch.object(alarms, "beep")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_in_flight(self):
        self.watch.tick()
        frame = self.watch.map_frame()
        self.assertEqual(frame["image"], (self.picture, 3))  # kept as the game sent it, in memory: GDI+ reads JPEG
        self.assertEqual(self.watch.map["seen"], minimap.keep(OBJECTS))
        self.assertTrue(frame["marks"])

    def test_the_aircraft_glides_between_readings(self):
        clock = [1000.0]  # the test's own: Python 3.12's on Windows moves by 15 ms steps
        with mock.patch.object(alarms.time, "monotonic", lambda: clock[0]):
            for x in (0.5, 0.52):
                self.objects[0] = {**ME, "x": x}
                self.watch.tick()
                clock[0] += alarms.MAP_S
        glide = self.watch.map["glide"]
        (t0, a), (t1, b) = glide.before, glide.latest
        self.assertAlmostEqual(glide.at(t1 + (t1 - t0) / 2)["x"], 0.51, places=5)
        self.assertEqual(list(self.watch.map["trail"]), [(0.5, 0.5), (0.52, 0.5)])

    def test_the_picture_asked_again_until_it_comes(self):
        self.picture = b"blank"  # the app opened as the battle starts: the game has no map yet
        clock = [1000.0]
        with mock.patch.object(alarms.time, "monotonic", lambda: clock[0]):
            self.watch.tick()
            self.assertIsNone(self.watch.map["image"])
            self.picture = b"\x89PNG a map" * 200
            clock[0] += alarms.MAP_S
            self.watch.tick()
            self.assertIsNone(self.watch.map["image"])  # not at every reading
            clock[0] += alarms.PICTURE_S
            self.watch.tick()
        self.assertEqual(self.watch.map["image"], self.picture)

    def test_allies_only_when_asked(self):
        self.watch.tick()
        self.assertEqual(self.watch.map["seen"]["allies"], [])
        self.watch.set_config({**CFG, "mapAllies": True}, {})
        self.watch.map["t"] = 0
        self.watch.tick()
        self.assertEqual(len(self.watch.map["seen"]["allies"]), 1)

    def test_off_reads_nothing(self):
        self.watch.set_config(alarms.clean({}, WORDS), {})
        with mock.patch.object(self.watch, "read_map") as read:
            self.watch.tick()
        read.assert_not_called()
        self.assertIsNone(self.watch.map_frame())

    def test_the_preview_shows_the_sample(self):
        self.watch.preview = CFG
        self.watch.map_live = None
        frame = self.watch.map_frame()
        self.assertEqual(frame["image"], (None, None))
        self.assertTrue(self.watch.sample_map(CFG))
        self.assertEqual(self.watch.sample_map(alarms.clean({}, WORDS)), [])


@unittest.skipUnless(PAINTER, "GDI+ or cairo")
class Painted(unittest.TestCase):
    """GDI+ or cairo into memory, no window: what the corners and the middle come out as."""

    def paint(self, **cfg):
        frame = minimap.draw(minimap.SAMPLE, minimap.SAMPLE_INFO, minimap.SAMPLE_TRAIL, {**CFG, "mapX": 10, "mapY": 10, "mapSize": 200, **cfg})
        px = painter().pixels({**frame, "image": (None, None)}, 224, 254, 8, 8)
        return lambda x, y: px[(y * 224 + x) * 4: (y * 224 + x) * 4 + 4]  # B, G, R, A

    def test_square(self):
        at = self.paint()
        self.assertEqual(at(4, 4)[3], 255)  # the corner of the map
        self.assertEqual(at(220, 250)[3], 0)  # outside it

    def test_round(self):
        at = self.paint(mapShape="round")
        self.assertEqual(at(4, 4)[3], 0)  # the corner, cut
        self.assertEqual(at(110, 110)[3], 255)  # the middle


@unittest.skipUnless(PAINTER, "GDI+ or cairo")
class Contrast(unittest.TestCase):
    """On a bright map (a white picture here): a dark edge round each mark, and the map darkened as set."""

    def setUp(self):
        import struct
        import zlib
        rows = b"".join(b"\x00" + b"\xff\xff\xff" * 64 for _ in range(64))
        chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
        png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 64, 64, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")
        self.painter = painter()
        self.assertTrue(self.painter.load(png, "white"))

    def pixel(self, dim, x, y):
        cfg = {**CFG, "mapX": 0, "mapY": 0, "mapSize": 200, "mapDim": dim}
        frame = minimap.draw({"me": None, "fixed": [{"type": "bombing_point", "color": "#174DFF", "x": 0.5, "y": 0.5}], "allies": []},
                             minimap.SAMPLE_INFO, [], cfg)
        px = self.painter.pixels(frame, 244, 234, 0, 0)
        return px[(y * 244 + x) * 4]  # its blue

    def test_the_map_darkened(self):
        self.assertGreater(self.pixel(0, 20, 20), 240)
        self.assertLess(self.pixel(50, 20, 20), 140)

    def test_a_dark_edge_round_a_mark(self):
        self.assertLess(self.pixel(0, 108, 100), 60)  # just outside the base's square, whose side is at 105
        self.assertGreater(self.pixel(0, 120, 100), 240)  # further out, the map


if __name__ == "__main__":
    unittest.main()
