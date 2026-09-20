import json
from pathlib import Path
import unittest

from corpus_atelier.rag import retrieve


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "experiments/atlas-snapshot/mucha-commercial"


class RetrievalTests(unittest.TestCase):
    def test_reference_control_fields_do_not_change_retrieval_query(self):
        common = {"topic": "women's watch", "purpose": "portrait advertisement"}
        grounded, _, _ = retrieve(
            {**common, "reference_mode": "style_grounded",
             "reference_scope": "all_snapshot_images"},
            "rhetoric-poster", SNAPSHOT, evidence_mode="hybrid-rag",
        )
        inspired, _, _ = retrieve(
            {**common, "reference_mode": "style_inspired",
             "reference_scope": "all_snapshot_images"},
            "rhetoric-poster", SNAPSHOT, evidence_mode="hybrid-rag",
        )
        self.assertEqual(grounded, inspired)

    def test_snapshot_is_verified_and_bundle_is_diverse(self):
        query, candidates, bundle = retrieve(
            {"topic": "floral poster", "purpose": "visual rhetoric"},
            "rhetoric-poster", SNAPSHOT,
            evidence_mode="hybrid-rag",
        )
        self.assertIn("poster", query["terms"])
        self.assertTrue(candidates)
        self.assertEqual({row["kind"] for row in bundle["selected"]},
                         {"knowledge", "reference"})

    def test_no_rag_is_explicit(self):
        _, candidates, bundle = retrieve(
            {"topic": "anything"}, "rhetoric-poster",
            SNAPSHOT, evidence_mode="no-rag",
        )
        self.assertEqual(candidates, [])
        self.assertEqual(bundle["selected"], [])
