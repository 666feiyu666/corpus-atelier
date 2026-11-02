"""Corpus record construction and validation."""

import unittest

from corpus_atelier.corpus.records import new_record, normalize_record


class CorpusRecordTests(unittest.TestCase):
    def test_new_record_fills_defaults(self):
        record = new_record(
            prompt="A warm city night poster",
            tags=["poster", "warm", "swiss-style"],
            source_kind="manual",
        )
        self.assertTrue(record["id"])
        self.assertTrue(record["created_at"])
        self.assertIsNone(record["negative_prompt"])
        self.assertIsNone(record["image"])
        self.assertEqual(record["source"]["kind"], "manual")
        self.assertEqual(record["meta"], {})
        self.assertEqual(record["translations"], {})

    def test_tags_are_deduplicated_in_declaration_order(self):
        record = new_record(
            prompt="poster", tags=["poster", "warm", "poster"], source_kind="manual",
        )
        self.assertEqual(record["tags"], ["poster", "warm"])

    def test_unknown_tag_is_rejected(self):
        with self.assertRaises(ValueError):
            new_record(prompt="x", tags=["poster", "not-a-tag"], source_kind="manual")

    def test_unknown_source_kind_is_rejected(self):
        with self.assertRaises(ValueError):
            new_record(prompt="x", tags=["poster"], source_kind="nonsense")

    def test_missing_prompt_is_rejected(self):
        with self.assertRaises(ValueError):
            new_record(prompt="", tags=["poster"], source_kind="manual")

    def test_atelier_source_keeps_run_id_for_traceability(self):
        record = new_record(
            prompt="cover",
            tags=["article-cover"],
            source_kind="atelier",
            source_run_id="run-123",
            meta={"model": "gpt-image-2", "quality": "high", "size": "1024x1024"},
            image={"path": "run-123/image.png", "sha256": "a" * 64},
        )
        self.assertEqual(record["source"]["run_id"], "run-123")
        self.assertEqual(record["meta"]["model"], "gpt-image-2")
        self.assertEqual(record["image"]["path"], "run-123/image.png")

    def test_bad_sha256_is_rejected(self):
        with self.assertRaises(ValueError):
            new_record(
                prompt="x",
                tags=["poster"],
                source_kind="manual",
                image={"path": "i.png", "sha256": "not-hex"},
            )

    def test_normalize_record_does_not_mutate_input(self):
        source = {
            "id": "r1",
            "prompt": "p",
            "tags": ["poster", "warm", "poster"],
            "source": {"kind": "manual"},
            "created_at": "2026-01-01T00:00:00+00:00",
        }
        out = normalize_record(source)
        self.assertEqual(out["tags"], ["poster", "warm"])
        self.assertEqual(source["tags"], ["poster", "warm", "poster"])

    def test_extra_field_is_rejected(self):
        with self.assertRaises(ValueError):
            normalize_record({
                "id": "r1",
                "prompt": "p",
                "tags": ["poster"],
                "source": {"kind": "manual"},
                "created_at": "2026-01-01T00:00:00+00:00",
                "surprise": True,
            })
