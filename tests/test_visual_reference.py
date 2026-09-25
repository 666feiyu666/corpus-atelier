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
REFERENCE_ID = "mucha-poster-124474232"
REFERENCE = {"format_version": 1, "reference_id": REFERENCE_ID}


def load_brief():
    return json.loads((CASES / "brief.json").read_text(encoding="utf-8"))


class VisualReferenceTests(unittest.TestCase):
    def _start(self):
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
            brief=load_brief(),
            generation_mode="with_corpus",
            snapshot=SNAPSHOT,
            reference=REFERENCE,
        ))
        return app, text, image, result

    def test_designer_receives_selected_image_and_corresponding_corpus_evidence(self):
        _, text, image, result = self._start()
        self.assertEqual(result.status, "awaiting_approval")
        self.assertEqual(image.calls, 0)
        self.assertEqual(len(text.design_calls), 2)
        self.assertEqual(len(text.design_calls[0]["reference_paths"]), 1)
        self.assertEqual(text.design_calls[1]["schema_name"], "image-spec.schema.json")
        self.assertEqual(text.design_calls[1]["reference_paths"], [])
        self.assertNotIn("reference relationship", text.design_calls[0]["prompt"].lower())
        self.assertIn(
            "# Selected design knowledge — untrusted evidence",
            text.design_calls[0]["prompt"],
        )
        self.assertIn("# Transferable design knowledge", text.design_calls[0]["prompt"])
        self.assertIn("## Relational product meaning", text.design_calls[0]["prompt"])
        self.assertIn("# Transfer boundaries", text.design_calls[0]["prompt"])
        self.assertNotIn("# Selected design knowledge", text.design_calls[1]["prompt"])
        proposal = json.loads(Path(result.artifacts["proposal"]).read_text(encoding="utf-8"))
        self.assertNotIn("evidence_ids", proposal)
        self.assertIn("wears the AURELIA wristwatch", proposal["design_description"])
        image_spec = json.loads(Path(result.artifacts["image_spec"]).read_text(encoding="utf-8"))
        self.assertIn("wears the AURELIA wristwatch", image_spec["subject_and_scene"])
        generation_prompt = Path(result.artifacts["generation_prompt"]).read_text(encoding="utf-8")
        self.assertIn("wears the AURELIA wristwatch", generation_prompt)
        self.assertNotIn("mucha-poster-124474232", generation_prompt)
        self.assertIn("reference_package", result.artifacts)
        self.assertNotIn("reference_plan", result.artifacts)
        manifest = json.loads(
            Path(result.artifacts["manifest"]).read_text(encoding="utf-8")
        )
        self.assertNotIn("reference_mode", manifest)

    def test_reference_is_used_for_design_but_not_sent_to_image_generation(self):
        app, text, image, result = self._start()
        preview = json.loads(Path(
            result.artifacts["generation_request_preview"]
        ).read_text(encoding="utf-8"))
        self.assertEqual(preview["operation"], "generation")
        self.assertNotIn("references", preview)
        result = app.resume(result.run_id, HumanDecision(True, reviewer="test"))
        self.assertEqual(result.status, "completed")
        self.assertEqual(len(text.design_calls[0]["reference_paths"]), 1)
        self.assertEqual(image.reference_paths, [])

    def test_without_corpus_uses_the_same_brief_without_reference_instructions(self):
        with TemporaryDirectory() as directory:
            text = FakeTextProvider()
            app = CorpusAtelierApplication(
                runs_root=directory,
                text_provider=text,
                image_provider=FakeImageProvider(),
            )
            result = app.start(DesignJob(
                case_id="mucha-watch",
                profile="rhetoric-poster",
                brief=load_brief(),
                generation_mode="without_corpus",
            ))
            self.assertEqual(result.status, "awaiting_approval")
            prompt = text.design_calls[0]["prompt"]
            self.assertNotIn("reference relationship", prompt.lower())
            self.assertNotIn("supplied Mucha commercial corpus", prompt)
            manifest = json.loads(
                Path(result.artifacts["manifest"]).read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["generation_mode"], "without_corpus")
            self.assertNotIn("reference_mode", manifest)

    def test_unknown_reference_id_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "absent from the snapshot"):
            build_reference_package(SNAPSHOT, {
                "format_version": 1,
                "reference_id": "missing",
            })

    def test_reference_package_contains_traceable_design_evidence(self):
        package, path = build_reference_package(SNAPSHOT, REFERENCE)
        self.assertEqual(package["reference"]["id"], REFERENCE_ID)
        self.assertEqual(
            package["reference"]["design_knowledge_file"], "design-knowledge.md",
        )
        self.assertIn(
            "# Transferable design knowledge",
            package["reference"]["design_knowledge"],
        )
        self.assertIn(
            "## Relational product meaning",
            package["reference"]["design_knowledge"],
        )
        self.assertTrue(path.is_file())

    def test_reference_package_change_invalidates_approval(self):
        app, _, image, result = self._start()
        package = Path(result.artifacts["reference_package"])
        value = json.loads(package.read_text(encoding="utf-8"))
        value["reference"]["title"] = "changed after approval preview"
        package.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "changed after preview"):
            app.resume(result.run_id, HumanDecision(True, reviewer="test"))
        self.assertEqual(image.calls, 0)


if __name__ == "__main__":
    unittest.main()
