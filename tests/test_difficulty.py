"""A mission's own difficulty: the game's presets read by the builder, the player's changes checked by the server."""
import json
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path
from unittest import mock

from wtftd import blk, builder, mission

AIR = {"baseDifficulty": 1, "realGunnery": 1, "hudAimPrediction": False, "limitViews": 0, "hudMarkers": 2, "ctaCaptureMul": 1}
DATA = {"presets": {"air": {"realistic": AIR}}, "options": [{"k": "realGunnery", "n": 0}, {"k": "hudAimPrediction", "n": 0},
                                                            {"k": "limitViews", "n": 3}, {"k": "hudMarkers", "n": 4}]}


class Builder(unittest.TestCase):
    def test_presets_by_kind_and_labels_from_the_game(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        dm, data = Path(tmp.name) / "dm", Path(tmp.name) / "data"
        (dm / "aces.vromfs.bin_u" / "config").mkdir(parents=True)
        data.mkdir()
        presets = {name: dict(AIR, baseDifficulty=i) for i, name in enumerate(builder.DIFFICULTIES)}
        tanks = {f"tank_{name}": dict(p, hudMarkers=1) for name, p in presets.items()}
        (dm / "aces.vromfs.bin_u" / "config" / "gameparams.blkx").write_text(json.dumps(
            {"difficulty_presets": presets, "custom_difficulty": {**tanks, "ship_arcade": presets["arcade"]}}), encoding="utf-8")
        lang = builder.Lang.__new__(builder.Lang)
        lang.all = {"options/hudMarkers": {"en": "Markers"}, "options/ally": {"en": "Ally", "fr": "Allié"},
                    "mainmenu/fullRealInstantAction": {"en": "Simulator Battles", "fr": "Simulateur"}}
        lang.lower, lang.out = {k.lower(): k for k in lang.all}, defaultdict(dict)
        with mock.patch.object(builder, "DM", dm), mock.patch.object(builder, "DATA", data):
            out = builder.build_difficulty(lang)
        self.assertEqual(out["presets"]["tank"]["realistic"]["hudMarkers"], 1)
        self.assertEqual(out["presets"]["ship"]["hardcore"], presets["hardcore"])  # no ship_hardcore in the game: the aircraft one
        # only the settings every preset has, with their number of values (0: on/off)
        self.assertEqual(out["options"], [{"k": "realGunnery", "n": 0}, {"k": "limitViews", "n": 3}, {"k": "hudAimPrediction", "n": 0}, {"k": "hudMarkers", "n": 4}])
        self.assertEqual(lang.out["difficulty"]["hudMarkers"], {"en": "Markers"})
        self.assertEqual(lang.out["difficulty"]["hudMarkers.3"], {"en": "Ally (Simulator Battles)", "fr": "Allié (Simulateur)"})
        self.assertEqual(json.loads((data / "difficulty.json").read_text(encoding="utf-8")), out)


class Block(unittest.TestCase):
    def block(self, changes, data=DATA):
        with mock.patch.object(mission, "_difficulty_data", return_value=data):
            return mission.difficulty_block("realistic", changes, "air")

    def test_changes_are_checked_against_the_games_window(self):
        out = self.block({"hudAimPrediction": True, "realGunnery": False, "limitViews": 2, "hudMarkers": 9, "ctaCaptureMul": 0, "x": 1})
        self.assertIs(out["hudAimPrediction"], True)
        self.assertEqual(out["realGunnery"], 0)  # an on/off setting the game writes 0/1 stays a number
        self.assertIs(type(out["realGunnery"]), int)
        self.assertEqual(out["limitViews"], 2)
        self.assertEqual(out["hudMarkers"], 2)  # out of range: the preset's
        self.assertEqual(out["ctaCaptureMul"], 1)  # not in the game's window
        self.assertNotIn("x", out)
        self.assertEqual(out["setDifficulty"], 3)
        self.assertEqual(self.block("junk")["limitViews"], 0)

    def test_none_without_the_data(self):
        self.assertIsNone(self.block({}, data=None))
        self.assertIsNone(self.block({}, data={"presets": {"tank": {}}}))


class Mission(unittest.TestCase):
    def build(self, data):
        bare = builder._hangar_mission("air_archipelago", "armada", [0.0, 1500.0, 0.0], "WTFTD", speed=450.0)
        with mock.patch.object(mission, "load_scenario", return_value=bare), mock.patch.object(mission, "_difficulty_data", return_value=data):
            _, text = mission.build({"scenario": "free_air_archipelago_air", "vehicle": "bf-109f-4", "block": "armada", "difficulty": "realistic",
                                     "difficultySettings": {"hudAimPrediction": True, "limitViews": 2}})
        return blk.loads(text)["mission_settings"]["mission"]

    def test_the_mission_carries_its_difficulty(self):
        m = self.build(DATA)
        self.assertEqual((m["difficulty"], m["openDiffLevels"]), ("custom", False))  # the game's briefing no longer asks
        self.assertEqual({k: m["netDifficultyBlk"][k] for k in ("baseDifficulty", "hudAimPrediction", "limitViews", "setDifficulty")},
                         {"baseDifficulty": 1, "hudAimPrediction": True, "limitViews": 2, "setDifficulty": 3})

    def test_old_data_names_it_only(self):
        m = self.build(None)
        self.assertEqual(m["difficulty"], "realistic")
        self.assertNotIn("netDifficultyBlk", m)


if __name__ == "__main__":
    unittest.main()
