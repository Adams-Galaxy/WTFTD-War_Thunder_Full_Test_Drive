"""The app window reopens where it was closed: WTFTD keeps its place (Edge loses an app window's own, 127.0.0.1 has dots)."""
import http.server
import json
import sys
import tempfile
import threading
import time
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
class Opened(unittest.TestCase):
    """The browser is told the place, in its pixels: physical ones over the main screen's scale."""

    def args(self, place):
        from wtftd import tray
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "window.json"
            path.write_text(json.dumps(place), encoding="utf-8")
            with mock.patch.object(app, "PLACE", path), mock.patch.object(tray, "usable", lambda p: True), \
                    mock.patch.object(tray, "primary_scale", lambda: 1.5), \
                    mock.patch.object(tray, "work_area", lambda p: {"x": 3840, "y": 0, "w": 3840, "h": 2088, "max": True}):
                return app.window_args()

    def test_where_it_was(self):
        self.assertEqual(self.args({**PLACE, "max": False}), ["--window-position=1733,27", "--window-size=1000,613"])

    def test_maximized_as_big_as_its_screen(self):
        # --start-maximized is dropped by the browser given a place: the screen's size instead, then keep_place maximizes it
        self.assertEqual(self.args(PLACE), ["--window-position=2560,0", "--window-size=2560,1392"])


@unittest.skipUnless(sys.platform == "win32", "Windows")
class Usable(unittest.TestCase):
    def test_odd_places(self):
        from wtftd import tray
        for bad in (None, [], {"x": 0}, {**PLACE, "w": 50}, {**PLACE, "x": 1.5}, {**PLACE, "max": 1}, {**PLACE, "x": -900000}):
            self.assertFalse(tray.usable(bad), bad)
        self.assertTrue(tray.usable({"x": 10, "y": 10, "w": 800, "h": 600, "max": False}))  # the primary screen's corner


if __name__ == "__main__":
    unittest.main()


class Started(unittest.TestCase):
    """WTFTD started a second time from the same folder: the running one comes to the front, a closing one is waited for."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.running = Path(tmp.name) / "running.json"
        self.answer = {"shown": True, "window": True}
        self.httpd = app.server.ThreadingHTTPServer(("127.0.0.1", 0), app.server.Handler)
        self.addCleanup(self.httpd.server_close)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.shutdown)
        self.port = self.httpd.server_address[1]
        p = mock.patch.object(app.server, "SHOW_WINDOW", lambda: self.answer["shown"])
        p.start()
        self.addCleanup(p.stop)

    def started(self, port=None, wait=0.0):
        self.running.write_text(json.dumps({"port": port or self.port}))
        with mock.patch.object(app.webbrowser, "open") as opened:
            return app.already_running(self.running, wait), opened

    def test_nothing_running(self):
        self.assertFalse(app.already_running(self.running))
        self.assertFalse(self.started(port=app.free_port(49200))[0])  # the file stayed after a crash: nobody answers

    def test_the_running_one_comes_to_the_front(self):
        before = dict(app.server.PAGE)
        stop, opened = self.started()
        self.assertTrue(stop)
        opened.assert_not_called()
        self.assertEqual(app.server.PAGE, before)  # not the page's doing: a closing WTFTD still sees its page gone

    def test_one_without_a_window_opens_its_page(self):
        with mock.patch.object(app.server, "SHOW_WINDOW", None):
            stop, opened = self.started()
        self.assertTrue(stop)
        opened.assert_called_once_with(f"http://127.0.0.1:{self.port}/")

    def test_a_closing_one_is_waited_for(self):
        self.answer["shown"] = False  # its window is gone
        threading.Timer(0.3, lambda: (self.httpd.shutdown(), self.httpd.server_close())).start()
        t0 = time.monotonic()
        stop, opened = self.started(wait=5)
        self.assertFalse(stop)  # this one starts, on the port freed
        self.assertLess(time.monotonic() - t0, 3)
        self.assertEqual(app.free_port(self.port), self.port)

    def test_another_program_on_that_port(self):
        other = http.server.HTTPServer(("127.0.0.1", 0), http.server.SimpleHTTPRequestHandler)
        self.addCleanup(other.server_close)
        threading.Thread(target=other.handle_request, daemon=True).start()
        self.assertFalse(self.started(port=other.server_address[1])[0])


class FromSteam(unittest.TestCase):
    """Steam's launch options (WTFTD --with-game %command%): the game first, WTFTD with it, and the process as long as the game."""

    def run_it(self, running: bool, argv=("WTFTD", "--with-game", r"D:\Steam\War Thunder\launcher.exe", "-x")):
        with mock.patch.object(app.sys, "argv", list(argv)), mock.patch.object(app.subprocess, "Popen") as started, \
                mock.patch.object(app.sys, "platform", "win32"), \
                mock.patch.object(app, "already_running", return_value=running), mock.patch.object(app, "wait_game") as waited:
            app.main()
        return started, waited

    def test_the_game_then_wtftd(self):
        started, waited = self.run_it(running=False)
        game, wtftd = started.call_args_list
        self.assertEqual(game.args[0], [r"D:\Steam\War Thunder\launcher.exe", "-x"])
        self.assertEqual(wtftd.args[0], [*app.server.app_command(), "--game-started"])
        waited.assert_called_once()

    def test_the_running_one_is_shown_instead(self):
        started, waited = self.run_it(running=True)
        self.assertEqual(len(started.call_args_list), 1)  # the game only: already_running brought WTFTD forward
        waited.assert_called_once()

    def test_waits_for_the_game_to_come_and_go(self):
        seen = iter([False, True, True, False, True])
        with mock.patch.object(app, "reader", lambda: True), mock.patch.object(app, "game_running", lambda: next(seen)), \
                mock.patch.object(app.time, "sleep"):
            app.wait_game(appear=60, poll=0)
        self.assertEqual(next(seen), True)  # left at the first False after the game was seen
        with mock.patch.object(app, "reader", lambda: True), mock.patch.object(app, "game_running", lambda: False), \
                mock.patch.object(app.time, "sleep"):
            app.wait_game(appear=0, poll=0)  # never came: gone at once

    def test_the_line_for_steam(self):
        with mock.patch.object(app.server.sys, "platform", "win32"), mock.patch.object(app.server.game, "is_steam_install", lambda gd: True):
            line = app.server.steam_launch_option(Path("."))
        self.assertTrue(line.endswith(" --with-game %command%") and line.startswith('"'))
        with mock.patch.object(app.server.game, "is_steam_install", lambda gd: False):
            self.assertIsNone(app.server.steam_launch_option(Path(".")))


class LaunchOnStart(unittest.TestCase):
    """Settings' option: War Thunder starts with WTFTD, unless it runs already or Steam is starting it."""

    def launched(self, on=True, running=False, argv=("WTFTD",)):
        with mock.patch.object(app.STATE, "settings", lambda: {"launchGame": on}), mock.patch.object(app.STATE, "game_dir", lambda: Path("wt")), \
                mock.patch.object(app, "reader", lambda: True), mock.patch.object(app, "game_running", lambda: running), \
                mock.patch.object(app.sys, "argv", list(argv)), mock.patch.object(app, "launch") as launch:
            app.launch_on_start()
        return launch.call_args_list

    def test_only_when_asked_and_not_running(self):
        self.assertEqual(self.launched(), [mock.call(Path("wt"))])
        self.assertEqual(self.launched(on=False), [])
        self.assertEqual(self.launched(running=True), [])
        self.assertEqual(self.launched(argv=("WTFTD", "--game-started")), [])  # Steam is starting it: not twice

    def test_steam_says_the_game_is_on_its_way(self):
        with mock.patch.object(app.sys, "argv", ["WTFTD", "--with-game", "launcher.exe"]), mock.patch.object(app.subprocess, "Popen") as started, \
                mock.patch.object(app.sys, "platform", "win32"), \
                mock.patch.object(app, "already_running", return_value=False), mock.patch.object(app, "wait_game"):
            app.main()
        self.assertEqual(started.call_args_list[1].args[0][-1], "--game-started")
