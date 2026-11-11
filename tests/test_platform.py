"""Windows / macOS / Linux differences: where the game files are, which Oodle runtime file names count, the alarms."""
import importlib
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from wtftd import __main__ as app, alarms, game, maptex, paths, server


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
    """Windows only (winsound, user32): off on macOS and Linux, without a trace in the app."""

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
