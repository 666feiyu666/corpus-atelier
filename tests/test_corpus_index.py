"""Corpus store: FTS5 keyword search and label filtering."""

import tempfile
import unittest
from pathlib import Path

from corpus_atelier.corpus.index import CorpusStore
from corpus_atelier.corpus.records import new_record


def _seed(store: CorpusStore) -> None:
    store.add(new_record(
        prompt="A vintage city travel poster with a skyline",
        tags=["poster", "warm", "swiss-style"],
        source_kind="manual",
        record_id="r-poster",
    ))
    store.add(new_record(
        prompt="A muted album cover for a jazz record",
        tags=["album-cover", "cool", "monochrome"],
        source_kind="manual",
        record_id="r-album",
    ))
    store.add(new_record(
        prompt="A flat vector social card for a product launch",
        tags=["social-card", "flat-vector", "vibrant"],
        source_kind="manual",
        record_id="r-card",
    ))


class CorpusStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = CorpusStore(Path(self._tmp.name) / "corpus.sqlite3")

    def tearDown(self):
        self.store.close()
        self._tmp.cleanup()

    def test_add_get_roundtrip(self):
        _seed(self.store)
        self.assertEqual(self.store.get("r-poster")["prompt"],
                         "A vintage city travel poster with a skyline")
        self.assertIsNone(self.store.get("missing"))

    def test_add_is_idempotent(self):
        _seed(self.store)
        self.store.add(new_record(
            prompt="updated poster",
            tags=["poster", "cool"],
            source_kind="manual",
            record_id="r-poster",
        ))
        self.assertEqual(self.store.count(), 3)
        self.assertEqual(self.store.get("r-poster")["prompt"], "updated poster")

    def test_keyword_search_matches_prompt(self):
        _seed(self.store)
        hits = self.store.search("jazz record")
        self.assertEqual([h["id"] for h in hits], ["r-album"])

    def test_search_matches_label_translation(self):
        _seed(self.store)
        hits = self.store.search("瑞士风格")
        self.assertEqual([h["id"] for h in hits], ["r-poster"])

    def test_tag_filter_is_anded(self):
        _seed(self.store)
        hits = self.store.search(tags=["poster", "warm"])
        self.assertEqual([h["id"] for h in hits], ["r-poster"])
        self.assertEqual(self.store.search(tags=["poster", "cool"]), [])

    def test_empty_query_lists_all_newest_first(self):
        _seed(self.store)
        self.assertEqual(len(self.store.search()), 3)

    def test_query_plus_tags(self):
        _seed(self.store)
        # "poster" matches r-poster; requiring warm keeps it (r-poster has warm).
        self.assertEqual(
            [h["id"] for h in self.store.search("poster", tags=["warm"])],
            ["r-poster"],
        )
        # "jazz" matches r-album, but warm is only on r-poster -> no intersection.
        self.assertEqual(self.store.search("jazz", tags=["warm"]), [])

    def test_limit(self):
        _seed(self.store)
        self.assertEqual(len(self.store.search(limit=1)), 1)

    def test_fts_operators_are_inert(self):
        _seed(self.store)
        # A query full of FTS operators must not raise and should simply not match.
        self.assertEqual(self.store.search('" OR * - :'), [])


if __name__ == "__main__":
    unittest.main()
