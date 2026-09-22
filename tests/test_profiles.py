import json
from pathlib import Path
import unittest

from corpus_atelier.design.validation import load_schema, validate
from corpus_atelier.providers.text import _schema_for_openai
from corpus_atelier.registry import PROFILES, get_profile


class ProfileTests(unittest.TestCase):
    def test_structured_output_constants_and_enums_have_explicit_types(self):
        schema_names = {
            profile.proposal_schema for profile in PROFILES.values()
        } | {
            profile.review_schema for profile in PROFILES.values()
        } | {
            "style-grounded-plan.schema.json",
            "style-inspired-plan.schema.json",
            "material-selection.schema.json",
        }

        def check_node(node, path):
            if isinstance(node, dict):
                if "const" in node or "enum" in node:
                    self.assertIn("type", node, f"Missing type at {path}")
                for key, value in node.items():
                    check_node(value, f"{path}.{key}")
            elif isinstance(node, list):
                for index, value in enumerate(node):
                    check_node(value, f"{path}[{index}]")

        for schema_name in schema_names:
            check_node(load_schema(schema_name), schema_name)

    def test_openai_schema_omits_unsupported_unique_items_keyword(self):
        schema_names = {
            profile.proposal_schema for profile in PROFILES.values()
        } | {
            profile.review_schema for profile in PROFILES.values()
        } | {
            "style-grounded-plan.schema.json",
            "style-inspired-plan.schema.json",
            "material-selection.schema.json",
        }

        def check_node(node, path):
            if isinstance(node, dict):
                self.assertNotIn("uniqueItems", node, f"Unsupported keyword at {path}")
                for key, value in node.items():
                    check_node(value, f"{path}.{key}")
            elif isinstance(node, list):
                for index, value in enumerate(node):
                    check_node(value, f"{path}[{index}]")

        for schema_name in schema_names:
            check_node(_schema_for_openai(schema_name), schema_name)

        local_schema = load_schema("style-grounded-plan.schema.json")
        local_evidence_ids = local_schema["properties"]["style_invariants"][
            "items"
        ]["properties"]["evidence_ids"]
        self.assertTrue(local_evidence_ids["uniqueItems"])

    def test_local_validation_still_rejects_duplicate_evidence_ids(self):
        plan = {
            "mode": "style_grounded",
            "summary": "A cross-reference style system.",
            "style_invariants": [
                {
                    "claim": "Repeated framing pattern.",
                    "evidence_ids": ["same-reference", "same-reference"],
                    "application": "Use a new framing system.",
                },
                {
                    "claim": "Repeated lettering pattern.",
                    "evidence_ids": ["reference-a", "reference-b"],
                    "application": "Integrate lettering into the composition.",
                },
            ],
            "allowed_variations": ["Vary the product composition."],
            "content_mapping_rules": ["Map the focal hierarchy to the new subject."],
            "work_specific_features_to_exclude": ["Do not copy a complete layout."],
            "human_review_questions": ["Is the pattern supported by multiple works?"],
        }

        with self.assertRaises(ValueError):
            validate(plan, "style-grounded-plan.schema.json")

    def test_expected_profiles_are_registered(self):
        self.assertEqual(set(PROFILES), {
            "rhetoric-poster", "art-article-cover", "rhetoric-graphic", "art-graphic",
        })
        self.assertNotEqual(
            get_profile("rhetoric-poster").objective,
            get_profile("art-article-cover").objective,
        )

    def test_general_graphic_brief_accepts_open_delivery_and_auto_canvas(self):
        brief = {
            "deliverable": "museum ticket graphic",
            "purpose": "Help visitors identify the evening program.",
            "audience": "Museum visitors",
            "use_context": "Printed on a narrow ticket and viewed at arm's length.",
            "exact_copy": ["NIGHT COLLECTION"],
            "constraints": [],
            "preferences": [],
            "canvas": {"mode": "auto"},
        }
        self.assertEqual(
            validate(brief, get_profile("rhetoric-graphic").brief_schema), brief,
        )

    def test_brief_schemas_are_strict(self):
        profile = get_profile("rhetoric-poster")
        with self.assertRaises(ValueError):
            validate({"topic": "incomplete"}, profile.brief_schema)

    def test_watch_briefs_are_paired_except_for_reference_mode(self):
        root = Path(__file__).resolve().parents[1] / "experiments/cases/mucha-watch"
        grounded = json.loads((root / "grounded-brief.json").read_text(encoding="utf-8"))
        inspired = json.loads((root / "inspired-brief.json").read_text(encoding="utf-8"))
        self.assertEqual(grounded.pop("reference_mode"), "style_grounded")
        self.assertEqual(inspired.pop("reference_mode"), "style_inspired")
        self.assertEqual(grounded, inspired)
        validate({**grounded, "reference_mode": "style_grounded"}, "poster-brief.schema.json")
