import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from corpus_atelier.application import CorpusAtelierApplication
from corpus_atelier.state import DesignJob, HumanDecision, RevisionDecision
from tests.fakes import FakeImageProvider, FakeTextProvider


ROOT = Path(__file__).resolve().parents[1]


def brief(name):
    path = ROOT / "experiments/cases" / name / "brief.json"
    return json.loads(path.read_text(encoding="utf-8"))


class GraphTests(unittest.TestCase):
    def _run(self, profile, case):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        image = FakeImageProvider()
        app = CorpusAtelierApplication(
            runs_root=Path(temporary.name), text_provider=FakeTextProvider(),
            image_provider=image,
        )
        result = app.start(DesignJob(
            profile=profile, brief=brief(case),
            snapshot=ROOT / "experiments/atlas-snapshot",
        ))
        self.assertEqual(result.status, "awaiting_approval")
        self.assertEqual(image.calls, 0)
        result = app.resume(result.run_id, HumanDecision(True, reviewer="test"))
        self.assertEqual(result.status, "awaiting_revision")
        self.assertEqual(image.calls, 1)
        self.assertIn("image", result.artifacts)
        self.assertIn("review", result.artifacts)
        from PIL import Image
        with Image.open(result.artifacts["image"]) as opened:
            expected = (2, 3) if profile == "rhetoric-poster" else (47, 20)
            self.assertEqual(opened.width * expected[1], opened.height * expected[0])
        result = app.resume(result.run_id, RevisionDecision("accept", reviewer="test"))
        self.assertEqual(result.status, "completed")
        return result

    def test_rhetoric_graph_end_to_end(self):
        self._run("rhetoric-poster", "poster-01")

    def test_artistic_graph_end_to_end(self):
        self._run("art-article-cover", "article-cover-01")

    def test_rejection_never_calls_image_provider(self):
        with TemporaryDirectory() as directory:
            image = FakeImageProvider()
            app = CorpusAtelierApplication(
                runs_root=directory, text_provider=FakeTextProvider(), image_provider=image,
            )
            started = app.start(DesignJob(
                profile="rhetoric-poster", brief=brief("poster-01"),
                snapshot=ROOT / "experiments/atlas-snapshot",
            ))
            result = app.resume(started.run_id, HumanDecision(False, reviewer="test"))
            self.assertEqual(result.status, "rejected")
            self.assertEqual(image.calls, 0)

    def test_failed_generation_is_recorded_without_retry(self):
        with TemporaryDirectory() as directory:
            image = FakeImageProvider(fail=True)
            app = CorpusAtelierApplication(
                runs_root=directory, text_provider=FakeTextProvider(), image_provider=image,
            )
            started = app.start(DesignJob(
                profile="rhetoric-poster", brief=brief("poster-01"),
                snapshot=ROOT / "experiments/atlas-snapshot",
            ))
            with self.assertRaises(RuntimeError):
                app.resume(started.run_id, HumanDecision(True, reviewer="test"))
            self.assertEqual(image.calls, 1)
            response = next(Path(directory).glob("*/generation/attempt_01/response.json"))
            self.assertEqual(json.loads(response.read_text())["status"], "failed")

    def test_edited_review_artifact_invalidates_approval(self):
        with TemporaryDirectory() as directory:
            image = FakeImageProvider()
            app = CorpusAtelierApplication(
                runs_root=directory, text_provider=FakeTextProvider(), image_provider=image,
            )
            started = app.start(DesignJob(
                profile="rhetoric-poster", brief=brief("poster-01"),
                snapshot=ROOT / "experiments/atlas-snapshot",
            ))
            prompt = started.run_dir / "generation/prompt.md"
            prompt.write_text(prompt.read_text(encoding="utf-8") + "\nchanged", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "changed after preview"):
                app.resume(started.run_id, HumanDecision(True, reviewer="test"))
            self.assertEqual(image.calls, 0)

    def test_explicit_revision_is_planned_approved_edited_and_compared(self):
        with TemporaryDirectory() as directory:
            image = FakeImageProvider()
            app = CorpusAtelierApplication(
                runs_root=directory, text_provider=FakeTextProvider(), image_provider=image,
            )
            result = app.start(DesignJob(
                profile="rhetoric-poster", brief=brief("poster-01"),
                snapshot=ROOT / "experiments/atlas-snapshot",
            ))
            result = app.resume(result.run_id, HumanDecision(True, reviewer="test"))
            self.assertEqual(result.status, "awaiting_revision")
            result = app.resume(result.run_id, RevisionDecision(
                "revise", instruction="Remove the lower-left handwriting only.",
                reviewer="test",
            ))
            self.assertEqual(result.status, "awaiting_revision_approval")
            self.assertIn("revision_plan", result.artifacts)
            self.assertIn("revision_prompt", result.artifacts)
            self.assertEqual(image.edit_calls, 0)
            result = app.resume(result.run_id, HumanDecision(True, reviewer="test"))
            self.assertEqual(result.status, "awaiting_revision")
            self.assertEqual(image.edit_calls, 1)
            review = json.loads(Path(result.artifacts["review"]).read_text(encoding="utf-8"))
            self.assertTrue(review["requested_change_met"])
            result = app.resume(result.run_id, RevisionDecision("accept", reviewer="test"))
            self.assertEqual(result.status, "completed")

    def test_review_does_not_trigger_revision_without_user_request(self):
        with TemporaryDirectory() as directory:
            image = FakeImageProvider()
            app = CorpusAtelierApplication(
                runs_root=directory, text_provider=FakeTextProvider(), image_provider=image,
            )
            result = app.start(DesignJob(
                profile="rhetoric-poster", brief=brief("poster-01"),
                snapshot=ROOT / "experiments/atlas-snapshot",
            ))
            result = app.resume(result.run_id, HumanDecision(True, reviewer="test"))
            self.assertEqual(result.status, "awaiting_revision")
            self.assertEqual(image.edit_calls, 0)
            result = app.resume(result.run_id, RevisionDecision("discard", reviewer="test"))
            self.assertEqual(result.status, "discarded")

    def test_revision_edit_requires_bound_approval(self):
        with TemporaryDirectory() as directory:
            image = FakeImageProvider()
            app = CorpusAtelierApplication(
                runs_root=directory, text_provider=FakeTextProvider(), image_provider=image,
            )
            result = app.start(DesignJob(
                profile="rhetoric-poster", brief=brief("poster-01"),
                snapshot=ROOT / "experiments/atlas-snapshot",
            ))
            result = app.resume(result.run_id, HumanDecision(True, reviewer="test"))
            result = app.resume(result.run_id, RevisionDecision(
                "revise", instruction="Remove the lower-left handwriting only.",
                reviewer="test",
            ))
            prompt = next(result.run_dir.glob("revision/attempt_01/prompt.md"))
            prompt.write_text(prompt.read_text(encoding="utf-8") + "\nchanged", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "changed after preview"):
                app.resume(result.run_id, HumanDecision(True, reviewer="test"))
            self.assertEqual(image.edit_calls, 0)

    def test_declined_revision_approval_returns_to_human_gate(self):
        with TemporaryDirectory() as directory:
            image = FakeImageProvider()
            app = CorpusAtelierApplication(
                runs_root=directory, text_provider=FakeTextProvider(), image_provider=image,
            )
            result = app.start(DesignJob(
                profile="rhetoric-poster", brief=brief("poster-01"),
                snapshot=ROOT / "experiments/atlas-snapshot",
            ))
            result = app.resume(result.run_id, HumanDecision(True, reviewer="test"))
            result = app.resume(result.run_id, RevisionDecision(
                "revise", instruction="Remove the lower-left handwriting only.",
                reviewer="test",
            ))
            result = app.resume(result.run_id, HumanDecision(False, reviewer="test"))
            self.assertEqual(result.status, "awaiting_revision")
            self.assertEqual(image.edit_calls, 0)
            result = app.resume(result.run_id, RevisionDecision("accept", reviewer="test"))
            self.assertEqual(result.status, "completed")
