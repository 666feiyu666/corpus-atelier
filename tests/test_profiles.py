import json
from pathlib import Path
import unittest

from corpus_atelier.design.validation import validate, validate_revision_review
from corpus_atelier.registry import PROFILES, get_profile


class ProfileTests(unittest.TestCase):
    def test_expected_profiles_are_registered(self):
        self.assertEqual(set(PROFILES), {"rhetoric-poster", "art-article-cover"})
        self.assertNotEqual(
            get_profile("rhetoric-poster").objective,
            get_profile("art-article-cover").objective,
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

    def test_accepted_revision_cannot_hide_regressions(self):
        plan = {
            "must_preserve": ["Preserve exact copy."],
        }
        review = {
            "verdict": "accept",
            "requested_change_met": True,
            "requested_change_evidence": ["The local defect is absent."],
            "preservation_checks": [{
                "criterion": "Preserve exact copy.", "passed": True,
                "evidence": "Copy remains visible.",
            }],
            "regressions": ["A new artifact appeared."],
            "copy_check": {"passed": True, "observed_copy": ["Exact"], "notes": ""},
            "uncertainties": [],
        }
        with self.assertRaisesRegex(ValueError, "reported regressions"):
            validate_revision_review(review, plan)
