import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from corpus_atelier.application import CorpusAtelierApplication
from corpus_atelier.state import DesignJob, HumanDecision
from tests.fakes import FakeImageProvider, FakeTextProvider


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "experiments/atlas-snapshot/mucha-commercial"
CASES = ROOT / "experiments/cases"
REFERENCE = {
    "format_version": 1,
    "reference_id": "mucha-poster-124474277",
}


def brief(case):
    return json.loads((CASES / case / "brief.json").read_text(encoding="utf-8"))


class GraphTests(unittest.TestCase):
    def _run(self, profile, case):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        image = FakeImageProvider()
        text = FakeTextProvider()
        app = CorpusAtelierApplication(
            runs_root=Path(temporary.name),
            text_provider=text,
            image_provider=image,
        )
        result = app.start(DesignJob(
            case_id=case,
            profile=profile,
            brief=brief(case),
            generation_mode="with_corpus",
            snapshot=SNAPSHOT,
            reference=REFERENCE,
        ))
        self.assertEqual(result.status, "awaiting_approval")
        self.assertEqual(image.calls, 0)
        preview = json.loads(Path(
            result.artifacts["generation_request_preview"]
        ).read_text(encoding="utf-8"))
        self.assertEqual(preview["model"], "fake-image")
        self.assertEqual(preview["quality"], "test")
        self.assertEqual(preview["prompt"], Path(
            result.artifacts["generation_prompt"]
        ).read_text(encoding="utf-8"))
        self.assertEqual(len(preview["references"]), 1)
        result = app.resume(result.run_id, HumanDecision(True, reviewer="test"))
        self.assertEqual(result.status, "completed")
        self.assertEqual(image.calls, 1)
        sent_request = json.loads(Path(
            result.artifacts["generation_request"]
        ).read_text(encoding="utf-8"))
        self.assertEqual(sent_request, preview)
        self.assertIn("image", result.artifacts)
        self.assertNotIn("review", result.artifacts)
        manifest = json.loads(
            Path(result.artifacts["manifest"]).read_text(encoding="utf-8")
        )
        self.assertIn("image_sha256", manifest)
        self.assertIn("completed_at", manifest)
        self.assertNotIn("final_decision_request", manifest)
        self.assertFalse((result.run_dir / "review").exists())
        from PIL import Image
        with Image.open(result.artifacts["image"]) as opened:
            expected = (2, 3) if profile == "rhetoric-poster" else (47, 20)
            self.assertEqual(opened.width * expected[1], opened.height * expected[0])
        self.assertEqual(result.run_dir.parent.name, case)
        self.assertEqual(manifest["case_id"], case)
        self.assertEqual(manifest["workflow_version"], 12)
        self.assertNotIn("review", manifest["artifacts"])
        self.assertNotIn("final_decision", manifest["artifacts"])
        return result

    def test_rhetoric_graph_end_to_end(self):
        self._run("rhetoric-poster", "poster-01")

    def test_artistic_profile_end_to_end(self):
        self._run("art-article-cover", "article-cover-01")

    def test_open_graphic_profile_uses_brief_canvas_without_corpus(self):
        with TemporaryDirectory() as directory:
            image = FakeImageProvider()
            app = CorpusAtelierApplication(
                runs_root=directory,
                text_provider=FakeTextProvider(),
                image_provider=image,
            )
            design_brief = {
                "deliverable": "小红书配图",
                "purpose": "Introduce a reading group.",
                "audience": "Mobile readers",
                "use_context": "Viewed in a mobile feed.",
                "exact_copy": ["Design for context"],
                "constraints": [],
                "preferences": [],
                "canvas": {"aspect_ratio": {"width": 4, "height": 5}},
            }
            result = app.start(DesignJob(
                case_id="open-graphic-01",
                profile="rhetoric-graphic",
                brief=design_brief,
                generation_mode="without_corpus",
            ))
            self.assertEqual(result.status, "awaiting_approval")
            self.assertNotIn("reference_package", result.artifacts)
            prompt = Path(result.artifacts["design_prompt"]).read_text(encoding="utf-8")
            self.assertNotIn("Untrusted selected visual reference", prompt)
            manifest = json.loads(Path(result.artifacts["manifest"]).read_text(encoding="utf-8"))
            self.assertEqual(manifest["generation_mode"], "without_corpus")
            self.assertNotIn("atlas_snapshot", manifest)
            canvas = json.loads(Path(result.artifacts["canvas"]).read_text(encoding="utf-8"))
            self.assertEqual(canvas["ratio"], [4, 5])

            result = app.resume(result.run_id, HumanDecision(True, reviewer="test"))
            self.assertEqual(result.status, "completed")
            self.assertEqual(image.last_size, canvas["size"])
            from PIL import Image
            with Image.open(result.artifacts["image"]) as opened:
                self.assertEqual(opened.width * 5, opened.height * 4)

    def test_generation_modes_reject_mixed_or_missing_corpus_inputs(self):
        with TemporaryDirectory() as directory:
            app = CorpusAtelierApplication(
                runs_root=directory,
                text_provider=FakeTextProvider(),
                image_provider=FakeImageProvider(),
            )
            with self.assertRaisesRegex(ValueError, "cannot include a snapshot or reference"):
                app.start(DesignJob(
                    case_id="poster-01",
                    profile="rhetoric-poster",
                    brief=brief("poster-01"),
                    generation_mode="without_corpus",
                    snapshot=SNAPSHOT,
                    reference=REFERENCE,
                ))
            with self.assertRaisesRegex(ValueError, "require a snapshot and reference selection"):
                app.start(DesignJob(
                    case_id="poster-01",
                    profile="rhetoric-poster",
                    brief=brief("poster-01"),
                    generation_mode="with_corpus",
                ))
            with self.assertRaisesRegex(ValueError, "Invalid reference-selection"):
                app.start(DesignJob(
                    case_id="poster-01",
                    profile="rhetoric-poster",
                    brief=brief("poster-01"),
                    generation_mode="with_corpus",
                    snapshot=SNAPSHOT,
                    reference={
                        "format_version": 1,
                        "reference_id": "",
                    },
                ))
    def test_rejection_never_calls_image_provider(self):
        with TemporaryDirectory() as directory:
            image = FakeImageProvider()
            app = CorpusAtelierApplication(
                runs_root=directory,
                text_provider=FakeTextProvider(),
                image_provider=image,
            )
            started = app.start(DesignJob(
                case_id="poster-01",
                profile="rhetoric-poster",
                brief=brief("poster-01"),
                generation_mode="with_corpus",
                snapshot=SNAPSHOT,
                reference=REFERENCE,
            ))
            result = app.resume(started.run_id, HumanDecision(False, reviewer="test"))
            self.assertEqual(result.status, "rejected")
            self.assertEqual(image.calls, 0)

    def test_failed_generation_is_recorded_without_retry(self):
        with TemporaryDirectory() as directory:
            image = FakeImageProvider(fail=True)
            app = CorpusAtelierApplication(
                runs_root=directory,
                text_provider=FakeTextProvider(),
                image_provider=image,
            )
            started = app.start(DesignJob(
                case_id="poster-01",
                profile="rhetoric-poster",
                brief=brief("poster-01"),
                generation_mode="with_corpus",
                snapshot=SNAPSHOT,
                reference=REFERENCE,
            ))
            with self.assertRaises(RuntimeError):
                app.resume(started.run_id, HumanDecision(True, reviewer="test"))
            self.assertEqual(image.calls, 1)
            response = next(
                Path(directory).glob("*/*/generation/attempt_01/response.json")
            )
            self.assertEqual(json.loads(response.read_text())["status"], "failed")

    def test_edited_generation_prompt_invalidates_approval(self):
        with TemporaryDirectory() as directory:
            image = FakeImageProvider()
            app = CorpusAtelierApplication(
                runs_root=directory,
                text_provider=FakeTextProvider(),
                image_provider=image,
            )
            started = app.start(DesignJob(
                case_id="poster-01",
                profile="rhetoric-poster",
                brief=brief("poster-01"),
                generation_mode="with_corpus",
                snapshot=SNAPSHOT,
                reference=REFERENCE,
            ))
            prompt = started.run_dir / "generation/prompt.md"
            prompt.write_text(
                prompt.read_text(encoding="utf-8") + "\nchanged", encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "changed after preview"):
                app.resume(started.run_id, HumanDecision(True, reviewer="test"))
            self.assertEqual(image.calls, 0)

    def test_changed_image_request_invalidates_preview(self):
        with TemporaryDirectory() as directory:
            image = FakeImageProvider()
            app = CorpusAtelierApplication(
                runs_root=directory,
                text_provider=FakeTextProvider(),
                image_provider=image,
            )
            started = app.start(DesignJob(
                case_id="poster-01",
                profile="rhetoric-poster",
                brief=brief("poster-01"),
                generation_mode="with_corpus",
                snapshot=SNAPSHOT,
                reference=REFERENCE,
            ))
            image.quality = "changed-after-preview"

            with self.assertRaisesRegex(ValueError, "changed after preview"):
                app.resume(started.run_id, HumanDecision(True, reviewer="test"))
            self.assertEqual(image.calls, 0)

    def test_edited_reference_package_invalidates_approval(self):
        with TemporaryDirectory() as directory:
            image = FakeImageProvider()
            app = CorpusAtelierApplication(
                runs_root=directory,
                text_provider=FakeTextProvider(),
                image_provider=image,
            )
            started = app.start(DesignJob(
                case_id="poster-01",
                profile="rhetoric-poster",
                brief=brief("poster-01"),
                generation_mode="with_corpus",
                snapshot=SNAPSHOT,
                reference=REFERENCE,
            ))
            package = Path(started.artifacts["reference_package"])
            value = json.loads(package.read_text(encoding="utf-8"))
            value["reference"]["title"] = "changed"
            package.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "changed after preview"):
                app.resume(started.run_id, HumanDecision(True, reviewer="test"))
            self.assertEqual(image.calls, 0)

if __name__ == "__main__":
    unittest.main()
