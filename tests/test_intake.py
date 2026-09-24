import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from corpus_atelier.application import CorpusAtelierApplication
from corpus_atelier.intake import compile_intake_prompt
from corpus_atelier.registry import get_profile
from corpus_atelier.state import NaturalLanguageDesignJob
from tests.fakes import FakeImageProvider, FakeTextProvider


WALLPAPER_REQUEST = (
    "我想要一个电脑壁纸，要让我忘记锁屏时，别人看到了我电脑也不翻。"
    "因为电脑是在工位上，所以可以戏谑一些，攻击性小一些，玩玩梗。"
    "更清晰的想法暂时没有，也不想投入很多精力。"
)


class IntakeTests(unittest.TestCase):
    def test_prompt_compiles_request_into_the_existing_profile_schema(self):
        prompt = compile_intake_prompt(
            get_profile("rhetoric-graphic"), WALLPAPER_REQUEST,
        )

        self.assertIn("Transform the user's everyday description", prompt)
        self.assertIn('"brief_schema": "graphic-design-brief.schema.json"', prompt)
        self.assertIn('"deliverable"', prompt)
        self.assertIn(WALLPAPER_REQUEST, prompt)
        self.assertIn("Do not write an image-model prompt", prompt)

    def test_natural_language_path_reaches_the_existing_approval_gate(self):
        with TemporaryDirectory() as directory:
            text = FakeTextProvider()
            image = FakeImageProvider()
            app = CorpusAtelierApplication(
                runs_root=directory,
                text_provider=text,
                image_provider=image,
            )

            result = app.start_request(NaturalLanguageDesignJob(
                case_id="natural-language",
                profile="rhetoric-graphic",
                request=WALLPAPER_REQUEST,
                generation_mode="without_corpus",
            ))

            self.assertEqual(result.status, "awaiting_approval")
            self.assertEqual(image.calls, 0)
            self.assertEqual(
                [call["schema_name"] for call in text.design_calls],
                [
                    "graphic-design-brief.schema.json",
                    "graphic-design-proposal.schema.json",
                    "image-spec.schema.json",
                ],
            )
            self.assertEqual(
                Path(result.artifacts["user_request"]).read_text(encoding="utf-8"),
                WALLPAPER_REQUEST,
            )
            brief = json.loads(
                Path(result.artifacts["brief"]).read_text(encoding="utf-8")
            )
            self.assertEqual(brief["canvas"]["aspect_ratio"], {
                "width": 16, "height": 9,
            })
            self.assertTrue(brief["exact_copy"])
            manifest = json.loads(
                Path(result.artifacts["manifest"]).read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["input_mode"], "natural_language")
            self.assertEqual(manifest["workflow_version"], 11)
            self.assertIn("intake_prompt", manifest["artifacts"])
            self.assertIn("intake_response", manifest["artifacts"])

    def test_empty_request_is_rejected_before_a_run_is_created(self):
        with TemporaryDirectory() as directory:
            app = CorpusAtelierApplication(
                runs_root=directory,
                text_provider=FakeTextProvider(),
                image_provider=FakeImageProvider(),
            )
            with self.assertRaisesRegex(ValueError, "must not be empty"):
                app.start_request(NaturalLanguageDesignJob(
                    case_id="natural-language",
                    profile="rhetoric-graphic",
                    request="  ",
                    generation_mode="without_corpus",
                ))
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
