import unittest

from corpus_atelier.design.canvas import reduce_ratio, resolve_canvas, resolve_image_size


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

    def test_fixed_ratio_must_match_designer_proposal(self):
        image_spec = {"canvas_plan": {
            "format": "mobile poster",
            "orientation": "portrait",
            "aspect_ratio": {"width": 4, "height": 5},
            "viewing_context": "phone",
            "safe_area": "central 80%",
            "size_rationale": "mobile feed",
        }}
        brief = {"canvas": {
            "mode": "fixed", "aspect_ratio": {"width": 1, "height": 1},
        }}
        with self.assertRaisesRegex(ValueError, "user-fixed ratio"):
            resolve_canvas(image_spec, brief)


if __name__ == "__main__":
    unittest.main()
