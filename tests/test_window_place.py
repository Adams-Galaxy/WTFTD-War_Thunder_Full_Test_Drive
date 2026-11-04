"""The app window reopens where it was closed: WTFTD keeps its place (Edge loses an app window's own, 127.0.0.1 has dots)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from wtftd import __main__ as app

PLACE = {"x": 2600, "y": 40, "w": 1500, "h": 920, "max": True}


class Window:
    """A stand-in for tray: a window seen a few times, then closed; it moves once."""

    def __init__(self, looks: int, places: list, usable=lambda p: isinstance(p, dict)):
        self.looks, self.places, self.usable = looks, list(places), usable
        self.put = mock.Mock()
        self.minimize = mock.Mock()

    def find_window(self):
        self.looks -= 1
        return 7 if self.looks >= 0 else None

    def place_of(self, window):
        return self.places.pop(0) if len(self.places) > 1 else self.places[0]


class KeepPlace(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "window.json"
        for name in ("PLACE_S",):
            p = mock.patch.object(app, name, 0)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(app.time, "sleep", lambda s: None)
        p.start()
        self.addCleanup(p.stop)

    def test_the_place_kept_is_put_back_then_followed(self):
        self.path.write_text(json.dumps(PLACE), encoding="utf-8")
        moved = {**PLACE, "x": 100, "max": False}
        window = Window(5, [PLACE, moved])
        app.keep_place(window, lambda key: False, self.path)
        window.put.assert_called_once_with(7, PLACE)
        window.minimize.assert_not_called()
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), moved)

    def test_first_time_nothing_to_put_back(self):
        window = Window(3, [PLACE])
        app.keep_place(window, lambda key: key == "startMinimized", self.path)
        window.put.assert_not_called()
        window.minimize.assert_called_once()  # after the place: minimized where it will come back
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), PLACE)

    def test_a_place_off_every_screen_stays_unused(self):
        self.path.write_text(json.dumps(PLACE), encoding="utf-8")
        window = Window(1, [PLACE], usable=lambda p: False)
        app.keep_place(window, lambda key: False, self.path)
        window.put.assert_not_called()

    def test_no_window_no_harm(self):
        window = Window(0, [PLACE])
        app.keep_place(window, lambda key: False, self.path)
        self.assertFalse(self.path.exists())


@unittest.skipUnless(sys.platform == "win32", "Windows")
class Usable(unittest.TestCase):
    def test_odd_places(self):
        from wtftd import tray
        for bad in (None, [], {"x": 0}, {**PLACE, "w": 50}, {**PLACE, "x": 1.5}, {**PLACE, "max": 1}, {**PLACE, "x": -900000}):
            self.assertFalse(tray.usable(bad), bad)
        self.assertTrue(tray.usable({"x": 10, "y": 10, "w": 800, "h": 600, "max": False}))  # the primary screen's corner


if __name__ == "__main__":
    unittest.main()
