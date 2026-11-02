"""Reverse prompt extraction from a reference image."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from corpus_atelier.atelier.reverse_prompt import reverse_prompt, reverse_prompt_instruction
from tests.fakes import FakeTextProvider


class ReversePromptTests(unittest.TestCase):
    def test_extracts_positive_and_negative(self):
        with TemporaryDirectory() as directory:
            image = Path(directory) / "reference.png"
            Image.new("RGB", (8, 8), "white").save(image)
            provider = FakeTextProvider()
            result, record = reverse_prompt(provider, image)

        self.assertTrue(result["positive_prompt"])
        self.assertTrue(result["negative_prompt"])
        self.assertEqual(record["status"], "completed")

    def test_passes_the_reference_image_through(self):
        with TemporaryDirectory() as directory:
            image = Path(directory) / "reference.png"
            Image.new("RGB", (8, 8), "white").save(image)
            provider = FakeTextProvider()
            reverse_prompt(provider, image)

        call = provider.design_calls[-1]
        self.assertEqual(call["schema_name"], "reverse-prompt.schema.json")
        self.assertEqual([p.name for p in call["reference_paths"]], ["reference.png"])

    def test_instruction_asks_for_standalone_prompts(self):
        text = reverse_prompt_instruction()
        self.assertIn("positive prompt", text)
        self.assertIn("negative prompt", text)
        self.assertIn("stand alone", text)


if __name__ == "__main__":
    unittest.main()
