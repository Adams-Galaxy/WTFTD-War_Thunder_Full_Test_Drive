"""What changed: the comparison of two databases, on made-up data, and what a build keeps of it."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from wtftd import armament, builder, patches, server, uninstall


_NO_DEV = []


def setUpModule():
    """Not the dev server's data this PC may have built (.cache/dev): each test that wants one makes its own."""
    tmp = tempfile.TemporaryDirectory()
    _NO_DEV[:] = [tmp, mock.patch.object(patches, "DEV_DATA", Path(tmp.name) / "no-dev")]
    _NO_DEV[1].start()


def tearDownModule():
    _NO_DEV[1].stop()
    _NO_DEV[0].cleanup()


def vehicle(vid="tank", **extra) -> dict:
    return {"id": vid, "c": "ground", "n": "usa", "r": 3, "br": [4.0, 4.3, 4.7], "s": {"spd": 50, "rel": 7.5, "armT": [100, 50, 30], "rp": 1000}, **extra}


def shell(pen=200, v=800.0) -> dict:
    return {"id": "", "b": ["m62"], "t": ["aphe"], "s": {"pc": [[10, pen], [1000, pen - 50]], "k": pen, "v": v, "m": 6.8, "e": 0.06}}


def db(version="2.59.0.92", schema=31, vehicles=None, details=None, items=None, scenarios=None) -> dict:
    return {"meta": {"version": version, "schema": schema, "built": 1750000000},
            "vehicles": [vehicle()] if vehicles is None else vehicles,
            "details": {"tank": {"am": [{"w": "76mm_gun", "opts": [shell()]}], "st": {}}} if details is None else details,
            "armament": {"items": [{"id": "aim_9", "c": "aam_ir", "g": "ir", "rng": 8000, "gl": 20}] if items is None else items},
            "scenarios": [{"id": "a", "map": "afghan"}] if scenarios is None else scenarios,
            "names": {"units": {"tank": "M4 Sherman", "gone_one": "Old tank"}, "arm": {"aim_9": "AIM-9"}, "maps": {"afghan": "Afghanistan"}}}


def write(folder: Path, d: dict) -> None:
    (folder / "lang").mkdir(parents=True, exist_ok=True)
    for name, key in (("meta", "meta"), ("vehicles", "vehicles"), ("details", "details"), ("armament", "armament"), ("scenarios", "scenarios")):
        (folder / f"{name}.json").write_text(json.dumps(d[key]), encoding="utf-8")
    (folder / "lang" / "en.json").write_text(json.dumps(d["names"]), encoding="utf-8")


def rows(old: dict, new: dict) -> list:
    return patches.compare(old, new)["rows"]


class Compare(unittest.TestCase):
    def test_same_database_moves_nothing(self):
        self.assertEqual(rows(db(), db("2.60.0.1")), [])

    def test_a_value_moved(self):
        new = db("2.60.0.1", vehicles=[vehicle(br=[4.0, 4.7, 4.7], s={"spd": 52, "rel": 7.5, "armT": [100, 60, 30], "rp": 1000})])
        self.assertEqual(rows(db(), new), [["tank", "brrb", 4.3, 4.7], ["tank", "spd", 50, 52], ["tank", "armT", [100, 50, 30], [100, 60, 30]]])

    def test_rounding_is_not_a_change(self):
        new = db("2.60.0.1", vehicles=[vehicle(br=[4.0000001, 4.3, 4.7], s={"spd": 50.4, "rel": 7.5400001, "armT": [100.2, 50, 30], "rp": 1000})])
        self.assertEqual(rows(db(), new), [])

    def test_added_and_removed_vehicles_keep_their_names(self):
        old = db(vehicles=[vehicle(), vehicle("gone_one", n="ussr", c="air")])
        new = db("2.60.0.1", vehicles=[vehicle(), vehicle("brand_new")])
        new["names"]["units"]["brand_new"] = "New tank"
        self.assertEqual(rows(old, new), [["brand_new", "new", None, "New tank", ["usa", "ground", None, [4.0, 4.3, 4.7]]],
                                          ["gone_one", "gone", "Old tank", None, ["ussr", "air"]]])

    def test_lists_say_what_came_and_went(self):
        old = db(vehicles=[vehicle(wp=["aim_9", "gbu_12"])])
        new = db("2.60.0.1", vehicles=[vehicle(wp=["aim_9", "gbu_16"], wg=["m61"])])
        self.assertEqual(rows(old, new), [["tank", "wg", [], ["m61"]], ["tank", "wp", ["gbu_12"], ["gbu_16"]]])

    def test_lists_compare_what_the_player_sees(self):
        old, new = db(vehicles=[vehicle(wp=["paveway_a", "m62_old"])]), db("2.60.0.1", vehicles=[vehicle(wp=["paveway_b"])])
        old["names"]["weapons"] = {"paveway_a": "Paveway II", "m62_old": "Old bomb"}
        new["names"]["weapons"] = {"paveway_b": "Paveway II"}
        self.assertEqual(rows(old, new), [["tank", "wp", ["Old bomb"], []]])  # another file, same name; and a name the new data doesn't have

    def test_a_weapon_the_game_renames_is_not_a_change(self):
        old, new = db(vehicles=[vehicle(wp=["fab_250"])]), db("2.60.0.1", vehicles=[vehicle(wp=["fab_250"])])
        old["names"]["weapons"], new["names"]["weapons"] = {"fab_250": "FAB-250"}, {"fab_250": "FAB-250 M-46"}
        self.assertEqual(rows(old, new), [])

    def test_one_shell_is_one_row_with_its_vehicles(self):
        gun = lambda s: {"am": [{"w": "76mm_gun", "opts": [s]}]}  # noqa: E731
        vs = [vehicle("a"), vehicle("b")]
        old = db(vehicles=vs, details={"a": gun(shell()), "b": gun(shell())})
        new = db("2.60.0.1", vehicles=vs, details={"a": gun(shell(210)), "b": gun(shell(210))})
        self.assertEqual(rows(old, new), [["76mm_gun||m62", "a.pen", 200, 210, ["a", "b"]]])

    def test_weapons_and_maps(self):
        new = db("2.60.0.1", items=[{"id": "aim_9", "c": "aam_ir", "g": "ir", "rng": 8500, "gl": 20, "ccm": 0.8}, {"id": "new_one", "c": "bomb", "g": ""}],
                 scenarios=[{"id": "a", "map": "afghan"}, {"id": "b", "map": "afghan"}, {"id": "c", "map": "new_map"}])
        self.assertEqual(rows(db(), new), [["new_one", "w.new", None, "new_one"], ["aim_9", "w.f", [], ["ccm"]], ["aim_9", "w.rng", 8000, 8500],
                                           ["new_map", "m.new", None, "new_map"], ["afghan", "m.n", 1, 2]])

    def test_every_value_of_a_weapon_file(self):
        old, new = db(), db("2.60.0.1")
        old["values"] = {"aim_9": {"dragCx": 0.018, "guidance.opticalSeeker.fov": 3.6, "force": 10800.0, "mass": 85.3, "fuseDelayDist": 0.4,
                                   "guidance.opticalSeeker.gateWidth": 0.2}}
        new["values"] = {"aim_9": {"dragCx": 0.021, "guidance.opticalSeeker.fov": 3.6000000001, "force": 11200.0, "mass": 86.0, "fuseDelayDist": 0.4,
                                   "force1": 2000.0}}
        self.assertEqual(rows(old, new), [["aim_9", "w.x", 0.018, 0.021, "dragCx"], ["aim_9", "w.x", 10800.0, 11200.0, "force"],
                                          ["aim_9", "w.x", None, 2000.0, "force1"], ["aim_9", "w.x", 0.2, None, "guidance.opticalSeeker.gateWidth"]])
        # mass is a column already; a float's last bits aren't a change; one that came or went is

    def test_no_weapon_values_kept_before_compares_none(self):
        new = db("2.60.0.1")
        new["values"] = {"aim_9": {"dragCx": 0.021}}
        self.assertEqual(rows(db(), new), [])  # the data replaced was built before WTFTD kept them

    def test_the_irccm_type(self):
        old = db(items=[{"id": "aim_9", "c": "aam_ir", "g": "ir", "rng": 8000, "gl": 20, "ccm": 0.8, "ccmt": "r"}])
        new = db("2.60.0.1", items=[{"id": "aim_9", "c": "aam_ir", "g": "ir", "rng": 8000, "gl": 20, "ccm": 1.0, "ccmt": "rg"}])
        self.assertIn(["aim_9", "w.ccmt", "r", "rg"], rows(old, new))

    def test_a_value_that_appears_between_equal_schemas_is_a_change(self):
        new = db("2.60.0.1", items=[{"id": "aim_9", "c": "aam_ir", "g": "ir", "rng": 8000, "gl": 20, "pf": 5.0}])
        self.assertEqual(rows(db(), new), [["aim_9", "w.pf", None, 5.0]])

    def test_schema_bump_adds_fields_without_changes(self):
        old = db(schema=30, vehicles=[{k: v for k, v in vehicle().items() if k != "br"}], details={"tank": {"am": [], "st": {}}})
        new = db("2.60.0.1", schema=31, vehicles=[vehicle(wa=["m62"], wg=["m61"])], details={"tank": {"am": [], "st": {"fuel": 300.0}}})
        entry = patches.compare(old, new)
        self.assertEqual(entry["rows"], [])
        self.assertEqual(entry["schema"], 1)  # the page says the app's reading changed too

    def test_a_real_change_still_shows_across_a_schema_bump(self):
        new = db("2.60.0.1", schema=32, vehicles=[vehicle(s={"spd": 60, "rel": 7.5, "armT": [100, 50, 30], "rp": 1000, "cal": 76.0})])
        self.assertEqual(rows(db(), new), [["tank", "spd", 50, 60]])

    def test_a_version_that_goes_down_is_marked(self):
        new = db("2.59.0.92", vehicles=[vehicle(s={"spd": 60, "rel": 7.5, "armT": [100, 50, 30], "rp": 1000})])
        self.assertEqual(patches.compare(db("2.60.0.21"), new)["back"], 1)
        self.assertNotIn("back", patches.compare(new | {"meta": {"version": "2.60.0.2"}}, db("2.60.0.10")))  # numbers, not text


class Keep(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.data = self.root / "data"
        p = mock.patch.object(patches, "FILE", self.root / "user" / "patches.json")
        p.start()
        self.addCleanup(p.stop)

    def build(self, old: dict, new: dict):
        write(self.data, old)
        before = patches.snapshot(self.data, new["meta"]["version"])
        write(self.data, new)
        return patches.record(before, self.data)

    def moved(self, version="2.60.0.21", **kw) -> dict:
        return db(version, vehicles=[vehicle(s={"spd": 60, "rel": 7.5, "armT": [100, 50, 30], "rp": 1000})], **kw)

    def test_a_patch_is_kept(self):
        self.assertIsNotNone(self.build(db(), self.moved()))
        kept = patches.index()["patches"]
        self.assertEqual([(p["from"], p["to"], p["counts"]) for p in kept], [("2.59.0.92", "2.60.0.21", {"perf": 1})])
        self.assertNotIn("rows", kept[0])
        self.assertEqual(patches.rows(kept[0]["id"]), [["tank", "spd", 50, 60]])
        self.assertIsNone(patches.rows("nope"))

    def test_same_version_gives_nothing(self):
        self.assertIsNone(self.build(db(), self.moved("2.59.0.92")))  # a rebuild, or a schema bump
        self.assertIsNone(self.build(db(schema=30), self.moved("2.59.0.92")))
        self.assertFalse(patches.FILE.exists())

    def test_source_switch_at_the_same_version_gives_nothing(self):
        old, new = db(), self.moved("2.59.0.92")
        old["meta"]["source"], new["meta"]["source"] = "datamine", "game"
        self.assertIsNone(self.build(old, new))
        self.assertFalse(patches.FILE.exists())

    def test_first_build_gives_nothing(self):
        self.assertIsNone(patches.snapshot(self.data, "2.59.0.92"))
        self.assertIsNone(patches.record(None, self.data))
        self.assertEqual(patches.index()["patches"], [])

    def test_a_patch_that_moved_nothing_takes_no_place(self):
        self.assertIsNone(self.build(db(), db("2.59.0.93")))
        self.assertFalse(patches.FILE.exists())

    def test_going_down_is_kept_and_marked(self):
        self.build(db("2.60.0.21"), self.moved("2.59.0.92"))
        self.assertEqual(patches.index()["patches"][0]["back"], 1)

    def test_the_same_versions_again_replace_their_entry(self):
        self.build(db(), self.moved())
        self.build(db("2.60.0.21"), self.moved("2.59.0.92"))
        self.build(db(), self.moved())
        self.assertEqual([p["id"] for p in patches.load()], ["2.59.0.92-2.60.0.21", "2.60.0.21-2.59.0.92"])

    def test_bounded_newest_first(self):
        for i in range(patches.KEEP + 5):
            self.build(db(f"2.{i}.0.0"), self.moved(f"2.{i + 1}.0.0"))
        kept = patches.load()
        self.assertEqual(len(kept), patches.KEEP)
        self.assertEqual(kept[0]["to"], f"2.{patches.KEEP + 5}.0.0")

    def test_damaged_file_starts_over(self):
        patches.FILE.parent.mkdir()
        patches.FILE.write_text("{ not json", encoding="utf-8")
        self.assertEqual(patches.load(), [])
        self.build(db(), self.moved())
        self.assertEqual(len(patches.load()), 1)

    def test_the_table_is_consistent(self):
        keys = [f[0] for f in patches.FIELDS]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertTrue(all(f[1] in patches.GROUPS and f[2] in ("", "v", "s", "w", "m", "x") for f in patches.FIELDS))
        labels = json.loads((Path(__file__).parent.parent / "web" / "locales" / "en.json").read_text(encoding="utf-8"))
        self.assertEqual([f[4] for f in patches.FIELDS if f[4] not in labels], [])
        self.assertEqual([g for g in patches.GROUPS if f"ch.group.{g}" not in labels], [])


class Build(unittest.TestCase):
    """builder._build around the steps that read the game: the comparison is its very last step."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.data, self.dm, self.file = root / "data", root / "dm", root / "user" / "patches.json"
        self.dm.mkdir()
        (self.dm / "version").write_text("2.60.0.21")
        write(self.data, db())

    def run_build(self, fail=None):
        moved = vehicle(s={"spd": 60, "rel": 7.5, "armT": [100, 50, 30], "rp": 1000})
        lang = mock.Mock()
        lang.write.side_effect = lambda: ["en"]
        steps = {"Lang": mock.Mock(return_value=lang), "apply_rarity": mock.Mock(), "build_vehicles": mock.Mock(return_value=([moved], {})),
                 "build_scenarios": mock.Mock(return_value=db()["scenarios"]), "build_trees": mock.Mock(return_value={}),
                 "build_levels": mock.Mock(return_value={}), "build_bullet_icons": mock.Mock(return_value={}),
                 "build_battle_words": mock.Mock(return_value={}), "build_bases": mock.Mock(return_value={}),
                 "DATA": self.data, "DM": self.dm}
        if fail:
            steps[fail] = mock.Mock(side_effect=RuntimeError("stopped"))
        with mock.patch.multiple(builder, **steps), mock.patch.object(patches, "FILE", self.file), mock.patch.object(armament, "build_armament"):
            return builder._build(None, "game")

    def test_a_finished_build_says_how_many_changes(self):
        meta = self.run_build()
        self.assertEqual(meta["version"], "2.60.0.21")
        self.assertEqual(meta["patch"], "2.59.0.92-2.60.0.21")
        self.assertGreaterEqual(meta["changes"], 1)
        self.assertTrue(self.file.exists())

    def test_a_failed_build_leaves_no_entry(self):
        with self.assertRaises(RuntimeError):
            self.run_build(fail="build_bases")  # vehicles.json is written by then, meta.json isn't
        self.assertFalse(self.file.exists())
        self.assertFalse(self.file.with_suffix(".tmp").exists())

    def test_a_comparison_that_fails_keeps_the_build(self):
        with mock.patch.object(patches, "compare", side_effect=KeyError("shape")):
            meta = self.run_build()
        self.assertEqual(meta["version"], "2.60.0.21")
        self.assertNotIn("patch", meta)


class Dev(unittest.TestCase):
    """The dev server's data (the datamine's newest version, built apart) beside the game's: one more entry, never kept."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.live, self.other = self.root / "data", self.root / "dev"
        write(self.live, db("2.59.0.98"))
        for name, value in (("FILE", self.root / "patches.json"), ("DATA", self.live), ("DEV_DATA", self.other)):
            p = mock.patch.object(patches, name, value)
            p.start()
            self.addCleanup(p.stop)
        patches._DEV.clear()

    def test_none_until_built(self):
        self.assertIsNone(patches.dev())
        write(self.other, db("2.59.0.98"))
        self.assertIsNone(patches.dev())  # the same version: nothing to set beside it

    def test_the_dev_server_beside_the_game(self):
        write(self.other, db("2.60.0.33", vehicles=[vehicle(br=[4.0, 4.7, 4.7])]))
        d = patches.dev()
        self.assertEqual((d["id"], d["dev"], d["from"], d["to"], d["rows"]), ("dev", 1, "2.59.0.98", "2.60.0.33", [["tank", "brrb", 4.3, 4.7]]))
        self.assertNotIn("back", d)
        self.assertIs(patches.dev(), d)  # compared once
        self.assertEqual(patches.index()["patches"][0]["id"], "dev")
        self.assertEqual(patches.rows("dev"), d["rows"])
        self.assertFalse(patches.FILE.exists())  # never in the game's history

    def test_a_datamine_behind_the_game(self):
        write(self.other, db("2.59.0.94"))
        self.assertTrue(patches.dev()["back"])


class BuildDev(unittest.TestCase):
    """builder.build_dev in its own process: the datamine into DEV/data, its progress in a file, the data of before kept on a failure."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dev = Path(tmp.name) / "dev"
        for target, name in ((builder, "DM"), (builder, "DATA"), (armament, "DATA")):  # build_dev sets them: its process is its own
            p = mock.patch.object(target, name, getattr(target, name))
            p.start()
            self.addCleanup(p.stop)

    def run_dev(self, build):
        with mock.patch.object(builder, "DEV", self.dev), mock.patch.object(builder, "fetch_datamine") as fetch, \
                mock.patch.object(builder, "_build", side_effect=build) as made:
            builder.build_dev(self.dev / "status.json")
        return fetch, made, json.loads((self.dev / "status.json").read_text(encoding="utf-8"))

    def test_built_apart_without_history(self):
        def build(progress, source, history):
            (builder.DATA / "meta.json").parent.mkdir(parents=True, exist_ok=True)
            (builder.DATA / "meta.json").write_text('{"version": "2.60.0.33"}')
            progress("Building")
            progress.set_frac(0.5)
        fetch, made, st = self.run_dev(build)
        self.assertEqual(made.call_args.args[1:], ("datamine",))
        self.assertEqual(made.call_args.kwargs, {"history": False})
        self.assertEqual(json.loads((self.dev / "data" / "meta.json").read_text())["version"], "2.60.0.33")
        self.assertFalse((self.dev / "data.tmp").exists())
        self.assertEqual((st["running"], st["error"], st["log"], st["progress"]), (False, None, ["Building"], 0.5))

    def test_a_failure_keeps_the_data_of_before(self):
        (self.dev / "data").mkdir(parents=True)
        (self.dev / "data" / "meta.json").write_text('{"version": "2.60.0.31"}')
        fetch, made, st = self.run_dev(RuntimeError("git failed"))
        self.assertEqual((st["running"], st["error"]), (False, "git failed"))
        self.assertEqual(json.loads((self.dev / "data" / "meta.json").read_text())["version"], "2.60.0.31")


class Server(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        p = mock.patch.object(patches, "FILE", Path(tmp.name) / "patches.json")
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(patches, "DEV_DATA", Path(tmp.name) / "no-dev")  # not the dev server's data of this PC
        p.start()
        self.addCleanup(p.stop)
        patches.FILE.write_text(json.dumps([{"id": "1.0-1.1", "from": "1.0", "to": "1.1", "at": 5, "rows": [["tank", "spd", 50, 60]]}]), encoding="utf-8")

    def test_routes(self):
        handler = mock.Mock()
        server.Handler.get_api(handler, "changes")
        sent = handler.send_json.call_args.args[0]
        self.assertEqual(sent["patches"][0]["counts"], {"perf": 1})
        self.assertEqual(sent["fields"]["spd"]["label"], "stat.spd")
        json.dumps(sent)
        server.Handler.get_api(handler, "changes/1.0-1.1")
        self.assertEqual(handler.send_json.call_args.args[0], [["tank", "spd", 50, 60]])
        server.Handler.get_api(handler, "changes/nope")
        self.assertEqual(handler.send_json.call_args.args[1], 404)

    def test_the_dev_server_routes(self):
        handler = mock.Mock()
        with mock.patch.object(server.STATE, "data_source", lambda: "datamine"), mock.patch.object(server, "start_dev_build") as start:
            server.Handler.post_api(handler, "dev-build", {})
        start.assert_not_called()  # the game data is the datamine's already
        self.assertEqual(handler.send_json.call_args.args[1], 400)
        with mock.patch.object(server.STATE, "data_source", lambda: "game"), mock.patch.object(server, "start_dev_build") as start:
            server.Handler.post_api(handler, "dev-build", {})
        start.assert_called_once()
        with mock.patch.object(server, "DEV_PROC", [mock.Mock(poll=lambda: None)]):
            server.Handler.post_api(handler, "dev-remove", {})
        self.assertEqual(handler.send_json.call_args.args[1], 400)  # not while it's being built

    def test_the_datamine_ahead_of_the_game(self):
        with mock.patch.object(server.vromfs, "version", lambda gd: "2.59.0.98"):
            self.assertEqual(server.data_ahead({"source": "datamine", "version": "2.60.0.33"}, Path(".")), {"data": "2.60.0.33", "game": "2.59.0.98"})
            self.assertIsNone(server.data_ahead({"source": "datamine", "version": "2.59.0.99"}, Path(".")))  # a live patch, not the dev server
            self.assertIsNone(server.data_ahead({"source": "game", "version": "2.60.0.33"}, Path(".")))
            self.assertIsNone(server.data_ahead({"source": "datamine", "version": "2.60.0.33"}, None))

    def test_the_update_says_how_many_changes(self):
        meta = {"version": "1.1", "vehicles": 1, "patch": "1.0-1.1", "changes": 7}
        with mock.patch.object(server.builder, "build", return_value=meta), mock.patch.object(server.STATE, "reload"), \
                mock.patch.object(server, "warm_weapon_icons"), mock.patch.object(server, "IMG_CACHE", Path(patches.FILE.parent)), \
                mock.patch.object(server.STATE, "update", {}):
            server.run_update()
            self.assertEqual((server.STATE.update["patch"], server.STATE.update["changes"], server.STATE.update["error"]), ("1.0-1.1", 7, None))


class Uninstall(unittest.TestCase):
    def test_the_history_goes_with_the_user_part_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            cache, data, user = home / ".cache", home / "data", home / "user"
            for d in (cache, data, user):
                d.mkdir()
            kept = user / "patches.json"
            kept.write_text("[]")
            with mock.patch.object(uninstall, "CACHE", cache), mock.patch.object(uninstall, "DATA", data), mock.patch.object(uninstall, "USER", user), \
                    mock.patch.object(uninstall, "HOME", home):
                uninstall.run(["cache", "data"], None)
                self.assertTrue(kept.exists())
                uninstall.run(["user"], None)
            self.assertFalse(kept.exists())


if __name__ == "__main__":
    unittest.main()
