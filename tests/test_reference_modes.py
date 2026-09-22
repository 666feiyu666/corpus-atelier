import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from corpus_atelier.application import CorpusAtelierApplication
from corpus_atelier.materials import build_reference_package
from corpus_atelier.state import DesignJob, HumanDecision
from tests.fakes import FakeImageProvider, FakeTextProvider


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "experiments/atlas-snapshot/mucha-commercial"
CASES = ROOT / "experiments/cases/mucha-watch"
REFERENCE_ID = "mucha-poster-124474277"
REFERENCE = {"format_version": 1, "reference_id": REFERENCE_ID}


def load_brief(mode):
    return json.loads((CASES / f"{mode}-brief.json").read_text(encoding="utf-8"))


class ReferenceModeTests(unittest.TestCase):
    def _start(self, mode):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        text = FakeTextProvider()
        image = FakeImageProvider()
        app = CorpusAtelierApplication(
            runs_root=temporary.name, text_provider=text, image_provider=image,
        )
        result = app.start(DesignJob(
            case_id="mucha-watch",
            profile="rhetoric-poster",
            brief=load_brief(mode),
            generation_mode="with_corpus",
            snapshot=SNAPSHOT,
            reference=REFERENCE,
        ))
        return app, text, image, result

    def test_grounded_designer_reads_the_selected_image_directly(self):
        _, text, image, result = self._start("grounded")
        self.assertEqual(result.status, "awaiting_approval")
        self.assertEqual(image.calls, 0)
        self.assertEqual(len(text.design_calls), 1)
        self.assertEqual(len(text.design_calls[0]["reference_paths"]), 1)
        self.assertIn("Style-grounded reference relationship", text.design_calls[0]["prompt"])
        proposal = json.loads(Path(result.artifacts["proposal"]).read_text(encoding="utf-8"))
        self.assertNotIn("evidence_ids", proposal)
        self.assertIn("reference_package", result.artifacts)
        self.assertNotIn("reference_plan", result.artifacts)

    def test_same_reference_is_used_for_design_and_generation(self):
        app, text, image, result = self._start("grounded")
        result = app.resume(result.run_id, HumanDecision(True, reviewer="test"))
        self.assertEqual(result.status, "awaiting_final_decision")
        self.assertEqual(image.reference_paths, text.design_calls[0]["reference_paths"])

    def test_inspired_mode_changes_the_direct_designer_contract(self):
        _, text, _, result = self._start("inspired")
        self.assertEqual(result.status, "awaiting_approval")
        self.assertIn(
            "loose visual inspiration",
            text.design_calls[0]["prompt"],
        )

    def test_unknown_reference_id_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "absent from the snapshot"):
            build_reference_package(SNAPSHOT, {
                "format_version": 1,
                "reference_id": "missing",
            })

    def test_reference_package_contains_no_text_knowledge(self):
        package, path = build_reference_package(SNAPSHOT, REFERENCE)
        self.assertEqual(package["reference"]["id"], REFERENCE_ID)
        self.assertNotIn("knowledge", package)
        self.assertTrue(path.is_file())

    def test_reference_package_change_invalidates_approval(self):
        app, _, image, result = self._start("grounded")
        package = Path(result.artifacts["reference_package"])
        value = json.loads(package.read_text(encoding="utf-8"))
        value["reference"]["title"] = "changed after approval preview"
        package.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "changed after preview"):
            app.resume(result.run_id, HumanDecision(True, reviewer="test"))
        self.assertEqual(image.calls, 0)


if __name__ == "__main__":
    unittest.main()
