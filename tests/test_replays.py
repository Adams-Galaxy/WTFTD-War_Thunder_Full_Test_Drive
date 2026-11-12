"""My battles: the player's own results from replay files. Synthetic files, plus the real ones when this PC has them."""
import json
import struct
import tempfile
import time
import unittest
from collections import deque
from pathlib import Path
from unittest import mock

from tests.test_alarms import setUpModule  # one reading flies (Watch.moving)
from tests.test_vromfs import blk_body, f32
from wtftd import alarms, battle, builder, game, paths, replays, server, vromfs

ME = "13672816"
PLANES = "gamedata/missions/cta/planes/historical/bfd/air_afghan_bfd_norespawn.blk"


def blk(root: dict) -> bytes:
    """A dict as the game writes a BLK: blocks breadth first, each one's params in that order."""
    names, params, blocks, data, queue = [], [], [], bytearray(), [("", root)]

    def name(s):
        if s not in names:
            names.append(s)
        return names.index(s)
    for i, (key, d) in enumerate(queue):  # the queue grows: children come after their parent
        kids = [(k, x) for k, v in d.items() for x in (v if isinstance(v, list) else [v]) if isinstance(x, dict)]
        first = len(queue)
        queue += kids
        count = 0
        for k, v in d.items():
            for x in v if isinstance(v, list) else [v]:
                if isinstance(x, dict):
                    continue
                count += 1
                if isinstance(x, str):
                    params.append((name(k), 1, len(data)))
                    data += x.encode() + b"\0"
                elif isinstance(x, bool):
                    params.append((name(k), 9, int(x)))
                elif isinstance(x, int):
                    params.append((name(k), 2, x & 0xFFFFFFFF))
                else:
                    params.append((name(k), 3, f32(x)))
        blocks.append([name(key) + 1 if i else 0, count, len(kids), first])
    return blk_body(names, params, [tuple(b) for b in blocks], bytes(data), own_names=names)


def player(uid, nick, **stats) -> dict:
    return {"name": nick, "clanTag": "=TAG=", "kills": 0, "deaths": 0, "assists": 0, "score": 0, "awardDamage": 0,
            "damageZone": 0, "groundKills": 0, "navalKills": 0, "aiKills": 0, "aiGroundKills": 0, "aiNavalKills": 0,
            "userId": uid, "team": 1, **stats}


def results(status="success", crafts=None, me=None) -> dict:
    players = [player(ME, "Myself", **(me or {})), player("555", "SomeoneElse", clanTag="=THEM=", kills=9, score=9999)]
    out = {"timePlayed": 404.5, "authorUserId": ME, "author": "=TAG= Myself", "player": players,
           "uiScriptsData": {"playersInfo": {f"__int_{ME}": {"name": "Myself", "crafts": crafts or {"0": "mirage_4000"}},
                                             "__int_555": {"name": "SomeoneElse", "crafts": {"0": "su_33"}}}}}
    return {"status": status, **out} if status else out


def wrpl(comments: dict | None, level="levels/air_afghan.bin", mission=PLANES, cls="base_dom", difficulty=0x75, start=1750000000,
         loc="missions/air_afghan_BfD_norespawn", recording=b"\xAA" * 64) -> bytes:
    head = bytearray(replays.HEADER + 128)
    head[:4] = replays.MAGIC
    for at, text in ((8, level), (136, mission), (780, loc), (968, cls)):
        head[at:at + len(text)] = text.encode()
    head[688] = difficulty
    struct.pack_into("<I", head, 908, start)
    if comments is not None:
        struct.pack_into("<I", head, 684, len(head) + len(recording))
    return bytes(head) + recording + (b"\x01" + blk(comments) if comments is not None else b"")


class Temp(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)

    def write(self, name, raw) -> Path:
        path = self.folder / name
        path.write_bytes(raw)
        return path

    def read(self, raw):
        return replays.read_battle(self.write("x.wrpl", raw))


class Reading(Temp):
    def test_a_battle(self):
        row = self.read(wrpl(results(me={"kills": 6, "groundKills": 1, "aiKills": 2, "aiGroundKills": 1, "deaths": 1,
                                         "assists": 3, "score": 3700, "damageZone": 1200}, crafts={"1": "su_30mkk", "0": "j_10c"})))
        self.assertEqual((row["level"], row["kind"], row["diff"], row["result"], row["offline"]), ("air_afghan", "air", "rb", "win", False))
        self.assertEqual((row["start"], row["played"]), (1750000000, 404))
        self.assertEqual(row["vehicles"], ["su_30mkk", "j_10c"])
        self.assertEqual((row["kills"], row["ai"], row["deaths"], row["assists"], row["score"], row["damage"]), (7, 3, 1, 3, 3700, 1200))

    def test_result(self):
        for status, result in (("success", "win"), ("fail", "loss"), ("", "left"), ("anything else", "left")):
            self.assertEqual(self.read(wrpl(results(status)))["result"], result)

    def test_nobody_elses_name_or_numbers(self):
        text = json.dumps(self.read(wrpl(results())))
        for other in ("SomeoneElse", "=THEM=", "su_33", "9999", ME):
            self.assertNotIn(other, text)
        self.assertEqual((json.loads(text)["me"], json.loads(text)["clan"]), ("Myself", "=TAG="))

    def test_no_squadron(self):
        comments = results()
        del comments["player"][0]["clanTag"]
        self.assertEqual(self.read(wrpl(comments))["clan"], "")

    def test_mode(self):
        cases = (("gamedata/missions/cta/tanks/alps/alps_dom.blk", 0x70, "ground", "ab"), (PLANES, 0x7A, "air", "sb"),
                 ("gamedata/missions/cta/ships/x/y.blk", 0x75, "ship", "rb"), ("gamedata/missions/cta/helicopters/y.blk", 0x75, "heli", "rb"),
                 ("gamedata/missions/cta/stalingrad_ffa.blk", 0x73, "", ""))
        for mission, difficulty, kind, diff in cases:
            row = self.read(wrpl(results(), mission=mission, difficulty=difficulty))
            self.assertEqual((row["kind"], row["diff"]), (kind, diff), mission)

    def test_a_test_drive(self):
        comments = {**results(""), "player": player(ME, "Myself"), "uiScriptsData": {"playersInfo": {}}}
        row = self.read(wrpl(comments, level="levels/firing_range.bin", cls="singleMission", loc="Test Drive: Rafale - Range",
                             mission="D:/Games/tanks/War Thunder/UserMissions/wtftd_rafale_c_f3.blk"))
        self.assertTrue(row["offline"])
        self.assertEqual((row["vehicles"], row["title"], row["kind"], row["result"]), (["rafale_c_f3"], "Test Drive: Rafale - Range", "", "left"))
        self.assertNotIn("challenge", row)

    def test_a_challenges_file_names_it_and_its_vehicle(self):
        comments = {**results(""), "player": player(ME, "Myself"), "uiScriptsData": {"playersInfo": {}}}
        row = self.read(wrpl(comments, level="levels/avg_training_ground.bin", cls="singleMission",
                             mission="D:/Games/War Thunder/UserMissions/wtftd_ch-range-hard-ussr_t_72a.blk"))
        self.assertEqual((row["vehicles"], row["challenge"]), (["ussr_t_72a"], ("range", "hard")))

    def test_offline_by_each_sign(self):
        for extra in ({"cls": "singleMission"}, {"mission": "D:/WT/UserMissions/my_own.blk"}, {"level": "levels/firing_range.bin"}):
            row = self.read(wrpl(results(), **extra))
            self.assertTrue(row["offline"], extra)
        self.assertEqual(self.read(wrpl(results(), cls="singleMission", mission="D:/WT/UserMissions/my_own.blk"))["title"], "missions/air_afghan_BfD_norespawn")
        self.assertEqual(self.read(wrpl(results()))["title"], "")  # a battle's name is its map

    def test_no_vehicle_known(self):
        self.assertEqual(self.read(wrpl({**results(), "uiScriptsData": {}}))["vehicles"], [])

    def test_what_can_not_be_read(self):
        good = wrpl(results())
        stranger = {**results(), "authorUserId": "1"}
        for raw in (b"", b"\xe5\xac", b"not a replay" * 200, b"\0" + good[1:], good[:len(good) - 40], good[:replays.HEADER - 1],
                    wrpl(None), wrpl(stranger), wrpl({"timePlayed": 1.0, "authorUserId": ME}), wrpl({"player": 3, "authorUserId": ME, "timePlayed": 1.0}),
                    good[:684] + struct.pack("<I", len(good) + 500) + good[688:], good[:684] + struct.pack("<I", 12) + good[688:]):
            self.assertIsNone(self.read(raw))


class Summary(Temp):
    def row(self, status="success", **extra):
        return self.read(wrpl(results(status, **extra)))

    def test_real_battles_only(self):
        rows = [self.row(me={"kills": 3, "deaths": 1}), self.row("fail", me={"kills": 1, "deaths": 1}), self.row("", me={"deaths": 1}),
                self.row(me={"kills": 50}) | {"offline": True}]
        self.assertEqual(replays.summary(rows), {"pilot": "Myself", "battles": 3, "kills": 4, "deaths": 3, "kd": 1.33, "winrate": 50})

    def test_nothing_known(self):
        self.assertEqual(replays.summary([]), {})
        self.assertNotIn("winrate", replays.summary([self.row("")]))  # left every battle: no rate to give
        self.assertEqual(replays.summary([self.row(me={"kills": 4})])["kd"], 4)  # no death yet


WORDS = {"crashed": ["hascrashed."], "lost": ["hasbeenwrecked", "shotdownbyairdefense."], "killed": ["destroyed", "shot down"],
         "killedBy": ["has been destroyed by", "destroyed by", "shot down by"]}


class Live(unittest.TestCase):
    def tally(self, *lines, name="Myself"):
        out = battle.Tally()
        out.add([], name, WORDS)  # the first look: the past
        out.add([{"id": i + 1, "time": 100 + i * 20, "text": x} for i, x in enumerate(lines)], name, WORDS)
        return out.kills, out.deaths

    def test_kills(self):
        self.assertEqual(self.tally("=TAG= Myself (F-16AM) shot down =X= Foe (MiG-29)", "=TAG= Myself (T-72A) destroyed Foe@psn (M1 Abrams)",
                                    "Foe (Su-33) shot down by Myself (F-15E)", "Foe (T-80) destroyed by =TAG= Myself (Rafale)"), (4, 0))

    def test_deaths(self):
        self.assertEqual(self.tally("=X= Foe (MiG-29) shot down =TAG= Myself (F-16AM)", "=TAG= Myself (F-16AM) shot down by Foe (MiG-29)",
                                    "=TAG= Myself (T-72A) has been destroyed by Foe (M1 Abrams)", "=TAG= Myself (F-16AM) has crashed.",
                                    "=TAG= Myself (T-72A) has been wrecked", "MiG-29 shot down Myself", "Myself (F-16AM) shot down by air defense."), (0, 7))

    def test_nobody_elses_line_counts(self):
        self.assertEqual(self.tally("=X= Foe (MiG-29) shot down =Y= Other (F-16AM)", "=X= Foe (MiG-29) has crashed.", "Foe (F-16) shot down Myselfie (Su-33)",
                                    "NotMyself (F-16) shot down Foe (Su-33)", "=TAG= Myself (F-16AM) set afire Foe (MiG-29)"), (0, 0))

    def test_an_ai_vehicle_is_no_kill(self):
        self.assertEqual(self.tally("=TAG= Myself (F-16AM) shot down IL-28", "=TAG= Myself (T-72A) destroyed Truck"), (0, 0))  # as in the replays

    def test_a_death_told_twice_is_one(self):
        out = battle.Tally()
        out.add([], "Myself", WORDS)
        out.add([{"id": 1, "time": 100, "text": "Foe (MiG-29) shot down Myself (F-16AM)"},
                 {"id": 2, "time": 104, "text": "Myself (F-16AM) has crashed."}, {"id": 3, "time": 180, "text": "Myself (F-16AM) has crashed."}], "Myself", WORDS)
        self.assertEqual(out.deaths, 2)

    def test_the_first_look_is_the_past(self):
        out = battle.Tally()
        out.add([{"id": 9, "time": 1, "text": "Myself (F-16AM) shot down Foe (MiG-29)"}], "Myself", WORDS)
        self.assertEqual((out.kills, out.after), (0, 9))

    def test_no_name_no_count(self):
        out = battle.Tally()
        out.add([], None, WORDS)
        out.add([{"id": 1, "time": 1, "text": "Myself (F-16AM) shot down Foe (MiG-29)"}], None, WORDS)
        self.assertEqual((out.kills, out.after), (0, 1))


class Words(unittest.TestCase):
    def test_one_word_for_both_reads_as_a_kill(self):
        rows = {"NET_UNIT_KILLED_FM": {"en": "shot down"}, "NET_UNIT_KILLED_GM": {"sr": "uni\\tstio"},
                "NET_UNIT_KILLED_BY_PLAYER": {"sr": "uni\\tstio"}, "NET_PLAYER_KILLED_BY_PLAYER": {"en": "shot down by"}}
        with mock.patch.object(builder, "read_lang_csv", return_value=rows):
            words = builder.build_battle_words()
        self.assertEqual((words["killed"], words["killedBy"]), (["shot down", "unistio"], ["shot down by"]))
        self.assertEqual(battle.duel("A (x) unistio B (y)", words), ("A (x)", "B (y)"))
        self.assertEqual(battle.duel("A (x) shot down by B (y)", words), ("B (y)", "A (x)"))


class Overlay(unittest.TestCase):
    """The numbers reach an overlay line, in the air and in a tank, and a new battle starts them over."""
    FLIGHT = json.dumps({"valid": True, "IAS, km/h": 500, "Mfuel, kg": 900, "Mfuel0, kg": 1000, "RPM 1": 9000, "throttle 1, %": 90}).encode()
    MAP = json.dumps({"valid": True}).encode()

    def setUp(self):
        patcher = mock.patch.object(alarms, "beep")  # an unknown aircraft beeps: not on the PC running the tests
        patcher.start()
        self.addCleanup(patcher.stop)
        self.in_battle, self.log, self.asked = True, [], []
        self.watch = alarms.Watch(self.get, dict, save=lambda: None, stats=self.stats, log_words=lambda: WORDS)
        line = {**alarms.clean(None, self.watch.words)["lines"][0], "text": "{kd} {winrate} {live_kills}/{live_deaths}", "when": "always", "alarm": ""}
        self.watch.base = self.watch.cfg = {**self.watch.base, "lines": [line]}
        self.watch.enabled = True

    def stats(self):
        self.asked.append(1)
        return {"pilot": "Myself", "kd": 1.75, "winrate": 89, "battles": 78}

    def get(self, path):
        if path == "/map_info.json":
            return self.MAP if self.in_battle else None
        if path.startswith("/hudmsg"):
            after = int(path.rsplit("=", 1)[1])
            return json.dumps({"damage": [x for x in self.log if x["id"] > after], "events": []}).encode()
        return self.FLIGHT if path == "/state" and self.in_battle else None

    def ticks(self, n=alarms.LOG_EVERY):
        for _ in range(n):
            self.watch.tick()

    def shown(self):
        return self.watch.display[-1][0]

    def test_past_and_live(self):
        self.ticks()
        self.assertEqual(self.shown(), "1.75 89 0/0")
        self.log.append({"id": 1, "time": 50, "msg": "=TAG= Myself (F-16AM) shot down =X= Foe (MiG-29)"})
        self.log.append({"id": 2, "time": 60, "msg": "=X= Foe (Su-33) shot down =TAG= Myself (F-16AM)"})
        self.ticks()
        self.ticks(1)
        self.assertEqual(self.shown(), "1.75 89 1/1")

    def test_a_new_battle_starts_over(self):
        self.ticks()
        self.log.append({"id": 1, "time": 50, "msg": "Myself (F-16AM) shot down Foe (MiG-29)"})
        self.ticks()
        self.assertEqual(self.watch.tally.kills, 1)
        self.in_battle = False
        self.ticks()
        self.assertEqual(self.watch.tally.kills, 0)
        self.in_battle = True
        self.log.append({"id": 2, "time": 5, "msg": "Myself (F-16AM) shot down Foe (MiG-29)"})  # before the first look: the past
        self.ticks()
        self.assertEqual(self.watch.tally.kills, 0)
        self.assertEqual(len(self.asked), 2)  # My battles read once per battle, not at every look

    def test_the_name_reaches_the_crash_detection(self):
        self.watch.crash_words = lambda: ["hascrashed."]
        self.ticks()
        self.log.append({"id": 1, "time": 50, "msg": "=X= Foe (MiG-29) has crashed."})
        self.ticks()
        self.assertEqual(self.watch._silent, 0)
        self.log.append({"id": 2, "time": 60, "msg": "=TAG= Myself (F-16AM) has crashed."})
        self.ticks()
        self.assertGreater(self.watch._silent, 0)

    def test_the_killers_go_on_when_the_battle_ends(self):
        self.ticks()
        self.log.append({"id": 1, "time": 50, "msg": "Foe (MiG-29) shot down Myself (F-16AM)"})
        self.ticks()
        self.assertEqual(len(self.watch.killed_by), 0)
        self.in_battle = False
        asked = len(self.asked)
        self.ticks()
        self.assertEqual([name for name, _ in self.watch.killed_by], ["Foe"])
        self.assertEqual(len(self.asked), asked + 1)  # server.battles files them

    def test_without_a_name_the_live_numbers_say_so(self):
        self.watch.stats = dict
        self.ticks(alarms.LOG_EVERY + 1)
        self.assertEqual(self.shown(), f"{alarms.NO_VALUE} {alarms.NO_VALUE} {alarms.NO_VALUE}/{alarms.NO_VALUE}")

    def test_off_nothing_is_asked(self):
        self.watch.enabled = False
        self.ticks()
        self.assertEqual(self.asked, [])

    def test_the_preview_has_them(self):
        self.assertEqual(alarms.fill("{kd} {winrate} {live_kd}", alarms.SAMPLE_STATS), "1.75 89 2")

    def test_every_value_has_a_label(self):
        names = [n for n in alarms.SAMPLE_STATS]
        en = json.loads((paths.WEB / "locales" / "en.json").read_text(encoding="utf-8"))
        self.assertTrue(all(f"ov.v.{n}" in en for n in names))
        script = (paths.WEB / "overlay.js").read_text(encoding="utf-8")
        self.assertTrue(all(f"'{n}'" in script for n in names))


class Teamkills(Temp):
    NOW = 1750000000

    def setUp(self):
        super().setUp()
        comments = results()  # SomeoneElse is on my team
        comments["player"].append(player("777", "Enemy", team=2, clanTag="=FOE="))
        self.write("a.wrpl", wrpl(comments, start=self.NOW))
        self.rows = replays.listing(replays.refresh(self.folder, {}))["rows"]

    def file(self, *killers):
        return replays.teamkills(self.folder, self.rows, [(name, self.NOW + 100) for name in killers])

    def test_a_teammate_is_kept(self):
        filed, waiting = self.file("=THEM= SomeoneElse")
        self.assertEqual(filed, [{"name": "SomeoneElse", "clan": "=THEM=", "at": self.NOW + 100, "level": "air_afghan", "file": "a.wrpl"}])
        self.assertEqual(waiting, [])

    def test_an_enemy_leaves_no_trace(self):
        self.assertEqual(self.file("=FOE= Enemy"), ([], []))

    def test_an_ai_vehicle_or_a_stranger_leaves_no_trace(self):
        self.assertEqual(self.file("MiG-29", "Nobody"), ([], []))

    def test_never_the_player(self):
        self.assertEqual(self.file("=TAG= Myself"), ([], []))  # a missile of one's own

    def test_a_replay_not_there_yet_waits(self):
        later = (("=THEM= SomeoneElse", time.time()),)
        self.assertEqual(replays.teamkills(self.folder, self.rows, later), ([], list(later)))

    def test_without_a_replay_the_name_goes(self):
        self.assertEqual(replays.teamkills(self.folder, self.rows, [("=THEM= SomeoneElse", time.time() - replays.WAIT_S - 1)]), ([], []))

    def test_a_late_look_is_still_this_battle(self):
        at = self.NOW + 404 + replays.SAME_BATTLE_S
        self.assertEqual(len(replays.teamkills(self.folder, self.rows, [("SomeoneElse", at)])[0]), 1)

    def test_offline_missions_keep_nobody(self):
        rows = [{**self.rows[0], "offline": True}]
        self.assertEqual(replays.teamkills(self.folder, rows, [("SomeoneElse", self.NOW + 100)]), ([], []))

    def test_a_replay_gone_or_damaged_names_nobody(self):
        (self.folder / "a.wrpl").write_bytes(b"damaged")
        self.assertEqual(self.file("SomeoneElse"), ([], []))

    def test_the_log_gives_the_killers(self):
        out = battle.Tally()
        out.add([], "Myself", WORDS)
        out.add([{"id": 1, "time": 10, "text": "=X= Foe (MiG-29) shot down =TAG= Myself (F-16AM)"},
                 {"id": 2, "time": 90, "text": "=TAG= Myself (F-16AM) shot down by Other (Su-33)"},
                 {"id": 3, "time": 180, "text": "=TAG= Myself (F-16AM) has crashed."},
                 {"id": 4, "time": 200, "text": "=TAG= Myself (F-16AM) shot down Foe (MiG-29)"}], "Myself", WORDS)
        self.assertEqual([name for name, _ in out.killers], ["=X= Foe", "Other"])


class Index(Temp):
    def test_unchanged_files_are_not_read_again(self):
        self.write("a.wrpl", wrpl(results(), start=100))
        self.write("b.wrpl", wrpl(results("fail"), start=200))
        self.write("c.wrpl", b"being written")
        self.write("notes.txt", b"not a replay")
        first = replays.refresh(self.folder, {})
        self.assertEqual(sorted(first["files"]), ["a.wrpl", "b.wrpl", "c.wrpl"])
        with mock.patch.object(replays, "read_battle", side_effect=AssertionError("read again")):
            self.assertEqual(replays.refresh(self.folder, first), first)
        self.write("b.wrpl", wrpl(results("success"), start=200) + b"\0")  # a replay finishing: read once more
        (self.folder / "a.wrpl").unlink()
        second = replays.refresh(self.folder, first)
        self.assertEqual(sorted(second["files"]), ["b.wrpl", "c.wrpl"])
        self.assertEqual(second["files"]["b.wrpl"]["row"]["result"], "win")

    def test_listing(self):
        self.write("old.wrpl", wrpl(results(), start=100))
        self.write("new.wrpl", wrpl(results(), start=200))
        self.write("broken.wrpl", b"x")
        out = replays.listing(replays.refresh(self.folder, {}))
        self.assertEqual([r["file"] for r in out["rows"]], ["new.wrpl", "old.wrpl"])
        self.assertEqual(out["skipped"], 1)

    def test_an_old_or_odd_index_is_rebuilt(self):
        self.write("a.wrpl", wrpl(results()))
        for index in ({"v": 0, "files": {"a.wrpl": {"size": 0, "mtime": 0, "row": None}}}, [], {"v": replays.VERSION, "files": 3}, None):
            self.assertIn("level", replays.refresh(self.folder, index)["files"]["a.wrpl"]["row"])

    def test_no_folder(self):
        self.assertEqual(replays.refresh(self.folder / "gone", {})["files"], {})
        self.assertEqual(replays.refresh(None, {})["files"], {})


class Route(Temp):
    def setUp(self):
        super().setUp()
        (self.folder / "Replays").mkdir()
        (self.folder / "Replays" / "a.wrpl").write_bytes(wrpl(results()))
        self.index = self.folder / "cache" / "battles.json"
        self.kept = self.folder / "user" / "teamkills.json"
        for target, name, value in ((server, "BATTLES", self.index), (server, "TEAMKILLS", self.kept), (server.STATE, "game_dir", lambda: self.folder),
                                    (server.WATCH, "killed_by", deque())):
            p = mock.patch.object(target, name, value)
            p.start()
            self.addCleanup(p.stop)

    def test_the_index_is_kept_and_used(self):
        self.assertEqual([r["file"] for r in server.battles()["rows"]], ["a.wrpl"])
        self.assertTrue(self.index.exists())
        with mock.patch.object(replays, "read_battle", side_effect=AssertionError("read again")):
            self.assertEqual(server.battles()["skipped"], 0)

    def test_no_game(self):
        with mock.patch.object(server.STATE, "game_dir", lambda: None):
            self.assertEqual(server.battles(), {"game": False, "rows": [], "skipped": 0, "teamkills": []})

    def test_a_teammate_is_kept_once_and_the_rest_waits(self):
        server.WATCH.killed_by.extend([("=THEM= SomeoneElse", 1750000100), ("=THEM= SomeoneElse", time.time())])
        out = server.battles()["teamkills"]
        self.assertEqual([x["name"] for x in out], ["SomeoneElse"])
        self.assertEqual(len(server.WATCH.killed_by), 1)  # the second one's replay isn't there yet
        self.assertEqual(len(server.battles()["teamkills"]), 1)
        self.assertEqual(len(json.loads(self.kept.read_text(encoding="utf-8"))), 1)

    def test_an_enemy_writes_nothing(self):
        server.WATCH.killed_by.append(("Stranger", 1750000100))
        self.assertEqual(server.battles()["teamkills"], [])
        self.assertFalse(self.kept.exists())
        self.assertEqual(len(server.WATCH.killed_by), 0)

    def test_the_index_goes_with_the_cache(self):
        self.assertEqual(self.index.name, "battles.json")
        mock.patch.stopall()
        self.assertEqual(server.BATTLES.parent, paths.CACHE)


GAME = game.detect_game_dir()


@unittest.skipUnless(GAME and any((GAME / "Replays").glob("*.wrpl")), "needs the game's replays")
class RealReplays(unittest.TestCase):
    def test_every_file_with_results_is_read(self):
        index = replays.refresh(GAME / "Replays", {})
        rows = replays.listing(index)["rows"]
        self.assertTrue(rows)
        for name, item in index["files"].items():
            with open(GAME / "Replays" / name, "rb") as f:
                head = f.read(replays.HEADER)
            if struct.unpack_from("<I", head, 684)[0]:
                self.assertIsNotNone(item["row"], name)
        for row in rows:
            self.assertRegex(row["level"], r"^[a-z0-9_]+$")
            self.assertGreater(row["played"], 0)
            if not row["offline"]:
                self.assertTrue(row["vehicles"], row["file"])
                self.assertTrue(row["kind"] and row["diff"], row["file"])

    def test_no_other_player_in_the_rows(self):
        index = replays.refresh(GAME / "Replays", {})
        rows = {r["file"]: json.dumps(r) for r in replays.listing(index)["rows"]}
        checked = 0
        for name, text in rows.items():
            with open(GAME / "Replays" / name, "rb") as f:
                f.seek(struct.unpack_from("<I", f.read(replays.HEADER), 684)[0] + 1)
                comments = vromfs.parse_blk(f.read(), [])
            players = comments["player"] if isinstance(comments["player"], list) else [comments["player"]]
            for p in players:
                if str(p["userId"]) != str(comments["authorUserId"]) and len(p["name"]) > 3:
                    self.assertNotIn(p["name"], text)
                    checked += 1
        if any(not r["offline"] for r in replays.listing(index)["rows"]):
            self.assertGreater(checked, 0)


if __name__ == "__main__":
    unittest.main()
