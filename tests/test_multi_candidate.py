import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from corpus_atelier.application import CorpusAtelierApplication
from corpus_atelier.state import (
    CandidateSelection,
    HumanDecision,
    NaturalLanguageDesignJob,
)
from tests.fakes import FakeImageProvider, FakeTextProvider
from corpus_atelier.artifacts.records import write_json


REQUEST = "设计一张桌面壁纸，用轻松的方式提醒同事离开工位时锁屏。"


class SecondCandidateFailingImageProvider(FakeImageProvider):
    def __init__(self):
        super().__init__()
        self.attempts = 0

    def generate(self, prompt: str, *, size: str, output: Path, reference_paths=None):
        self.attempts += 1
        if "c02" in output.parts:
            write_json(output / "response.json", {
                "status": "failed", "error_type": "RuntimeError",
            })
            raise RuntimeError("deliberate c02 failure")
        return super().generate(
            prompt, size=size, output=output, reference_paths=reference_paths,
        )


class MultiCandidateTests(unittest.TestCase):
    def _start(self, directory, *, count=3):
        text = FakeTextProvider()
        image = FakeImageProvider()
        app = CorpusAtelierApplication(
            runs_root=directory,
            text_provider=text,
            image_provider=image,
        )
        result = app.start_request(NaturalLanguageDesignJob(
            case_id="multi-candidate",
            profile="rhetoric-graphic",
            request=REQUEST,
            candidate_count=count,
        ))
        return app, text, image, result

    def test_three_candidates_form_one_batch_and_require_selection(self):
        with TemporaryDirectory() as directory:
            app, text, image, result = self._start(directory)

            self.assertEqual(result.status, "awaiting_approval")
            self.assertEqual(image.calls, 0)
            plan = json.loads(Path(
                result.artifacts["direction_plan"]
            ).read_text(encoding="utf-8"))
            self.assertEqual(plan["candidate_count"], 3)
            self.assertEqual(
                [direction["candidate_id"] for direction in plan["directions"]],
                ["c01", "c02", "c03"],
            )
            self.assertTrue(all(
                not direction["movement_references"]
                for direction in plan["directions"]
            ))
            self.assertEqual(
                sum(
                    call["schema_name"] == "graphic-design-proposal.schema.json"
                    for call in text.design_calls
                ),
                3,
            )

            candidates = json.loads(Path(
                result.artifacts["candidate_index"]
            ).read_text(encoding="utf-8"))
            self.assertEqual(len(candidates), 3)
            self.assertEqual({candidate["status"] for candidate in candidates}, {"ready"})
            self.assertEqual(
                len({candidate["proposal"]["chosen_direction"] for candidate in candidates}),
                3,
            )
            for candidate in candidates:
                root = result.run_dir / "candidates" / candidate["candidate_id"]
                self.assertTrue((root / "design/proposal.json").is_file())
                self.assertTrue((root / "generation/request-preview.json").is_file())

            generated = app.resume(
                result.run_id, HumanDecision(True, reviewer="test"),
            )
            self.assertEqual(generated.status, "awaiting_selection")
            self.assertEqual(image.calls, 3)

            completed = app.resume(
                generated.run_id,
                CandidateSelection("c02", reviewer="test"),
            )
            self.assertEqual(completed.status, "completed")
            selection = json.loads(Path(
                completed.artifacts["selection"]
            ).read_text(encoding="utf-8"))
            self.assertEqual(selection["selected_candidate_id"], "c02")
            self.assertTrue(selection["selected_image_sha256"])
            self.assertIn("/c02/", completed.artifacts["image"].replace("\\", "/"))

    def test_one_generation_failure_preserves_other_candidates(self):
        with TemporaryDirectory() as directory:
            image = SecondCandidateFailingImageProvider()
            app = CorpusAtelierApplication(
                runs_root=directory,
                text_provider=FakeTextProvider(),
                image_provider=image,
            )
            result = app.start_request(NaturalLanguageDesignJob(
                case_id="partial-candidate-failure",
                profile="rhetoric-graphic",
                request=REQUEST,
                candidate_count=3,
            ))
            result = app.resume(
                result.run_id, HumanDecision(True, reviewer="test"),
            )
            self.assertEqual(result.status, "awaiting_selection")
            self.assertEqual(image.attempts, 3)
            candidates = json.loads(Path(
                result.artifacts["candidate_index"]
            ).read_text(encoding="utf-8"))
            self.assertEqual(
                [candidate["status"] for candidate in candidates],
                ["generated", "failed", "generated"],
            )

    def test_batch_rejection_never_calls_image_provider(self):
        with TemporaryDirectory() as directory:
            app, _, image, result = self._start(directory, count=2)
            rejected = app.resume(
                result.run_id, HumanDecision(False, reviewer="test"),
            )
            self.assertEqual(rejected.status, "rejected")
            self.assertEqual(image.calls, 0)

    def test_editing_one_candidate_invalidates_the_whole_batch(self):
        with TemporaryDirectory() as directory:
            app, _, image, result = self._start(directory)
            prompt = result.run_dir / "candidates/c02/generation/prompt.md"
            prompt.write_text(
                prompt.read_text(encoding="utf-8") + "\nchanged",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "changed after preview"):
                app.resume(
                    result.run_id, HumanDecision(True, reviewer="test"),
                )
            self.assertEqual(image.calls, 0)

    def test_candidate_count_is_a_deterministic_product_limit(self):
        with TemporaryDirectory() as directory:
            app = CorpusAtelierApplication(
                runs_root=directory,
                text_provider=FakeTextProvider(),
                image_provider=FakeImageProvider(),
            )
            for invalid in (0, 4, True):
                with self.subTest(candidate_count=invalid):
                    with self.assertRaisesRegex(ValueError, "1, 2, or 3"):
                        app.start_request(NaturalLanguageDesignJob(
                            case_id="invalid-count",
                            profile="rhetoric-graphic",
                            request=REQUEST,
                            candidate_count=invalid,
                        ))


if __name__ == "__main__":
    unittest.main()
