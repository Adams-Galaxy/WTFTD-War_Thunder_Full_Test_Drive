"""Test bench: synthetic recordings of each test, good runs and every kind of invalid one, what's kept, and a whole flight."""
import csv
import json
import math
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from wtftd import alarms, bench, builder, flightlog, mission, server, uninstall

HZ = 5


def reading(t, **values):
    """A reading in level flight, with the wobble of a hand on the stick: nothing a real log holds perfectly still."""
    wobble = math.sin(t * 2.3)
    r = {"t": round(t, 1), "ias": 500.0, "tas": 600.0, "mach": .55, "alt": 5000.0, "vy": .3 * wobble, "throttle": 100.0, "bank": 1.0 * wobble, "g": 1.0 + .01 * wobble,
         "gear": 0.0, "flaps": 0.0, "airbrake": 0.0, "heading": 90.0, "aoa": 2.0, "fuel": 500.0 - t / 10}
    r.update(values)
    r["alt"] += 2 * wobble
    return r


def stretch(start, seconds, rate=HZ, **change):
    """Readings from this time on; a value of change that's a function takes the seconds since the start of the stretch."""
    return [reading(start + i / rate, **{k: v(i / rate) if callable(v) else v for k, v in change.items()}) for i in range(int(seconds * rate))]


def reasons(result):
    return {x["why"] for x in result["rejected"]}


class TopSpeed(unittest.TestCase):
    def test_a_settled_run(self):
        rows = stretch(0, 30, ias=lambda s: 480 + 20 * (1 - math.exp(-s / 3)), tas=lambda s: 590 + 20 * (1 - math.exp(-s / 3))) + stretch(30, 40, tas=610.0, ias=500.0)
        result = bench.analyse("top", rows)
        self.assertEqual(len(result["points"]), 1)
        p = result["points"][0]
        self.assertEqual(p["tas"], 610.0)
        self.assertEqual(p["ias"], 500.0)
        self.assertEqual(round(p["alt"], -1), 5000.0)
        self.assertEqual(p["throttle"], 100.0)
        self.assertAlmostEqual(p["s"], 20, delta=.5)

    def test_still_accelerating(self):
        result = bench.analyse("top", stretch(0, 40, tas=lambda s: 500 + 2 * s, ias=lambda s: 400 + 2 * s))
        self.assertEqual(result["points"], [])
        self.assertEqual(reasons(result), {"moving"})
        self.assertGreater(result["rejected"][0]["v"], 5)  # the energy still gained, m/s

    def test_a_small_trade_of_height_for_speed_is_not_a_change_of_energy(self):
        # 15 m up and down: 3 km/h of speed the other way, enough to look unsteady on the speed alone
        h = lambda s: 5000 + 15 * math.sin(s / 5)
        v = lambda s: 600 - 3 * math.sin(s / 5) * 400 / 600
        self.assertEqual(len(bench.analyse("top", stretch(0, 40, alt=h, tas=v))["points"]), 1)

    def test_each_altitude_its_own_point(self):
        rows = stretch(0, 30, tas=610.0) + stretch(30, 10, throttle=60.0, alt=lambda s: 5000 - 200 * s) + stretch(40, 30, alt=3000.0, tas=580.0)
        result = bench.analyse("top", rows)
        self.assertEqual(sorted(p["tas"] for p in result["points"]), [580.0, 610.0])
        self.assertEqual(reasons(result), {"full"})

    def test_war_emergency_power_is_a_condition_of_its_own(self):
        rows = stretch(0, 30, tas=600.0) + stretch(30, 30, tas=620.0, throttle=110.0)
        self.assertEqual(sorted(p["tas"] for p in bench.analyse("top", rows)["points"]), [600.0, 620.0])

    def test_each_kind_of_invalid_flight(self):
        for change, why in (({"throttle": 80.0}, "full"), ({"flaps": 20.0}, "flaps"), ({"gear": 100.0}, "gear"), ({"airbrake": 100.0}, "airbrake"),
                            ({"bank": 25.0}, "wings"), ({"vy": -8.0}, "level")):
            result = bench.analyse("top", stretch(0, 40, **change))
            self.assertEqual((result["points"], reasons(result)), ([], {why}), why)

    def test_too_short(self):
        result = bench.analyse("top", stretch(0, 10))
        self.assertEqual((result["points"], reasons(result)), ([], {"short"}))

    def test_a_blip_does_not_break_a_stretch(self):
        rows = stretch(0, 40)
        rows[100]["bank"] = 40.0
        self.assertEqual(len(bench.analyse("top", rows)["points"]), 1)

    def test_the_pause_menu_is_not_flight_time(self):
        rows = stretch(0, 15) + [dict(reading(15), t=15 + i / HZ, alt=5000.0) for i in range(100)] + stretch(35, 15)
        result = bench.analyse("top", rows)
        self.assertEqual(result["points"], [])
        self.assertIn("paused", reasons(result))

    def test_a_settled_flight_is_not_a_pause(self):
        # the game gives whole metres and km/h: a trimmed aircraft repeats them, its marker moves on
        rows = [dict(reading(0), t=i / HZ, vy=0.0, bank=0.0, g=1.0, alt=5000.0, east=i * 30.0, north=0.0) for i in range(200)]
        self.assertEqual(len(bench.analyse("top", rows)["points"]), 1)

    def test_the_player_own_log_rate_is_enough(self):
        self.assertEqual(len(bench.analyse("top", stretch(0, 40, rate=1))["points"]), 1)

    def test_a_reading_gap_ends_a_stretch(self):
        result = bench.analyse("top", stretch(0, 15) + stretch(25, 15))
        self.assertEqual((result["points"], reasons(result)), ([], {"short"}))


class Climb(unittest.TestCase):
    climbing = {"vy": lambda s: 20 - s / 25, "alt": lambda s: 300 + 20 * s - s * s / 50, "ias": 300.0, "bank": 2.0}

    def test_a_climb(self):
        result = bench.analyse("climb", stretch(0, 180, **self.climbing))
        p = result["points"][0]
        self.assertEqual(p["from"], round(300 + 20 * 0 + 2 * math.sin(0)))
        self.assertGreater(p["to"], 3000)
        self.assertEqual(p["ias"], 300.0)
        self.assertGreater(len(p["curve"]), 4)
        alts = [c[0] for c in p["curve"]]
        self.assertEqual(alts, sorted(alts))
        self.assertGreater(p["curve"][0][1], p["curve"][-1][1])  # thinner air, slower climb
        self.assertEqual(p["curve"][0][2], 0.0)
        self.assertGreater(p["curve"][-1][2], 100)  # time to get there

    def test_the_longest_climb_stays(self):
        rows = stretch(0, 60, **self.climbing) + stretch(60, 5, throttle=50.0, ias=300.0) + stretch(65, 120, **self.climbing)
        self.assertEqual(bench.analyse("climb", rows)["points"][0]["n"], 2)
        self.assertAlmostEqual(bench.analyse("climb", rows)["points"][0]["s"], 120, delta=1)

    def test_a_speed_not_held_is_a_zoom(self):
        result = bench.analyse("climb", stretch(0, 60, vy=30.0, alt=lambda s: 1000 + 30 * s, ias=lambda s: 600 - 6 * s))
        self.assertEqual(result["points"], [])
        self.assertIn("steady", reasons(result))

    def test_too_little_height(self):
        result = bench.analyse("climb", stretch(0, 20, vy=3.0, alt=lambda s: 1000 + 3 * s))
        self.assertEqual((result["points"], reasons(result)), ([], {"low"}))

    def test_throttle_and_flaps(self):
        for change, why in (({"throttle": 70.0}, "full"), ({"flaps": 10.0}, "flaps")):
            self.assertEqual(reasons(bench.analyse("climb", stretch(0, 60, vy=15.0, alt=lambda s: 1000 + 15 * s, **change))), {why})


class Turn(unittest.TestCase):
    def laps(self, rate=18.0, seconds=45, **change):
        return stretch(0, seconds, heading=lambda s: (90 + rate * s) % 360, bank=70.0, g=3.0, ias=450.0, tas=500.0, alt=2000.0, **change)

    def test_a_sustained_turn(self):
        p = bench.analyse("turn", self.laps())["points"][0]
        self.assertAlmostEqual(p["s"], 20.0, delta=.1)
        self.assertEqual(p["g"], 3.0)
        self.assertEqual(p["ias"], 450.0)
        self.assertEqual(p["radius"], round(500 / 3.6 * p["s"] / (2 * math.pi)))

    def test_either_way_round(self):
        self.assertAlmostEqual(bench.analyse("turn", self.laps(rate=-18.0))["points"][0]["s"], 20.0, delta=.1)

    def test_one_point_per_speed(self):
        fast = stretch(50, 45, heading=lambda s: (20 * s) % 360, bank=70.0, ias=550.0, tas=620.0, alt=2000.0)
        result = bench.analyse("turn", self.laps() + stretch(45, 5, bank=0.0) + fast)
        self.assertEqual([p["ias"] for p in result["points"]], [450.0, 550.0])

    def test_the_map_heading_stands_in_for_the_compass(self):
        rows = self.laps()
        for r in rows:
            r["hdg"] = r.pop("heading")
        self.assertAlmostEqual(bench.analyse("turn", rows)["points"][0]["s"], 20.0, delta=.1)

    def test_no_heading_at_all(self):
        rows = self.laps()
        for r in rows:
            del r["heading"]
        self.assertEqual(reasons(bench.analyse("turn", rows)), {"heading"})

    def test_speed_bled_is_not_sustained(self):
        result = bench.analyse("turn", stretch(0, 45, heading=lambda s: (18 * s) % 360, bank=70.0, ias=lambda s: 500 - s, alt=2000.0))
        self.assertEqual(result["points"], [])
        self.assertEqual(reasons(result), {"speed"})

    def test_height_traded_is_not_sustained(self):
        result = bench.analyse("turn", stretch(0, 45, heading=lambda s: (18 * s) % 360, bank=70.0, ias=450.0, alt=lambda s: 2000 - 3.5 * s, vy=-3.5))
        self.assertEqual(result["points"], [])
        self.assertEqual(reasons(result), {"altitude"})

    def test_not_a_full_circle(self):
        result = bench.analyse("turn", self.laps(seconds=12))
        self.assertEqual(reasons(result), {"lap"})
        self.assertAlmostEqual(result["rejected"][0]["v"], 216, delta=4)

    def test_wings_level_is_no_turn(self):
        self.assertEqual(reasons(bench.analyse("turn", stretch(0, 30))), {"banked"})

    def test_a_throttle_cut_breaks_the_lap(self):
        result = bench.analyse("turn", stretch(0, 15, heading=lambda s: (18 * s) % 360, bank=70.0, ias=450.0) + stretch(15, 15, heading=lambda s: (270 + 18 * s) % 360, bank=70.0, ias=450.0, throttle=40.0))
        self.assertEqual(result["points"], [])
        self.assertEqual(reasons(result), {"full", "lap"})


class Acceleration(unittest.TestCase):
    plan = {"from": 400, "to": 600}

    def test_between_two_speeds(self):
        p = bench.analyse("accel", stretch(0, 60, ias=lambda s: 350 + 5 * s), self.plan)["points"][0]
        self.assertAlmostEqual(p["s"], 40.0, delta=.1)
        self.assertEqual((p["from"], p["to"]), (400, 600))

    def test_throttle_opened_past_the_first_speed(self):
        rows = stretch(0, 20, ias=lambda s: 350 + 5 * s, throttle=70.0) + stretch(20, 40, ias=lambda s: 450 + 5 * s)
        result = bench.analyse("accel", rows, self.plan)
        self.assertEqual(result["points"], [])
        self.assertIn("late", reasons(result))

    def test_never_gets_there(self):
        result = bench.analyse("accel", stretch(0, 20, ias=lambda s: 350 + 5 * s), self.plan)
        self.assertEqual((result["points"], reasons(result)), ([], {"slow"}))
        self.assertEqual(result["rejected"][0]["v"], 449)

    def test_a_dive_is_no_acceleration(self):
        result = bench.analyse("accel", stretch(0, 60, ias=lambda s: 350 + 5 * s, vy=-3.0, alt=lambda s: 5000 - 3 * s), self.plan)
        self.assertEqual((result["points"], reasons(result)), ([], {"altitude"}))

    def test_a_steep_dive_fails_at_once(self):
        result = bench.analyse("accel", stretch(0, 60, ias=lambda s: 350 + 5 * s, vy=-20.0, alt=lambda s: 5000 - 20 * s), self.plan)
        self.assertEqual((result["points"], reasons(result)), ([], {"level"}))


class HardTurn(unittest.TestCase):
    plan = {"speed": 700}

    def pull(self, rate=20.0, **change):
        values = {"heading": lambda s: (rate * s) % 360, "g": 6.0, "bank": 80.0, "ias": lambda s: 700 - 8 * s, "alt": 2000.0, **change}
        return stretch(0, 3, ias=700.0, alt=2000.0, heading=0.0) + [dict(r, t=r["t"] + 3) for r in stretch(0, 12, **values)]

    def test_half_a_circle(self):
        p = bench.analyse("bleed", self.pull(), self.plan)["points"][0]
        self.assertEqual(p["v0"], 700.0)
        self.assertAlmostEqual(p["lost"], 72, delta=2)
        self.assertAlmostEqual(p["s"], 9.0, delta=.3)
        self.assertEqual(p["g"], 6.0)

    def test_begun_at_another_speed(self):
        result = bench.analyse("bleed", self.pull(ias=lambda s: 600 - 8 * s), self.plan)
        self.assertEqual((result["points"], reasons(result)), ([], {"entry"}))

    def test_a_turn_that_climbs_away_its_speed(self):
        result = bench.analyse("bleed", self.pull(alt=lambda s: 2000 + 40 * s, vy=40.0), self.plan)
        self.assertEqual((result["points"], reasons(result)), ([], {"altitude"}))

    def test_not_half_a_circle(self):
        result = bench.analyse("bleed", self.pull(rate=10.0), self.plan)
        self.assertEqual((result["points"], reasons(result)), ([], {"lap"}))

    def test_not_pulling(self):
        self.assertEqual(reasons(bench.analyse("bleed", stretch(0, 20), self.plan)), {"soft"})

    def test_throttle_off(self):
        self.assertEqual(bench.analyse("bleed", [dict(r, throttle=0.0) for r in self.pull()], self.plan)["points"], [])


class Stall(unittest.TestCase):
    def slow(self, rate=2.0, g=1.0, level=20.0):
        down = {"throttle": 0.0, "ias": lambda s: 300 - rate * s, "g": g}
        rows = stretch(0, level, **down)
        end = 300 - rate * level
        return rows + [dict(r, t=r["t"] + level) for r in stretch(0, 8, throttle=0.0, ias=lambda s: end - s, vy=-10.0, alt=lambda s: 5000 - 10 * s)]

    def test_where_level_flight_gives_way(self):
        p = bench.analyse("stall", self.slow())["points"][0]
        self.assertAlmostEqual(p["ias"], 260.4, delta=1)

    def test_pulled_is_not_a_stall_speed(self):
        self.assertEqual(reasons(bench.analyse("stall", self.slow(g=1.8))), {"pulled"})

    def test_a_speed_chopped_is_not_a_slow_down(self):
        self.assertEqual(reasons(bench.analyse("stall", self.slow(rate=12.0, level=15.0))), {"rate"})

    def test_no_speed_lost_before_it(self):
        self.assertEqual(reasons(bench.analyse("stall", self.slow(rate=0.0))), {"rate"})

    def test_sinking_from_a_dive(self):
        rows = stretch(0, 20, throttle=0.0, vy=-9.0, alt=lambda s: 5000 - 9 * s, ias=lambda s: 300 - 2 * s)
        self.assertEqual(reasons(bench.analyse("stall", rows)), {"notLevel"})

    def test_engine_left_on(self):
        self.assertEqual(reasons(bench.analyse("stall", stretch(0, 30))), {"idle"})

    def test_never_gave_way(self):
        self.assertEqual(reasons(bench.analyse("stall", stretch(0, 30, throttle=0.0, ias=lambda s: 300 - s))), {"noStall"})


class Live(unittest.TestCase):
    def test_every_check_on_the_latest_reading(self):
        state = bench.live("top", stretch(0, 12))
        self.assertTrue(all(c["ok"] for c in state["checks"]))
        self.assertAlmostEqual(state["held"], 11.8, delta=.3)
        self.assertEqual(state["need"], 20.0)
        self.assertEqual(state["now"]["throttle"], 100.0)

    def test_what_is_wrong_right_now(self):
        state = bench.live("top", stretch(0, 12) + stretch(12, 3, throttle=70.0))
        self.assertEqual([c["key"] for c in state["checks"] if not c["ok"]], ["full"])
        self.assertEqual(state["held"], 0.0)

    def test_paused(self):
        rows = stretch(0, 5) + [dict(reading(5), t=5 + i / HZ, alt=5000.0) for i in range(20)]
        self.assertTrue(bench.live("top", rows)["paused"])

    def test_no_reading_yet(self):
        self.assertEqual(bench.live("top", []), {})


def plan(**change):
    return {"vehicle": "bf-109f-4", "test": "top", "preset": "Bf-109F-4_default", "fuel": 50, "allMods": True, "difficulty": "realistic", "altitude": 5000,
            "speed": 600, "from": 0, "to": 0, **change}


class Files(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        p = mock.patch.object(bench, "FILE", Path(tmp.name) / "user" / "bench.json")
        p.start()
        self.addCleanup(p.stop)

    def run_(self, **change):
        return {**plan(), "id": "r1", "time": 1800000000, "game": "2.59.0.92", "log": "bf-109f-4-2026_11_01_12_00_00.csv", "points": [{"alt": 5000.0, "tas": 610.0}], **change}

    def test_no_file_no_run(self):
        self.assertEqual(bench.load(), {"runs": []})

    def test_a_run_comes_back_with_its_conditions(self):
        bench.add(self.run_())
        run = bench.load()["runs"][0]
        self.assertEqual((run["vehicle"], run["preset"], run["fuel"], run["allMods"], run["game"], run["custom"], run["cheats"]),
                         ("bf-109f-4", "Bf-109F-4_default", 50, True, "2.59.0.92", False, False))
        self.assertEqual(run["points"], [{"alt": 5000.0, "tas": 610.0}])

    def test_what_the_file_cannot_hold(self):
        bad = [{"id": "x"}, self.run_(vehicle="../x"), self.run_(test="nope"), self.run_(id="a/b"), "junk"]
        self.assertEqual(bench.clean({"runs": bad})["runs"], [])
        run = bench.clean({"runs": [self.run_(log="../../x.csv", points=[{"tas": "<b>", "alt": 1.0, "x": float("inf")}, 3], fuel=900)]})["runs"][0]
        self.assertEqual((run["log"], run["points"], run["fuel"]), ("", [{"alt": 1.0}], 0))

    def test_a_curve_keeps_only_numbers(self):
        run = bench.clean({"runs": [self.run_(points=[{"curve": [[1, 2, 3, 4], [1, "2", 3, 4], [1, 2]]}])]})["runs"][0]
        self.assertEqual(run["points"][0]["curve"], [[1.0, 2.0, 3.0, 4.0]])

    def test_remove(self):
        bench.add(self.run_())
        bench.add(self.run_(id="r2"))
        self.assertEqual([x["id"] for x in bench.remove("r1")["runs"]], ["r2"])
        self.assertEqual([x["id"] for x in bench.load()["runs"]], ["r2"])

    def test_the_oldest_go_first(self):
        with mock.patch.object(bench, "MAX_RUNS", 2):
            for i in range(3):
                bench.add(self.run_(id=f"r{i}"))
        self.assertEqual([x["id"] for x in bench.load()["runs"]], ["r1", "r2"])

    def test_a_file_nothing_can_read_is_kept_aside(self):
        bench.FILE.parent.mkdir()
        bench.FILE.write_bytes(b"{ not json")
        self.assertEqual(bench.load(), {"runs": [], "damaged": True})
        self.assertEqual(bench.FILE.with_suffix(".bad.json").read_bytes(), b"{ not json")
        self.assertEqual(bench.load(), {"runs": []})

    def test_a_plan_from_the_page(self):
        self.assertIsNone(bench.plan_of({"vehicle": "x", "test": "drag"}))
        self.assertIsNone(bench.plan_of({"vehicle": "a b", "test": "top"}))
        self.assertIsNone(bench.plan_of("top"))
        out = bench.plan_of(plan(preset="<x>", difficulty="cheat", fuel="50", altitude=-5, custom="yes"))
        self.assertEqual((out["preset"], out["difficulty"], out["fuel"], out["altitude"], out["custom"]), ("", "realistic", 0, 0, False))


class Watch:
    """The part of alarms.Watch the bench reads, with a log of the real format."""

    def __init__(self, folder):
        self.folder, self.log, self.bench, self.flying, self.current, self.on_map, self.viewed = folder, None, False, False, "bf-109f-4", True, 0.0

    def mission_on_map(self):
        return self.on_map

    def set_log(self, on):
        if on and not self.log:
            self.log = flightlog.Log(self.folder, "bf-109f-4", [*(alarms.column(n) for n in alarms.SERIES), *alarms.POSITION])
        elif self.log and not on:
            self.log.close()
            self.log = None

    def fly(self, rows):
        """Rows into the log as Log.write would put them."""
        self.log.file.flush()
        names = [alarms.column(n) for n in alarms.SERIES]
        for r in rows:
            row = [r["t"]] + [r.get(n, "") for n in alarms.SERIES] + ["", "", ""]
            self.log.writer.writerow(row)
        self.log.file.flush()
        return names


class Flow(unittest.TestCase):
    """Armed, flown, analysed: what happens with the game's port and the page both out of the picture."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        p = mock.patch.object(bench, "FILE", self.folder / "bench.json")
        p.start()
        self.addCleanup(p.stop)
        q = mock.patch.object(bench, "AWAY_S", 0)
        q.start()
        self.addCleanup(q.stop)
        self.watch = Watch(self.folder)
        self.addCleanup(lambda: self.watch.set_log(False))
        self.bench = bench.Bench(self.watch, self.folder, lambda: "2.59.0.92")

    def flight(self, rows):
        self.watch.flying = True
        self.bench.step()
        self.watch.fly(rows)
        status = self.bench.status()
        self.watch.flying = False
        self.bench.step()  # the flight is over
        self.bench.step()  # and it stays so
        return status

    def test_a_good_run_is_saved_with_its_conditions(self):
        self.bench.arm(plan(fuel=33))
        self.assertTrue(self.watch.bench)
        status = self.flight(stretch(1, 40, tas=610.0))
        self.assertEqual(len(status["found"]["points"]), 1)  # shown while flying
        self.assertTrue(all(c["ok"] for c in status["live"]["checks"]))
        run = bench.load()["runs"][0]
        self.assertEqual((run["fuel"], run["game"], run["test"], run["points"][0]["tas"]), (33, "2.59.0.92", "top", 610.0))
        self.assertTrue((self.folder / run["log"]).is_file())
        self.assertIsNone(self.watch.log)  # the recording stopped with the flight
        self.assertIsNone(self.bench.log)

    def test_the_next_try_is_a_new_run(self):
        self.bench.arm(plan())
        self.flight(stretch(1, 40, tas=610.0))
        with mock.patch.object(bench.time, "time", lambda: 1900000000.0):
            self.flight(stretch(1, 40, tas=612.0))
        self.assertEqual([r["points"][0]["tas"] for r in bench.load()["runs"]], [610.0, 612.0])

    def test_a_flight_that_gave_nothing_says_why_and_saves_nothing(self):
        self.bench.arm(plan())
        self.flight(stretch(1, 40, throttle=70.0))
        self.assertEqual(bench.load()["runs"], [])
        self.assertEqual(reasons(self.bench.last), {"full"})

    def test_someone_else_on_the_same_map(self):
        self.bench.arm(plan())
        self.watch.flying, self.watch.current = True, "spitfire_mk5"
        self.bench.step()
        self.assertIsNone(self.watch.log)

    def test_the_same_aircraft_in_a_real_battle(self):
        self.bench.arm(plan())
        self.watch.flying, self.watch.on_map = True, False
        self.bench.step()
        self.assertIsNone(self.watch.log)

    def test_nothing_armed_nothing_recorded(self):
        self.watch.flying = True
        self.bench.step()
        self.assertIsNone(self.watch.log)
        self.assertEqual(self.watch.viewed, 0.0)

    def test_the_player_own_recording_is_left_running(self):
        self.watch.set_log(True)
        self.watch.fly(stretch(1, 40, tas=500.0, alt=1000.0))  # an earlier flight, in another test or none
        self.bench.arm(plan())
        self.bench.since = 0
        self.watch.flying = True
        self.bench.step()
        self.bench.since = 100.0
        self.watch.fly(stretch(100, 40, tas=610.0))
        self.watch.flying = False
        self.bench.step()
        self.bench.step()
        self.assertIsNotNone(self.watch.log)
        self.assertEqual([p["tas"] for p in bench.load()["runs"][0]["points"]], [610.0])

    def test_another_mission_disarms_and_ends_the_run(self):
        self.bench.arm(plan())
        self.watch.flying = True
        self.bench.step()
        self.watch.fly(stretch(1, 40, tas=610.0))
        self.bench.arm(None)
        self.assertIsNone(self.bench.plan)
        self.assertFalse(self.watch.bench)
        self.assertEqual(len(bench.load()["runs"]), 1)

    def test_the_csv_is_what_flight_data_reads(self):
        self.bench.arm(plan())
        self.flight(stretch(1, 40, tas=610.0))
        run = bench.load()["runs"][0]
        with open(self.folder / run["log"], encoding="utf-8-sig", newline="") as f:
            self.assertEqual(next(csv.reader(f))[0], flightlog.TIME)
        names = {alarms.column(n): n for n in alarms.SERIES}
        self.assertTrue(flightlog.report(flightlog.read_log(self.folder, run["log"], names)["rows"]))


class Rate(unittest.TestCase):
    def test_a_test_reads_faster_than_the_player_rate(self):
        w = alarms.Watch(lambda path: None, dict)
        w._sampled = time.monotonic() - .3
        w.record({"IAS, km/h": 500})
        self.assertEqual(len(w.trace), 0)  # 1 s by default
        w.bench = True
        w.record({"IAS, km/h": 500})
        self.assertEqual(len(w.trace), 1)


class Mission(unittest.TestCase):
    def test_alone_in_the_air_with_the_test_in_its_description(self):
        bare = builder._hangar_mission("air_archipelago", "armada", [0.0, 1500.0, 0.0], "WTFTD", speed=450.0)
        # without the game's presets (data/difficulty.json): the difficulty is only named, test_difficulty has the rest
        with mock.patch.object(mission, "load_scenario", return_value=bare), mock.patch.object(mission, "_difficulty_data", return_value=None):
            name, text = mission.build({"scenario": "free_air_archipelago_air", "vehicle": "bf-109f-4", "block": "armada", "preset": "Bf-109F-4_default", "start": "air", "altitude": 5000,
                                        "speed": 600, "fuel": 40, "allMods": True, "weather": "clear", "environment": "Noon", "difficulty": "realistic", "fileName": "wtftd_bench_bf-109f-4",
                                        "title": "Test bench: Bf 109 F-4, Top speed, 5,000 m", "description": "Hold 5,000 m.", "bench": plan()})
        self.assertEqual(name, "wtftd_bench_bf-109f-4.blk")
        for line in ('locName:t="Test bench: Bf 109 F-4, Top speed, 5,000 m"', 'locDesc:t="Hold 5,000 m."', 'weather:t="clear"', 'difficulty:t="realistic"', "fuelAmount:r=0.4",
                     "[0, 5000, 0]]", "speed:r=600", "applyAllMods:b=yes"):
            self.assertIn(line, text)
        self.assertEqual(text.count("unit_class"), 1)  # nobody else on the map
        self.assertNotIn("bench:", text.replace("Test bench:", ""))


class Route(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        p = mock.patch.object(bench, "FILE", Path(tmp.name) / "user" / "bench.json")
        p.start()
        self.addCleanup(p.stop)

    def test_routes(self):
        bench.add({**plan(), "id": "r1", "points": [{"tas": 600.0}]})
        handler = mock.Mock()
        server.Handler.get_api(handler, "bench")
        self.assertEqual(handler.send_json.call_args.args[0]["runs"][0]["id"], "r1")
        server.Handler.get_api(handler, "bench-live")
        self.assertIsNone(handler.send_json.call_args.args[0]["plan"])
        server.Handler.post_api(handler, "bench-delete", {"id": "r1"})
        self.assertEqual(handler.send_json.call_args.args[0]["runs"], [])
        with mock.patch.object(server.BENCH, "plan", plan()):
            server.Handler.post_api(handler, "bench-stop", {})
        self.assertIsNone(server.BENCH.plan)

    def test_it_goes_with_the_user_part_of_uninstall_only(self):
        bench.add({**plan(), "id": "r1"})
        home, user = bench.FILE.parent.parent, bench.FILE.parent
        with mock.patch.object(uninstall, "CACHE", home / "cache"), mock.patch.object(uninstall, "DATA", home / "data"), mock.patch.object(uninstall, "USER", user), \
                mock.patch.object(uninstall, "HOME", home):
            uninstall.run(["cache", "data"], None)
            self.assertTrue(bench.FILE.exists())
            uninstall.run(["user"], None)
        self.assertFalse(bench.FILE.exists())

    def test_a_normal_mission_disarms(self):
        watch = Watch(Path("."))
        b = bench.Bench(watch, Path("."))
        b.arm(plan())
        b.arm({})
        self.assertIsNone(b.plan)

    def test_the_server_keeps_one_bench(self):
        self.assertIsInstance(server.BENCH, bench.Bench)
        self.assertIs(server.BENCH.watch, server.WATCH)
        json.dumps(server.BENCH.status())
