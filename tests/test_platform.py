"""Windows / macOS / Linux differences: where the game files are, which Oodle runtime file names count, the alarms, the
game read in flight."""
import importlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from wtftd import __main__ as app, alarms, bench, flightlog, game, maptex, paths, server, waveout, x11


class GameFolder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "War Thunder"

    def tearDown(self):
        self.tmp.cleanup()

    def install(self, rel: Path) -> Path:
        files = self.root / rel
        files.mkdir(parents=True)
        (files / "aces.vromfs.bin").write_bytes(b"")
        return files

    def test_windows_layout(self):
        files = self.install(Path("."))
        self.assertEqual(game.resolve_game_dir(self.root), files)

    def test_mac_layout_from_any_level(self):
        files = self.install(game.MAC_GAME)
        for start in (self.root, self.root / "WarThunderLauncher.app",
                      self.root / "WarThunderLauncher.app/Contents/WarThunder.app", files):
            self.assertEqual(game.resolve_game_dir(start), files, start)

    def test_not_a_game_folder(self):
        self.root.mkdir()
        self.assertIsNone(game.resolve_game_dir(self.root))

    def test_which_servers_an_install_plays_on(self):
        files = self.install(Path("."))
        self.assertIsNone(game.circuit(files))  # no config.blk yet
        self.assertIsNone(game.circuit(None))
        live = b'graphics{\n  vsync:b=yes\n}\nyunetwork{\n  curCircuit:t="production"\n}\nlogin:t="someone"\n'
        (files / "config.blk").write_bytes(live)
        self.assertEqual(game.circuit(files), "production")
        (files / "config.blk").write_bytes(live.replace(b"production", b"dev"))
        self.assertEqual(game.circuit(files), "dev")
        (files / "config.blk").write_bytes(live)
        (files / "matchingdevmode").write_bytes(b"")  # Gaijin's wiki: the dev client's folder has it, empty
        self.assertEqual(game.circuit(files), "dev")

    def test_mac_launcher_app(self):
        files = self.install(game.MAC_GAME)
        self.assertEqual(game._mac_app(files), self.root / "WarThunderLauncher.app")
        self.assertIsNone(game._mac_app(self.root))


class Standalone(unittest.TestCase):
    """Gaijin launcher install (no Steam): found in %LOCALAPPDATA%\\WarThunder, started with its launcher.exe."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.local = Path(self.tmp.name)
        self.files = self.local / "WarThunder"
        self.files.mkdir()
        for name in ("aces.vromfs.bin", "launcher.exe"):
            (self.files / name).write_bytes(b"")

    def tearDown(self):
        self.tmp.cleanup()

    def test_detected_and_launched_without_steam(self):
        with mock.patch.object(sys, "platform", "win32"), mock.patch.object(game, "_steam_roots", return_value=[]), \
                mock.patch.dict("os.environ", {"LOCALAPPDATA": str(self.local)}):
            found = game.detect_game_dir()
        self.assertEqual(found, self.files)
        self.assertFalse(game.is_steam_install(found))
        self.assertEqual(game.user_missions_dir(found), self.files / "UserMissions")
        with mock.patch.object(sys, "platform", "win32"), mock.patch.object(game.subprocess, "Popen") as popen:
            self.assertEqual(game.launch(found), "launcher")
        popen.assert_called_once_with([str(self.files / "launcher.exe")], cwd=str(self.files))

    def test_steam_install_launches_through_steam(self):
        steam = self.local / "steamapps" / "common" / "War Thunder"
        steam.mkdir(parents=True)
        (steam / "aces.vromfs.bin").write_bytes(b"")
        self.assertTrue(game.is_steam_install(steam))
        with mock.patch.object(game, "_open") as op:
            self.assertEqual(game.launch(steam), "steam")
        op.assert_called_once_with(f"steam://rungameid/{game.STEAM_APP_ID}")


class Linux(unittest.TestCase):
    """Linux: its data folder, Steam (also Flatpak) or Gaijin's launcher, a Chromium browser for the app window."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.linux = mock.patch.object(sys, "platform", "linux")
        self.linux.start()
        self.addCleanup(self.linux.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def install(self, folder: Path, *names: str) -> Path:
        folder.mkdir(parents=True)
        for name in ("aces.vromfs.bin", *names):
            (folder / name).write_bytes(b"")
        return folder

    def test_data_folder_follows_xdg(self):
        with mock.patch.object(Path, "home", return_value=self.home):
            with mock.patch.dict("os.environ", {"XDG_DATA_HOME": str(self.home / "data")}):
                self.assertEqual(paths._app_home(), self.home / "data" / "WTFTD")
            for unset in ("", "relative/data"):  # the XDG rule: a relative path is ignored
                with mock.patch.dict("os.environ", {"XDG_DATA_HOME": unset}):
                    self.assertEqual(paths._app_home(), self.home / ".local" / "share" / "WTFTD")

    def test_flatpak_steam(self):
        files = self.install(self.home / ".var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/common/War Thunder")
        with mock.patch.object(Path, "home", return_value=self.home):
            self.assertEqual(game.detect_game_dir(), files)
        self.assertTrue(game.is_steam_install(files))

    def test_standalone_found_and_launched(self):
        files = self.install(self.home / "WarThunder", "launcher")
        with mock.patch.object(Path, "home", return_value=self.home), mock.patch.object(game, "_steam_roots", return_value=[]):
            self.assertEqual(game.detect_game_dir(), files)
        with mock.patch.object(game.subprocess, "Popen") as popen:
            self.assertEqual(game.launch(files), "launcher")
        popen.assert_called_once_with([str(files / "launcher")], cwd=str(files))

    def test_app_window_in_a_chromium_browser(self):
        with mock.patch.object(app.shutil, "which", side_effect={"chromium": "/usr/bin/chromium"}.get):
            self.assertEqual(app.find_app_browser(), "/usr/bin/chromium")
        with mock.patch.object(app.shutil, "which", return_value=None):  # Firefox alone: the default browser instead
            self.assertIsNone(app.find_app_browser())


class Alarms(unittest.TestCase):
    """The overlay and its sounds: Windows only (winmm, user32), off on macOS and Linux without a trace in the app. The game
    read in flight, for Flight data and the Test bench: Windows and Linux."""

    def test_the_game_is_read_in_flight_on_windows_and_linux(self):
        for platform, on in (("win32", True), ("linux", True), ("darwin", False)):
            with mock.patch.object(sys, "platform", platform):
                self.assertEqual(alarms.reader(), on, platform)

    def test_mac_and_linux_have_no_alarms(self):
        for platform in ("darwin", "linux"):
            with mock.patch.object(sys, "platform", platform):
                self.assertFalse(alarms.available())
                with mock.patch.object(server.WATCH, "set_enabled") as switch:
                    server.apply_alarm_settings()
                switch.assert_called_once_with(False)

    def test_off_until_the_player_turns_them_on(self):
        for saved, on in (({}, False), ({"alarms": False}, False), ({"alarms": True}, True)):
            with mock.patch.object(sys, "platform", "win32"), mock.patch.object(server.STATE, "settings", return_value=saved), \
                    mock.patch.object(server.WATCH, "set_enabled") as switch:
                server.apply_alarm_settings()
            switch.assert_called_once_with(on)

    def test_loads_without_windows_modules(self):
        with mock.patch.dict(sys.modules, {"winsound": None, "tkinter": None}):
            importlib.reload(alarms)

    def test_no_overlay_while_off(self):
        w = alarms.Watch(lambda path: None, dict)
        w.set_enabled(False)
        self.assertIsNone(w.overlay)
        w.stop()


class GameProcess(unittest.TestCase):
    """Linux: the game is running when one of its processes is (/proc/<pid>/comm), there's no window to look for."""

    def proc(self, *names) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        for pid, name in enumerate(names, 100):
            (root / str(pid)).mkdir()
            (root / str(pid) / "comm").write_text(name + "\n", encoding="utf-8")
        (root / "99").mkdir()  # gone between the listing and the read
        (root / "self").mkdir()  # not a process
        (root / "self" / "comm").write_text("aces\n", encoding="utf-8")
        return root

    def test_the_native_client_or_the_windows_one_under_proton(self):
        with mock.patch.object(sys, "platform", "linux"):
            for name in ("aces", "aces.exe"):
                self.assertTrue(alarms.game_running(self.proc("bash", name)), name)
            self.assertFalse(alarms.game_running(self.proc("bash", "launcher", "steam", "aces_be")))  # the launcher alone isn't the game

    def test_the_page_is_told_on_windows_and_linux(self):
        for platform, told in (("win32", True), ("linux", True), ("darwin", False)):
            with mock.patch.object(sys, "platform", platform), mock.patch.object(alarms, "game_running", return_value=True):
                self.assertEqual(server.game_up(), told, platform)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux's /proc")
    def test_a_real_process(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        aces = Path(tmp.name) / "aces"
        shutil.copy(shutil.which("sleep"), aces)
        self.assertFalse(alarms.game_running())
        proc = subprocess.Popen([str(aces), "30"])
        try:
            self.assertTrue(alarms.game_running())
        finally:
            proc.kill()
            proc.wait()


class GameOnLinux(unittest.TestCase):
    """Linux: the game in front and the screen from X11, War Thunder launched with WTFTD, and from Steam's launch line."""

    def test_the_game_in_front(self):
        with mock.patch.object(sys, "platform", "linux"):
            for pid, name, front in ((None, "", True), (42, "aces", True), (42, "aces.exe", True), (42, "chromium", False)):
                with mock.patch.object(alarms.x11, "active_pid", return_value=pid), mock.patch.object(alarms, "_process_name", return_value=name):
                    self.assertEqual(alarms.game_focused(), front, (pid, name))  # None: can't be told, as if it were

    def test_the_screen(self):
        with mock.patch.object(sys, "platform", "linux"):
            with mock.patch.object(alarms.x11, "screen_size", return_value=(2560, 1440)):
                self.assertEqual(alarms.screen(), (2560, 1440))
            with mock.patch.object(alarms.x11, "screen_size", return_value=None):  # no X display
                self.assertEqual(alarms.screen(), (3840, 2160))

    def test_no_x_display(self):
        with mock.patch.dict(x11._lib, {"x": None}), mock.patch.object(x11, "_local", threading.local()):
            self.assertIsNone(x11.active_pid())
            self.assertIsNone(x11.screen_size())

    @unittest.skipUnless(sys.platform.startswith("linux") and os.environ.get("DISPLAY"), "an X display")
    def test_a_real_display(self):
        width, height = x11.screen_size()
        self.assertTrue(width > 0 and height > 0)
        pid = x11.active_pid()
        self.assertTrue(pid is None or pid > 0)

    def test_launched_with_wtftd(self):
        with mock.patch.object(sys, "platform", "linux"), mock.patch.object(app.STATE, "settings", lambda: {"launchGame": True}), \
                mock.patch.object(app.STATE, "game_dir", lambda: Path("wt")), mock.patch.object(app, "game_running", lambda: False), \
                mock.patch.object(app.sys, "argv", ["WTFTD"]), mock.patch.object(app, "launch") as launch:
            app.launch_on_start()
        launch.assert_called_once_with(Path("wt"))

    def from_steam(self, systemd: bool) -> list:
        command = ["/home/u/.steam/steam/ubuntu12_32/reaper", "SteamLaunch", "AppId=236390", "--", "/home/u/War Thunder/launcher"]
        with mock.patch.object(sys, "platform", "linux"), mock.patch.object(app.sys, "argv", ["WTFTD", "--with-game", *command]), \
                mock.patch.object(app.subprocess, "Popen") as started, mock.patch.object(app, "already_running", return_value=False), \
                mock.patch.object(app, "wait_game") as waited, mock.patch.dict(os.environ, {"DISPLAY": ":0"}), \
                mock.patch.object(app.shutil, "which", lambda name: "/usr/bin/systemd-run" if systemd and name == "systemd-run" else None):
            app.main()
        waited.assert_called_once()
        game_, wtftd = started.call_args_list
        self.assertEqual((game_.args[0], game_.kwargs["cwd"]), (command, None))  # Steam's wrapper, in the folder Steam gave
        self.assertEqual(wtftd.args[0][-1], "--game-started")
        self.assertTrue(wtftd.kwargs["start_new_session"])
        return wtftd.args[0]

    def test_from_steam_wtftd_apart_from_the_game(self):
        line = self.from_steam(systemd=True)
        self.assertEqual(line[:4], ["systemd-run", "--user", "--quiet", "--collect"])
        self.assertIn("--setenv=DISPLAY", line)
        self.assertEqual(line[line.index("--") + 1:-1], app.server.app_command())
        self.assertEqual(self.from_steam(systemd=False), [*app.server.app_command(), "--game-started"])

    def test_the_line_for_steam(self):
        steam = Path("/home/u/.local/share/Steam/steamapps/common/War Thunder")
        with mock.patch.object(sys, "platform", "linux"):
            self.assertTrue(server.steam_launch_option(steam).endswith(" --with-game %command%"))
            self.assertIsNone(server.steam_launch_option(Path("/home/u/WarThunder")))  # Gaijin's launcher: no Steam
        with mock.patch.object(sys, "platform", "darwin"):
            self.assertIsNone(server.steam_launch_option(steam))


class Pulse:
    """A stand-in for libpulse-simple: what each stream was opened with and given (functions, as ctypes' take a restype)."""

    def __init__(self):
        self.opened, self.written, self.calls = [], [], []

        def pa_simple_new(server_, name, direction, sink, stream, spec, channels, attr, error):
            self.opened.append((sink, spec._obj.format, spec._obj.rate, spec._obj.channels, attr._obj.tlength))
            return 1234

        def pa_simple_write(stream, data, size, error):
            self.written.append(bytes(data[:size]))
            return 0

        def pa_simple_drain(stream, error):
            self.calls.append("drain")

        def pa_simple_flush(stream, error):
            self.calls.append("flush")

        def pa_simple_free(stream):
            self.calls.append("free")

        for fn in (pa_simple_new, pa_simple_write, pa_simple_drain, pa_simple_flush, pa_simple_free):
            setattr(self, fn.__name__, fn)


class SoundOnLinux(unittest.TestCase):
    """Linux: the alarms' sounds through PulseAudio's simple API (PipeWire's too), else ALSA's aplay; outputs from pactl.
    No sound reaches a speaker here: the libraries and programs are stand-ins, the real one plays silence."""

    SINKS = json.dumps([{"name": "alsa_output.pci.analog-stereo", "description": "Built-in Audio"},
                        {"name": "bluez_output.headset", "description": "Headset"}]).encode()

    def setUp(self):
        for p in (mock.patch.object(sys, "platform", "linux"), mock.patch.dict(waveout._SINKS, clear=True),
                  mock.patch.object(waveout.subprocess, "run", return_value=mock.Mock(stdout=self.SINKS))):
            p.start()
            self.addCleanup(p.stop)
        self.wav = alarms.tone(880, 200, 0)

    def test_the_outputs_by_their_names(self):
        self.assertEqual(waveout.devices(), ["Built-in Audio", "Headset"])
        with mock.patch.object(waveout.subprocess, "run", side_effect=FileNotFoundError):  # no pactl: the default output only
            self.assertEqual(waveout.devices(), [])

    def test_played_on_the_output_picked(self):
        pulse = Pulse()
        with mock.patch.object(waveout.ctypes, "CDLL", return_value=pulse):
            self.assertTrue(waveout.play(self.wav, "Headset"))
            self.assertTrue(waveout.play(self.wav, "Gone"))  # unplugged since: the default one
        self.assertEqual(pulse.opened, [(b"bluez_output.headset", 3, alarms.SOUND_RATE, 1, alarms.SOUND_RATE * 2 // 10),
                                        (None, 3, alarms.SOUND_RATE, 1, alarms.SOUND_RATE * 2 // 10)])
        self.assertEqual(len(pulse.written[0]), alarms.SOUND_RATE * 2 // 5)  # 200 ms of 16-bit mono, at once
        self.assertEqual(pulse.calls, ["drain", "free"] * 2)

    def test_aplay_without_pulseaudio(self):
        proc = mock.Mock()
        with mock.patch.object(waveout.ctypes, "CDLL", side_effect=OSError("no libpulse")), \
                mock.patch.object(waveout.subprocess, "Popen", return_value=proc) as started:
            self.assertTrue(waveout.play(self.wav, "Headset"))
        self.assertEqual(started.call_args.args[0], ["aplay", "-q", "-t", "raw", "-f", "S16_LE", "-r", str(alarms.SOUND_RATE), "-c", "1"])
        self.assertEqual(len(proc.stdin.write.call_args.args[0]), alarms.SOUND_RATE * 2 // 5)
        proc.stdin.close.assert_called_once()
        proc.kill.assert_not_called()  # played to its end
        with mock.patch.object(waveout.ctypes, "CDLL", side_effect=OSError), mock.patch.object(waveout.subprocess, "Popen", side_effect=FileNotFoundError):
            self.assertFalse(waveout.play(self.wav))  # nothing to play it with

    def test_a_held_sound_until_stopped(self):
        pulse = Pulse()
        with mock.patch.object(waveout.ctypes, "CDLL", return_value=pulse):
            loop = waveout.Loop(self.wav, "")
            for _ in range(200):
                if len(pulse.written) > 8:
                    break
                time.sleep(0.01)
            loop.stop()
        self.assertGreater(len(pulse.written), 8)  # 200 ms in chunks of 50, written again and again
        self.assertEqual(len(pulse.written[0]), int(alarms.SOUND_RATE * waveout.CHUNK_S) * 2)  # whole 16-bit frames
        self.assertEqual(pulse.calls, ["flush", "free"])  # what's left in the buffer dropped at once
        self.assertFalse(loop.linux.is_alive())

    @unittest.skipUnless(sys.platform.startswith("linux") and os.environ.get("PULSE_SERVER"), "a PulseAudio server")
    def test_a_real_sound_server(self):
        self.assertTrue(waveout.play(self.wav))  # silence: volume 0


class Game(BaseHTTPRequestHandler):
    """A stand-in for the game's own page on port 8111: what self.server.said holds, by path."""

    def do_GET(self):
        body = self.server.said.get(self.path.split("?")[0])
        if body is None:
            return self.send_error(404)
        raw = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):
        pass


class FlightOnLinux(unittest.TestCase):
    """Linux: the game's page on port 8111 read as on Windows (here its stand-in, over HTTP), a test flight recorded to
    CSV and analysed by the Test bench, the overlay and its sounds left out. The clock is the test's: 25 s flown at once."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.game = ThreadingHTTPServer(("127.0.0.1", 0), Game)
        self.game.said = {}
        threading.Thread(target=self.game.serve_forever, daemon=True).start()
        self.addCleanup(self.game.server_close)
        self.addCleanup(self.game.shutdown)
        self.now = 1000.0
        clock = types.SimpleNamespace(monotonic=lambda: self.now, time=lambda: 1.8e9 + self.now, strftime=time.strftime)
        for p in (mock.patch.object(sys, "platform", "linux"), mock.patch.object(server, "WT_API", f"http://127.0.0.1:{self.game.server_port}"),
                  mock.patch.object(alarms, "time", clock), mock.patch.object(flightlog, "time", clock), mock.patch.object(bench, "time", clock),
                  mock.patch.object(bench, "FILE", self.folder / "bench.json"), mock.patch.object(bench, "AWAY_S", 0)):
            p.start()
            self.addCleanup(p.stop)
        self.watch = alarms.Watch(server._wt_get, dict, lambda: True, save=lambda: None, logs=self.folder)
        self.addCleanup(self.watch.set_log, False)
        self.bench = bench.Bench(self.watch, self.folder, lambda: "2.59.0.92")

    def look(self, seconds: float, flying: bool = True, rate: int = 4):
        """The bench and Watch, as their threads do, this long; flying: level at full throttle, else in the hangar."""
        for _ in range(int(seconds * rate)):
            wobble = math.sin(self.now * 2.3)  # a hand on the stick: a settled game that repeats every number looks paused
            self.game.said["/state"] = {"valid": True, "Mfuel0, kg": 300, "Mfuel, kg": 250, "IAS, km/h": 500, "TAS, km/h": 610, "M": 0.55,
                                        "H, m": 5000 + round(2 * wobble), "Vy, m/s": round(.3 * wobble, 1), "Ny": 1.0,
                                        "throttle 1, %": 100} if flying else {"valid": False}
            self.game.said["/indicators"] = {"valid": True, "type": "bf-109f-4", "aviahorizon_roll": round(wobble, 1), "compass": 90}
            self.bench.step()
            self.watch.tick()
            self.now += 1 / rate

    def test_a_top_speed_run(self):
        self.assertTrue(alarms.reader())
        self.bench.arm({"vehicle": "bf-109f-4", "test": "top", "fuel": 50, "altitude": 5000})
        with mock.patch.object(alarms, "play") as play:
            self.look(25)
            self.assertTrue(self.watch.flying)
            self.assertEqual(self.watch.trace[-1]["tas"], 610)  # Flight data's curves
            log = self.bench.log
            self.assertTrue(log and log.startswith("bf-109f-4-"))
            self.look(1, flying=False)  # back in the hangar
        play.assert_not_called()
        self.assertIsNone(self.watch.overlay)
        self.assertEqual(self.watch.display, [])
        names = {alarms.column(n): n for n in alarms.SERIES}
        rows = flightlog.read_log(self.folder, log, names)["rows"]
        self.assertGreater(rows[-1]["t"] - rows[0]["t"], bench.TOP_S)
        run = bench.load()["runs"][0]
        self.assertEqual((run["test"], run["log"], run["game"], run["points"][0]["tas"]), ("top", log, "2.59.0.92", 610.0))
        self.assertIsNone(self.watch.log)  # the recording stopped with the flight


class Feedback(unittest.TestCase):
    """The app fills the GitHub issue forms by their field ids: renaming one would silently empty it."""

    def test_the_fields_exist_in_the_forms(self):
        forms = Path(__file__).parent.parent / ".github" / "ISSUE_TEMPLATE"
        ids = {f: set(re.findall(r"^\s+id: (\w+)", (forms / f).read_text(encoding="utf-8"), re.M))
               for f in ("bug_report.yml", "feature_request.yml")}
        self.assertLessEqual({"version", "game", "what", "vehicle", "share"}, ids["bug_report.yml"])
        self.assertIn("idea", ids["feature_request.yml"])


class OodleNames(unittest.TestCase):
    def test_windows(self):
        with mock.patch.object(sys, "platform", "win32"):
            self.assertEqual(maptex.oodle_version("oo2core_9_win64.dll"), 9)
            self.assertIsNone(maptex.oodle_version("liboo2coremac64.2.9.dylib"))

    def test_mac(self):
        with mock.patch.object(sys, "platform", "darwin"):
            self.assertEqual(maptex.oodle_version("liboo2coremac64.2.9.dylib"), 9)
            self.assertEqual(maptex.oodle_version("liboo2coremac64.2.9.10.dylib"), 9)
            self.assertIsNone(maptex.oodle_version("oo2core_9_win64.dll"))
            self.assertIsNone(maptex.oodle_version("libfoo.dylib"))

    def test_linux(self):
        with mock.patch.object(sys, "platform", "linux"):
            self.assertEqual(maptex.oodle_version("liboo2corelinux64.so.9"), 9)
            self.assertIsNone(maptex.oodle_version("oo2core_9_win64.dll"))
            self.assertIsNone(maptex.oodle_version("liboo2coremac64.2.9.dylib"))


if __name__ == "__main__":
    unittest.main()
