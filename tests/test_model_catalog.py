import unittest

from corpus_atelier.model_catalog import (
    IMAGE_BACKGROUNDS,
    IMAGE_FORMATS,
    IMAGE_MODEL_PROFILES,
    IMAGE_QUALITIES,
    TEXT_MODEL_PROFILES,
    get_image_model_profile,
    get_text_model_profile,
    validate_image_background,
    validate_image_format,
    validate_image_quality,
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

    def test_image_quality_grades_are_allow_listed(self):
        for quality in IMAGE_QUALITIES:
            self.assertEqual(
                validate_image_quality("gpt-image-2.5-flare", quality), quality,
            )
        with self.assertRaises(ValueError):
            validate_image_quality("gpt-image-2.5-flare", "ultra")

    def test_max_quality_requires_2_5_model(self):
        self.assertEqual(
            validate_image_quality("gpt-image-2", "high"), "high",
        )
        with self.assertRaises(ValueError):
            validate_image_quality("gpt-image-2", "xhigh")
        self.assertEqual(
            validate_image_quality("gpt-image-2.5-sunburst", "max"), "max",
        )

    def test_image_formats_are_allow_listed(self):
        for fmt in IMAGE_FORMATS:
            self.assertEqual(validate_image_format(fmt), fmt)
        with self.assertRaises(ValueError):
            validate_image_format("gif")

    def test_transparent_background_rules(self):
        self.assertEqual(
            validate_image_background("gpt-image-2.5-flare", "transparent", "png"),
            "transparent",
        )
        self.assertEqual(
            validate_image_background("gpt-image-2.5-flare", "transparent", "webp"),
            "transparent",
        )
        with self.assertRaises(ValueError):
            validate_image_background("gpt-image-2.5-flare", "transparent", "jpeg")
        with self.assertRaises(ValueError):
            validate_image_background("gpt-image-2", "transparent", "png")
        for background in ("auto", "opaque"):
            self.assertEqual(
                validate_image_background("gpt-image-2", background, "png"), background,
            )


if __name__ == "__main__":
    unittest.main()
