import json
from pathlib import Path
import unittest

from corpus_atelier.rag import retrieve


ROOT = Path(__file__).resolve().parents[1]


class RetrievalTests(unittest.TestCase):
    def test_snapshot_is_verified_and_bundle_is_diverse(self):
        query, candidates, bundle = retrieve(
            {"topic": "floral poster", "purpose": "visual rhetoric"},
            "rhetoric-poster", ROOT / "experiments/atlas-snapshot",
            evidence_mode="hybrid-rag",
        )
        self.assertIn("poster", query["terms"])
        self.assertTrue(candidates)
        self.assertEqual({row["kind"] for row in bundle["selected"]},
                         {"knowledge", "reference"})

    def test_no_rag_is_explicit(self):
        _, candidates, bundle = retrieve(
            {"topic": "anything"}, "rhetoric-poster",
            ROOT / "experiments/atlas-snapshot", evidence_mode="no-rag",
        )
        self.assertEqual(candidates, [])
        self.assertEqual(bundle["selected"], [])
