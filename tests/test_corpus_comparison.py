import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier, BrokenBarrierError, Lock
import unittest

from corpus_atelier.application import CorpusAtelierApplication
from corpus_atelier.state import CorpusComparisonJob, HumanDecision
from tests.fakes import FakeImageProvider, FakeTextProvider


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "experiments/atlas-snapshot/mucha-commercial"
REFERENCE = {
    "format_version": 1,
    "reference_id": "mucha-poster-124474232",
}
BRIEF = {
    "deliverable": "微信公众号封面",
    "purpose": "Introduce a visual-corpus research project.",
    "audience": "Digital humanities researchers",
    "use_context": "Viewed on a mobile article index.",
    "exact_copy": ["Design for context"],
    "constraints": [],
    "preferences": [],
    "canvas": {"aspect_ratio": {"width": 47, "height": 20}},
}


class ConcurrentTextProvider(FakeTextProvider):
    concurrent_schemas = {
        "graphic-design-proposal.schema.json",
        "image-spec.schema.json",
    }

    def __init__(self):
        super().__init__()
        self.barriers = {
            schema: Barrier(2) for schema in self.concurrent_schemas
        }
        self.completed_stages = set()
        self.lock = Lock()

    def propose(self, prompt: str, *, schema_name: str, reference_paths=None):
        if schema_name in self.barriers:
            try:
                self.barriers[schema_name].wait(timeout=3)
            except BrokenBarrierError as exc:
                raise AssertionError(
                    f"Comparison arms did not overlap at {schema_name}."
                ) from exc
            with self.lock:
                self.completed_stages.add(schema_name)
        return super().propose(
            prompt,
            schema_name=schema_name,
            reference_paths=reference_paths,
        )


class ConcurrentImageProvider(FakeImageProvider):
    def __init__(self):
        super().__init__()
        self.barrier = Barrier(2)
        self.completed_calls = 0
        self.lock = Lock()

    def generate(self, prompt: str, *, size: str, output: Path):
        try:
            self.barrier.wait(timeout=3)
        except BrokenBarrierError as exc:
            raise AssertionError(
                "Comparison image generations did not overlap."
            ) from exc
        response = super().generate(prompt, size=size, output=output)
        with self.lock:
            self.completed_calls += 1
        return response


class CorpusComparisonTests(unittest.TestCase):
    def _start(self, directory, *, text=None, image=None):
        app = CorpusAtelierApplication(
            runs_root=directory,
            text_provider=text or FakeTextProvider(),
            image_provider=image or FakeImageProvider(),
        )
        comparison = app.start_comparison(CorpusComparisonJob(
            case_id="paired-corpus-test",
            profile="rhetoric-graphic",
            brief=BRIEF,
            snapshot=SNAPSHOT,
            reference=REFERENCE,
        ))
        return app, comparison

    def test_two_arms_share_one_frozen_brief_and_distinct_corpus_conditions(self):
        with TemporaryDirectory() as directory:
            app, comparison = self._start(directory)

            self.assertEqual(comparison.baseline.status, "awaiting_approval")
            self.assertEqual(comparison.corpus.status, "awaiting_approval")
            baseline_brief = json.loads(Path(
                comparison.baseline.artifacts["brief"]
            ).read_text(encoding="utf-8"))
            corpus_brief = json.loads(Path(
                comparison.corpus.artifacts["brief"]
            ).read_text(encoding="utf-8"))
            self.assertEqual(baseline_brief, BRIEF)
            self.assertEqual(corpus_brief, BRIEF)

            baseline_manifest = json.loads(Path(
                comparison.baseline.artifacts["manifest"]
            ).read_text(encoding="utf-8"))
            corpus_manifest = json.loads(Path(
                comparison.corpus.artifacts["manifest"]
            ).read_text(encoding="utf-8"))
            self.assertEqual(
                baseline_manifest["experiment"]["group_id"],
                comparison.group_id,
            )
            self.assertEqual(
                baseline_manifest["experiment"]["shared_brief_sha256"],
                corpus_manifest["experiment"]["shared_brief_sha256"],
            )
            self.assertEqual(
                baseline_manifest["experiment"]["condition"],
                "baseline_no_explicit_corpus",
            )
            self.assertNotIn("corpus", baseline_manifest["experiment"])
            self.assertEqual(
                corpus_manifest["experiment"]["condition"],
                "explicit_corpus",
            )
            self.assertIn("corpus", corpus_manifest["experiment"])
            self.assertNotIn("reference_package", comparison.baseline.artifacts)
            self.assertIn("reference_package", comparison.corpus.artifacts)

    def test_both_text_stages_run_in_parallel(self):
        with TemporaryDirectory() as directory:
            text = ConcurrentTextProvider()
            _, comparison = self._start(directory, text=text)

            self.assertEqual(
                text.completed_stages,
                ConcurrentTextProvider.concurrent_schemas,
            )
            self.assertEqual(comparison.baseline.status, "awaiting_approval")
            self.assertEqual(comparison.corpus.status, "awaiting_approval")

    def test_one_approval_generates_both_images_in_parallel(self):
        with TemporaryDirectory() as directory:
            image = ConcurrentImageProvider()
            app, comparison = self._start(directory, image=image)

            completed = app.resume_comparison(
                comparison,
                HumanDecision(True, reviewer="test"),
            )

            self.assertEqual(image.completed_calls, 2)
            self.assertEqual(completed.baseline.status, "completed")
            self.assertEqual(completed.corpus.status, "completed")
            group_manifest = json.loads(
                (comparison.group_dir / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(group_manifest["status"], "completed")

    def test_one_rejection_cancels_both_arms_without_image_calls(self):
        with TemporaryDirectory() as directory:
            image = FakeImageProvider()
            app, comparison = self._start(directory, image=image)

            rejected = app.resume_comparison(
                comparison,
                HumanDecision(False, reviewer="test"),
            )

            self.assertEqual(rejected.baseline.status, "rejected")
            self.assertEqual(rejected.corpus.status, "rejected")
            self.assertEqual(image.calls, 0)


if __name__ == "__main__":
    unittest.main()
