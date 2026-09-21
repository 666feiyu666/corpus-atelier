import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from corpus_atelier.application import CorpusAtelierApplication
from corpus_atelier.state import DesignJob, FinalDecision, HumanDecision
from tests.fakes import FakeImageProvider, FakeTextProvider


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "experiments/atlas-snapshot/mucha-commercial"
CASES = ROOT / "experiments/cases"
MATERIALS = {
    "format_version": 1,
    "knowledge_ids": ["mucha-commercial-lettering-image-integration"],
    "reference_ids": [],
}


def brief(case):
    return json.loads((CASES / case / "brief.json").read_text(encoding="utf-8"))


class GraphTests(unittest.TestCase):
    def _run(self, profile, case):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        image = FakeImageProvider()
        app = CorpusAtelierApplication(
            runs_root=Path(temporary.name),
            text_provider=FakeTextProvider(),
            image_provider=image,
        )
        result = app.start(DesignJob(
            profile=profile,
            brief=brief(case),
            snapshot=SNAPSHOT,
            materials=MATERIALS,
        ))
        self.assertEqual(result.status, "awaiting_approval")
        self.assertEqual(image.calls, 0)
        result = app.resume(result.run_id, HumanDecision(True, reviewer="test"))
        self.assertEqual(result.status, "awaiting_final_decision")
        self.assertEqual(image.calls, 1)
        self.assertIn("image", result.artifacts)
        self.assertIn("review", result.artifacts)
        from PIL import Image
        with Image.open(result.artifacts["image"]) as opened:
            expected = (2, 3) if profile == "rhetoric-poster" else (47, 20)
            self.assertEqual(opened.width * expected[1], opened.height * expected[0])
        result = app.resume(result.run_id, FinalDecision("accept", reviewer="test"))
        self.assertEqual(result.status, "completed")
        self.assertIn("final_decision", result.artifacts)
        return result

    def test_rhetoric_graph_end_to_end(self):
        self._run("rhetoric-poster", "poster-01")

    def test_artistic_profile_end_to_end(self):
        self._run("art-article-cover", "article-cover-01")

    def test_rejection_never_calls_image_provider(self):
        with TemporaryDirectory() as directory:
            image = FakeImageProvider()
            app = CorpusAtelierApplication(
                runs_root=directory,
                text_provider=FakeTextProvider(),
                image_provider=image,
            )
            started = app.start(DesignJob(
                profile="rhetoric-poster",
                brief=brief("poster-01"),
                snapshot=SNAPSHOT,
                materials=MATERIALS,
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
                profile="rhetoric-poster",
                brief=brief("poster-01"),
                snapshot=SNAPSHOT,
                materials=MATERIALS,
            ))
            with self.assertRaises(RuntimeError):
                app.resume(started.run_id, HumanDecision(True, reviewer="test"))
            self.assertEqual(image.calls, 1)
            response = next(Path(directory).glob("*/generation/attempt_01/response.json"))
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
                profile="rhetoric-poster",
                brief=brief("poster-01"),
                snapshot=SNAPSHOT,
                materials=MATERIALS,
            ))
            prompt = started.run_dir / "generation/prompt.md"
            prompt.write_text(
                prompt.read_text(encoding="utf-8") + "\nchanged", encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "changed after preview"):
                app.resume(started.run_id, HumanDecision(True, reviewer="test"))
            self.assertEqual(image.calls, 0)

    def test_edited_material_package_invalidates_approval(self):
        with TemporaryDirectory() as directory:
            image = FakeImageProvider()
            app = CorpusAtelierApplication(
                runs_root=directory,
                text_provider=FakeTextProvider(),
                image_provider=image,
            )
            started = app.start(DesignJob(
                profile="rhetoric-poster",
                brief=brief("poster-01"),
                snapshot=SNAPSHOT,
                materials=MATERIALS,
            ))
            package = Path(started.artifacts["materials_package"])
            value = json.loads(package.read_text(encoding="utf-8"))
            value["knowledge"][0]["title"] = "changed"
            package.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "changed after preview"):
                app.resume(started.run_id, HumanDecision(True, reviewer="test"))
            self.assertEqual(image.calls, 0)

    def test_final_decision_only_accepts_or_discards(self):
        with TemporaryDirectory() as directory:
            app = CorpusAtelierApplication(
                runs_root=directory,
                text_provider=FakeTextProvider(),
                image_provider=FakeImageProvider(),
            )
            result = app.start(DesignJob(
                profile="rhetoric-poster",
                brief=brief("poster-01"),
                snapshot=SNAPSHOT,
                materials=MATERIALS,
            ))
            result = app.resume(result.run_id, HumanDecision(True, reviewer="test"))
            result = app.resume(result.run_id, FinalDecision("discard", reviewer="test"))
            self.assertEqual(result.status, "discarded")


if __name__ == "__main__":
    unittest.main()
