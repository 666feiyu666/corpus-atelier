import json
from pathlib import Path
import unittest

from corpus_atelier.design_support.validation import (
    load_schema,
    validate,
    validate_proposal,
)
from corpus_atelier.providers.text import _schema_for_openai
from corpus_atelier.registry import PROFILES, get_profile


class ProfileTests(unittest.TestCase):
    def test_structured_output_constants_and_enums_have_explicit_types(self):
        schema_names = {
            profile.proposal_schema for profile in PROFILES.values()
        } | {"design-direction-plan.schema.json"}

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
        } | {"design-direction-plan.schema.json"}

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

    def test_expected_profiles_are_registered(self):
        self.assertEqual(set(PROFILES), {
            "rhetoric-poster", "art-article-cover", "rhetoric-graphic", "art-graphic",
        })
        self.assertNotEqual(
            get_profile("rhetoric-poster").objective,
            get_profile("art-article-cover").objective,
        )

    def test_general_graphic_brief_accepts_open_delivery_and_explicit_canvas(self):
        brief = {
            "deliverable": "museum ticket graphic",
            "purpose": "Help visitors identify the evening program.",
            "audience": "Museum visitors",
            "use_context": "Printed on a narrow ticket and viewed at arm's length.",
            "exact_copy": ["NIGHT COLLECTION"],
            "constraints": [],
            "preferences": [],
            "canvas": {"aspect_ratio": {"width": 4, "height": 5}},
        }
        self.assertEqual(
            validate(brief, get_profile("rhetoric-graphic").brief_schema), brief,
        )

    def test_brief_schemas_are_strict(self):
        profile = get_profile("rhetoric-poster")
        with self.assertRaises(ValueError):
            validate({"topic": "incomplete"}, profile.brief_schema)

    def test_proposal_rejects_legacy_blocked_fields(self):
        proposal = {
            "candidate_id": "c01",
            "status": "needs_sources",
            "brief_interpretation": "A complete interpretation.",
            "chosen_direction": "A complete direction.",
            "design_description": "A complete visible design.",
            "design_rationale": "A concise rationale.",
            "review_criteria": [],
            "source_requirements": [
                "Provide references/objectives/rhetoric-led.md.",
            ],
            "clarification_questions": [],
        }

        with self.assertRaisesRegex(ValueError, "Additional properties"):
            validate_proposal(proposal, "graphic-design-proposal.schema.json")

    def test_proposal_requires_nonempty_implemented_design(self):
        proposal = {
            "candidate_id": "c01",
            "brief_interpretation": "A complete interpretation.",
            "chosen_direction": "A complete direction.",
            "design_description": "",
            "design_rationale": "A concise rationale.",
            "review_criteria": [],
        }

        with self.assertRaisesRegex(ValueError, "should be non-empty"):
            validate_proposal(proposal, "graphic-design-proposal.schema.json")

    def test_watch_has_one_mode_independent_brief(self):
        root = Path(__file__).resolve().parents[1] / "tests/fixtures/cases/mucha-watch"
        brief = json.loads((root / "brief.json").read_text(encoding="utf-8"))
        self.assertNotIn("reference_mode", brief)
        self.assertNotIn("corpus", brief["purpose"].lower())
        validate(brief, "poster-brief.schema.json")
