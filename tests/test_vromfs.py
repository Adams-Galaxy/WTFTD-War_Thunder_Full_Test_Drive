"""The game's own files as a data source: small handmade containers and BLK files (they run anywhere), then the real
game against the datamine, on a PC that has both."""
import hashlib
import importlib
import json
import math
import runpy
import struct
import sys
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest import mock

from wtftd import builder, game, server, vromfs

zstd = vromfs.zstd


def uleb(n: int) -> bytes:
    out = bytearray()
    while True:
        out.append((n & 0x7F) | (0x80 if n > 0x7F else 0))
        n >>= 7
        if not n:
            return bytes(out)


def names_table(names: list[str]) -> bytes:
    text = b"".join(n.encode() + b"\0" for n in names)
    return uleb(len(names)) + uleb(len(text)) + text


def blk_body(names, params, blocks, data=b"", own_names=None):
    """params: (name id, type, raw u32); blocks: (name id + 1, params, children, first child)."""
    out = names_table(own_names) if own_names else uleb(0)
    out += uleb(len(blocks)) + uleb(len(params)) + uleb(len(data)) + data
    out += b"".join(struct.pack("<II", i | t << 24, v) for i, t, v in params)
    for name, count, children, first in blocks:
        out += uleb(name) + uleb(count) + uleb(children) + (uleb(first) if children else b"")
    return out


def f32(x: float) -> int:
    return struct.unpack("<I", struct.pack("<f", x))[0]


NAMES = ["s", "i", "f", "p2", "p3", "p4", "ip2", "ip3", "ip4", "b", "c", "m", "l", "again", "sub", "nm"]


def sample_body():
    data = b"text\0" + struct.pack("<2f", 1.5, 2.5) + struct.pack("<3f", 1, 2, 3) + struct.pack("<4f", 1, 2, 3, 4)
    data += struct.pack("<2i", 1, -2) + struct.pack("<3i", 1, 2, 3) + struct.pack("<4i", 1, 2, 3, 4)
    data += struct.pack("<12f", *range(12)) + struct.pack("<q", 1 << 40)
    at = 5
    params = [(0, 1, 0), (15, 1, 0x80000000 | 3), (1, 2, 0xFFFFFFFE), (2, 3, f32(0.1))]
    for name, kind, size in ((3, 4, 8), (4, 5, 12), (5, 6, 16), (6, 7, 8), (7, 8, 12), (8, 13, 16)):
        params.append((name, kind, at))
        at += size
    params += [(9, 9, 1), (10, 10, 0x04030201), (11, 11, at), (12, 12, at + 48)]
    params += [(13, 2, 1), (13, 2, 2), (3, 4, 5), (14, 2, 9), (14, 2, 7)]  # p2 again: a list of vectors
    return blk_body(NAMES, params, [(0, 18, 2, 1), (15, 0, 0, 0), (15, 1, 0, 0)], data)  # "sub": a param and two blocks


class Blk(unittest.TestCase):
    def test_every_type_like_the_datamine(self):
        d = vromfs.parse_blk(sample_body(), NAMES)
        self.assertEqual(d["s"], "text")
        self.assertEqual(d["i"], -2)
        self.assertEqual(d["f"], 0.1)
        self.assertEqual(d["p2"], [[1.5, 2.5], [1.5, 2.5]])  # repeated key: a list of its values
        self.assertEqual(d["p3"], [1.0, 2.0, 3.0])
        self.assertEqual(d["p4"], [1.0, 2.0, 3.0, 4.0])
        self.assertEqual(d["ip2"], [1, -2])
        self.assertEqual(d["ip3"], [1, 2, 3])
        self.assertEqual(d["ip4"], [1, 2, 3, 4])
        self.assertIs(d["b"], True)
        self.assertEqual(d["c"], [1, 2, 3, 4])
        self.assertEqual(d["m"], [[0.0, 1.0, 2.0], [3.0, 4.0, 5.0], [6.0, 7.0, 8.0], [9.0, 10.0, 11.0]])
        self.assertEqual(d["l"], 1 << 40)
        self.assertEqual(d["again"], [1, 2])
        self.assertEqual(d["nm"], "p2")  # a string kept in the name table
        self.assertEqual(d["sub"], [9, {}, {"sub": 7}])  # params first, then the blocks of that name

    def test_fat_file_has_its_own_names(self):
        body = blk_body(None, [(1, 2, 5)], [(0, 1, 1, 1), (1, 0, 0, 0)], own_names=["block", "value"])
        self.assertEqual(vromfs.parse_blk(body, ["other"]), {"value": 5, "block": {}})

    def test_unknown_value_type_says_so(self):
        with self.assertRaises(vromfs.VromfsError):
            vromfs.parse_blk(blk_body(["a"], [(0, 14, 0)], [(0, 1, 0, 0)]), ["a"])

    def test_floats_are_the_shortest_decimal_of_their_32_bits(self):
        for raw, shown in ((0.10000000149011612, 0.1), (23.14069175720215, 23.140692), (-0.0009978469554334879, -0.000997847),
                           (1.401298464324817e-45, 1e-45), (6.0, 6.0), (-0.0, -0.0)):
            self.assertEqual(vromfs._float(raw), shown)


def pack_container(files: dict, version=(2, 59, 0, 92)) -> bytes:
    """{name as bytes: content} -> a .vromfs.bin as the game writes it."""
    names = list(files)
    head = 32
    names_at = head + 8 * len(names)
    offsets, text = [], b""
    for n in names:
        offsets.append(names_at + len(text))
        text += n + b"\0"
    table_at = names_at + len(text)
    data_at = table_at + 16 * len(names)
    table, blob = b"", b""
    for n in names:
        table += struct.pack("<II8x", data_at + len(blob), len(files[n]))
        blob += files[n]
    payload = struct.pack("<II8xII8x", head, len(names), table_at, len(names))
    payload += struct.pack(f"<{len(names)}Q", *offsets) + text + table + blob
    body = bytearray(zstd.compress(payload))
    vromfs._xor(body, 0, vromfs.XOR_HEAD)
    vromfs._xor(body, (len(body) & 0x03FFFFFC) - 16, vromfs.XOR_TAIL)
    out = b"VRFx\0\0PC" + struct.pack("<II", len(payload), vromfs.PACKED << 26 | len(body))
    out += struct.pack("<HH", 8, 0) + bytes(reversed(version)) + bytes(body)
    return out + hashlib.md5(payload).digest() + bytes(256)


def make_game(folder: Path, version=(2, 59, 0, 92)):
    """The four containers of a tiny game: dictionary + shared names in aces, a plain slim file in char, CSV in lang."""
    samples = [f"sample {i} ".encode() * 40 for i in range(300)]
    trained = zstd.train_dict(samples, 2048)
    digest = bytes(range(32))
    nm = bytes(8) + digest + zstd.compress(names_table(NAMES))
    body = blk_body(NAMES, [(1, 2, 7)], [(0, 1, 0, 0)])
    aces = {b"\xff?nm": nm, digest.hex().encode() + b".dict": trained.dict_content,
            b"gamedata/weapons/a.blk": bytes([vromfs.BLK_SLIM_DICT]) + zstd.compress(body, zstd_dict=trained),
            b"gamedata/flightmodels/b.blk": bytes([vromfs.BLK_SLIM]) + body,
            b"gamedata/other/skipped.blk": bytes([vromfs.BLK_SLIM]) + body,
            b"config/settings.ps5.patch": b"raw"}
    plain = {b"\xff?nm": bytes(40) + zstd.compress(names_table(NAMES)),
             b"config/wpcost.blk": bytes([vromfs.BLK_SLIM_ZSTD]) + zstd.compress(body)}
    files = {"aces": aces, "char": plain, "lang": {b"lang/units.csv": b'"<ID>";"<English>"\r\n"a";"one\ntwo"\r\n'},
             "mis": {b"gamedata/missions/m.blk": bytes([vromfs.BLK_FAT]) + blk_body(None, [(0, 3, f32(0.5))], [(0, 1, 0, 0)], own_names=["t"])}}
    for name, content in files.items():
        (folder / f"{name}.vromfs.bin").write_bytes(pack_container(content, version))


@unittest.skipUnless(vromfs.available(), "needs Python 3.14 (compression.zstd)")
class Containers(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.game = self.root / "game"
        self.game.mkdir()
        make_game(self.game)

    def test_unpack_writes_the_datamine_layout(self):
        out = self.root / "out"
        progress = []
        vromfs.unpack(self.game, out, ["aces.vromfs.bin_u/gamedata/weapons", "aces.vromfs.bin_u/gamedata/flightmodels", "aces.vromfs.bin_u/config",
                                       "char.vromfs.bin_u/config", "lang.vromfs.bin_u/lang", "mis.vromfs.bin_u/gamedata/missions"], progress.append)
        read = lambda p: json.loads((out / p).read_text(encoding="utf-8"))
        self.assertEqual(read("aces.vromfs.bin_u/gamedata/weapons/a.blkx"), {"i": 7})  # dictionary
        self.assertEqual(read("aces.vromfs.bin_u/gamedata/flightmodels/b.blkx"), {"i": 7})
        self.assertEqual(read("char.vromfs.bin_u/config/wpcost.blkx"), {"i": 7})  # zstd without dictionary
        self.assertEqual(read("mis.vromfs.bin_u/gamedata/missions/m.blkx"), {"t": 0.5})  # own names
        self.assertEqual((out / "aces.vromfs.bin_u/config/settings.ps5.patch").read_bytes(), b"raw")
        self.assertEqual((out / "lang.vromfs.bin_u/lang/units.csv").read_bytes(), b'"<ID>";"<English>"\r\n"a";"one\r\ntwo"\r\n')
        self.assertFalse((out / "aces.vromfs.bin_u/gamedata/other").exists())  # only the folders asked for
        self.assertEqual((out / "version").read_text(), "2.59.0.92")
        self.assertTrue(progress)

    def test_a_name_leaving_its_folder_is_not_written(self):
        for name in (b"lang/../../../outside.csv", b"lang\\..\\..\\..\\outside.csv"):
            (self.game / "lang.vromfs.bin").write_bytes(pack_container({name: b"x", b"lang/units.csv": b"y"}))
            vromfs.unpack(self.game, self.root / "out", ["lang.vromfs.bin_u/lang"])
            self.assertTrue((self.root / "out/lang.vromfs.bin_u/lang/units.csv").exists())
            self.assertFalse((self.root / "outside.csv").exists())

    def test_version_is_the_newest_container(self):
        (self.game / "char.vromfs.bin").write_bytes(pack_container({b"a": b"x"}, (2, 59, 0, 100)))
        self.assertEqual(vromfs.version(self.game), "2.59.0.100")

    def broken(self, change):
        path = self.game / "aces.vromfs.bin"
        path.write_bytes(change(path.read_bytes()))
        with self.assertRaises(vromfs.VromfsError):
            vromfs.read_container(path)

    def test_damaged_content(self):
        self.broken(lambda raw: raw[:100] + bytes([raw[100] ^ 0xFF]) + raw[101:])

    def test_half_written(self):
        self.broken(lambda raw: raw[:len(raw) // 2])

    def test_not_a_container(self):
        self.broken(lambda raw: b"\0" * 64)

    def test_unknown_packing(self):
        self.broken(lambda raw: raw[:15] + bytes([0x40]) + raw[16:])

    def test_missing_or_locked(self):
        (self.game / "aces.vromfs.bin").unlink()
        with self.assertRaises(vromfs.VromfsError):
            vromfs.read_container(self.game / "aces.vromfs.bin")
        with self.assertRaises(vromfs.VromfsError):
            vromfs.version(self.game)

    def test_a_failed_unpack_leaves_the_last_one(self):
        keep, cache = builder.GAMEFILES, self.root / "cache"
        with mock.patch.object(builder, "GAMEFILES", cache / "gamefiles"):
            builder.GAMEFILES.mkdir(parents=True)
            (builder.GAMEFILES / "version").write_text("old")
            (self.game / "mis.vromfs.bin").write_bytes(b"VRFx")
            with self.assertRaises(vromfs.VromfsError):
                builder.fetch_gamefiles(self.game)
            self.assertEqual((builder.GAMEFILES / "version").read_text(), "old")
            self.assertFalse(builder.GAMEFILES.with_name("gamefiles.tmp").exists())
        self.assertEqual(builder.GAMEFILES, keep)


class Source(unittest.TestCase):
    """The setting: absent = datamine, game mode makes no network call for the data."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.settings = {}
        for target, name, value in ((server.STATE, "settings", lambda: self.settings), (server.STATE, "game_dir", lambda: self.root)):
            p = mock.patch.object(target, name, value)
            p.start()
            self.addCleanup(p.stop)

    def check(self, meta, version, start=True):
        started = []
        with mock.patch.object(server.vromfs, "version", lambda gd: version), \
                mock.patch.object(server, "read_json", lambda p, d=None: meta), \
                mock.patch.object(server.urllib.request, "urlopen", side_effect=AssertionError("network")), \
                mock.patch.object(server.threading, "Thread", lambda **kw: started.append(kw) or mock.Mock()), \
                mock.patch.dict(server.STATE.update, {"running": False}):
            st = dict(server.check_for_update(start=start))
        return st, started

    def test_default_is_the_datamine(self):
        self.assertEqual(server.STATE.data_source(), "datamine")

    def test_game_patch_is_seen_without_network(self):
        self.settings["dataSource"] = "game"
        meta = {"version": "2.59.0.92", "schema": builder.SCHEMA, "source": "game"}
        st, started = self.check(meta, "2.59.0.92")
        self.assertFalse(st["available"])
        st, started = self.check(meta, "2.59.0.93")
        self.assertTrue(st["available"])
        self.assertEqual(len(started), 1)

    def test_automatic_updates_off_still_offer_a_game_patch(self):
        self.settings.update(dataSource="game", autoUpdate=False)
        meta = {"version": "2.59.0.92", "schema": builder.SCHEMA, "source": "game"}
        with mock.patch.object(server, "check_for_update") as check:
            server.auto_check()
        check.assert_called_once_with(start=False)
        st, started = self.check(meta, "2.59.0.98", start=False)
        self.assertEqual((st["available"], st["remote"], started), (True, "2.59.0.98", []))  # seen, not built: the page offers it
        self.settings["dataSource"] = "datamine"
        with mock.patch.object(server, "check_for_update") as check:
            server.auto_check()
        check.assert_not_called()  # the datamine's version is on the network: not without automatic updates

    def test_command_line_builds_through_the_real_module(self):
        """Weapons read builder.DM: from `python -m` a copy of the module would stay on the datamine, and with no data yet the Weapons page came out empty."""
        with mock.patch.object(builder, "build") as run, mock.patch.object(game, "detect_game_dir", lambda: self.root), \
                mock.patch.object(sys, "argv", ["wtftd.builder", "--game"]), warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)  # runpy says the module is already imported: that's the point
            runpy.run_module("wtftd.builder", run_name="__main__")
        run.assert_called_once_with(pull=True, source="game", game_dir=self.root)

    def test_other_source_is_rebuilt(self):
        self.settings["dataSource"] = "game"
        st, _ = self.check({"version": "2.59.0.92", "schema": builder.SCHEMA}, "2.59.0.92")  # data from before this setting
        self.assertTrue(st["available"])

    def test_game_updating_is_not_a_new_version(self):
        self.settings["dataSource"] = "game"
        with mock.patch.object(server.vromfs, "version", side_effect=vromfs.VromfsError("locked")):
            self.assertIsNone(server.remote_version())

    def test_no_game_folder(self):
        self.settings["dataSource"] = "game"
        with mock.patch.object(server.STATE, "game_dir", lambda: None):
            self.assertIsNone(server.remote_version())
            self.assertEqual(server.api_status()["gameSourceIssue"], "python" if not vromfs.available() else "game")

    def test_failed_build_keeps_the_files_of_the_data_in_use(self):
        before = builder.DM
        with mock.patch.object(builder, "fetch_gamefiles", side_effect=vromfs.VromfsError("damaged")):
            with self.assertRaises(vromfs.VromfsError):
                builder.build(source="game", game_dir=self.root)
        self.assertEqual(builder.DM, before)

    def test_switching_keeps_the_datamine_copy(self):
        datamine = self.root / "datamine"
        datamine.mkdir()
        with mock.patch.object(builder, "DATAMINE", datamine), mock.patch.object(builder, "DM", datamine), \
                mock.patch.object(builder, "fetch_gamefiles"), mock.patch.object(builder, "_build", return_value={"source": "game"}):
            builder.build(source="game", game_dir=self.root)
            self.assertEqual(builder.DM, builder.GAMEFILES)
        self.assertTrue(datamine.is_dir())

    def test_datamine_copy_goes_only_when_unused(self):
        handler = mock.Mock()
        with mock.patch.object(builder, "remove_datamine") as remove, mock.patch.dict(server.STATE.update, {"running": False}):
            with mock.patch.object(builder, "DM", builder.DATAMINE):
                server.Handler.post_api(handler, "remove-datamine", {})
            remove.assert_not_called()
            self.assertEqual(handler.send_json.call_args.args[1], 400)
            with mock.patch.object(builder, "DM", builder.GAMEFILES):
                server.Handler.post_api(handler, "remove-datamine", {})
            remove.assert_called_once()

    def test_setting_is_checked(self):
        handler = mock.Mock()
        with mock.patch.object(server.STATE, "save_settings") as save:
            server.Handler.post_api(handler, "settings", {"dataSource": "elsewhere"})
            self.assertEqual(handler.send_json.call_args.args[1], 400)
            with mock.patch.object(vromfs, "zstd", None):
                server.Handler.post_api(handler, "settings", {"dataSource": "game"})
            self.assertEqual(handler.send_json.call_args.args[1], 400)
        save.assert_not_called()

    def test_app_reads_the_files_its_data_came_from(self):
        data = self.root / "data"
        data.mkdir()
        (data / "meta.json").write_text('{"source": "game"}')
        self.addCleanup(importlib.reload, builder)
        with mock.patch("wtftd.paths.DATA", data):
            importlib.reload(builder)
            self.assertEqual(builder.DM, builder.GAMEFILES)

    def test_python_without_zstd(self):
        """Below 3.14: the app starts, the datamine works, the option is off with its reason."""
        with mock.patch.object(vromfs, "zstd", None):
            self.assertFalse(vromfs.available())
            self.assertEqual(server.api_status()["gameSourceIssue"], "python")
            with self.assertRaisesRegex(RuntimeError, "Python 3.14"):
                builder.fetch_gamefiles(self.root)
            self.assertEqual(server.STATE.data_source(), "datamine")


REF = builder.DATAMINE
GD = game.detect_game_dir()
# old vehicles and files: they rarely change, so the sample stays good when the game and the datamine aren't at the same version
SAMPLE = {"aces": ["gamedata/flightmodels/bf-109e-3.blk", "gamedata/units/tankmodels/ussr_t_34_1941_cast_turret.blk",
                   "gamedata/weapons/rocketguns/us_aim9b_sidewinder.blk", "config/gui.blk"],
          "char": ["config/unittags.blk"], "mis": ["gamedata/missions/cta/tanks/stalingrad_factory/stalingrad_factory_bttl.blk"]}


def paths(d, at=""):
    """Every value of a file as 'path:type', repeated blocks together."""
    if isinstance(d, dict):
        return {p for k, v in d.items() for p in paths(v, f"{at}/{k}")}
    if isinstance(d, list):
        return {p for v in d for p in paths(v, at)} | {f"{at}:list"}
    return {f"{at}:{type(d).__name__}"}


@unittest.skipUnless(vromfs.available() and GD and (REF / "version").exists(), "needs the game, the datamine and Python 3.14")
class AgainstDatamine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.out = Path(cls.tmp.name)
        vromfs.unpack(GD, cls.out, ["lang.vromfs.bin_u/lang"])
        cls.same_version = (REF / "version").read_text().strip() == (cls.out / "version").read_text()

    def close(self, a, b, at=""):
        if isinstance(a, dict) and isinstance(b, dict):
            self.assertEqual(sorted(a), sorted(b), at)
            for k in a:
                self.close(a[k], b[k], f"{at}/{k}")
        elif isinstance(a, list) and isinstance(b, list):
            self.assertEqual(len(a), len(b), at)
            for i, (x, y) in enumerate(zip(a, b)):
                self.close(x, y, f"{at}[{i}]")
        elif isinstance(a, float) and isinstance(b, float):
            self.assertTrue(math.isclose(a, b, rel_tol=1e-5, abs_tol=1e-6), f"{at}: {a} {b}")
        else:
            self.assertEqual(a, b, at)
            self.assertEqual(type(a), type(b), at)

    def test_sample_of_each_container(self):
        for name, files in SAMPLE.items():
            c = vromfs.Container(GD / f"{name}.vromfs.bin")
            for rel in files:
                with self.subTest(rel):
                    a = c.blk(rel)
                    b = json.loads((REF / f"{name}.vromfs.bin_u" / (rel + "x")).read_text(encoding="utf-8"))
                    if self.same_version:
                        self.close(a, b)
                    else:  # another build of the game: values move, the shape of the file must not
                        pa, pb = paths(a), paths(b)
                        self.assertGreater(len(pa & pb) / len(pa | pb), 0.9)

    def test_language_table(self):
        with mock.patch.object(builder, "DM", self.out):
            table = builder.read_lang_csv("units_weaponry.csv")
        with mock.patch.object(builder, "DM", REF):
            ref = builder.read_lang_csv("units_weaponry.csv")
        shared = table.keys() & ref.keys()
        self.assertGreaterEqual(len(shared) / len(ref), 1 if self.same_version else 0.9)
        self.assertGreaterEqual(sum(table[k] == ref[k] for k in shared) / len(shared), 1 if self.same_version else 0.9)


if __name__ == "__main__":
    unittest.main()
