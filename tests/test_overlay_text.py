"""The overlay's text painted by GDI+ (Windows): laid out as the Tk overlay was, smooth letters with a dark halo when no
outline is set, see-through backgrounds, blinking lines; no window, into memory."""
import sys
import unittest

from tests.test_alarms import WORDS
from wtftd import alarms


def line(text, color="#E6E6E6", size=40, blinks=False, block=0, parts=None):
    return (text, color, size, blinks, block, parts or [(text, color)])


@unittest.skipUnless(sys.platform == "win32", "Windows")
class Text(unittest.TestCase):
    def setUp(self):
        from wtftd import mappaint
        self.painter = mappaint.Painter()
        self.cfg = {**alarms.clean({}, WORDS), "x": 100, "y": 50, "font": "Consolas", "bold": True, "outline": 0}

    def alpha(self, px, box, x, y):
        return px[((y - box[1]) * box[2] + (x - box[0])) * 4 + 3]

    def test_spaces_count_and_parts_follow_each_other(self):
        parts, _ = self.painter.text_layout(self.cfg, [line("IAS    771", parts=[("IAS    ", "#E6E6E6"), ("771", "#FF0000")])])
        (x0, _, a, *_), (x1, _, b, *_) = parts
        self.assertEqual((a, b), ("IAS    ", "771"))
        self.assertGreater(x1 - x0, 6 * 18)  # 7 characters of a 40 px Consolas: the spaces are kept

    def test_columns_and_lines_go_down(self):
        cfg = {**self.cfg, "blocks": [], "columns": 2}
        parts, boxes = self.painter.text_layout(cfg, [line("A"), line("B"), line("C")])
        ys = [p[1] for p in parts]
        self.assertEqual(ys[0], ys[2])  # C starts the second column, at the top
        self.assertGreater(ys[1], ys[0])
        self.assertGreater(parts[2][0], parts[0][0])
        self.assertEqual(len(boxes), 1)

    def test_a_dark_halo_round_light_text(self):
        px, box = self.painter.text_pixels(self.cfg, [line("I")])
        alphas = [self.alpha(px, box, x, y) for y in range(box[1], box[1] + box[3]) for x in range(box[0], box[0] + box[2])]
        self.assertTrue(any(a == 255 for a in alphas))  # the letter
        dark = [px[i:i + 3] for i in range(0, len(px), 4) if 100 < px[i + 3] < 255 and max(px[i:i + 3]) < 60]
        self.assertTrue(dark)  # the halo: dark and partly see-through

    def test_an_outline_instead_of_the_halo(self):
        px, _ = self.painter.text_pixels({**self.cfg, "outline": 2, "outlineColor": "#FF0000"}, [line("I")])
        reds = [i for i in range(0, len(px), 4) if px[i + 2] > 200 and px[i] < 40 and px[i + 3] > 200]  # B, G, R, A
        self.assertTrue(reds)

    def test_a_see_through_background(self):
        cfg = {**self.cfg, "background": "#000000", "bgOpacity": 50}
        px, box = self.painter.text_pixels(cfg, [line("I")])
        self.assertIn(self.alpha(px, box, 100 - 8, 50 - 8), range(120, 136))  # inside the padding: half see-through

    def test_a_flashing_part_out_of_its_turn_keeps_its_place_in_another_colour(self):
        lines = [line("W", parts=[("W", "#FF0000", True, "#00FF00")])]
        lit, box = self.painter.text_pixels(self.cfg, lines, True)
        dark, box2 = self.painter.text_pixels(self.cfg, lines, False)
        self.assertEqual(box, box2)
        self.assertEqual([i for i in range(3, len(lit), 4) if lit[i]], [i for i in range(3, len(dark), 4) if dark[i]])  # the same pixels
        self.assertNotEqual(lit, dark)  # in another colour

    def test_a_blinking_line_out_of_its_turn(self):
        lines = [line("W", blinks=True)]
        lit, box = self.painter.text_pixels(self.cfg, lines, True)
        dark, _ = self.painter.text_pixels(self.cfg, lines, False)
        self.assertGreater(max(lit[3::4]), 0)
        self.assertEqual(max(dark[3::4]), 0)

    def test_nothing_to_show(self):
        self.assertIsNone(self.painter.text_box(self.cfg, []))


if __name__ == "__main__":
    unittest.main()
