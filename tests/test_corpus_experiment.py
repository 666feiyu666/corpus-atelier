import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
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
            self.assertEqual(proposal_calls[0]["reference_paths"], [])
            self.assertEqual(len(proposal_calls[1]["reference_paths"]), 1)
            self.assertNotIn(
                "# Selected design knowledge — untrusted evidence",
                proposal_calls[0]["prompt"],
            )
            self.assertIn(
                "# Selected design knowledge — untrusted evidence",
                proposal_calls[1]["prompt"],
            )

            baseline = app.resume(
                comparison.baseline.run_id,
                HumanDecision(True, reviewer="test"),
            )
            corpus = app.resume(
                comparison.corpus.run_id,
                HumanDecision(True, reviewer="test"),
            )
            self.assertEqual(baseline.status, "completed")
            self.assertEqual(corpus.status, "completed")
            self.assertEqual(image.calls, 2)
            self.assertEqual(image.reference_paths, [])
            group_manifest = json.loads(
                (comparison.group_dir / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(group_manifest["status"], "completed")
            self.assertEqual(set(group_manifest["arm_statuses"].values()), {"completed"})

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
