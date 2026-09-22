import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from corpus_atelier.application import CorpusAtelierApplication
from corpus_atelier.design.validation import validate_reference_plan
from corpus_atelier.materials import build_material_package
from corpus_atelier.state import DesignJob, HumanDecision
from tests.fakes import FakeImageProvider, FakeTextProvider


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "experiments/atlas-snapshot/mucha-commercial"
CASES = ROOT / "experiments/cases/mucha-watch"
KNOWLEDGE_IDS = [
    "mucha-commercial-color-print-character",
    "mucha-commercial-product-rhetoric",
    "mucha-commercial-vertical-figure-organization",
]
REFERENCE_IDS = [
    "mucha-poster-124474277",
    "mucha-poster-124474282",
    "mucha-poster-124474229",
]


def load_brief(mode):
    return json.loads((CASES / f"{mode}-brief.json").read_text(encoding="utf-8"))


def selection(count=1):
    return {
        "format_version": 1,
        "knowledge_ids": KNOWLEDGE_IDS,
        "reference_ids": REFERENCE_IDS[:count],
    }


class ReferenceModeTests(unittest.TestCase):
    def _start(self, mode, count=1):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        text = FakeTextProvider()
        image = FakeImageProvider()
        app = CorpusAtelierApplication(
            runs_root=temporary.name, text_provider=text, image_provider=image,
        )
        brief = load_brief(mode)
        brief["reference_count"] = count
        result = app.start(DesignJob(
            profile="rhetoric-poster",
            brief=brief,
            snapshot=SNAPSHOT,
            materials=selection(count),
        ))
        return app, text, image, result

    def test_grounded_branch_uses_explicit_reference(self):
        _, text, image, result = self._start("grounded")
        self.assertEqual(result.status, "awaiting_approval")
        self.assertEqual(image.calls, 0)
        self.assertEqual(len(text.reference_calls), 1)
        self.assertEqual(len(text.reference_calls[0]["image_paths"]), 1)
        self.assertEqual(
            text.reference_calls[0]["schema_name"], "style-grounded-plan.schema.json",
        )
        self.assertIn("materials_package", result.artifacts)
        self.assertIn("reference_plan", result.artifacts)

    def test_three_selected_references_are_used_for_planning_and_generation(self):
        app, text, image, result = self._start("grounded", count=3)
        self.assertEqual(len(text.reference_calls[0]["image_paths"]), 3)
        result = app.resume(result.run_id, HumanDecision(True, reviewer="test"))
        self.assertEqual(result.status, "awaiting_final_decision")
        self.assertEqual(image.reference_paths, text.reference_calls[0]["image_paths"])

    def test_inspired_branch_uses_its_distinct_contract(self):
        _, text, _, result = self._start("inspired")
        self.assertEqual(result.status, "awaiting_approval")
        self.assertEqual(
            text.reference_calls[0]["schema_name"], "style-inspired-plan.schema.json",
        )
        prompt = Path(result.artifacts["reference_prompt"]).read_text(encoding="utf-8")
        self.assertIn("independent contemporary design concept", prompt)

    def test_unknown_reference_id_is_rejected(self):
        plan = {
            "mode": "style_inspired",
            "independent_concept": "Independent concept.",
            "inspiration_mappings": [{
                "evidence_ids": ["invented-reference"],
                "source_attribute": "curve",
                "transformation": "abstract it",
                "destination": "background",
            }],
            "features_not_carried_forward": ["period figure", "complete border"],
            "human_review_questions": ["Is the mapping supported?"],
        }
        with self.assertRaisesRegex(ValueError, "unavailable evidence IDs"):
            validate_reference_plan(
                plan,
                schema_name="style-inspired-plan.schema.json",
                mode="style_inspired",
                available_ids={"real-reference"},
            )

    def test_reference_plan_may_cite_selected_knowledge(self):
        plan = {
            "mode": "style_inspired",
            "independent_concept": "Independent concept.",
            "inspiration_mappings": [{
                "evidence_ids": ["corpus-pattern"],
                "source_attribute": "curve",
                "transformation": "abstract it",
                "destination": "background",
            }],
            "features_not_carried_forward": ["period figure", "complete border"],
            "human_review_questions": ["Is the mapping supported?"],
        }
        self.assertEqual(
            validate_reference_plan(
                plan,
                schema_name="style-inspired-plan.schema.json",
                mode="style_inspired",
                available_ids={"corpus-pattern"},
            ),
            plan,
        )

    def test_material_selection_rejects_unknown_ids(self):
        value = selection()
        value["knowledge_ids"] = ["missing"]
        with self.assertRaisesRegex(ValueError, "absent from the snapshot"):
            build_material_package(SNAPSHOT, value)

    def test_material_selection_can_be_empty_for_no_corpus_baseline(self):
        package, paths = build_material_package(SNAPSHOT, {
            "format_version": 1,
            "knowledge_ids": [],
            "reference_ids": [],
        })
        self.assertEqual(package["knowledge"], [])
        self.assertEqual(package["references"], [])
        self.assertEqual(paths, [])

    def test_reference_plan_change_invalidates_approval(self):
        app, _, image, result = self._start("grounded")
        plan = Path(result.artifacts["reference_plan"])
        value = json.loads(plan.read_text(encoding="utf-8"))
        value["summary"] = "changed after approval preview"
        plan.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "reference artifacts changed"):
            app.resume(result.run_id, HumanDecision(True, reviewer="test"))
        self.assertEqual(image.calls, 0)


if __name__ == "__main__":
    unittest.main()
