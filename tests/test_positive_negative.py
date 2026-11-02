"""Positive/negative prompt structuring from an image specification."""

import unittest

from corpus_atelier.atelier.image_prompt.prompt_compiler import (
    compile_generation_prompt,
    compile_positive_negative,
)


class PositiveNegativeTests(unittest.TestCase):
    def test_splits_scene_and_copy_into_positive(self):
        positive, _ = compile_positive_negative({
            "subject_and_scene": "A red fox standing in snow",
            "composition": "Fox on the right third",
            "typography": "Sans-serif title at top-left",
            "visual_treatment": "Painterly, soft rim light",
            "visible_copy": ["WINTER", "DEC 2026"],
            "exclusions": ["photorealistic"],
        })
        self.assertIn("A red fox standing in snow", positive)
        self.assertIn("WINTER | DEC 2026", positive)

    def test_exclusions_become_negative(self):
        _, negative = compile_positive_negative({
            "subject_and_scene": "scene",
            "composition": "comp",
            "typography": "type",
            "visual_treatment": "treat",
            "visible_copy": [],
            "exclusions": ["photorealistic", "readable text other than copy"],
        })
        self.assertIn("photorealistic", negative)
        self.assertIn("readable text other than copy", negative)

    def test_empty_exclusions_give_empty_negative(self):
        _, negative = compile_positive_negative({
            "subject_and_scene": "scene",
            "composition": "comp",
            "typography": "type",
            "visual_treatment": "treat",
            "visible_copy": [],
            "exclusions": [],
        })
        self.assertEqual(negative, "")

    def test_generation_prompt_has_both_sections(self):
        spec = {
            "subject_and_scene": "scene",
            "composition": "comp",
            "typography": "type",
            "visual_treatment": "treat",
            "visible_copy": [],
            "exclusions": ["photorealistic"],
        }
        prompt = compile_generation_prompt(spec)
        self.assertIn("# Positive prompt", prompt)
        self.assertIn("# Negative prompt", prompt)
        self.assertIn("# Approved image specification", prompt)
        self.assertIn("photorealistic", prompt)

    def test_generation_prompt_negative_placeholder(self):
        spec = {
            "subject_and_scene": "scene",
            "composition": "comp",
            "typography": "type",
            "visual_treatment": "treat",
            "visible_copy": [],
            "exclusions": [],
        }
        prompt = compile_generation_prompt(spec)
        self.assertIn("(none)", prompt)


if __name__ == "__main__":
    unittest.main()
