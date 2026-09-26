import unittest

from corpus_atelier.design_support.canvas import reduce_ratio, resolve_canvas, resolve_image_size


class CanvasTests(unittest.TestCase):
    def test_common_ratios_resolve_to_exact_supported_sizes(self):
        for ratio in ((2, 3), (4, 5), (47, 20), (1, 1)):
            size, reduced = resolve_image_size(ratio)
            width, height = (int(value) for value in size.split("x"))
            self.assertEqual(width % 16, 0)
            self.assertEqual(height % 16, 0)
            self.assertLessEqual(max(width, height), 3840)
            self.assertGreaterEqual(width * height, 655_360)
            self.assertLessEqual(width * height, 8_294_400)
            self.assertEqual(width * reduced[1], height * reduced[0])

    def test_ratio_is_reduced_and_extreme_ratio_is_rejected(self):
        self.assertEqual(reduce_ratio(8, 10), (4, 5))
        with self.assertRaisesRegex(ValueError, "between 1:3 and 3:1"):
            reduce_ratio(4, 1)

    def test_canvas_is_resolved_from_the_brief(self):
        brief = {"canvas": {"aspect_ratio": {"width": 8, "height": 10}}}
        size, ratio, record = resolve_canvas(brief)
        self.assertEqual(ratio, (4, 5))
        self.assertEqual(record, {"size": size, "ratio": [4, 5], "source": "brief"})

    def test_canvas_requires_a_brief_ratio(self):
        with self.assertRaisesRegex(ValueError, "requires a canvas aspect ratio"):
            resolve_canvas({"canvas": {}})


if __name__ == "__main__":
    unittest.main()
