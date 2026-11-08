"""Flight limits from a flight model, aircraft recognition, alarms: no game needed (fake /state)."""
import base64
import io
import json
import re
import tempfile
import time
import unittest
import wave
from array import array
from pathlib import Path
from unittest import mock

from wtftd import alarms, battle, blk, builder, cdk, flightlog, server

SU30 = {"v": 1540, "m": 2.1, "gear": 700, "flaps": [[0.2, 1018], [1, 600]], "fuel": [9400, 9400], "eng": 2}
J10 = {"v": 1543, "m": 2.1, "gear": 620, "flaps": [[0.1, 550], [1, 400]], "fuel": [5945, 6220.02], "eng": 1}
PLANES = {"su_30mkk": SU30, "j_10c": J10, "j_10_twin": dict(J10, v=900), "j_10a": dict(J10)}


WORDS = alarms.labels("en")


def airframe(**fields) -> dict:
    """An overlay of one line with the airframe's alarm, as set."""
    return alarms.clean({"lines": [{"text": "IAS {ias}", "rules": [{"limit": "airframe", **fields}]}]}, WORDS)


def state(**fields) -> dict:
    return {"valid": True, "Mfuel0, kg": 5945, "IAS, km/h": 500, "M": 0.5, "throttle 1, %": 100, **fields}


def details(planes=PLANES) -> dict:
    return {vid: {"st": {"lim": lim}} for vid, lim in planes.items()}


class Limits(unittest.TestCase):
    def fm(self, **mass):
        return {"Vne": 800, "VneMach": 0.9, "Mass": {"MaxFuelMass0": 500, **mass}, "Engine0": {"Type": 0},
                "EngineType0": {"Main": {"Type": "Inline"}}}

    def test_strength_block_when_nothing_at_the_root(self):
        lim = builder.flight_limits({"Aerodynamics": {"WingPlane": {"Strength": {"VNE": 1540, "MNE": 2.1}}}}, "air")
        self.assertEqual((lim["v"], lim["m"]), (1540, 2.1))

    def test_root_wins(self):
        fm = dict(self.fm(), Aerodynamics={"WingPlane": {"Strength": {"VNE": 1, "MNE": 1}}})
        self.assertEqual(builder.flight_limits(fm, "air")["v"], 800)

    def test_variable_sweep_keeps_the_swept_limit(self):
        strength = lambda v, m: {"Strength": {"VNE": v, "MNE": m}}
        aero = {"WingPlaneSweep1": dict(strength(1555, 2.25), Sweep=1.0), "WingPlaneSweep0": dict(strength(1021, 0.96), Sweep=0.0)}
        lim = builder.flight_limits({"Aerodynamics": aero}, "air")
        self.assertEqual(lim["sw"], [[0.0, 1021, 0.96], [1.0, 1555, 2.25]])
        self.assertEqual((lim["v"], lim["m"]), (1555, 2.25))

    def test_flaps_flat_list(self):
        lim = builder.flight_limits(self.fm(FlapsDestructionIndSpeedP=[0.1, 550, 1.0, 400]), "air")
        self.assertEqual(lim["flaps"], [[0.1, 550], [1.0, 400]])

    def test_flaps_one_pair_per_key(self):
        lim = builder.flight_limits(self.fm(FlapsDestructionIndSpeedP1=[1.0, 600], FlapsDestructionIndSpeedP0=[0.2, 1018]), "air")
        self.assertEqual(lim["flaps"], [[0.2, 1018], [1.0, 600]])

    def test_flaps_repeated_key(self):  # BB-1: P1 twice
        lim = builder.flight_limits(self.fm(FlapsDestructionIndSpeedP0=[0.1, 450],
                                            FlapsDestructionIndSpeedP1=[[0.3, 340], [1.0, 280]]), "air")
        self.assertEqual(lim["flaps"], [[0.1, 450], [0.3, 340], [1.0, 280]])

    def test_flaps_lone_speed(self):  # I-16
        self.assertEqual(builder.flight_limits(self.fm(FlapsDestructionIndSpeedP=700.0), "air")["flaps"], [[0, 700.0]])

    def test_helicopter_flaps_ignored(self):
        lim = builder.flight_limits(self.fm(FlapsDestructionIndSpeedP1=[0.0, 600], GearDestructionIndSpeed=420), "heli")
        self.assertNotIn("flaps", lim)
        self.assertEqual(lim["gear"], 420)

    def test_no_gear_limit(self):
        self.assertEqual(builder.flight_limits(self.fm(), "air")["gear"], 0)

    def test_fuel_both_values_with_repeated_tanks(self):  # Il-2M: a tank key twice
        lim = builder.flight_limits(self.fm(Parts={"tank1_capacity": [235.25, 135.25], "tank2_capacity": 200, "tank2_hp": 9}), "air")
        self.assertEqual(lim["fuel"], [500, 570.5])

    def test_fm_file_spellings(self):
        want = builder.fm_file("fm/x.blk")
        self.assertEqual(want.parts[-2:], ("fm", "x.blkx"))
        for path in ("fm/x", "/fm/x.blk", "FM/X.blk"):
            self.assertEqual(builder.fm_file(path), want, path)

    def test_no_limits_no_entry(self):
        self.assertEqual(builder.flight_limits({"Mass": {}}, "air"), {})

    def test_engines_skip_take_off_rockets(self):
        fm = {"Engine0": {"Type": 0}, "Engine1": {"Type": 0}, "Engine2": {"Type": 1},
              "EngineType0": {"Main": {"Type": "Jet"}}, "EngineType1": {"Main": {"Type": "Rocket"}}}
        self.assertEqual(builder.engine_count(fm), 2)

    def test_engines_described_in_place(self):  # Me 262 C: no EngineType<n>
        fm = {"Engine0": {"Main": {"Type": "Jet"}}, "Engine1": {"Main": {"Type": "Rocket"}}}
        self.assertEqual(builder.engine_count(fm), 1)

    def test_rocket_plane_has_engines(self):  # Me 163
        fm = {"Engine0": {"Type": 0}, "EngineType0": {"Main": {"Type": "Rocket"}}}
        self.assertEqual(builder.engine_count(fm), 1)


class Migration(unittest.TestCase):
    """An overlay saved before 0.27: the aircraft's alarms in a tab, lines red "with" one."""

    OLD = {"alarms": {"airframe": {"on": True, "red": 85, "at": 95, "hz": 1500, "dyn": False}, "gear": {"on": True}, "flaps": {"on": False}},
           "lines": [{"text": "IAS {ias}", "alarm": "airframe", "blink": True, "rules": [{"value": "g", "op": ">", "at": 9}]},
                     {"text": "FLAPS", "alarm": "flaps"}]}

    def test_each_line_gets_the_alarm_it_followed(self):
        cfg = alarms.clean(self.OLD, WORDS)
        first = cfg["lines"][0]["rules"]
        self.assertEqual([(r["limit"], r["at"], r["red"], r["hz"], r["full"]) for r in first], [("airframe", 95, 85, 1500, None), ("", 9, None, 1000, None)])
        self.assertEqual(first[0]["blink"], list(alarms.PARTS))
        self.assertEqual(cfg["lines"][1]["rules"], [])  # flaps was off

    def test_an_alarm_no_line_followed_gets_one_and_g_and_aoa_come(self):
        cfg = alarms.clean(self.OLD, WORDS)
        extra = [(x["when"], x["rules"][0]["limit"]) for x in cfg["lines"][2:]]
        self.assertEqual(extra, [("own", "gear"), ("own", "load"), ("own", "aoa")])
        self.assertNotIn("alarms", cfg)
        self.assertEqual(alarms.clean(cfg, WORDS), cfg)  # once


class Limits(unittest.TestCase):
    LIM = {"mass": 10000, "load": [-100000, 245166], "aoa": [[-20, 30], [-10, 20]]}

    def test_g_at_the_mass_flown(self):
        self.assertEqual([round(x, 2) for x in alarms.load_limits(self.LIM, {"Mfuel, kg": 2500})], [-1.63, 4.0])

    def test_negative_g_against_its_own_limit(self):
        pct = alarms.percents({"v": 1000, "m": 0, **self.LIM}, {"Ny": -0.8, "Mfuel, kg": 2500})
        self.assertAlmostEqual(pct["load"], 49, delta=0.1)

    def test_aoa_moves_with_the_flaps(self):
        self.assertEqual(alarms.aoa_limits(self.LIM, {"flaps, %": 50}), (-15, 25))

    def test_the_flight_model_s(self):
        jet = {"Aerodynamics": {"WingPlane": {"Strength": {"VNE": 1000, "MNE": 1, "CritOverload": [-1, 2]},
                                              "FlapsPolar0": {"alphaCritLow": -20, "alphaCritHigh": 28}, "FlapsPolar1": {"alphaCritLow": -22, "alphaCritHigh": 29}}}}
        self.assertEqual({k: builder.flight_limits(jet, "air")[k] for k in ("load", "aoa")}, {"load": [-1, 2], "aoa": [[-20, 28], [-22, 29]]})
        old = {"Aerodynamics": {"WingPlane": {"Strength": {"VNE": 700}}, "NoFlaps": {"alphaCritLow": -14, "alphaCritHigh": 17.2},
                                "FullFlaps": {"alphaCritLow": -17, "alphaCritHigh": 15.1}},
               "Mass": {"WingCritOverload": [-85000, 175100], "MaxNitro": 100, "MaxFuelMass1": 40},
               "Engine0": {"Type": 0}, "EngineType0": {"Afterburner": {"NitroConsumption": 0.1}},
               "Engine1": {"Type": 1, "Main": {"FuelSystemNum": 1}}, "EngineType1": {"Booster": True, "Main": {"Type": "Rocket", "FuelConsumptionOnFullThr": 8}}}
        lim = builder.flight_limits(old, "air")
        self.assertEqual((lim["load"], lim["aoa"], lim["wep"], lim["boost"]), ([-85000, 175100], [[-14, 17.2], [-17, 15.1]], [100, 0.1], [[40, 8]]))


class Speeds(unittest.TestCase):
    def test_flaps_between_points(self):
        self.assertEqual(alarms.flaps_limit([[0.2, 1000], [1, 600]], 0.6), 800)

    def test_flaps_outside_the_points(self):
        self.assertEqual(alarms.flaps_limit([[0.2, 1000], [1, 600]], 0.1), 1000)
        self.assertEqual(alarms.flaps_limit([[0.2, 1000], [0.5, 600]], 1), 600)

    def test_same_position_twice(self):  # Ki-87
        self.assertEqual(alarms.flaps_limit([[0.1, 400], [0.1, 480], [1, 280]], 0.1), 400)

    def test_airframe_is_the_worse_of_speed_and_mach(self):
        lim = {"v": 1000, "m": 1.0}
        self.assertEqual(alarms.percents(lim, {"IAS, km/h": 500, "M": 0.8})["airframe"], 80)
        self.assertEqual(alarms.percents(lim, {"IAS, km/h": 900, "M": 0.5})["airframe"], 90)

    def test_gear_and_flaps_only_when_out(self):
        self.assertEqual(set(alarms.percents(SU30, {"IAS, km/h": 300, "gear, %": 0})), {"airframe"})
        self.assertEqual(alarms.percents(SU30, {"IAS, km/h": 350, "gear, %": 100})["gear"], 50)
        self.assertEqual(alarms.percents(SU30, {"IAS, km/h": 300, "flaps, %": 100})["flaps"], 50)

    def test_no_gear_limit_no_line(self):
        self.assertNotIn("gear", alarms.percents(dict(SU30, gear=0), {"IAS, km/h": 300, "gear, %": 100}))

    def test_missing_fields(self):
        self.assertEqual(alarms.percents(J10, {"IAS, km/h": 0})["airframe"], 0)

    def test_thresholds(self):
        cfg = alarms.clean(None, WORDS)
        on = lambda pct: sorted({alarms.sound_of(cfg, x)["limit"] for x in alarms.own_alerts(cfg, {}, pct)})
        self.assertEqual(on({"airframe": 92.9, "gear": 89.9, "flaps": 89.9, "load": 89.9, "aoa": 89.9}), [])
        self.assertEqual(on({"airframe": 93, "gear": 90, "flaps": 90, "load": 90, "aoa": 90}), ["airframe", "aoa", "flaps", "gear", "load"])

    def test_a_switched_off_alarm_stays_off(self):  # saved before 0.27: no line gets it
        cfg = alarms.clean({"alarms": {"gear": {"on": False}}, "lines": [{"text": "GEAR", "alarm": "gear"}]}, WORDS)
        self.assertEqual(alarms.own_alerts(cfg, {}, {"gear": 500}), [])


class Recognition(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "global.blk"

    def tearDown(self):
        self.tmp.cleanup()

    def test_reported_type(self):
        self.assertEqual(alarms.reported_type({"valid": True, "army": "air", "type": "su_30mkk"}), "su_30mkk")  # in game
        self.assertIsNone(alarms.reported_type({"valid": True, "type": 3}))

    def test_saved_model(self):
        self.path.write_text('x:i=1\nselectedAir{\n  current_model:t="j_10c"\n}\n', encoding="utf-8")
        self.assertEqual(alarms.read_model(self.path), "j_10c")

    def test_file_absent(self):
        self.assertIsNone(alarms.read_model(self.path))

    def test_key_absent(self):
        self.path.write_text('selectedTank{\n  current_model:t="us_m2a4"\n}\n', encoding="utf-8")
        self.assertIsNone(alarms.read_model(self.path))

    def test_the_real_aircraft_among_look_alikes(self):
        self.assertIs(alarms.recognise(PLANES, state(), "j_10_twin"), PLANES["j_10_twin"])

    def test_either_fuel_value(self):
        self.assertIs(alarms.recognise(PLANES, state(**{"Mfuel0, kg": 6220}), "j_10c"), J10)

    def test_look_alikes_with_other_limits_are_never_guessed(self):
        for model in (None, "su_30mkk", "gone"):
            self.assertIsNone(alarms.recognise(PLANES, state(), model), model)

    def test_same_limits_any_will_do(self):
        twins = {k: PLANES[k] for k in ("j_10c", "j_10a")}
        self.assertEqual(alarms.recognise(twins, state(), None), J10)

    def test_engines_must_fit(self):
        self.assertIsNone(alarms.recognise({"j_10c": J10}, state(**{"throttle 2, %": 100}), "j_10c"))

    def test_nothing_fits(self):
        self.assertIsNone(alarms.recognise(PLANES, state(**{"Mfuel0, kg": 1}), "j_10c"))


class Settings(unittest.TestCase):
    def line(self, **fields):
        return alarms.clean({"lines": [{"text": "x", **fields}]}, WORDS)

    def test_what_comes_from_the_page_is_checked(self):
        cfg = alarms.clean({"volume": -5, "pollMs": 1, "logMs": "x", "outline": 40, "spacing": True, "outlineColor": "red",
                            "muteKey": [0], "holdKey": ["a"], "blocks": [{"x": "a", "scale": 9999}] * 9}, WORDS)
        self.assertEqual((cfg["volume"], cfg["pollMs"]), (0, 50))
        self.assertEqual((cfg["logMs"], cfg["outline"], cfg["spacing"], cfg["outlineColor"]), (1000, 4, 0, "#000000"))
        self.assertEqual((cfg["muteKey"], cfg["holdKey"]), ([], []))
        self.assertEqual([b["scale"] for b in cfg["blocks"]], [400] * alarms.MAX_BLOCKS)
        self.assertEqual(cfg["blocks"][0], {"x": 0, "y": 0, "scale": 400, "columns": 1, "frame": 0, "frameColor": "#FFFFFF", "background": "", "bgOpacity": 50,
                                            "title": "", "feed": "", "rows": alarms.FEED_ROWS})

    def test_a_bad_condition_is_no_condition(self):
        for test in ("x", {"op": ">", "at": 1}, {"value": "g", "op": "=", "at": 1}, {"value": "g", "op": ">", "at": "1"},
                     {"value": "g", "op": ">", "at": float("nan")}, {"value": "g", "op": ">", "at": True}, {"value": "", "op": ">", "at": 1}):
            self.assertIsNone(self.line(**{"if": test})["lines"][0]["if"], test)
            self.assertEqual(self.line(rule=test)["lines"][0]["rules"], [], test)
            self.assertEqual(self.line(rules=[test])["lines"][0]["rules"], [], test)

    def test_a_sound_is_a_plain_name(self):
        sound = lambda name: self.line(rules=[{"limit": "gear", "sound": name}])["lines"][0]["rules"][0]["sound"]
        for name in ("../x.wav", "a/b.wav", "x.exe", "", 3):
            self.assertEqual(sound(name), "", name)
        self.assertEqual(sound("Horn 2.wav"), "Horn 2.wav")

    def test_a_line_shows_on_its_condition(self):
        cfg = self.line(**{"if": {"value": "alt", "op": "<", "at": 100}})
        self.assertEqual(len(alarms.lines_for(cfg, {"H, m": 50}, [])), 1)
        self.assertEqual(alarms.lines_for(cfg, {"H, m": 500}, []), [])
        self.assertEqual(alarms.lines_for(cfg, {}, []), [])  # a value that isn't there meets nothing

    def test_a_line_hides_when_a_value_is_missing(self):
        cfg = self.line(text="{gear_max} km/h", hideNA=True)
        self.assertEqual(alarms.lines_for(cfg, {}, []), [])
        self.assertEqual(alarms.lines_for(cfg, {"gear_max": 700}, [])[0][0], "700 km/h")

    def test_blocks_keep_their_place_and_size(self):
        cfg = alarms.clean({"size": 40, "blocks": [{"x": 5, "y": 6, "scale": 50}], "lines": [{"text": "a"}, {"text": "b", "block": 1}, {"text": "c", "block": 3}]}, WORDS)
        self.assertEqual([(x[0], x[2], x[4]) for x in alarms.lines_for(cfg, {}, [])], [("a", 40, 0), ("b", 20, 1), ("c", 40, 0)])

    def test_a_line_blinks_only_with_its_alarm(self):
        cfg = self.line(blink=True, rules=[alarms.limit_alarm("gear")])  # saved before 0.27: the whole line, now each part
        self.assertFalse(alarms.lines_for(cfg, {}, [])[0][3])
        self.assertTrue(alarms.lines_for(cfg, {}, [(0, 0)])[0][3])
        self.assertEqual(cfg["lines"][0]["rules"][0]["blink"], list(alarms.PARTS))

    def test_only_the_parts_asked_flash(self):
        cfg = self.line(text="IAS {ias} km/h", rules=[{**alarms.limit_alarm("gear"), "blink": ["value"]}])
        parts = alarms.lines_for(cfg, {"IAS, km/h": 700}, [(0, 0)])[0][5]
        self.assertEqual([x[2] for x in parts], [False, True, False])
        self.assertEqual(parts[1][3], cfg["color"])  # out of its turn the value keeps the line's colour: never hidden

    def test_several_conditions(self):
        test = {"value": "alt", "op": "<", "at": 100, "more": [{"value": "ias", "op": ">", "at": 300}]}
        both = self.line(**{"if": test})
        either = self.line(**{"if": {**test, "join": "or"}})
        for values, needs_both, needs_one in (({"H, m": 50, "IAS, km/h": 400}, 1, 1), ({"H, m": 50, "IAS, km/h": 200}, 0, 1), ({"H, m": 500, "IAS, km/h": 200}, 0, 0)):
            self.assertEqual(len(alarms.lines_for(both, values, [])), needs_both, values)
            self.assertEqual(len(alarms.lines_for(either, values, [])), needs_one, values)
        self.assertEqual(len(self.line(**{"if": {**test, "more": [test] * 9}})["lines"][0]["if"]["more"]), alarms.MAX_TESTS - 1)

    def test_a_lines_colours_by_part(self):
        cfg = alarms.clean({"color": "#111111", "valueColor": "#222222", "unitColor": "#333333", "alert": "#FF0000",
                            "lines": [{"text": "IAS {ias} km/h", "rules": [alarms.limit_alarm("gear")]}]}, WORDS)
        parts = alarms.lines_for(cfg, {"IAS, km/h": 700}, [])[0][5]
        self.assertEqual(parts, [("IAS ", "#111111", False), ("700", "#222222", False), (" km/h", "#333333", False)])
        self.assertEqual(alarms.lines_for(cfg, {"IAS, km/h": 700}, [(0, 0)])[0][5], [("IAS 700 km/h", "#FF0000", False)])  # the alert is the whole line

    def test_each_alarm_its_colour_the_last_one_on_wins(self):
        rules = [{"value": "ias", "op": ">", "at": 600, "color": "#FFA500"}, {"value": "ias", "op": ">", "at": 800}]
        cfg = alarms.clean({"alert": "#FF0000", "lines": [{"text": "{ias}", "rules": rules}]}, WORDS)
        color = lambda ias: alarms.lines_for(cfg, {"IAS, km/h": ias}, alarms.own_alerts(cfg, {"IAS, km/h": ias}, red=True))[0][1]
        self.assertEqual((color(700), color(900)), ("#FFA500", "#FF0000"))  # orange first, then the overlay's alert colour

    def test_a_line_keeps_its_own_colours(self):
        cfg = alarms.clean({"valueColor": "#222222", "lines": [{"text": "{ias}", "valueColor": "#00FF00"}]}, WORDS)
        self.assertEqual(alarms.lines_for(cfg, {"IAS, km/h": 700}, [])[0][5], [("700", "#00FF00", False)])

    def test_columns_read_top_to_bottom(self):
        self.assertEqual(alarms.columns_of([1, 2, 3, 4, 5], 2), [[1, 2, 3], [4, 5]])
        self.assertEqual(alarms.columns_of([1, 2], 4), [[1], [2]])
        self.assertEqual(alarms.columns_of([], 3), [])

    def test_gear_and_flaps_when_retracted(self):
        state = {"IAS, km/h": 350, "gear, %": 0, "flaps, %": 0}
        self.assertNotIn("gear_pct", alarms.computed(SU30, state, WORDS))
        out = alarms.computed(SU30, state, WORDS, always=True)
        self.assertEqual(round(out["gear_pct"]), 50)
        self.assertIn("flaps_pct", out)
        self.assertEqual(alarms.own_alerts(alarms.defaults(WORDS), state, alarms.percents(SU30, state)), [])  # no alarm from it

    def test_a_beep_at_its_volume(self):
        loud, soft = [array("h", wave.open(io.BytesIO(alarms.tone(1000, 100, v)), "rb").readframes(10 ** 6)) for v in (100, 50)]
        self.assertEqual(len(loud), alarms.SOUND_RATE // 10)
        self.assertLessEqual(abs(max(loud) - 32767), 400)
        self.assertLessEqual(abs(max(soft) - max(loud) / 2), 200)
        self.assertEqual(max(map(abs, alarms.tone(1000, 100, 0)[44:])), 0)

    def test_the_players_sounds(self):
        out = io.BytesIO()
        with wave.open(out, "wb") as w:
            w.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
            w.writeframes(array("h", [1000, -1000, 2000, -2000]).tobytes())
        data = base64.b64encode(out.getvalue()).decode()
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "sounds"
            name = alarms.save_sound(folder, "../../my:horn?.wav", data)
            self.assertEqual(name, "my_horn_.wav")
            self.assertEqual(alarms.sound_list(folder), [name])
            self.assertEqual([p.name for p in Path(tmp).iterdir()], ["sounds"])  # nothing outside its folder
            half = alarms.scaled(str(folder / name), 1.0, 50)
            self.assertEqual(list(array("h", wave.open(io.BytesIO(half), "rb").readframes(4))), [500, -500, 1000, -1000])
            for bad in ("", "not base64!", base64.b64encode(b"MZ not a wav").decode()):
                with self.assertRaises(ValueError):
                    alarms.save_sound(folder, "x.wav", bad)

    def test_a_missing_sound_falls_back_on_its_beep(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(alarms, "beep") as beep:
            alarms.play({"hz": 900, "ms": 80, "sound": "gone.wav"}, 70, Path(tmp))
            beep.assert_called_once_with(900, 80, 70)


class SurfaceMissiles(unittest.TestCase):
    GUIDED = {"bulletName": "x", "guidanceType": "radar", "guidance": {"workTime": 30.0}, "loadFactorMax": 40.0}

    def test_a_launcher_is_a_gun_holding_a_missile(self):
        launcher = {"cannon": True, "bullet": {"mass": 900.0, "bulletType": "sam_tank", "mesh": "m", "rocket": {**self.GUIDED, "mesh": "m_deployed"}}}
        missile = builder.launched_missile(launcher)
        self.assertEqual((missile["mass"], missile["guidanceType"], missile["mesh"]), (900.0, "radar", "m_deployed"))
        self.assertNotIn("rocket", missile)

    def test_a_few_are_written_as_an_aircrafts(self):
        self.assertEqual(builder.launched_missile({"rocket": self.GUIDED})["bulletName"], "x")

    def test_guns_and_plain_rockets_are_not_missiles(self):
        for launcher in ({"bullet": {"mass": 1.0}}, {"bullet": {"rocket": {"guidanceType": "none"}}}, {"rocket": {"mass": 1.0}}, None, []):
            self.assertIsNone(builder.launched_missile(launcher), launcher)

    def test_on_a_pylon(self):
        air = cdk.airborne({**self.GUIDED, "bulletType": "sam_tank", "mesh": "deployed"}, "body", True)
        self.assertTrue(air["rocketGun"])
        self.assertEqual((air["mesh"], air["bullets"]), ("body", 1))
        self.assertEqual((air["rocket"]["bulletType"], air["rocket"]["finsLatAccel"]), ("aam", 40.0))
        self.assertEqual(air["mesh_deployed"], "deployed")  # hung folded, flown unfolded, as us_starstreak
        self.assertNotIn("mesh", air["rocket"])
        self.assertEqual(blk.loads(blk.dumps(air))["rocket"]["bulletName"], "x")

    def test_one_model_for_both(self):
        self.assertEqual(cdk.airborne(self.GUIDED, "body", False)["mesh_deployed"], "body")

    def test_an_animation_shows_it_on_the_pylon(self):
        # Aster-30: invisible without an animChar, and it has one for flight and one for its launcher
        aster = {**self.GUIDED, "shellAnimChar": "aster30_rocket_deployed_char"}
        self.assertEqual(cdk.airborne(aster, "aster30_rocket", True, "aster30_rocket_char")["animChar"], "aster30_rocket_deployed_char")
        self.assertEqual(cdk.airborne(self.GUIDED, "9m113_rocket_deployed", False, "9m113_rocket_char")["animChar"], "9m113_rocket_char")
        self.assertNotIn("animChar", cdk.airborne(self.GUIDED, "mim_104_patriot_missile", True))

    def aster(self):
        return f"{cdk.MARKER} - x\n" + blk.dumps(cdk.airborne({**self.GUIDED, "mass": 450.0, "mesh": "aster30_rocket"}, "aster30_rocket", True, "aster30_rocket_char"))

    def test_in_its_launch_tube(self):
        # the Aster-30's model holds the covers of its tube: only a container hides them (checked in game), and its part
        # named after the model faces forward: from a jet emitter the missile left backward
        at = "gameData/Weapons/wtftd/rafale_c_f3_1/aster.blk"
        files = cdk._in_tube(at, self.aster())
        box = blk.loads(files[at].split("\n", 1)[1])
        self.assertTrue(box["container"])
        self.assertEqual((box["mesh"], box["emitter"], box["hiddenNode"]), ("aster30_rocket", "aster30_rocket", ["cap_01", "cap_02"]))
        self.assertEqual(box["cap"], ["aster30_rocket", "engine", "stab_01", "stab_02", "stab_03", "stab_04"])
        self.assertEqual((box["blk"], box["bullets"], box["mass"], box["animChar"]),
                         ("gameData/Weapons/wtftd/rafale_c_f3_1_missile/aster.blk", 1, 450.0, "aster30_rocket_char"))
        missile = blk.loads(files[box["blk"]].split("\n", 1)[1])
        self.assertNotIn("mesh", missile)  # the container shows it on the pylon: a model here would bring the covers back
        self.assertNotIn("animChar", missile)  # so would an animation (seen in game)
        self.assertEqual(missile["mesh_deployed"], "aster30_rocket")

    def test_any_other_model_stays_a_missile(self):
        text = f"{cdk.MARKER} - x\n" + blk.dumps(cdk.airborne(self.GUIDED, "mim_104_patriot_missile", True))
        self.assertIsNone(cdk._in_tube("a/b.blk", text))

    def test_a_tube_on_a_pylon(self):
        details = {"sl": [{"i": 1, "e": "rocket_001", "o": []}, {"i": 2, "e": "rocket_002", "o": []}], "am": [], "pr": [], "b": "armada"}
        catalog = {"aster": {"p": "gameData/Weapons/groundmodels_weapons/aster.blk", "c": "sam", "t": "aam", "air": 1}}
        with mock.patch.object(cdk, "_air_copy", return_value=self.aster()):
            files = cdk.build_files("x", "air", details, {}, "", {"1": {"w": "aster", "n": 1}, "2": {"w": "aster", "n": 1}}, "custom", None, catalog)[0]
        self.assertEqual(sorted(k for k in files if "Weapons/wtftd" in k),
                         ["gameData/Weapons/wtftd/x_1/aster.blk", "gameData/Weapons/wtftd/x_1_missile/aster.blk"])
        text = next(v for k, v in files.items() if "weaponPresets" in k)
        self.assertEqual(text.count('blk:t="gameData/Weapons/wtftd/x_1/aster.blk"'), 2)
        self.assertNotIn("bullets", text)  # a container says how many it holds

    def test_an_atgm_keeps_its_type(self):
        self.assertEqual(cdk.airborne({"bulletType": "atgm_tank"}, "m", False)["rocket"]["bulletType"], "atgm_tank")


class Aircraft(unittest.TestCase):
    FM = {"EngineType0": {"Main": {"Type": "Jet", "Thrust": 100.0, "Mass": 900.0}, "Afterburner": {"Boost": 1.5}, "Controls": {"X": 1.0}}}
    OTHER = {"EngineType0": {"Main": {"Type": "Jet", "Thrust": 200.0, "Extra": 3, "Mass": 700.0}, "Afterburner": {"Boost": 2.0}, "Controls": {"X": 9.0}}}

    def text(self, write):
        b = cdk.Blk()
        write(b)
        return str(b)

    def test_another_radar_and_what_it_lacked(self):
        mods = {"sensors": {"0": "us_an_apg_63"}, "sensorsAdd": {"rwr": "us_rwr"}}
        text = self.text(lambda b: cdk._sensors(b, {"se": ["su_n_001ve", "su_spo"]}, mods, {"sensors": {}}))
        self.assertIn('"@override:sensor[1]"{', text)
        self.assertIn('blk":t="gameData/sensors/us_an_apg_63.blk"', text)
        self.assertIn('sensor{ blk:t="gameData/sensors/us_rwr.blk" }', text)

    def test_sensors_on_an_aircraft_with_none(self):
        text = self.text(lambda b: cdk._sensors(b, {}, {"sensorsAdd": {"radar": "x"}}, {}))
        self.assertTrue(text.startswith("sensors{"))

    def test_only_a_plain_file_name_gets_in(self):
        self.assertEqual(self.text(lambda b: cdk._sensors(b, {"se": ["a"]}, {"sensors": {"0": "../x"}, "sensorsAdd": {"radar": 'a"b'}}, {})), "\n")

    def test_avionics_override_or_add(self):
        text = self.text(lambda b: cdk._avionics(b, {"avionics": {"laserDesignator": True, "hasHelmetDesignator": False, "nope": True}}, {"laserDesignator": False}))
        self.assertIn('"@override:laserDesignator":b=yes', text)
        self.assertIn("hasHelmetDesignator:b=no", text)
        self.assertNotIn("nope", text)

    def test_another_engine(self):
        out = cdk._engine_overrides(self.FM, self.OTHER)
        self.assertEqual(out[("EngineType0", "Main", "Thrust")], ("r", 200.0))
        self.assertEqual(out[("EngineType0", "Main", "Extra")], ("+i", 3))  # a value ours doesn't have
        self.assertEqual(out[("EngineType0", "Afterburner", "Boost")], ("r", 2.0))
        self.assertNotIn(("EngineType0", "Main", "Type"), out)
        self.assertNotIn(("EngineType0", "Controls", "X"), out)

    def test_the_cockpits_voice(self):
        text = self.text(lambda b: cdk._voices(b, {"warningVoice": "rita"}, {"Sound": {"voiceWarningSystem": "betty"}}))
        self.assertIn('"@override:voiceWarningSystem":t="rita"', text)
        self.assertIn("voiceWarningSystem:t=", self.text(lambda b: cdk._voices(b, {"warningVoice": "rita"}, {"Sound": {}})))

    def test_a_special_crew_voice(self):
        self.assertIn('specialSpeechLanguage:t="SmMaria"', self.text(lambda b: cdk._voices(b, {"crewVoice": "SmMaria"}, {})))
        self.assertEqual(self.text(lambda b: cdk._voices(b, {"crewVoice": 'x" evil', "warningVoice": "nobody"}, {})), "\n")

    def test_a_jet_takes_no_propeller_engine(self):
        with self.assertRaises(cdk.CdkError):
            cdk._engine_overrides(self.FM, {"EngineType0": {"Main": {"Type": "Inline"}}})


class Ground(unittest.TestCase):
    def setUp(self):
        self.seen = {"valid": True, "army": "tank", "type": "tankModels/ussr_t_72b", "speed": 41.0}
        self.watch = alarms.Watch(lambda p: json.dumps(self.seen).encode() if p == "/indicators" else None, dict, save=lambda: None)
        self.watch.enabled = True

    def test_a_tank_is_followed_without_an_aircraft(self):
        self.watch.tick()
        self.assertTrue(self.watch.flying)
        self.assertEqual(self.watch.last["speed"], 41.0)
        self.assertEqual(self.watch.display, [])  # no overlay for tanks yet: an aircraft's lines would say nothing

    def test_its_own_overlay(self):
        self.watch.set_config(self.watch.base, {"type:tank": alarms.clean({"lines": [{"text": "{speed} km/h"}]}, WORDS)})
        self.watch.tick()
        self.assertEqual(self.watch.display[0][0], "41 km/h")

    def test_an_aircraft_is_not_a_tank(self):
        self.seen["army"] = "air"
        self.watch.tick()
        self.assertFalse(self.watch.flying)


class Archive(unittest.TestCase):
    def line(self, n, text="hi"):
        return {"id": n, "time": 75, "text": text, "sender": "Bob", "enemy": False, "mode": "All"}

    def test_each_line_once_until_the_game_starts_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = battle.Archive(Path(tmp) / "logs")
            seen = {"up": True, "chat": [self.line(1), self.line(2)], "events": [], "damage": []}
            archive.add(seen)
            archive.add(seen)  # a page opened again asks from the start
            read = lambda: next((Path(tmp) / "logs").glob("battle-*.txt")).read_text(encoding="utf-8").splitlines()
            self.assertEqual(read(), ["1:15  Bob: hi", "1:15  Bob: hi"])
            archive.add({"up": False, "chat": [], "events": [], "damage": []})
            archive.add({"up": True, "chat": [self.line(1, "new game")], "events": [], "damage": []})
            self.assertEqual(read()[-1], "1:15  Bob: new game")


class Glow(unittest.TestCase):
    def alpha(self, pixels, width, x, y):
        return pixels[(y * width + x) * 4 + 3]

    def test_strong_at_the_edges_nothing_inside(self):
        pixels = alarms.glow_pixels((400, 200), "#FF0000")
        self.assertEqual(self.alpha(pixels, 400, 0, 0), alarms.GLOW_ALPHA)
        self.assertEqual(self.alpha(pixels, 400, 200, 100), 0)
        self.assertGreater(self.alpha(pixels, 400, 200, 0), self.alpha(pixels, 400, 200, 12))
        self.assertGreater(self.alpha(pixels, 400, 200, 12), self.alpha(pixels, 400, 200, 28))

    def test_premultiplied(self):  # what the window takes: red no stronger than the opacity, nothing else
        pixels = alarms.glow_pixels((40, 20), "#FF0000")
        for b, g, r, a in zip(*[iter(pixels)] * 4):
            self.assertEqual((b, g, r), (0, 0, a))
        self.assertEqual(alarms.glow_pixels((8, 4), "#102030")[:4], bytes((33, 22, 11, 180)))

    def test_any_screen_size(self):
        for size in ((1920, 1080), (3840, 2160), (1366, 768), (2561, 1439)):
            self.assertEqual(len(alarms.glow_pixels(size, "#FF0000")), size[0] * size[1] * 4)

    def test_its_size(self):
        small, big = (alarms.glow_pixels((400, 200), "#FF0000", size) for size in (10, 40))
        self.assertEqual(self.alpha(small, 400, 200, 40), 0)
        self.assertGreater(self.alpha(big, 400, 200, 40), 0)

    def test_each_alarm_its_glow_in_its_colour(self):
        cfg = alarms.clean({"alert": "#123456", "lines": [{"text": "x", "rules": [{"limit": "gear", "glow": True, "glowSize": 30},
                                                                                  {"limit": "flaps", "glow": True, "color": "#00FF80", "glowFlash": True},
                                                                                  {"limit": "airframe"}]}]}, WORDS)
        self.assertEqual(alarms.glow_of(cfg, [(0, 0)]), ("#123456", 30, False))  # the overlay's alert colour by default
        self.assertEqual(alarms.glow_of(cfg, [(0, 0), (0, 1)]), ("#00FF80", alarms.GLOW_SIZE, True))  # the last one on that has one
        self.assertIsNone(alarms.glow_of(cfg, [(0, 2)]))
        self.assertEqual(alarms.first_glow(cfg), ("#123456", 30, False))
        self.assertEqual(alarms.glow_pixels((8, 4), "#00FF80")[:4], bytes((90, 180, 0, 180)))

    def test_off_by_default(self):
        self.assertFalse(alarms.clean(None, WORDS)["lines"][0]["rules"][0]["glow"])
        self.assertIsNone(alarms.first_glow(alarms.clean(None, WORDS)))

    def test_the_overlay_s_repeat_goes_to_the_alarms_without_one(self):  # saved before 0.27
        lines = [{"text": "x", "rules": [{"limit": "gear", "full": None}, {"limit": "flaps", "full": None, "repeat": 900}]}]
        cfg = alarms.clean({"repeat": 450, "lines": lines}, WORDS)
        self.assertEqual([r["repeat"] for r in cfg["lines"][0]["rules"]], [450, 900])
        self.assertNotIn("repeat", cfg)
        self.assertEqual(alarms.pace(cfg, (0, 0), None), 0.45)
        self.assertEqual(alarms.clean({"repeat": alarms.REPEAT_MS, "lines": lines}, WORDS)["lines"][0]["rules"][0]["repeat"], 0)  # the default: left empty
        self.assertEqual(alarms.pace(alarms.clean({"lines": lines}, WORDS), (0, 0), None), alarms.REPEAT_MS / 1000)

    def test_the_overlay_s_glow_goes_to_every_alarm(self):  # saved before 0.27
        cfg = alarms.clean({"glow": True, "glowSize": 25, "glowFlash": True, "glowColor": "#00FF00", "lines": [{"text": "x", "rules": [{"limit": "gear"}]}]}, WORDS)
        rule = cfg["lines"][0]["rules"][0]
        self.assertEqual((rule["glow"], rule["glowSize"], rule["glowFlash"]), (True, 25, True))
        self.assertNotIn("glow", cfg)
        self.assertEqual(alarms.clean(cfg, WORDS), cfg)

    def test_a_profile_has_its_own(self):
        watch = alarms.Watch(lambda path: None, dict, save=lambda: None)
        mine = alarms.clean({"lines": [{"text": "x", "rules": [{"limit": "gear", "glow": True, "color": "#00FF00"}]}]}, WORDS)
        watch.set_config(alarms.clean(None, WORDS), {"j_10c": mine})
        self.assertIsNone(alarms.first_glow(watch.cfg))
        watch.current = "j_10c"
        watch.pick()
        self.assertEqual(alarms.first_glow(watch.cfg)[0], "#00FF00")

    def test_the_page_offers_it_on_each_alarm(self):
        page = (alarms.WEB / "index.html").read_text(encoding="utf-8")
        script = (alarms.WEB / "overlay.js").read_text(encoding="utf-8")
        self.assertNotIn('data-ov="glow', page)  # no longer the overlay's
        self.assertIn("sw('glow', 'ov.glow')", script)
        self.assertIn("first.color || c.alert", script)  # the preview
        for code in ("en", "fr", "de", "es", "it", "pt", "pl", "cs", "ru", "ja", "zh"):
            words = json.loads((alarms.WEB / "locales" / f"{code}.json").read_text(encoding="utf-8"))
            self.assertTrue(words["ov.glow"] and words["ov.glowSize"] and words["ov.glowFlash"], code)



class Watching(unittest.TestCase):
    def setUp(self):
        self.reply = json.dumps(state()).encode()
        self.indicators = b'{"valid": false}'  # the fallback's case, seen on 2.59
        self.on_map = False
        self.model = "j_10c"
        self.watch = alarms.Watch(lambda path: self.indicators if path == "/indicators" else self.reply,
                                  lambda: self.data, lambda: self.on_map, lambda: None)
        self.data = details()
        self.watch.enabled = True
        self.watch.model = lambda: self.model
        patcher = mock.patch.object(alarms, "beep")
        self.beep = patcher.start()
        self.addCleanup(patcher.stop)

    def fly(self, **fields):
        self.reply = json.dumps(state(**fields)).encode()
        return self.watch.tick()

    def texts(self):
        return [x[0] for x in self.watch.display]

    def test_lines_say_real_speeds(self):
        self.assertEqual(self.fly(**{"IAS, km/h": 771, "gear, %": 100}), alarms.POLL_S)
        self.assertEqual(self.texts(), ["IAS    771 / 1543 km/h", "MACH   0.50 / 2.10", "GEAR   771 / 620 km/h"])

    def test_only_the_line_of_the_alarm_goes_to_the_alert_colour(self):
        self.fly(**{"IAS, km/h": 771, "gear, %": 100})
        cfg = self.watch.cfg
        self.assertEqual([x[1] for x in self.watch.display], [cfg["color"], cfg["color"], cfg["alert"]])

    def test_thresholds_and_sounds_are_the_players(self):
        self.watch.set_config(airframe(at=30, hz=500, ms=80), {})
        self.fly()
        self.beep.assert_called_once_with(500, 80, 100)

    def test_gear_alarm_beeps_at_its_pitch(self):
        self.fly(**{"gear, %": 100, "IAS, km/h": 600})
        self.beep.assert_called_once_with(1000, alarms.BEEP_MS, 100)

    def test_no_alarm_no_beep(self):
        self.fly()
        self.assertNotIn(self.watch.cfg["alert"], [x[1] for x in self.watch.display])
        self.beep.assert_not_called()

    def test_beeps_are_spaced(self):
        self.fly(**{"IAS, km/h": 1500})
        self.fly(**{"IAS, km/h": 1500})
        self.assertEqual(self.beep.call_count, 1)
        self.watch._last_beep -= 1
        self.fly(**{"IAS, km/h": 1500})
        self.assertEqual(self.beep.call_count, 2)

    def test_red_before_the_beep(self):
        self.watch.set_config(airframe(red=80, at=95), {})
        self.fly(**{"IAS, km/h": 1300})  # 84 % of 1543: red, quiet
        self.assertEqual(self.watch.display[0][1], self.watch.cfg["alert"])
        self.beep.assert_not_called()
        self.watch._last_beep -= 5
        self.fly(**{"IAS, km/h": 1500})  # 97 %: it beeps too
        self.beep.assert_called_once()

    def test_beeps_close_in_up_to_the_break(self):
        cfg = alarms.clean({"lines": [{"text": "IAS", "rules": [{"limit": "airframe", "at": 90, "ms": 100, "gap": 800}]}]}, WORDS)
        for pct, wait in ((90, 0.9), (95, 0.5), (100, 0.1), (120, 0.1)):
            close = alarms.closeness(cfg, (0, 0), {"airframe": pct}, {})
            self.assertAlmostEqual(alarms.pace(cfg, (0, 0), close), wait)
        steady = alarms.clean({"lines": [{"text": "IAS", "rules": [{"limit": "airframe", "at": 90, "full": None, "repeat": 450}]}]}, WORDS)
        self.assertEqual(alarms.pace(steady, (0, 0), alarms.closeness(steady, (0, 0), {"airframe": 99}, {})), 0.45)  # its own repeat
        self.watch.set_config(cfg, {})
        self.fly(**{"IAS, km/h": 1600})  # past the limit: one continuous sound, its beeps as long as two readings
        self.beep.assert_called_once_with(cfg["lines"][0]["rules"][0]["hz"], cfg["pollMs"] * 2, 100)

    def test_several_alarms_on_one_line(self):
        g = {"value": "g", "op": ">", "ms": 80}
        self.watch.set_config(alarms.clean({"lines": [{"text": "G {g}", "rules": [{**g, "at": 6, "hz": 900}, {**g, "at": 8, "hz": 1500, "red": 7}]}]}, WORDS), {})
        self.fly(**{"Ny": 6.5})
        self.beep.assert_called_once_with(900, 80, 100)
        self.assertEqual(self.watch.display[0][1], self.watch.cfg["alert"])  # the first one turns it red
        self.beep.reset_mock()
        self.watch._last_beep -= 5
        self.fly(**{"Ny": 9})
        self.assertEqual(sorted(c.args[0] for c in self.beep.call_args_list), [900, 1500])

    def test_gear_torn_off_goes_quiet(self):
        self.fly(**{"gear, %": 100, "IAS, km/h": 640})  # 103 % of 620: past its breaking speed
        self.beep.assert_called()
        self.beep.reset_mock()
        self.watch._last_beep -= 5
        self.fly(**{"gear, %": 100, "IAS, km/h": 640})
        self.beep.assert_not_called()
        self.assertEqual(self.watch.broken, {"gear"})
        self.reply = b'{"valid": false}'
        self.watch.tick()  # the next spawn has its gear again
        self.assertEqual(self.watch.broken, set())

    def test_an_alarm_that_must_last(self):
        self.watch.set_config(airframe(at=30, after=500), {})
        with mock.patch.object(alarms.time, "monotonic", return_value=100.0):
            self.fly()
        self.beep.assert_not_called()
        self.assertEqual(self.watch.display[0][1], self.watch.cfg["color"])  # not red yet either
        with mock.patch.object(alarms.time, "monotonic", return_value=100.6):
            self.fly()
        self.beep.assert_called_once()
        self.assertEqual(self.watch.display[0][1], self.watch.cfg["alert"])

    def test_the_same_alarm_on_two_lines_beeps_once(self):
        self.fly(**{"IAS, km/h": 1500})  # IAS and MACH lines both follow the airframe
        self.beep.assert_called_once()

    def test_wep_left(self):
        self.data = details({"j_10c": dict(J10, wep=[60, 0.5])})  # 120 s of WEP
        times = iter([10.0, 10.0, 10.0, 11.0, 11.0, 11.0, 12.0, 12.0, 12.0, 13.0, 13.0, 13.0])
        with mock.patch.object(alarms.time, "monotonic", side_effect=lambda: next(times, 13.0)):
            for throttle in (110, 110, 100, 100):
                self.fly(**{"throttle 1, %": throttle})
        self.assertAlmostEqual(self.watch.wep.left(self.watch._lim)["wep_s"], 118, delta=1)

    def test_g_load_and_aoa_alarms(self):
        self.data = details({"j_10c": dict(J10, mass=9045, load=[-230000, 630000], aoa=[[-32, 35], [-31, 35]])})
        self.fly(**{"Ny": 4, "Mfuel, kg": 2900})  # 4 G of 10.8 at this mass: quiet
        self.beep.assert_not_called()
        self.assertEqual(round(self.watch.last["g_lim"], 1), 10.8)
        self.fly(**{"Ny": 10, "Mfuel, kg": 2900})
        self.beep.assert_called_once_with(1200, alarms.BEEP_MS, 100)
        self.assertIn("G      10.0 / 10.8", self.texts())  # its line shows during its alarm only

    def test_a_block_of_the_chat_with_a_title(self):
        cfg = alarms.clean({"blocks": [{"x": 5, "feed": "chat", "rows": 2, "title": "CHAT"}]}, WORDS)
        rows = alarms.lines_for(cfg, {}, [], {"chat": ["a", "b", "c"]})
        self.assertEqual([x[0] for x in rows if x[4] == 1], ["CHAT", "b", "c"])

    def test_the_chat_comes_once(self):
        cfg = alarms.clean({"blocks": [{"feed": "chat"}]}, WORDS)
        said = {"/gamechat?lastId=0": [{"id": 1, "msg": "o7", "sender": "Bob", "time": 1}], "/gamechat?lastId=1": []}
        self.watch.get = lambda path: json.dumps(said.get(path.split("&")[0], {})).encode() if "gamechat" in path or "hudmsg" in path else None
        self.watch.read_feeds(cfg)
        self.watch._feed["t"] = -9
        self.watch.read_feeds(cfg)
        self.assertEqual(list(self.watch.feeds["chat"]), ["Bob: o7"])

    def test_the_sheet_while_its_key_is_held(self):
        self.watch.sheet = True
        self.fly()
        self.assertEqual(self.texts()[:2], ["j_10c", "Vne 1543 km/h   Mne 2.10"])

    def test_the_profile_key_goes_through_the_overlays(self):
        mine = airframe(at=30)
        self.watch.set_config(self.watch.base, {"type:fighter": mine})
        self.watch.next_profile()
        self.assertEqual((self.watch.profile, self.watch.cfg), ("type:fighter", mine))
        self.watch.next_profile()
        self.assertEqual(self.watch.profile, "")
        self.reply = b'{"valid": false}'
        self.watch.tick()  # the next spawn picks its own again
        self.assertIsNone(self.watch.forced)

    def test_the_bell_beeps_between_readings(self):  # 0.22 s apart at 99 %, not rounded up to the next reading (0.3 s)
        self.watch.set_config(airframe(at=90, ms=150, gap=700), {})
        clock = [100.0]
        with mock.patch.object(alarms.time, "monotonic", side_effect=lambda: clock[0]):
            self.watch.ring(self.watch.cfg, [(0, 0)], {"airframe": 99}, {})
            self.beep.assert_called_once()
            self.assertAlmostEqual(self.watch.chime(), 0.22)  # the bell's wait
            clock[0] += 0.22
            self.watch.chime()
            self.assertEqual(self.beep.call_count, 2)
            clock[0] += 1  # no reading told it again: it stops by itself
            self.assertIsNone(self.watch.chime())
            self.assertEqual(self.beep.call_count, 2)

    def test_flashes_on_the_beat(self):  # lit with each beep, as long as it sounds; without beeps, FLASH_MS
        self.watch.set_config(airframe(at=90, ms=150, gap=700), {})
        clock = [100.0]
        with mock.patch.object(alarms.time, "monotonic", side_effect=lambda: clock[0]):
            self.watch.ring(self.watch.cfg, [(0, 0)], {"airframe": 95}, {})  # a beep now, the next in 0.5 s
            for at, lit in ((0.1, True), (0.2, True), (0.3, False), (0.45, False)):  # half of the 0.5 s beat at least
                clock[0] = 100 + at
                self.assertEqual(self.watch.lit(), lit, at)
            self.watch.ring(self.watch.cfg, [(0, 0)], {"airframe": 100}, {})  # at the break: lit throughout
            for clock[0] in (100.5, 100.6, 100.7, 100.75, 100.8):
                self.watch.chime()  # the bell, between readings
                self.assertTrue(self.watch.lit(), clock[0])
            self.assertEqual(self.watch.lit(250), int(100.8 * 2000 / 250) % 2 == 0)  # an alarm's own cycle
            self.watch.ringing = None
            clock[0] = 100.8  # nothing rings: FLASH_MS, in its dark half
            self.assertFalse(self.watch.lit())

    def test_each_part_flashes_on_its_alarm_s_clock(self):
        rules = [{**alarms.limit_alarm("gear"), "blink": ["value"]}, {**alarms.limit_alarm("flaps"), "blink": ["name"], "flashMs": 250}]
        cfg = alarms.clean({"lines": [{"text": "GEAR {ias}", "rules": rules}]}, WORDS)
        self.assertEqual([p[2] for p in alarms.lines_for(cfg, {"IAS, km/h": 700}, [(0, 0), (0, 1)])[0][5]], [250, True])
        glow = alarms.clean({"lines": [{"text": "x", "rules": [{"limit": "gear", "glow": True, "glowFlash": True, "flashMs": 300}]}]}, WORDS)
        self.assertEqual(alarms.glow_of(glow, [(0, 0)])[2], 300)

    def test_the_overlay_s_flash_cycle_goes_to_the_alarms(self):  # saved before 0.27
        lines = [{"text": "x", "rules": [{"limit": "gear"}]}]
        self.assertEqual(alarms.clean({"flashMs": 800, "lines": lines}, WORDS)["lines"][0]["rules"][0]["flashMs"], 800)
        self.assertEqual(alarms.clean({"flashMs": 500, "lines": lines}, WORDS)["lines"][0]["rules"][0]["flashMs"], 0)  # the default: with the beeps
        self.assertNotIn("flashMs", alarms.clean({"flashMs": 800, "lines": lines}, WORDS))

    def test_try_an_alarm(self):  # My overlay's Try: the IAS line's airframe alarm at a value set by hand
        cfg = self.watch.base
        self.reply = b'{"valid": false}'  # in the hangar: the sample
        with mock.patch.object(self.watch, "start_overlay"):
            rows = self.watch.set_trial("", (0, 0), 95)
        self.assertEqual([r[1] for r in rows][:3], [cfg["alert"], cfg["color"], cfg["color"]])  # only it: not Mach, not the sample's gear
        self.assertEqual(rows[0][0], "IAS    1463 / 1540 km/h")  # the line follows the value tried, not only its colour
        self.beep.assert_not_called()  # the loop rings it, woken at once
        self.watch.tick()
        self.beep.assert_called_once()
        self.beep.reset_mock()
        self.watch._last_beep -= 5
        rows = self.watch.set_trial("", (0, 0), 50)
        self.assertEqual(rows[0][1], cfg["color"])
        self.beep.assert_not_called()
        self.watch.trial["t"] -= alarms.TRY_S + 1  # the page that started it is gone
        self.assertEqual(self.watch.trial_frame(), [])
        self.assertIsNone(self.watch.trial)

    def test_try_in_flight(self):  # the flight's own lines and limits; a real alarm wins
        with mock.patch.object(self.watch, "start_overlay"):
            self.watch.set_trial("", (0, 0), 96)
            self.fly()  # 500 km/h: no alarm of the flight
        self.beep.assert_called_once()
        self.assertEqual(self.texts()[0], "IAS    1481 / 1543 km/h")  # 96 % of the J-10C's limit
        self.assertEqual(self.watch.display[0][1], self.watch.cfg["alert"])
        self.beep.reset_mock()
        self.watch._last_beep -= 5
        self.fly(**{"IAS, km/h": 1000, "gear, %": 100})  # gear out past its limit, for real
        self.assertEqual(self.texts()[0], "IAS    1000 / 1543 km/h")  # the flight's own overlay again
        self.assertEqual(self.watch.display[2][1], self.watch.cfg["alert"])
        self.assertEqual(self.beep.call_args.args[0], 1000)  # the gear's pitch, continuous past its limit

    def test_trying_in_flight_never_shows_the_flight_s_overlay_in_between(self):  # the window draws every 16 ms
        rule = {"limit": "airframe", "glow": True}
        self.watch.set_config(alarms.clean({"lines": [{"text": "IAS {ias}", "rules": [rule]}]}, WORDS), {})
        seen = []

        class Spy(alarms.Watch):  # every overlay and glow the window could catch, as they're set
            def __setattr__(spy, name, value):
                if name in ("display", "glow"):
                    seen.append((name, value))
                object.__setattr__(spy, name, value)

        self.watch.__class__ = Spy
        with mock.patch.object(self.watch, "start_overlay"):
            self.watch.set_trial("", (0, 0), 96)
            seen.clear()
            for _ in range(3):
                self.fly()  # 500 km/h: no alarm of the flight
        self.assertTrue(all(v and v[0][0] == "IAS 1481" for n, v in seen if n == "display"), seen)  # never the flight's 500
        self.assertTrue(all(v for n, v in seen if n == "glow"), seen)  # the glow never off in between

    def test_try_a_value_alarm_and_its_glow(self):
        rule = {"value": "fuel_pct", "op": "<", "at": 15, "red": 25, "glow": True, "color": "#FFA500"}
        self.watch.set_config(alarms.clean({"lines": [{"text": "FUEL {fuel_pct}", "rules": [rule]}]}, WORDS), {})
        with mock.patch.object(self.watch, "start_overlay"):
            rows = self.watch.set_trial("", (0, 0), 20)  # red, quiet
        self.assertEqual(rows[0][1], "#FFA500")
        self.assertEqual(self.watch.glow, ("#FFA500", alarms.GLOW_SIZE, False))
        self.beep.assert_not_called()

    def test_a_tried_value_moves_what_its_line_shows(self):
        mach = alarms._line({"text": "MACH {mach}", "rules": [alarms.limit_alarm("airframe")]})
        self.assertEqual(alarms.tried_state(mach["rules"][0], 50, mach["text"])[0]["M"], 1.05)
        self.assertEqual(alarms.tried_state({"limit": "", "value": "fuel_pct"}, 10)[0]["Mfuel, kg"], 940)
        self.assertEqual(alarms.tried_state({"limit": "", "value": "RPM 2"}, 9000)[0]["RPM 2"], 9000)  # any field the game sends

    def test_a_sound_file_paces_by_its_length(self):
        with tempfile.TemporaryDirectory() as folder:
            with wave.open(str(Path(folder) / "horn.wav"), "wb") as w:
                w.setparams((1, 2, 22050, 0, "NONE", "not compressed"))
                w.writeframes(bytes(2 * 22050))  # 1 s
            self.assertAlmostEqual(alarms.sound_ms({"sound": "horn.wav", "ms": 150}, Path(folder)), 1000)
            self.assertEqual(alarms.sound_ms({"sound": "gone.wav", "ms": 150}, Path(folder)), 150)

    def test_the_try_route(self):
        handler = mock.Mock()
        with mock.patch.object(server, "WATCH", self.watch), mock.patch.object(alarms, "available", return_value=True),                 mock.patch.object(self.watch, "start_overlay"):
            server.Handler.post_api(handler, "overlay-try", {"profile": "", "line": 0, "rule": 0, "value": 95})
            self.assertTrue(handler.send_json.call_args.args[0]["on"])
            for body in ({"line": 0, "rule": 0, "value": "95"}, {"line": 0, "rule": 0, "value": float("nan")}, {"line": 0, "value": True}, {"on": False}):
                server.Handler.post_api(handler, "overlay-try", body)
                self.assertFalse(handler.send_json.call_args.args[0]["on"], body)
                self.assertTrue(handler.send_json.call_args.args[0]["lines"])  # the sample again

    def test_the_test_button_plays_that_alarm(self):  # the page's "Test", on each of a line's alarms
        g = {"value": "g", "op": ">"}
        cfg, handler = alarms.clean({"lines": [{"text": "G {g}", "rules": [{**g, "at": 6, "hz": 500}, {**g, "at": 8, "hz": 900}]}]}, WORDS), mock.Mock()
        with mock.patch.object(server, "WATCH", mock.Mock(profiles={}, base=cfg)), mock.patch.object(alarms, "available", return_value=True), \
                mock.patch.object(alarms, "play") as play:
            for body, hz in (({"line": 0, "rule": 1}, 900), ({"line": 0}, 500)):
                server.Handler.post_api(handler, "overlay-test", body)
                self.assertEqual(play.call_args.args[0]["hz"], hz)
            play.reset_mock()
            for body in ({"line": 0, "rule": 2}, {"line": 0, "rule": "1"}, {"line": 1}, {"alarm": "gear"}):
                server.Handler.post_api(handler, "overlay-test", body)
                self.assertEqual(handler.send_json.call_args.args[0], {"ok": False}, body)
            play.assert_not_called()

    def test_the_page_offers_several_alarms_per_line(self):
        script = (alarms.WEB / "overlay.js").read_text(encoding="utf-8")
        for bit in ("data-oradd", "data-ordel", "data-orclear", "data-orblink", "data-or=\"${key}\"", "'red'", "'dyn'", "'after'", "'repeat'",
                    "rule: +b.closest('.ov-rule').dataset.j", "'own'", "load: [90, 1200]", "aoa: [90, 500]", "'wep'", "api('overlay-try'", "data-ortry ", "data-olshown",
                    f"OV_MAX_RULES = {alarms.MAX_RULES}", f"OV_GAP_MS = {alarms.GAP_MS}"):  # the page and the engine agree
            self.assertIn(bit, script)
        for code in ("en", "fr", "de", "es", "it", "pt", "pl", "cs", "ru", "ja", "zh"):
            words = json.loads((alarms.WEB / "locales" / f"{code}.json").read_text(encoding="utf-8"))
            for key in ("ov.redFrom", "ov.beepFrom", "ov.dynamic", "ov.gap", "ov.redFromValue", "ov.fullAt", "ov.addAlarm", "ov.removeAlarm", "ov.withBeep",
                        "ov.noFull", "ov.alarm.load", "ov.alarm.aoa", "ov.when.own", "ov.alarmValue", "ov.alarmColor", "ov.flash", "ov.after",
                        "ov.feed.chat", "ov.feed.log", "ov.sheetKey", "ov.profileKey", "ov.v.g_lim", "ov.v.wep", "ov.try", "ov.tryStop", "ov.tryHint", "ov.shownAs", "ov.shown.value",
                        "ov.shown.percent", "ov.shown.both"):
                self.assertTrue(words.get(key), (code, key))
        page = (alarms.WEB / "index.html").read_text(encoding="utf-8")
        self.assertNotIn('id="ovAlarms"', page)  # the alarms live on the lines
        self.assertNotIn('id="ovStyle"', page)  # and so does how a line shows its limit
        self.assertIn('data-ovkey="sheetKey"', page)

    def test_a_lines_own_alarm_red_first_and_continuous_at_its_value(self):
        self.own_alert(red=25, full=5)
        self.fly(**{"Mfuel, kg": 1300})  # 22 % of 5945 kg: red only
        self.assertEqual(self.watch.display[0][1], self.watch.cfg["alert"])
        self.beep.assert_not_called()
        rule = self.watch.cfg["lines"][0]["rules"][0]
        self.assertAlmostEqual(alarms.closeness(self.watch.cfg, (0, 0), {}, {"fuel_pct": 10}), 0.5)
        self.assertEqual(alarms.closeness(self.watch.cfg, (0, 0), {}, {"fuel_pct": 2}), 1.0)
        self.assertEqual((rule["red"], rule["full"]), (25, 5))

    def test_an_aircraft_with_fuel_in_the_hangar_is_not_flying(self):  # the Swiss F/A-18C, read live on 2.60 (2026-11-08)
        hangar = state(**{"IAS, km/h": 1, "Mfuel, kg": 925, "Mfuel0, kg": 7460, "RPM 1": 0})
        self.assertIsNone(alarms.flying(json.dumps(hangar).encode(), lambda: False))
        moving = {**hangar, "IAS, km/h": 300}
        self.assertEqual(alarms.flying(json.dumps(moving).encode(), lambda: False), moving)  # in the air, a map or not

    def test_the_menus_are_not_a_flight(self):  # as read in the hangar on 2.59
        hangar = state(**{"IAS, km/h": 1, "Mfuel, kg": 0, "RPM 1": 0})
        self.assertIsNone(alarms.flying(json.dumps(hangar).encode(), lambda: False))
        self.assertEqual(alarms.flying(json.dumps(hangar).encode(), lambda: True), hangar)  # gliding on empty tanks
        get = {"/state": json.dumps(hangar).encode(), "/map_info.json": b'{"valid" : false}'}.get
        watch = alarms.Watch(get, dict, save=lambda: None)
        watch.enabled = True
        self.assertEqual(watch.tick(), alarms.IDLE_S)
        self.assertFalse(watch.flying)

    def own_alert(self, **rule):
        self.watch.cfg = alarms.clean({"lines": [{"text": "FUEL", "blink": True, "rule": {"value": "fuel_pct", "op": "<", "at": 15, "hz": 900, "ms": 80, **rule}}]}, WORDS)
        self.watch.pick = lambda: None

    def test_a_lines_own_alert(self):
        self.own_alert()
        self.fly(**{"Mfuel, kg": 300})
        self.beep.assert_called_once_with(900, 80, 100)
        self.assertTrue(self.watch.warn)
        self.assertEqual(self.watch.display[0][1], self.watch.cfg["alert"])
        self.assertTrue(self.watch.display[0][3])
        self.beep.reset_mock()
        self.watch._last_beep -= 1
        self.fly(**{"Mfuel, kg": 3000})
        self.beep.assert_not_called()
        self.assertFalse(self.watch.warn)

    def test_a_lines_own_alert_stops_at_a_crash(self):
        self.own_alert()
        self.fly(**{"Mfuel, kg": 300, "RPM 1": 9000})
        self.watch._last_beep -= 1
        self.beep.reset_mock()
        self.fly(**{"Mfuel, kg": 300, "RPM 1": 0, "throttle 1, %": 0})
        self.beep.assert_not_called()
        self.assertFalse(self.watch.warn)

    def test_when_the_alarms_keep_quiet(self):
        for setting, fields, front in (({"soundEngine": True}, {"IAS, km/h": 1500, "RPM 1": 0}, True), ({"soundFocus": True}, {"IAS, km/h": 1500}, False)):
            self.watch.cfg = alarms.clean(setting, WORDS)
            self.watch.pick = lambda: None
            self.watch._last_beep = -10
            with mock.patch.object(alarms, "game_focused", return_value=front):
                self.fly(**fields)
            self.beep.assert_not_called()
            self.assertTrue(self.watch.warn)  # still shown
        self.watch.cfg = alarms.clean({}, WORDS)
        self.watch.muted = True
        self.fly(**{"IAS, km/h": 1500})
        self.beep.assert_not_called()

    def test_the_game_is_read_as_often_as_asked(self):
        self.watch.cfg = alarms.clean({"pollMs": 250}, WORDS)
        self.watch.pick = lambda: None
        self.assertEqual(self.fly(), 0.25)

    def test_overlays_by_kind_of_engine(self):
        self.data = {**details(), "jet": {"c": "air", "st": {"lim": {**J10, "jet": True}}}}
        self.watch.kind = lambda vid: "fighter"
        self.watch.set_config(self.watch.base, {"type:jet": alarms.clean({"size": 77}, WORDS), "type:prop": alarms.clean({"size": 55}, WORDS)})
        self.watch._lim, self.watch.current = {"jet": True}, "jet"
        self.watch.pick()
        self.assertEqual(self.watch.profile, "type:jet")
        self.watch._lim, self.watch.current = {}, "prop"
        self.watch.pick()
        self.assertEqual(self.watch.profile, "type:prop")
        self.watch.kind = lambda vid: "helicopter"
        self.watch.pick()
        self.assertEqual(self.watch.profile, "")
        self.watch.current = None
        self.watch.pick()
        self.assertEqual(self.watch.profile, "")

    def test_the_glow_follows_the_alarms(self):
        self.fly(**{"IAS, km/h": 1500})
        self.assertTrue(self.watch.warn)
        self.fly(**{"IAS, km/h": 300})
        self.assertFalse(self.watch.warn)
        self.fly(**{"IAS, km/h": 1500})
        self.reply = b'{"valid": false}'
        self.watch.tick()
        self.assertFalse(self.watch.warn)

    def test_not_flying(self):
        for reply in (None, b"", b"not json", b"[]", b'{"valid": false}', b'{"valid": true}',
                      json.dumps(state(**{"IAS, km/h": 0})).encode()):
            self.watch.display = [("x", "#000000", 40)]
            self.reply = reply
            self.assertEqual(self.watch.tick(), alarms.IDLE_S, reply)
            self.assertEqual(self.watch.display, [], reply)
        self.beep.assert_not_called()

    def test_disabled(self):
        self.watch.enabled = False
        self.fly(**{"IAS, km/h": 1500})
        self.assertEqual(self.watch.display, [])
        self.beep.assert_not_called()

    def test_unknown_aircraft_makes_no_sound(self):
        self.model = None
        for _ in range(3):
            self.fly(**{"IAS, km/h": 1500})
        self.assertEqual(self.watch.display[0][:2], ("AIRCRAFT UNKNOWN", self.watch.cfg["alert"]))
        self.assertEqual(self.texts()[1:], ["IAS    1500 / N/A km/h", "MACH   0.50 / N/A"])  # the game's own values remain
        self.beep.assert_not_called()

    def test_the_overlay_can_wait_for_a_known_aircraft(self):
        self.watch.set_config(alarms.clean({"hideUnknown": True}, WORDS), {})
        self.model = None
        self.fly()
        self.assertEqual(self.watch.display, [])
        self.model = "j_10c"
        self.fly()
        self.assertIn("IAS", self.texts()[0])

    def test_changing_aircraft_in_the_hangar(self):
        self.fly()
        self.assertIs(self.watch._lim, J10)
        self.reply = b'{"valid": false}'
        self.watch.tick()
        self.model = "su_30mkk"
        self.fly(**{"Mfuel0, kg": 9400, "throttle 2, %": 100})
        self.assertIs(self.watch._lim, SU30)

    def test_new_data_after_an_update(self):
        self.fly()
        self.data = details({"j_10c": dict(J10, v=1000)})
        self.reply = None
        self.watch.tick()
        self.fly()
        self.assertEqual(self.watch._lim["v"], 1000)

    def test_swept_limit_is_said(self):
        self.data = details({"j_10c": dict(J10, sw=[[0, 1000, 1], [1, 1543, 2.1]])})
        self.fly(**{"IAS, km/h": 771})
        self.assertEqual(self.texts()[0], "IAS    771 / 1543 km/h (swept limit)")

    def test_the_game_naming_the_aircraft_comes_before_the_fallback(self):
        self.model = "su_30mkk"
        self.indicators = b'{"valid": true, "army": "air", "type": "j_10_twin"}'
        self.fly()
        self.assertIs(self.watch._lim, PLANES["j_10_twin"])

    def test_the_game_is_believed_even_if_fuel_says_otherwise(self):  # external tanks, if they change Mfuel0
        self.model = None
        self.indicators = b'{"valid": true, "type": "j_10c"}'
        self.fly(**{"Mfuel0, kg": 7000})
        self.assertIs(self.watch._lim, J10)
        self.beep.assert_not_called()

    def test_fallback_when_indicators_says_nothing_useful(self):
        for reply in (None, b"", b"not json", b"[]", b'{"valid": false}', b'{"valid": true}',
                      b'{"valid": true, "type": 3}', b'{"valid": true, "type": "wtftd_custom"}'):
            self.indicators = reply
            self.watch._key = None
            self.fly()
            self.assertIs(self.watch._lim, J10, reply)

    def test_indicators_coming_back_mid_flight(self):
        self.model = None
        self.fly()
        self.assertIsNone(self.watch._lim)
        self.indicators = b'{"valid": true, "type": "j_10c"}'
        self.fly()
        self.assertIs(self.watch._lim, J10)

    def test_generated_mission_comes_first(self):
        self.model = "su_30mkk"
        self.on_map = True
        self.indicators = b'{"valid": true, "type": "su_30mkk"}'  # a custom vehicle's host
        self.watch.mission = {"id": "j_10a", "fuel": None, "unbreakable": False}
        self.fly()
        self.assertIs(self.watch._lim, PLANES["j_10a"])

    def test_generated_mission_with_its_own_fuel(self):
        self.on_map = True
        self.watch.mission = {"id": "j_10c", "fuel": 3000.0, "unbreakable": False}
        self.fly(**{"Mfuel0, kg": 3000})
        self.assertIs(self.watch._lim, J10)

    def test_unbreakable_airframe(self):
        self.on_map = True
        self.watch.mission = {"id": "j_10c", "fuel": None, "unbreakable": True}
        self.fly(**{"IAS, km/h": 1500})
        self.assertEqual(self.texts()[0], "UNBREAKABLE AIRFRAME")
        self.assertNotIn(self.watch.cfg["alert"], [x[1] for x in self.watch.display])
        self.beep.assert_not_called()

    def test_real_battle_after_an_unbreakable_mission(self):
        self.watch.mission = {"id": "j_10c", "fuel": None, "unbreakable": True}
        self.fly(**{"IAS, km/h": 1500})  # another map: not that mission
        self.beep.assert_called_once_with(1400, alarms.BEEP_MS, 100)

    def test_a_mission_with_another_aircraft_does_not_count(self):
        self.on_map = True
        self.watch.mission = {"id": "su_30mkk", "fuel": None, "unbreakable": True}
        self.fly(**{"IAS, km/h": 1500})
        self.assertIs(self.watch._lim, J10)
        self.assertEqual(self.beep.call_count, 1)


class Lines(unittest.TestCase):
    VALUES = {"IAS, km/h": 1284, "M": 1.25, "RPM 2": 13300.5, "vne": 1540, "swept": ""}

    def test_values_with_their_decimals(self):
        self.assertEqual(alarms.fill("IAS {ias} / {vne} km/h", self.VALUES), "IAS 1284 / 1540 km/h")
        self.assertEqual(alarms.fill("M {mach}", self.VALUES), "M 1.25")

    def test_decimals_can_be_chosen(self):
        self.assertEqual(alarms.fill("{mach:3} {ias:1}", self.VALUES), "1.250 1284.0")

    def test_any_field_of_the_game_under_its_own_name(self):
        self.assertEqual(alarms.fill("{RPM 2}", self.VALUES), "13300.5")

    def test_what_is_not_there(self):
        self.assertEqual(alarms.fill("{heading} {nothing}", self.VALUES), "N/A N/A")

    def test_plain_text_and_empty_values(self):
        self.assertEqual(alarms.fill("hello { {ias", self.VALUES), "hello { {ias")
        self.assertEqual(alarms.fill("IAS {swept}", self.VALUES), "IAS")

    def test_no_python_formatting_gets_through(self):
        self.assertEqual(alarms.fill("{ias.__class__} {ias!r}", self.VALUES), "N/A N/A")

    def test_computed_values(self):
        out = alarms.computed(SU30, {"IAS, km/h": 770, "M": 1.05, "flaps, %": 60, "gear, %": 100, "Mfuel, kg": 4700,
                                     "Mfuel0, kg": 9400}, WORDS)
        self.assertEqual((out["vne"], out["mne"], out["gear_max"]), (1540, 2.1, 700))
        for key, value in (("airframe_pct", 50), ("gear_pct", 110), ("flaps_max", 809), ("fuel_pct", 50), ("margin", 770)):
            self.assertAlmostEqual(out[key], value, msg=key)

    def test_margin_is_to_the_nearest_limit(self):  # high up: Mach comes first
        self.assertAlmostEqual(alarms.computed(SU30, {"IAS, km/h": 700, "M": 1.75}, WORDS)["margin"], 140)

    def test_unknown_aircraft_has_no_limits(self):
        self.assertEqual(alarms.computed(None, {"IAS, km/h": 700}, WORDS), {"swept": ""})

    def test_conditions(self):
        cfg = alarms.clean(None, WORDS)
        cfg["lines"] = [alarms._line({"text": w, "when": w, "rules": [alarms.limit_alarm("gear")]}) for w in alarms.WHEN]
        shown = lambda values, on: [x[0] for x in alarms.lines_for(cfg, values, on)]
        self.assertEqual(shown({}, []), ["always"])
        own = list(alarms.WHEN).index("own")
        self.assertEqual(shown({"gear, %": 1, "flaps, %": 1, "airbrake, %": 1, "rec": 1}, [(own, 0)]), list(alarms.WHEN))
        self.assertNotIn("own", shown({}, [(0, 0)]))  # another line's alarm: not its own

    def test_a_line_keeps_its_own_size_and_colour(self):
        cfg = alarms.clean(None, WORDS)
        cfg["lines"] = [alarms._line({"text": "x", "color": "#123456", "size": 90})]
        self.assertEqual(alarms.lines_for(cfg, {}, []), [("x", "#123456", 90, False, 0, [("x", "#123456", False)])])


class Computed(unittest.TestCase):
    def test_a_level_turn(self):  # 2 G at 100 m/s
        out = alarms.computed(None, {"TAS, km/h": 360, "Ny": 2}, WORDS)
        self.assertAlmostEqual(out["turn_radius"], 588.8, 0)
        self.assertAlmostEqual(out["turn_rate"], 9.74, 1)
        self.assertAlmostEqual(out["turn"], 37, 0)

    def test_no_turn_flying_straight(self):
        self.assertNotIn("turn", alarms.computed(None, {"TAS, km/h": 360, "Ny": 1.02}, WORDS))

    def test_horizontal_speed(self):
        self.assertAlmostEqual(alarms.computed(None, {"TAS, km/h": 360, "Vy, m/s": 60}, WORDS)["hspeed"], 288)

    def test_thrust_adds_up_and_mass_is_empty_plus_fuel(self):
        lim = dict(SU30, mass=17520)
        out = alarms.computed(lim, {"thrust 1, kgs": 1874, "thrust 2, kgs": 1874, "Mfuel, kg": 9400}, WORDS)
        self.assertEqual((out["thrust_total"], out["mass"]), (3748, 26920))
        self.assertAlmostEqual(out["twr"], 0.139, 3)

    def test_no_mass_no_ratio(self):
        self.assertNotIn("twr", alarms.computed(SU30, {"thrust 1, kgs": 1874}, WORDS))

    def test_endurance_and_range(self):
        out = alarms.computed(None, {"Mfuel, kg": 500, "TAS, km/h": 720}, WORDS, {"burn": 100})
        self.assertEqual(out["fuel_time"], "5:00")
        self.assertEqual(out["range"], 60)

    def test_nothing_burning(self):
        self.assertNotIn("fuel_time", alarms.computed(None, {"Mfuel, kg": 500}, WORDS, {"burn": 0}))

    def test_excess_power(self):
        out = alarms.computed(None, {"TAS, km/h": 360, "Vy, m/s": 10}, WORDS, {"accel": alarms.G})
        self.assertAlmostEqual(out["sep"], 110)

    def test_trend(self):
        trend = alarms.Trend()
        for t in range(0, 41, 10):  # 2 kg a second
            trend.add(t, {"Mfuel, kg": 1000 - 2 * t, "TAS, km/h": (100 + t) * 3.6})
        self.assertAlmostEqual(trend.rates()["burn"], 120)
        self.assertEqual(len(trend.points), 4)  # older than BURN_S: gone

    def burn_after(self, before, after, seconds):
        """The burn shown that long after it changed, on whole kg read 10 times a second like the game's."""
        trend, fuel = alarms.Trend(), 1500
        for tick in range(int((60 + seconds) * 10)):
            fuel -= (before if tick < 600 else after) / 600
            trend.add(tick / 10, {"Mfuel, kg": int(fuel)})
        return trend.rates()["burn"]

    def test_burn_follows_the_afterburner(self):
        self.assertAlmostEqual(self.burn_after(40, 240, 5), 240, delta=24)
        self.assertAlmostEqual(self.burn_after(240, 40, 15), 40, delta=4)

    def test_whole_kg_make_the_burn_neither_jump_nor_read_high(self):
        for seconds in (0.3, 0.7, 1.1, 1.5):
            self.assertAlmostEqual(self.burn_after(40, 40, seconds), 40, delta=1)

    def test_acceleration_over_the_last_seconds(self):
        trend = alarms.Trend()
        for t, v in ((0, 100), (9, 100), (10, 120), (11, 140)):
            trend.add(t, {"TAS, km/h": v * 3.6})
        self.assertAlmostEqual(trend.rates()["accel"], 20)

    def test_a_first_reading_has_no_rates(self):
        trend = alarms.Trend()
        trend.add(0, {"Mfuel, kg": 10})
        self.assertEqual(trend.rates(), {})

    def test_refuelling_is_no_negative_burn(self):
        trend = alarms.Trend()
        trend.add(0, {"Mfuel, kg": 10})
        trend.add(10, {"Mfuel, kg": 100})
        self.assertEqual(trend.rates()["burn"], 0)

    def test_every_value_has_its_own_log_column(self):
        columns = [alarms.column(name) for name in alarms.SERIES]
        self.assertEqual(len(columns), len(set(columns)))


class Recording(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name) / "logs"
        self.reply = json.dumps(state(**{"TAS, km/h": 700})).encode()
        self.watch = alarms.Watch(lambda path: self.reply if path == "/state" else None, lambda: details(),
                                  save=lambda: None, logs=self.folder)
        self.watch.model = lambda: "j_10c"

    def tearDown(self):
        self.watch.set_log(False)
        self.tmp.cleanup()

    def names(self):
        return {alarms.column(n): n for n in alarms.SERIES}

    def test_not_read_when_nobody_wants_it(self):
        self.watch.get = mock.Mock(return_value=self.reply)
        self.watch.tick()
        self.watch.get.assert_not_called()

    def test_the_tab_being_open_is_enough(self):
        self.watch.viewed = time.monotonic()
        with mock.patch.object(alarms, "beep") as beep:
            self.watch.tick()
        self.assertEqual(self.watch.trace[-1]["ias"], 500)
        self.assertEqual(self.watch.display, [])  # the overlay stays off
        beep.assert_not_called()

    def test_a_reading_a_second(self):
        self.watch.viewed = time.monotonic()
        for _ in range(3):
            self.watch.tick()
        self.assertEqual(len(self.watch.trace), 1)
        self.watch._sampled -= 2 * alarms.SAMPLE_S
        self.watch.tick()
        self.assertEqual([r["n"] for r in self.watch.trace], [1, 2])

    def test_a_log(self):
        self.watch.viewed = time.monotonic()
        self.watch.tick()
        self.watch.set_log(True)
        name = self.watch.log.name
        self.assertTrue(name.startswith("j_10c-"))
        self.watch._sampled -= 2 * alarms.SAMPLE_S
        self.watch.tick()
        self.watch.set_log(False)
        raw = (self.folder / name).read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"), "BOM for Excel")
        self.assertIn('"Time, s","IAS, km/h"', raw.decode("utf-8-sig"))
        rows = flightlog.read_log(self.folder, name, self.names())["rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["ias"], rows[0]["vne"]), (500, 1543))

    def test_recording_is_shown_by_its_line(self):
        self.watch.enabled = True
        self.watch.tick()
        self.assertNotIn("REC", [x[0] for x in self.watch.display])
        self.watch.set_log(True)
        self.watch.tick()
        self.assertIn("REC", [x[0] for x in self.watch.display])

    def test_logs_listed_and_deleted(self):
        self.folder.mkdir()
        for name in ("a.csv", "b.csv"):
            (self.folder / name).write_text("x", encoding="utf-8")
        self.assertEqual({x["name"] for x in flightlog.list_logs(self.folder)}, {"a.csv", "b.csv"})
        self.assertTrue(flightlog.delete_log(self.folder, "a.csv"))
        self.assertFalse(flightlog.delete_log(self.folder, "a.csv"))

    def test_names_from_the_page_stay_in_the_folder(self):
        self.folder.mkdir()
        outside = self.folder.parent / "x.csv"
        outside.write_text("Time, s\n1\n", encoding="utf-8")
        for name in ("../x.csv", "..\\x.csv", "C:/x.csv", "x.txt", ""):
            self.assertIsNone(flightlog.read_log(self.folder, name, {}), name)
            self.assertFalse(flightlog.delete_log(self.folder, name), name)
        self.assertTrue(outside.exists())

    def test_a_broken_log_is_refused(self):
        self.folder.mkdir()
        (self.folder / "bad.csv").write_text('"Time, s"\nabc\n', encoding="utf-8")
        self.assertIsNone(flightlog.read_log(self.folder, "bad.csv", {}))

    def test_a_name_is_made_safe(self):
        log = flightlog.Log(self.folder, "a/b:c", ["x"])
        log.close()
        self.assertTrue(log.name.startswith("a_b_c-"))


class Configuration(unittest.TestCase):
    def test_nothing_saved(self):
        for saved in (None, [], "x", 3):
            self.assertEqual(alarms.clean(saved, WORDS), alarms.defaults(WORDS))

    def test_defaults_scale_with_the_screen(self):
        with mock.patch.object(alarms, "screen", return_value=(3840, 2160)):
            self.assertEqual([alarms.defaults(WORDS)[k] for k in ("x", "y", "size")], [700, 55, 40])
        with mock.patch.object(alarms, "screen", return_value=(1920, 1080)):
            self.assertEqual([alarms.defaults(WORDS)[k] for k in ("x", "y", "size")], [350, 28, 20])

    def test_a_setting_survives_with_the_rest_filled_in(self):
        cfg = alarms.clean({"x": 12, "font": "Segoe UI"}, WORDS)
        self.assertEqual((cfg["x"], cfg["font"], cfg["opacity"]), (12, "Segoe UI", 100))
        self.assertEqual(cfg["lines"][0]["rules"][0]["limit"], "airframe")
        self.assertEqual(cfg["lines"][0]["rules"][0]["at"], 93)

    def test_odd_values_fall_back(self):
        cfg = alarms.clean({"x": "a", "size": True, "font": "x;y{}", "color": "red", "alert": "#12", "bold": 1,
                            "hotkey": ["F1"], "lines": "no", "alarms": {"gear": {"at": "x", "hz": None}}}, WORDS)
        self.assertEqual(cfg, alarms.defaults(WORDS))

    def test_numbers_stay_in_range(self):
        rule = {"limit": "gear", "at": 900, "hz": 1, "ms": 99999, "gap": -5, "repeat": -1, "after": 99999, "color": "red", "blink": ["value", "x"],
                "glow": "yes", "glowSize": 999}
        cfg = alarms.clean({"size": 1, "opacity": 900, "lines": [{"text": "x", "rules": [rule]}]}, WORDS)
        self.assertEqual((cfg["size"], cfg["opacity"]), (6, 100))
        self.assertEqual(cfg["lines"][0]["rules"][0], {"value": "", "op": ">", "at": 200, "join": "and", "more": [], "limit": "gear", "hz": 37,
                                                       "ms": 2000, "sound": "", "red": None, "full": 100, "gap": 0, "color": "",
                                                       "blink": ["value"], "repeat": 0, "after": 10000, "glow": False, "glowSize": 50, "glowFlash": False,
                                                       "flashMs": 0})

    def test_lines_are_limited(self):
        cfg = alarms.clean({"lines": [{"text": "x" * 500, "when": "?", "alarm": "?", "color": "?", "size": -3}, "no"] * 40}, WORDS)
        self.assertEqual(len(cfg["lines"]), alarms.MAX_LINES)
        self.assertEqual(cfg["lines"][0], {"text": "x" * alarms.MAX_TEXT, "when": "always", "color": "", "size": 0, "valueColor": "",
                                           "unitColor": "", "hideNA": False, "block": 0, "if": None, "rules": []})

    def test_no_lines_at_all_is_a_choice(self):
        self.assertEqual(alarms.clean({"lines": []}, WORDS)["lines"], [])

    def test_a_show_hide_key(self):
        cfg = alarms.clean({"hotkey": [17, 123], "hotkeyName": "Ctrl+F12"}, WORDS)
        self.assertEqual((cfg["hotkey"], cfg["hotkeyName"]), ([17, 123], "Ctrl+F12"))
        self.assertEqual(alarms.clean({"hotkey": [1000]}, WORDS)["hotkey"], [])

    def test_every_value_of_the_default_lines_exists(self):
        names = {n for line in alarms.defaults(WORDS)["lines"] for n, _ in alarms.FIELD.findall(line["text"])}
        self.assertLessEqual(names, set(alarms.FIELDS) | set(alarms.COMPUTED) | {"swept"})

    def test_every_value_of_the_page_exists(self):
        page = (alarms.WEB / "overlay.js").read_text(encoding="utf-8")
        names = set(re.findall(r"'(\w+)'", page[page.index("OV_VALUES = {"):page.index("function ovShow")]))
        self.assertTrue(names)
        self.assertLessEqual(names, set(alarms.FIELDS) | set(alarms.COMPUTED) | set(alarms.SAMPLE_STATS) | {"swept", "fuel_time", "wep", "vehicle"})


class Preview(unittest.TestCase):
    def setUp(self):
        self.watch = alarms.Watch(lambda path: None, dict, save=lambda: None)
        self.watch.start_overlay = lambda: None

    def test_sample_lines_show_all_with_an_alarm_on(self):
        lines = self.watch.sample(self.watch.cfg)
        self.assertEqual(len(lines), 4)  # G and AoA show only during their alarm
        alert = self.watch.cfg["alert"]
        self.assertEqual(lines[2], ("GEAR   640 / 700 km/h", alert, self.watch.cfg["size"], False, 0, [("GEAR   640 / 700 km/h", alert, False)]))

    def test_shown_without_the_game_then_taken_off(self):
        self.watch.set_preview(self.watch.cfg)
        self.watch.tick()
        self.assertEqual(self.watch.display, self.watch.sample(self.watch.cfg))
        self.watch.set_preview(None)
        self.watch.tick()
        self.assertEqual(self.watch.display, [])

    def test_shows_the_overlay_being_edited(self):
        self.watch.set_preview(alarms.clean({"lines": [{"text": "hello"}]}, WORDS))
        self.assertEqual(self.watch.display[0][0], "hello")


class VehicleName(unittest.TestCase):
    """{vehicle}: a name in a line, never a number."""
    NAMES = {"j_10c": "J-10C", "su_30mkk": "Su-30MKK", "ussr_t_72b": "T-72B"}

    def setUp(self):
        self.reply = json.dumps(state()).encode()
        self.indicators = b'{"valid": false}'
        self.model = "j_10c"
        self.watch = alarms.Watch(lambda path: self.indicators if path == "/indicators" else self.reply, details, lambda: True,
                                  lambda: None, name=lambda vid: self.NAMES.get(vid, vid))
        self.watch.model = lambda: self.model
        self.watch.enabled = True
        self.line = alarms.clean({"lines": [{"text": "Flying {vehicle} now"}]}, WORDS)
        self.watch.set_config(self.line, {"type:tank": self.line, "type:ship": self.line})
        patcher = mock.patch.object(alarms, "beep")
        self.beep = patcher.start()
        self.addCleanup(patcher.stop)

    def shown(self):
        self.watch.tick()
        return self.watch.display[-1][0]

    def test_a_recognised_aircraft_by_its_name(self):
        self.assertEqual(self.shown(), "Flying J-10C now")

    def test_what_the_game_reports_comes_first(self):
        self.indicators = b'{"valid": true, "army": "air", "type": "su_30mkk"}'
        self.assertEqual(self.shown(), "Flying Su-30MKK now")

    def test_a_custom_vehicle_keeps_its_real_vehicle_s_name(self):
        self.indicators = b'{"valid": true, "army": "air", "type": "wtftd_custom"}'
        self.watch.mission = {"id": "j_10c", "fuel": None, "unbreakable": False}
        self.assertEqual(self.shown(), "Flying J-10C now")

    def test_not_recognised_gives_the_game_s_id(self):
        self.indicators, self.model = b'{"valid": true, "army": "air", "type": "some_new_plane"}', None
        self.reply = json.dumps(state(**{"Mfuel0, kg": 1234})).encode()
        self.assertEqual(self.shown(), "Flying some_new_plane now")
        self.assertEqual(self.watch.display[0][0], "AIRCRAFT UNKNOWN")

    def test_nothing_known_says_no_value(self):
        for indicators in (b'{"valid": false}', b'{"valid": true, "army": "air", "type": ""}', b'{"valid": true, "army": "air", "type": 7}'):
            self.indicators, self.model, self.watch._key = indicators, None, None
            self.reply = json.dumps(state(**{"Mfuel0, kg": 1234})).encode()
            self.assertEqual(self.shown(), "Flying N/A now", indicators)
        self.beep.assert_not_called()

    def test_a_tank_or_a_ship_without_its_folder(self):
        self.reply = b'{"valid": false}'
        self.indicators = b'{"valid": true, "army": "tank", "type": "tankModels/ussr_t_72b", "speed": 41.0}'
        self.assertEqual(self.shown(), "Flying T-72B now")
        self.indicators = b'{"valid": true, "army": "ship", "type": "ship_nobody_knows", "speed": 12.0}'
        self.assertEqual(self.shown(), "Flying ship_nobody_knows now")
        self.indicators = b'{"valid": true, "army": "tank", "speed": 41.0}'
        self.assertEqual(self.shown(), "Flying N/A now")

    def test_the_preview_shows_an_example(self):
        self.assertEqual(self.watch.sample(self.line)[0][0], "Flying Su-30MKK now")
        self.assertEqual(alarms.Watch(None, dict).sample(self.line)[0][0], f"Flying {alarms.SAMPLE_VEHICLE} now")  # no data yet

    def test_a_long_name_keeps_its_line_and_its_column(self):
        cfg = alarms.clean({"lines": [{"text": "{vehicle}", "block": 0}, {"text": "IAS {ias}"}, {"text": "{vehicle}"}], "columns": 2}, WORDS)
        values = {"vehicle": "Pz.Kpfw. VI Ausf. B Tiger II (H)", "IAS, km/h": 640}
        lines = alarms.lines_for(cfg, values, [])
        self.assertEqual([x[0] for x in lines], ["Pz.Kpfw. VI Ausf. B Tiger II (H)", "IAS 640", "Pz.Kpfw. VI Ausf. B Tiger II (H)"])
        self.assertEqual([len(c) for c in alarms.columns_of(lines, cfg["columns"])], [2, 1])

    def test_its_colour_is_a_value_s(self):
        self.assertEqual(alarms.pieces("In {vehicle}!", {"vehicle": "T-72B"}), [("In ", "name"), ("T-72B", "value"), ("!", "unit")])

    def test_places_change_nothing(self):
        self.assertEqual(alarms.fill("{vehicle:2}", {"vehicle": "T-72B"}), "T-72B")

    def test_a_condition_on_it_never_holds_and_never_breaks(self):
        rule = {"value": "vehicle", "op": ">", "at": 1}
        self.assertFalse(alarms.met(rule, {"vehicle": "T-72B"}))
        self.assertEqual(alarms.lines_for(alarms.clean({"lines": [{"text": "x", "if": rule}]}, WORDS), {"vehicle": "T-72B"}, []), [])

    def test_a_missing_name_can_hide_its_line(self):
        cfg = alarms.clean({"lines": [{"text": "{vehicle}", "hideNA": True}]}, WORDS)
        self.assertEqual(alarms.lines_for(cfg, {}, []), [])

    def test_stays_out_of_curves_and_logs(self):
        self.assertNotIn("vehicle", alarms.SERIES)
        self.watch.tick()
        self.assertNotIn("vehicle", self.watch.last)
        self.assertNotIn("vehicle", self.watch.trace[-1])

    def test_not_in_the_default_lines(self):
        self.assertFalse(any("{vehicle}" in line["text"] for line in alarms.defaults(WORDS)["lines"]))

    def test_the_page_offers_it_for_lines_only(self):
        script = (alarms.WEB / "overlay.js").read_text(encoding="utf-8")
        self.assertLess(script.index("vehicle: ['vehicle']"), script.index("speed: ["))
        self.assertIn("'wep', 'vehicle'].includes(x)", script)  # no number to compare in a condition
        self.assertIn("group !== 'vehicle'", (alarms.WEB / "flight.js").read_text(encoding="utf-8"))  # nor to draw in a curve

    def test_every_language_has_its_labels(self):
        for code in ("en", "fr", "de", "es", "it", "pt", "pl", "cs", "ru", "ja", "zh"):
            words = json.loads((alarms.WEB / "locales" / f"{code}.json").read_text(encoding="utf-8"))
            self.assertTrue(words["ov.g.vehicle"] and words["ov.v.vehicle"], code)


class NamesOfTheApp(unittest.TestCase):
    """What the server gives the Watch: the names I18N.unit gives on the page, in the app's language."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.data = Path(folder.name)
        (self.data / "lang").mkdir()
        self.write("en", {"su_30mkk": "Su-30MKK", "ussr_t_72b": "T-72B"})
        self.write("fr", {"ussr_t_72b": "T-72 B"})  # the build leaves out what's the same as in English
        self.lang = "fr"
        for patcher in (mock.patch.object(server, "DATA", self.data), mock.patch.object(server.STATE, "units", None),
                        mock.patch.object(server.STATE, "settings", lambda: {"lang": self.lang})):
            patcher.start()
            self.addCleanup(patcher.stop)

    def write(self, code: str, units: dict):
        (self.data / "lang" / f"{code}.json").write_text(json.dumps({"units": units}), encoding="utf-8")

    def test_the_language_then_english_then_the_id(self):
        self.assertEqual([server.WATCH.vehicle(x) for x in ("ussr_t_72b", "su_30mkk", "new_plane")], ["T-72 B", "Su-30MKK", "new_plane"])

    def test_a_language_without_names_is_english(self):
        for self.lang in ("xx", "../../secrets", "a\0b", None, 7):
            server.STATE.units = None
            self.assertEqual(server.STATE.unit_name("ussr_t_72b"), "T-72B", self.lang)

    def test_no_data_yet(self):
        (self.data / "lang" / "en.json").unlink()
        (self.data / "lang" / "fr.json").unlink()
        self.assertEqual(server.STATE.unit_name("ussr_t_72b"), "ussr_t_72b")

    def test_files_are_read_once_not_at_every_reading(self):
        with mock.patch.object(server, "read_json", wraps=server.read_json) as read:
            for _ in range(5):
                server.STATE.unit_name("ussr_t_72b")
        self.assertEqual(read.call_count, 2)

    def test_a_new_language_is_followed(self):
        self.assertEqual(server.STATE.unit_name("ussr_t_72b"), "T-72 B")
        self.lang = "en"
        self.addCleanup(server.apply_alarm_settings)  # the Watch as it was, once the language is back to English
        server.apply_alarm_settings()
        self.assertEqual(server.STATE.unit_name("ussr_t_72b"), "T-72B")

    def test_new_data_is_followed(self):
        self.assertEqual(server.STATE.unit_name("new_plane"), "new_plane")
        self.write("en", {"new_plane": "New Plane"})
        server.STATE.reload()
        self.assertEqual(server.STATE.unit_name("new_plane"), "New Plane")


class Profiles(unittest.TestCase):
    def setUp(self):
        self.jet = alarms.clean({"lines": [{"text": "J-10"}]}, WORDS)
        self.fighters = alarms.clean({"lines": [{"text": "fighter"}]}, WORDS)
        self.reply = json.dumps(state()).encode()
        self.indicators = b'{"valid": true, "type": "j_10c"}'
        kinds = {"j_10c": "fighter", "j_10a": "fighter", "su_30mkk": "bomber"}
        self.watch = alarms.Watch(lambda path: self.indicators if path == "/indicators" else self.reply, details,
                                  save=lambda: None, kind=kinds.get)
        self.watch.enabled = True
        self.watch.start_overlay = lambda: None

    def texts(self):
        return [x[0] for x in self.watch.display]

    def test_the_aircraft_s_own_comes_first(self):
        self.watch.set_config(self.watch.base, {"j_10c": self.jet, "type:fighter": self.fighters})
        self.watch.tick()
        self.assertEqual((self.watch.current, self.watch.profile, self.texts()), ("j_10c", "j_10c", ["J-10"]))

    def test_then_its_type(self):
        self.watch.set_config(self.watch.base, {"type:fighter": self.fighters})
        self.watch.tick()
        self.assertEqual((self.watch.profile, self.texts()), ("type:fighter", ["fighter"]))

    def test_then_the_one_for_all_aircraft(self):
        self.watch.set_config(self.watch.base, {"su_30mkk": self.jet, "type:bomber": self.fighters})
        self.watch.tick()
        self.assertEqual(self.watch.profile, "")
        self.assertEqual(self.texts()[0], "IAS    500 / 1543 km/h")

    def test_alarms_are_the_profile_s_too(self):
        self.watch.set_config(self.watch.base, {"j_10c": airframe(at=30, hz=500, ms=80)})
        with mock.patch.object(alarms, "beep") as beep:
            self.watch.tick()
        beep.assert_called_once_with(500, 80, 100)

    def test_back_in_the_hangar(self):
        self.watch.set_config(self.watch.base, {"j_10c": self.jet})
        self.watch.tick()
        self.reply = b'{"valid": false}'
        self.watch.tick()
        self.assertEqual((self.watch.current, self.watch.profile, self.watch.cfg), (None, "", self.watch.base))

    def test_changed_while_flying(self):
        self.watch.tick()
        self.watch.set_config(self.watch.base, {"j_10c": self.jet})
        self.watch.tick()
        self.assertEqual(self.texts(), ["J-10"])

    def test_profile_names(self):
        for good in ("j_10c", "a-20g", "type:fighter"):
            self.assertTrue(alarms.PROFILE.fullmatch(good), good)
        for bad in ("", "../x", "a b", "type:", "x:y"):
            self.assertFalse(alarms.PROFILE.fullmatch(bad), bad)


class Battle(unittest.TestCase):
    def get(self, path):
        self.asked.append(path)
        return self.answers.get(path.split("?")[0])

    def setUp(self):
        self.asked = []
        self.answers = {
            "/gamechat": json.dumps([{"id": 7, "msg": "<color=#ff0000>hi</color> <b>there", "sender": "Bob\ue001", "enemy": True,
                                      "mode": "All", "time": 12}]).encode(),
            "/hudmsg": json.dumps({"events": [], "damage": [{"id": 3, "msg": "=FrEB= Pilot (\u2417Su-30MKK) s'est \u00e9cras\u00e9.",
                                                             "sender": "", "enemy": False, "mode": "", "time": 1417}]}).encode()}

    def test_asks_after_the_page_s_last_look(self):
        battle.news(self.get, 7, 2, 3)
        self.assertEqual(self.asked, ["/gamechat?lastId=7", "/hudmsg?lastEvt=2&lastDmg=3"])

    def test_text_comes_clean(self):
        out = battle.news(self.get, 0, 0, 0)
        self.assertEqual(out["chat"], [{"id": 7, "time": 12, "text": "hi there", "sender": "Bob", "enemy": True, "mode": "All"}])
        self.assertEqual(out["damage"][0]["text"], "=FrEB= Pilot (Su-30MKK) s'est \u00e9cras\u00e9.")
        self.assertTrue(out["up"])

    def test_game_closed(self):
        self.answers = {}
        self.assertEqual(battle.news(self.get, 1, 2, 3), {"up": False, "chat": [], "events": [], "damage": []})

    def test_bad_answers(self):
        self.answers = {"/gamechat": b"not json", "/hudmsg": b"[1, 2]"}
        self.assertEqual(battle.news(self.get, 0, 0, 0)["damage"], [])
        self.answers = {"/gamechat": b'{"a": 1}', "/hudmsg": b'{"damage": ["x", 3]}'}
        out = battle.news(self.get, 0, 0, 0)
        self.assertEqual((out["chat"], out["damage"]), ([], []))


class Crash(unittest.TestCase):
    """Numbers recorded on real crashes and hard flying (Su-30MKK, 10 readings a second)."""
    FLYING = {"RPM 1": 13300, "RPM 2": 13300, "throttle 1, %": 110, "throttle 2, %": 110}
    DEAD = {"RPM 1": 0, "RPM 2": 0, "throttle 1, %": 0, "throttle 2, %": 0}

    def setUp(self):
        self.reply = None
        self.watch = alarms.Watch(lambda path: self.reply if path == "/state" else None, details, save=lambda: None)
        self.watch.enabled = True
        self.watch.start_overlay = lambda: None
        self.watch.model = lambda: "j_10c"
        patcher = mock.patch.object(alarms, "beep")
        self.beep = patcher.start()
        self.addCleanup(patcher.stop)

    def fly(self, **fields):
        self.reply = json.dumps(state(**{"throttle 1, %": 110, "RPM 1": 13300, **fields})).encode()
        self.watch.tick()

    def test_into_the_ground(self):  # IAS 151 -> 50
        self.assertTrue(alarms.crashed({**self.FLYING, "IAS, km/h": 151}, {**self.DEAD, "IAS, km/h": 50}))

    def test_speed_is_not_what_tells_it(self):  # IAS 1140 -> 1137: the reading that had the impact
        self.assertTrue(alarms.crashed({**self.FLYING, "IAS, km/h": 1140}, {**self.DEAD, "IAS, km/h": 1137}))

    def test_a_hard_pull_is_no_crash(self):  # 11 G: 40 km/h lost every reading
        self.assertFalse(alarms.crashed({**self.FLYING, "IAS, km/h": 855}, {**self.FLYING, "IAS, km/h": 816, "Ny": 11.3}))

    def test_one_engine_lost_is_no_crash(self):
        self.assertFalse(alarms.crashed(self.FLYING, {**self.DEAD, "RPM 2": 13300, "throttle 2, %": 110}))

    def test_an_engine_shut_down_keeps_winding_down(self):
        self.assertFalse(alarms.crashed(self.FLYING, {**self.DEAD, "RPM 1": 12000, "RPM 2": 12000}))

    def test_a_dead_engine_stopping_is_no_crash(self):  # gliding, throttle closed
        self.assertFalse(alarms.crashed({**self.DEAD, "RPM 1": 300, "RPM 2": 300}, self.DEAD))

    def test_throttle_closed_with_the_engine_stopped_by_the_game(self):
        self.assertFalse(alarms.crashed(self.FLYING, {**self.FLYING, "RPM 1": 0, "RPM 2": 0}))

    def test_nothing_to_compare_with(self):
        self.assertFalse(alarms.crashed(None, self.DEAD))
        self.assertFalse(alarms.crashed({}, self.DEAD))
        self.assertFalse(alarms.crashed(self.FLYING, {}))

    def test_beeps_stop_in_the_wreck(self):
        self.fly(**{"IAS, km/h": 1500})
        self.assertEqual(self.beep.call_count, 1)
        self.watch._last_beep = 0
        self.fly(**{"IAS, km/h": 1500, "throttle 1, %": 0, "RPM 1": 0})
        self.assertTrue(self.watch.crash)
        self.assertEqual(self.beep.call_count, 1)
        self.assertNotIn(self.watch.cfg["alert"], [x[1] for x in self.watch.display])

    def test_the_overlay_stays_unless_asked(self):
        self.fly()
        self.fly(**{"throttle 1, %": 0, "RPM 1": 0})
        self.assertTrue(self.watch.display)
        self.watch.set_config(alarms.clean({"hideCrash": True}, WORDS), {})
        self.fly(**{"throttle 1, %": 0, "RPM 1": 0})
        self.assertTrue(self.watch.crash)
        self.assertEqual(self.watch.display, [])

    def test_the_next_spawn_ends_it(self):
        self.fly()
        self.fly(**{"throttle 1, %": 0, "RPM 1": 0})
        self.fly(**{"throttle 1, %": 0, "RPM 1": 0, "IAS, km/h": 40})
        self.assertTrue(self.watch.crash)
        self.fly(**{"throttle 1, %": 100, "RPM 1": 13008, "IAS, km/h": 527})
        self.assertFalse(self.watch.crash)

    def test_a_wreck_at_rest_ends_it(self):  # IAS 0: /state stops counting as flying
        self.fly()
        self.fly(**{"throttle 1, %": 0, "RPM 1": 0})
        self.fly(**{"throttle 1, %": 0, "RPM 1": 0, "IAS, km/h": 0})
        self.assertFalse(self.watch.crash)
        self.assertEqual(self.watch.display, [])

    def test_recording_goes_on(self):
        self.watch.viewed = time.monotonic()
        self.fly()
        self.watch._sampled -= 2 * alarms.SAMPLE_S
        self.fly(**{"throttle 1, %": 0, "RPM 1": 0})
        self.assertEqual(len(self.watch.trace), 2)


class BattleLog(unittest.TestCase):
    """Real lines of the battle log: the only sign of a break-up in the air, engines still running."""
    WORDS = ["hascrashed.", "s'estécrasé.", "разбился"]
    MINE = "=FrEB= StonewarP (\u2417Su-30MKK) s'est \u00e9cras\u00e9."
    OTHER = "=XX= Wingman (\u2417Su-30MKK) s'est \u00e9cras\u00e9."

    def setUp(self):
        self.reply, self.log = json.dumps(state(**{"RPM 1": 13300, "IAS, km/h": 1500})).encode(), []
        self.watch = alarms.Watch(self.get, details, save=lambda: None, crash_words=lambda: self.WORDS)
        self.watch.enabled = True
        self.watch.start_overlay = lambda: None
        self.watch.model = lambda: "j_10c"
        patcher = mock.patch.object(alarms, "beep")
        self.beep = patcher.start()
        self.addCleanup(patcher.stop)
        for _ in range(alarms.LOG_EVERY):  # the first look at the log only sets where it starts
            self.watch.tick()
        self.beep.reset_mock()

    def get(self, path):
        if path.startswith("/hudmsg"):
            after = int(path.rsplit("=", 1)[1])
            return json.dumps({"events": [], "damage": [{"id": n, "msg": m, "sender": "", "enemy": False, "mode": "", "time": n}
                                                        for n, m in enumerate(self.log, 1) if n > after]}).encode()
        return self.reply if path == "/state" else None

    def look(self):
        for _ in range(alarms.LOG_EVERY):
            self.watch._last_beep = 0
            self.watch.tick()

    def test_the_line(self):
        self.assertEqual(alarms.crash_name(alarms.battle.clean(self.MINE), self.WORDS), "=FrEB= StonewarP")
        self.assertEqual(alarms.crash_name("Bob (Yak-9) разбился", self.WORDS), "Bob")

    def test_other_lines(self):
        for line in ("Surchauffe du moteur", "MiG-29 abattu =FrEB= StonewarP", "s'est \u00e9cras\u00e9.", ""):
            self.assertIsNone(alarms.crash_name(line, self.WORDS), line)

    def test_the_name_comes_with_an_impact(self):
        self.log = [self.OTHER]
        self.look()
        self.assertIsNone(self.watch.pilot)  # no impact of ours: not us
        self.reply = json.dumps(state(**{"RPM 1": 0, "throttle 1, %": 0, "IAS, km/h": 300})).encode()
        self.watch.tick()
        self.assertTrue(self.watch.crash)
        self.log.append(self.MINE)
        self.look()
        self.assertEqual(self.watch.pilot, "=FrEB= StonewarP")

    def learnt(self):
        self.watch.pilot = "=FrEB= StonewarP"

    def test_break_up_in_the_air_stops_the_beeps(self):
        self.learnt()
        self.look()
        self.assertTrue(self.beep.called)
        self.beep.reset_mock()
        self.log.append(self.MINE)
        self.look()
        self.beep.reset_mock()
        self.look()
        self.beep.assert_not_called()

    def test_the_replays_give_the_name_before_any_crash(self):
        self.watch.past = {"pilot": "StonewarP"}  # without the clan's tag, which can change
        self.log.append(self.OTHER)
        self.look()
        self.assertTrue(self.beep.called)  # somebody else's crash silences nothing
        self.log.append(self.MINE)
        self.look()
        self.beep.reset_mock()
        self.look()
        self.beep.assert_not_called()

    def test_a_replay_name_that_differs_from_the_log_loses_nothing(self):
        self.watch.past = {"pilot": "StonewarP@steam"}
        self.learnt()
        self.log.append(self.MINE)
        self.look()
        self.beep.reset_mock()
        self.look()
        self.beep.assert_not_called()

    def test_it_lasts_until_the_next_spawn_at_most(self):
        self.learnt()
        self.log.append(self.MINE)
        self.look()
        self.watch._silent = time.monotonic() - 1
        self.beep.reset_mock()
        self.look()
        self.assertTrue(self.beep.called)

    def test_somebody_else_s_crash_changes_nothing(self):
        self.learnt()
        self.log.append(self.OTHER)
        self.beep.reset_mock()
        self.look()
        self.assertTrue(self.beep.called)

    def test_nothing_before_the_name_is_known(self):
        self.log.append(self.MINE)
        self.beep.reset_mock()
        self.look()
        self.assertTrue(self.beep.called)

    def test_old_lines_don_t_count(self):
        self.log = [self.MINE] * 3
        self.watch._log_id = None
        self.learnt()
        self.beep.reset_mock()
        self.look()
        self.assertTrue(self.beep.called)


class Pitch(unittest.TestCase):
    def test_nose_up_reads_positive(self):  # the game said -7.4 at 8.1 of path angle, -0.7 of angle of attack
        self.assertEqual(alarms.numbers(alarms.read_indicators(b'{"valid": true, "aviahorizon_pitch": -7.4}'))["pitch"], 7.4)

    def test_no_pitch(self):
        self.assertNotIn("pitch", alarms.numbers(alarms.read_indicators(b'{"valid": false}')))


class Labels(unittest.TestCase):
    def test_every_language_has_every_word(self):
        en = alarms.labels("en")
        self.assertEqual(set(en), {"gear", "flaps", "swept", "unknown", "unbreakable", "booster", "mass"})
        for path in Path(alarms.WEB / "locales").glob("*.json"):
            if path.stem != "index":
                self.assertEqual(set(alarms.labels(path.stem)), set(en), path.stem)

    def test_unknown_language_falls_back_to_english(self):
        self.assertEqual(alarms.labels("xx")["gear"], "GEAR")
        self.assertEqual(alarms.labels("../secrets")["gear"], "GEAR")

    def test_translated(self):
        self.assertEqual(alarms.labels("fr")["gear"], "TRAIN")


if __name__ == "__main__":
    unittest.main()
