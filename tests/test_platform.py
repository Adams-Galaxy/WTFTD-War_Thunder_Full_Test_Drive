"""Windows / macOS / Linux differences: where the game files are, which Oodle runtime file names count, the alarms, the
game read in flight."""
import base64
import ctypes
import importlib
import json
import math
import os
import re
import shutil
import struct
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

from wtftd import __main__ as app, alarms, bench, cairopaint, flightlog, game, maptex, minimap, paths, server, waveout, x11, xoverlay, xwindow


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

    def test_mac_has_no_alarms(self):
        with mock.patch.object(sys, "platform", "darwin"):
            self.assertFalse(alarms.available())
            with mock.patch.object(server.WATCH, "set_enabled") as switch:
                server.apply_alarm_settings()
            switch.assert_called_once_with(False)

    def test_linux_has_them_as_windows(self):
        with mock.patch.object(sys, "platform", "linux"), mock.patch.object(server.STATE, "settings", return_value={"alarms": True}), \
                mock.patch.object(server.WATCH, "set_enabled") as switch:
            self.assertTrue(alarms.available())
            server.apply_alarm_settings()
        switch.assert_called_once_with(True)

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
        with mock.patch.dict(x11._lib, {"x": None}, clear=True):
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


class JoystickOnLinux(unittest.TestCase):
    """Linux: joystick buttons from /dev/input/js<n> (here files holding the same 8-byte events), as winmm gives them."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        for p in (mock.patch.object(sys, "platform", "linux"), mock.patch.object(alarms, "JS_PATH", str(self.folder / "js{}")),
                  mock.patch.dict(alarms._JS, clear=True)):
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(lambda: [os.close(device) for device, _ in alarms._JS.values()])

    def events(self, joy: int, *events):
        """(button, pressed, at opening): what the device would send next."""
        with open(self.folder / f"js{joy}", "ab") as f:
            for button, pressed, init in events:
                f.write(struct.pack("<IhBB", 1000, int(pressed), 0x01 | (0x80 if init else 0), button))

    def test_held_buttons_as_key_codes(self):
        self.events(1, (0, False, True), (3, True, True))  # its state when opened: button 3 held
        self.assertEqual(alarms.joy_buttons([0, 1]), {alarms.JOY + 32 + 3})  # no js0: nothing from it
        self.events(1, (0, True, False), (3, False, False))
        with open(self.folder / "js1", "ab") as f:
            f.write(struct.pack("<IhBB", 1001, 3000, 0x02, 1))  # an axis: not a button
        self.assertEqual(alarms.joy_buttons([1]), {alarms.JOY + 32})
        self.events(1, (40, True, False))  # past the 32 buttons a key code can tell apart
        self.assertEqual(alarms.joy_buttons([1]), {alarms.JOY + 32})

    def test_waiting_for_a_button(self):
        self.events(0, (2, True, True))  # held already: doesn't count
        with mock.patch.object(alarms.time, "sleep", lambda s: self.events(0, (5, True, False))):
            self.assertEqual(alarms.joy_wait(1), alarms.JOY + 5)


RED_JPEG = base64.b64decode(  # 16 x 16, all (200, 30, 30): a map the game sends as JPEG
    "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAMCAgMCAgMDAwMEAwMEBQgFBQQEBQoHBwYIDAoMDAsKCwsNDhIQDQ4RDgsLEBYQERMUFRUVDA8XGB"
    "YUGBIUFRT/2wBDAQMEBAUEBQkFBQkUDQsNFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBT/wAARCAAQ"
    "ABADASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhBy"
    "JxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKT"
    "lJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAA"
    "AAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRom"
    "JygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExc"
    "bHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDwKiiivzI/uM//2Q==")


class FakeX:
    """A stand-in for libX11's keyboard and pointer: these keycodes held, this pointer mask."""

    def __init__(self, held: set, mask: int):
        self.held_codes, self.mask, self.codes = held, mask, {0x61: 38, 0xFFE1: 50, 0xFFE2: 62, 0xFFBE: 67}

    def XQueryKeymap(self, d, keymap):
        for code in self.held_codes:
            keymap[code >> 3] = bytes([keymap.raw[code >> 3] | 1 << (code & 7)])

    def XKeysymToKeycode(self, d, sym):
        return self.codes.get(sym, 0)

    def XDefaultRootWindow(self, d):
        return 1

    def XQueryPointer(self, d, root, w1, w2, i1, i2, i3, i4, mask):
        mask._obj.value = self.mask
        return 1


class OverlayOnLinux(unittest.TestCase):
    """Linux: My overlay's keys read from X, what may keep the overlay off the screen, and cairo's pictures (the text and
    the minimap have their own tests in test_overlay_text and test_minimap, run with both painters)."""

    def test_keys_and_mouse_buttons_from_x(self):
        with mock.patch.object(x11, "lib", return_value=FakeX({38, 62}, 1 << 9)), mock.patch.object(x11, "display", return_value=1), \
                mock.patch.dict(x11._codes, clear=True):
            held = x11.held([0x41, 0x10, 0x70, 4, 2, 5])  # A, Shift (the right one), F1; middle, right and side buttons
        self.assertEqual(held, {0x41, 0x10, 4})  # the side buttons aren't in X's pointer mask
        with mock.patch.object(x11, "display", return_value=None):
            self.assertEqual(x11.held([0x41]), set())

    def test_what_may_keep_it_off_the_screen(self):
        with mock.patch.object(sys, "platform", "linux"):
            for shown, composited, wayland, note in ((None, False, "", "x11"), (1, False, "", "compositor"),
                                                     (1, True, "wayland-0", "wayland"), (1, True, "", None)):
                with mock.patch.object(x11, "display", return_value=shown), mock.patch.object(x11, "composited", return_value=composited), \
                        mock.patch.dict(os.environ, {"WAYLAND_DISPLAY": wayland}):
                    self.assertEqual(xoverlay.note(), note)
        with mock.patch.object(sys, "platform", "win32"):
            self.assertIsNone(xoverlay.note())

    def test_off_without_an_x_display(self):
        watch = alarms.Watch(lambda path: None, dict, save=lambda: None)
        with mock.patch.object(xoverlay, "note", return_value="x11"), mock.patch("builtins.print") as said:
            xoverlay.run(watch)  # returns: the alarms go on without it
        self.assertIn("no X display", said.call_args.args[0])

    @unittest.skipUnless(sys.platform.startswith("linux") and cairopaint.available(), "cairo")
    def test_the_hud_as_tk_draws_it(self):
        cfg = alarms.clean({"hudColor": "#00FF00", "alert": "#FF0000"}, alarms.labels("en"))
        line, alert = ("l", 10, 50, 90, 50, 3, False), ("l", 10, 80, 90, 80, 3, True)
        px = cairopaint.Painter().hud_pixels(cfg, [line, alert], True, 100, 100)
        at = lambda x, y: px[(y * 100 + x) * 4:(y * 100 + x) * 4 + 4]  # B, G, R, A
        self.assertEqual(at(50, 50), b"\x00\xff\x00\xff")
        self.assertEqual(at(50, 80), b"\x00\x00\xff\xff")  # an alarm on: the alert colour while lit
        self.assertEqual(at(50, 20), b"\x00\x00\x00\x00")
        self.assertEqual(cairopaint.hud_box([line]), (2, 42, 98, 58))

    @unittest.skipUnless(sys.platform.startswith("linux") and cairopaint.available(), "cairo")
    def test_a_jpeg_map(self):
        try:
            ctypes.CDLL("libgdk_pixbuf-2.0.so.0")
        except OSError:
            self.skipTest("no gdk-pixbuf")
        painter = cairopaint.Painter()
        self.assertTrue(painter.load(RED_JPEG, "jpeg"))
        self.assertEqual(painter.image_size, (16, 16))
        frame = minimap.draw({"me": None, "fixed": [], "allies": []}, minimap.SAMPLE_INFO, [],
                             alarms.clean({"mapMode": "on", "mapX": 0, "mapY": 0, "mapSize": 100, "mapDim": 0}, alarms.labels("en")))
        px = painter.pixels(frame, 104, 134, -2, -2)
        b, g, r, a = px[(52 * 104 + 52) * 4:(52 * 104 + 52) * 4 + 4]
        self.assertTrue(r > 180 and g < 60 and b < 60 and a == 255, (b, g, r, a))
        self.assertFalse(painter.load(b"not a picture", "junk"))

    @unittest.skipUnless(sys.platform.startswith("linux") and os.environ.get("WTFTD_X11_TEST") and cairopaint.available(),
                         "real windows on the X display: WTFTD_X11_TEST=1 (in WSL they show on the Windows desktop)")
    def test_real_windows(self):
        made, real = [], x11.Layer

        class Recorded(real):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                made.append(self)

        watch = alarms.Watch(lambda path: None, dict, save=lambda: None)
        cfg = alarms.clean({"hudMode": "on", "mapMode": "on", "blocks": []}, watch.words)
        watch.preview = watch.base = cfg
        watch.display, watch.hud = watch.sample(cfg), watch.sample_hud(cfg, "", "cockpit")
        with mock.patch.object(x11, "Layer", Recorded):
            thread = threading.Thread(target=xoverlay.run, args=(watch,), daemon=True)
            thread.start()
            time.sleep(1.5)
            painter = cairopaint.Painter()
            drawn = {x11.prop(layer.window, "WM_NAME"): (layer.shown, self.read(painter, layer)) for layer in made}
            watch.stopping.set()
            thread.join(3)
        self.assertFalse(thread.is_alive())
        for name in (b"WTFTD HUD", b"WTFTD text", b"WTFTD minimap"):  # drawn before they were shown: kept by their pixmaps
            shown, pixels = drawn[name]
            self.assertTrue(shown and pixels > 1000, (name, shown, pixels))
        self.assertEqual(drawn[b"WTFTD glow"], (False, None))

    @staticmethod
    def read(painter, layer):
        """How many pixels of a shown window aren't see-through, read back through its own connection."""
        if not layer.shown:
            return None
        c, (w, h) = painter.c, layer.box[2:]
        window = c.cairo_xlib_surface_create(layer.d, layer.window, layer.visual, w, h)
        image = c.cairo_image_surface_create(cairopaint.ARGB32, w, h)
        cr = c.cairo_create(image)
        c.cairo_set_source_surface(cr, window, 0, 0)
        c.cairo_set_operator(cr, cairopaint.SOURCE)
        c.cairo_paint(cr)
        c.cairo_surface_flush(image)
        raw = ctypes.string_at(c.cairo_image_surface_get_data(image), c.cairo_image_surface_get_stride(image) * h)
        c.cairo_destroy(cr)
        c.cairo_surface_destroy(image)
        c.cairo_surface_destroy(window)
        return sum(1 for a in raw[3::4] if a)


class FakeWM:
    """A stand-in for X and its window manager: the app's window (10) and a terminal (9), in a frame with a 30 px title
    bar. A move counts from the frame's corner (EWMH's usual way), or from the window's (from_window: WSLg's)."""

    TITLE = "WTFTD — War Thunder Full Test Drive".encode()

    def __init__(self, listed: bool = True, from_window: bool = False):
        self.at, self.from_window, self.sent, self.kept = [100, 80, 1000, 700], from_window, [], []
        self.props = {(1, "_NET_CLIENT_LIST"): [9, 10] if listed else None, (9, "_NET_WM_NAME"): b"Terminal",
                      (10, "_NET_WM_NAME"): self.TITLE, (10, "_NET_FRAME_EXTENTS"): [0, 0, 30, 0], (10, "_NET_WM_STATE"): []}

    def prop(self, window, name):
        return self.props.get((window, name))

    @staticmethod
    def atom(name):
        return sum(name.encode()) * 7 + len(name)

    def XDefaultRootWindow(self, d):
        return 1

    def XDefaultScreen(self, d):
        return 0

    def XDisplayWidth(self, d, screen):
        return 1920

    def XDisplayHeight(self, d, screen):
        return 1080

    def XQueryTree(self, d, window, root, parent, kids, count):
        found = {1: [5], 5: [9, 10]}.get(window, [])
        held = (ctypes.c_ulong * max(1, len(found)))(*found)
        self.kept.append(held)
        kids._obj.contents = ctypes.c_ulong.from_buffer(held)
        count._obj.value = len(found)
        return 1

    def XGetWindowAttributes(self, d, window, attrs):
        attrs._obj.x, attrs._obj.y, attrs._obj.width, attrs._obj.height = 0, 0, *self.at[2:]
        return 1

    def XTranslateCoordinates(self, d, window, root, x, y, left, top, child):
        left._obj.value, top._obj.value = self.at[:2]
        return 1

    def XMoveResizeWindow(self, d, window, left, top, width, height):
        self.at = [left, top + (0 if self.from_window else 30), width, height]

    def XSendEvent(self, d, to, propagate, mask, event):
        message = event._obj.client
        self.sent.append((to, message.window, message.message_type, list(message.data)))

    def XFlush(self, d):
        pass

    def XFree(self, data):
        pass

    def XIconifyWindow(self, d, window, screen):
        self.sent.append(("iconify", window))


class AppWindowOnLinux(unittest.TestCase):
    """Linux: the app window found, kept in its place, minimized and closed through X and its window manager, as tray does
    on Windows; no notification area there."""

    def wm(self, **kind) -> FakeWM:
        wm = FakeWM(**kind)
        for p in (mock.patch.object(x11, "display", return_value=1), mock.patch.object(x11, "lib", return_value=wm),
                  mock.patch.object(xwindow, "_lib", return_value=wm), mock.patch.object(x11, "prop", wm.prop),
                  mock.patch.object(x11, "atom", wm.atom), mock.patch.object(xwindow, "SETTLE_S", 0),
                  mock.patch.dict(xwindow._normal, clear=True)):
            p.start()
            self.addCleanup(p.stop)
        return wm

    def test_found_by_its_title(self):
        self.wm()
        self.assertEqual(xwindow.find_window(), 10)
        self.wm(listed=False)  # a window manager that lists nothing: the whole tree
        self.assertEqual(xwindow.find_window(), 10)
        with mock.patch.object(x11, "display", return_value=None):
            self.assertIsNone(xwindow.find_window())

    def test_its_place_maximized_or_not(self):
        wm = self.wm()
        self.assertEqual(xwindow.place_of(10), {"x": 100, "y": 50, "w": 1000, "h": 700, "max": False})  # the frame's corner
        wm.props[(10, "_NET_WM_STATE")] = [wm.atom("_NET_WM_STATE_MAXIMIZED_VERT"), wm.atom("_NET_WM_STATE_MAXIMIZED_HORZ")]
        wm.at = [0, 30, 1920, 1050]
        self.assertEqual(xwindow.place_of(10), {"x": 100, "y": 50, "w": 1000, "h": 700, "max": True})  # where it goes back to

    def test_put_back_exactly_whichever_way_the_window_manager_counts(self):
        for from_window in (False, True):
            self.wm(from_window=from_window)
            place = {"x": 300, "y": 200, "w": 900, "h": 600, "max": False}
            xwindow.put(10, place)
            self.assertEqual(xwindow.place_of(10), place, from_window)
            xwindow.put(10, xwindow.place_of(10))
            self.assertEqual(xwindow.place_of(10), place, from_window)  # no creep from one start to the next

    def test_maximized_then(self):
        wm = self.wm()
        xwindow.put(10, {"x": 300, "y": 200, "w": 900, "h": 600, "max": True})
        maximize = [wm.atom("_NET_WM_STATE_MAXIMIZED_VERT"), wm.atom("_NET_WM_STATE_MAXIMIZED_HORZ")]
        self.assertEqual(wm.sent[-1], (1, 10, wm.atom("_NET_WM_STATE"), [xwindow.ADD, *maximize, xwindow.FROM_PAGER, 0]))

    def test_minimized_brought_forward_and_closed(self):
        wm = self.wm()
        self.assertTrue(xwindow.minimize())
        self.assertTrue(xwindow.show())
        self.assertTrue(xwindow.close())
        self.assertEqual(wm.sent, [("iconify", 10), (1, 10, wm.atom("_NET_ACTIVE_WINDOW"), [xwindow.FROM_PAGER, 0, 0, 0, 0]),
                                   (10, 10, wm.atom("WM_PROTOCOLS"), [wm.atom("WM_DELETE_WINDOW"), 0, 0, 0, 0])])  # to the window itself
        self.assertFalse(xwindow.Tray().click())  # no notification area

    def test_a_saved_place_still_on_the_screen(self):
        self.wm()
        place = {"x": 300, "y": 200, "w": 900, "h": 600, "max": False}
        self.assertTrue(xwindow.usable(place))
        for bad in ({**place, "x": 5000}, {**place, "w": 50}, {**place, "x": 1.5}, None):
            self.assertFalse(xwindow.usable(bad), bad)

    def test_which_controls_the_window(self):
        from wtftd import tray
        for platform, shown, control in (("win32", None, tray), ("linux", 1, xwindow), ("linux", None, None), ("darwin", 1, None)):
            with mock.patch.object(sys, "platform", platform), mock.patch.object(x11, "display", return_value=shown):
                self.assertIs(server.window_control(), control, (platform, shown))

    def test_the_browser_opens_where_it_was(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "window.json"
        path.write_text(json.dumps({"x": 300, "y": 200, "w": 900, "h": 600, "max": True}), encoding="utf-8")
        with mock.patch.object(sys, "platform", "linux"), mock.patch.object(app, "PLACE", path), \
                mock.patch.object(server, "window_control", return_value=mock.Mock(usable=lambda p: True)):
            self.assertEqual(app.window_args(), ["--window-position=300,200", "--window-size=900,600"])  # keep_place maximizes it


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
