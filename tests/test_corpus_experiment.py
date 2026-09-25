import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from threading import Barrier, BrokenBarrierError, Lock
import unittest

from corpus_atelier.application import CorpusAtelierApplication
from corpus_atelier.materials import build_reference_package, load_snapshot
from corpus_atelier.state import (
    CorpusComparisonJob,
    CorpusExperimentJob,
    HumanDecision,
    NaturalLanguageDesignJob,
)
from tests.fakes import FakeImageProvider, FakeTextProvider


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "experiments/atlas-snapshot/mucha-commercial"
REFERENCE = {
    "format_version": 1,
    "reference_id": "mucha-poster-124474232",
}
REQUEST = "制作一张穆夏风格的手表广告。"


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
                    f"Experiment arms did not overlap at {schema_name}."
                ) from exc
            with self.lock:
                self.completed_stages.add(schema_name)
        return super().propose(
            prompt,
            schema_name=schema_name,
            reference_paths=reference_paths,
        )


class BaselineFailingTextProvider(FakeTextProvider):
    def propose(self, prompt: str, *, schema_name: str, reference_paths=None):
        reference_paths = list(reference_paths or [])
        if (
            schema_name == "graphic-design-proposal.schema.json"
            and not reference_paths
        ):
            raise RuntimeError("deliberate baseline failure")
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

    def generate(self, prompt: str, *, size: str, output: Path,
                 reference_paths=None):
        try:
            self.barrier.wait(timeout=3)
        except BrokenBarrierError as exc:
            raise AssertionError(
                "Comparison image generations did not overlap."
            ) from exc
        response = super().generate(
            prompt,
            size=size,
            output=output,
            reference_paths=reference_paths,
        )
        with self.lock:
            self.completed_calls += 1
        return response


class BaselineFailingImageProvider(FakeImageProvider):
    def generate(self, prompt: str, *, size: str, output: Path,
                 reference_paths=None):
        manifest = json.loads(
            (output.parent.parent / "manifest.json").read_text(encoding="utf-8")
        )
        if (
            manifest.get("experiment", {}).get("condition")
            == "baseline_no_explicit_corpus"
        ):
            raise RuntimeError("deliberate baseline image failure")
        return super().generate(
            prompt,
            size=size,
            output=output,
            reference_paths=reference_paths,
        )


class CorpusExperimentTests(unittest.TestCase):
    def _app(self, directory):
        text = FakeTextProvider()
        image = FakeImageProvider()
        app = CorpusAtelierApplication(
            runs_root=directory,
            text_provider=text,
            image_provider=image,
        )
        return app, text, image

    def test_paired_run_interprets_once_and_freezes_one_shared_brief(self):
        with TemporaryDirectory() as directory:
            app, text, image = self._app(directory)
            comparison = app.start_comparison(CorpusComparisonJob(
                case_id="mucha-watch-comparison",
                profile="rhetoric-graphic",
                request=REQUEST,
                snapshot=SNAPSHOT,
                reference=REFERENCE,
            ))

            intake_calls = [
                call for call in text.design_calls
                if call["schema_name"] == "graphic-design-brief.schema.json"
            ]
            self.assertEqual(len(intake_calls), 1)
            baseline_brief = json.loads(
                Path(comparison.baseline.artifacts["brief"]).read_text(encoding="utf-8")
            )
            corpus_brief = json.loads(
                Path(comparison.corpus.artifacts["brief"]).read_text(encoding="utf-8")
            )
            self.assertEqual(baseline_brief, corpus_brief)
            self.assertEqual(baseline_brief, comparison.brief)

            baseline_manifest = json.loads(Path(
                comparison.baseline.artifacts["manifest"]
            ).read_text(encoding="utf-8"))
            corpus_manifest = json.loads(Path(
                comparison.corpus.artifacts["manifest"]
            ).read_text(encoding="utf-8"))
            self.assertEqual(
                baseline_manifest["experiment"]["group_id"], comparison.group_id,
            )
            self.assertEqual(
                baseline_manifest["experiment"]["kind"],
                "corpus_generation_comparison",
            )
            self.assertEqual(
                corpus_manifest["experiment"]["group_id"], comparison.group_id,
            )
            self.assertEqual(
                baseline_manifest["experiment"]["shared_brief_sha256"],
                corpus_manifest["experiment"]["shared_brief_sha256"],
            )
            self.assertNotIn("corpus", baseline_manifest["experiment"])
            self.assertEqual(
                corpus_manifest["experiment"]["corpus"]["snapshot_id"],
                "mucha-job-design-knowledge-v1",
            )
            self.assertNotIn("reference_package", comparison.baseline.artifacts)
            self.assertIn("reference_package", comparison.corpus.artifacts)
            self.assertIn("reference_image", comparison.corpus.artifacts)

            proposal_calls = [
                call for call in text.design_calls
                if call["schema_name"] == "graphic-design-proposal.schema.json"
            ]
            self.assertEqual(len(proposal_calls), 2)
            baseline_call = next(
                call for call in proposal_calls if not call["reference_paths"]
            )
            corpus_call = next(
                call for call in proposal_calls if call["reference_paths"]
            )
            self.assertNotIn(
                "# Selected design knowledge — untrusted evidence",
                baseline_call["prompt"],
            )
            self.assertIn(
                "# Selected design knowledge — untrusted evidence",
                corpus_call["prompt"],
            )
            image_spec_calls = [
                call for call in text.design_calls
                if call["schema_name"] == "image-spec.schema.json"
            ]
            self.assertEqual(len(image_spec_calls), 2)

            completed = app.resume_comparison(
                comparison,
                HumanDecision(True, reviewer="test"),
            )
            self.assertEqual(completed.baseline.status, "completed")
            self.assertEqual(completed.corpus.status, "completed")
            self.assertEqual(image.calls, 2)
            self.assertEqual(image.reference_paths, [])
            for result in (completed.baseline, completed.corpus):
                approval = json.loads(
                    Path(result.artifacts["approval"]).read_text(encoding="utf-8")
                )
                self.assertTrue(approval["approved"])
            group_manifest = json.loads(
                (comparison.group_dir / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(group_manifest["status"], "completed")
            self.assertEqual(set(group_manifest["arm_statuses"].values()), {"completed"})

    def test_paired_arms_overlap_at_both_model_call_stages(self):
        with TemporaryDirectory() as directory:
            text = ConcurrentTextProvider()
            app = CorpusAtelierApplication(
                runs_root=directory,
                text_provider=text,
                image_provider=FakeImageProvider(),
            )

            comparison = app.start_comparison(CorpusComparisonJob(
                case_id="parallel-comparison",
                profile="rhetoric-graphic",
                request=REQUEST,
                snapshot=SNAPSHOT,
                reference=REFERENCE,
            ))

            self.assertEqual(
                text.completed_stages,
                ConcurrentTextProvider.concurrent_schemas,
            )
            self.assertEqual(comparison.baseline.status, "awaiting_approval")
            self.assertEqual(comparison.corpus.status, "awaiting_approval")

    def test_paired_image_generations_overlap_after_one_approval(self):
        with TemporaryDirectory() as directory:
            image = ConcurrentImageProvider()
            app = CorpusAtelierApplication(
                runs_root=directory,
                text_provider=FakeTextProvider(),
                image_provider=image,
            )
            comparison = app.start_comparison(CorpusComparisonJob(
                case_id="parallel-generation-comparison",
                profile="rhetoric-graphic",
                request=REQUEST,
                snapshot=SNAPSHOT,
                reference=REFERENCE,
            ))

            completed = app.resume_comparison(
                comparison,
                HumanDecision(True, reviewer="test"),
            )

            self.assertEqual(image.completed_calls, 2)
            self.assertEqual(completed.baseline.status, "completed")
            self.assertEqual(completed.corpus.status, "completed")

    def test_one_rejection_cancels_both_arms_without_image_calls(self):
        with TemporaryDirectory() as directory:
            app, _, image = self._app(directory)
            comparison = app.start_comparison(CorpusComparisonJob(
                case_id="rejected-comparison",
                profile="rhetoric-graphic",
                request=REQUEST,
                snapshot=SNAPSHOT,
                reference=REFERENCE,
            ))

            rejected = app.resume_comparison(
                comparison,
                HumanDecision(False, reviewer="test"),
            )

            self.assertEqual(rejected.baseline.status, "rejected")
            self.assertEqual(rejected.corpus.status, "rejected")
            self.assertEqual(image.calls, 0)

    def test_paired_image_failure_preserves_the_other_arm_result(self):
        with TemporaryDirectory() as directory:
            app = CorpusAtelierApplication(
                runs_root=directory,
                text_provider=FakeTextProvider(),
                image_provider=BaselineFailingImageProvider(),
            )
            comparison = app.start_comparison(CorpusComparisonJob(
                case_id="partial-generation-failure",
                profile="rhetoric-graphic",
                request=REQUEST,
                snapshot=SNAPSHOT,
                reference=REFERENCE,
            ))

            completed = app.resume_comparison(
                comparison,
                HumanDecision(True, reviewer="test"),
            )

            self.assertEqual(completed.baseline.status, "failed")
            self.assertEqual(completed.corpus.status, "completed")
            group_manifest = json.loads(
                (comparison.group_dir / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(group_manifest["status"], "failed")
            self.assertEqual(
                group_manifest["arm_statuses"],
                {
                    "baseline_no_explicit_corpus": "failed",
                    "explicit_corpus": "completed",
                },
            )

    def test_paired_failure_records_both_arm_ids_and_observed_statuses(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            app = CorpusAtelierApplication(
                runs_root=root,
                text_provider=BaselineFailingTextProvider(),
                image_provider=FakeImageProvider(),
            )

            with self.assertRaisesRegex(RuntimeError, "deliberate baseline failure"):
                app.start_comparison(CorpusComparisonJob(
                    case_id="partial-failure-comparison",
                    profile="rhetoric-graphic",
                    request=REQUEST,
                    snapshot=SNAPSHOT,
                    reference=REFERENCE,
                ))

            manifests = list(
                (root / "_comparisons" / "partial-failure-comparison").glob(
                    "comparison_*/manifest.json"
                )
            )
            self.assertEqual(len(manifests), 1)
            group_manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
            self.assertEqual(group_manifest["status"], "failed")
            self.assertEqual(
                set(group_manifest["arms"]),
                {"baseline_no_explicit_corpus", "explicit_corpus"},
            )
            self.assertEqual(
                group_manifest["arm_statuses"],
                {
                    "baseline_no_explicit_corpus": "failed",
                    "explicit_corpus": "awaiting_approval",
                },
            )
            for run_id in group_manifest["arms"].values():
                self.assertTrue(
                    (root / "partial-failure-comparison" / run_id / "manifest.json").is_file()
                )

    def test_single_explicit_condition_is_labelled_and_bound_to_approval(self):
        with TemporaryDirectory() as directory:
            app, _, image = self._app(directory)
            started = app.start_experiment(CorpusExperimentJob(
                case_id="mucha-watch",
                profile="rhetoric-graphic",
                request=REQUEST,
                condition="explicit_corpus",
                snapshot=SNAPSHOT,
                reference=REFERENCE,
            ))
            manifest = json.loads(Path(
                started.artifacts["manifest"]
            ).read_text(encoding="utf-8"))
            self.assertEqual(
                manifest["experiment"]["condition"], "explicit_corpus",
            )
            self.assertEqual(
                manifest["experiment"]["kind"], "corpus_generation_experiment",
            )
            package = Path(started.artifacts["reference_package"])
            value = json.loads(package.read_text(encoding="utf-8"))
            value["reference"]["title"] = "changed after preview"
            package.write_text(json.dumps(value), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "changed after preview"):
                app.resume(started.run_id, HumanDecision(True, reviewer="test"))
            self.assertEqual(image.calls, 0)

    def test_baseline_rejects_corpus_inputs(self):
        with TemporaryDirectory() as directory:
            app, _, _ = self._app(directory)
            with self.assertRaisesRegex(ValueError, "cannot include corpus inputs"):
                app.start_experiment(CorpusExperimentJob(
                    case_id="mucha-watch",
                    profile="rhetoric-graphic",
                    request=REQUEST,
                    condition="baseline_no_explicit_corpus",
                    snapshot=SNAPSHOT,
                    reference=REFERENCE,
                ))

    def test_snapshot_binds_both_image_and_design_knowledge(self):
        package, image_path = build_reference_package(SNAPSHOT, REFERENCE)
        reference = package["reference"]
        self.assertTrue(image_path.is_file())
        self.assertEqual(len(reference["sha256"]), 64)
        self.assertEqual(len(reference["design_knowledge_sha256"]), 64)
        self.assertIn("# Transferable design knowledge", reference["design_knowledge"])

        with TemporaryDirectory() as directory:
            copied = Path(directory) / "snapshot"
            shutil.copytree(SNAPSHOT, copied)
            knowledge = copied / "design-knowledge.md"
            knowledge.write_text(
                knowledge.read_text(encoding="utf-8") + "\nchanged",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "Design knowledge.*changed"):
                load_snapshot(copied)

    def test_unknown_reference_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "absent from the snapshot"):
            build_reference_package(SNAPSHOT, {
                "format_version": 1,
                "reference_id": "missing",
            })

    def test_external_corpus_change_invalidates_existing_approval(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            copied = root / "snapshot"
            shutil.copytree(SNAPSHOT, copied)
            app, _, image = self._app(root / "runs")
            started = app.start_experiment(CorpusExperimentJob(
                case_id="mucha-watch",
                profile="rhetoric-graphic",
                request=REQUEST,
                condition="explicit_corpus",
                snapshot=copied,
                reference=REFERENCE,
            ))
            knowledge = copied / "design-knowledge.md"
            knowledge.write_text(
                knowledge.read_text(encoding="utf-8") + "\nchanged",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "Design knowledge.*changed"):
                app.resume(started.run_id, HumanDecision(True, reviewer="test"))
            self.assertEqual(image.calls, 0)

    def test_stable_request_remains_outside_the_experiment_contract(self):
        with TemporaryDirectory() as directory:
            app, _, _ = self._app(directory)
            result = app.start_request(NaturalLanguageDesignJob(
                case_id="natural-language",
                profile="rhetoric-graphic",
                request=REQUEST,
            ))
            manifest = json.loads(Path(
                result.artifacts["manifest"]
            ).read_text(encoding="utf-8"))
            self.assertNotIn("experiment", manifest)
            self.assertNotIn("reference_package", result.artifacts)


if __name__ == "__main__":
    unittest.main()
