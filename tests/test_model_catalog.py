import unittest

from corpus_atelier.model_catalog import (
    IMAGE_MODEL_PROFILES,
    TEXT_MODEL_PROFILES,
    get_image_model_profile,
    get_text_model_profile,
    validate_reasoning_effort,
)


class ModelCatalogTests(unittest.TestCase):
    def test_openai_models_are_allow_listed(self):
        self.assertEqual(
            [profile.model for profile in TEXT_MODEL_PROFILES],
            ["gpt-5.6-luna", "gpt-6-sol", "gpt-6-astra"],
        )
        self.assertEqual(get_text_model_profile("gpt-6-sol").label, "GPT-6 Sol")

    def test_openai_image_models_are_allow_listed_with_image_2_as_default(self):
        self.assertEqual(
            [profile.model for profile in IMAGE_MODEL_PROFILES],
            [
                "gpt-image-2",
                "gpt-image-2.5-sunburst",
                "gpt-image-2.5-flare",
            ],
        )
        self.assertEqual(
            get_image_model_profile("gpt-image-2").label,
            "GPT Image 2",
        )

    def test_unknown_model_and_effort_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported OpenAI text model"):
            get_text_model_profile("arbitrary-model")
        with self.assertRaisesRegex(ValueError, "Unsupported reasoning effort"):
            validate_reasoning_effort("gpt-6-sol", "unbounded")
        with self.assertRaisesRegex(ValueError, "Unsupported OpenAI image model"):
            get_image_model_profile("arbitrary-image-model")


if __name__ == "__main__":
    unittest.main()
