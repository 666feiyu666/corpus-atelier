"""Ingest: archiving a finished atelier run into the corpus."""

import io
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from corpus_atelier.artifacts.records import write_json
from corpus_atelier.corpus.index import CorpusStore
from corpus_atelier.corpus.ingest import from_atelier_run, ingest_run


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 6), (200, 30, 30)).save(buf, format="PNG")
    return buf.getvalue()


class _RunFixture:
    def __init__(self, root: Path, status: str = "completed"):
        self.root = root
        self.run_dir = root / "case-1" / "20260101T000000Z_abcdef12"
        candidates = self.run_dir / "candidates" / "c01" / "generation"
        candidates.mkdir(parents=True)
        (candidates / "prompt.md").write_text("A vintage city poster\n", encoding="utf-8")
        image_dir = candidates / "attempt_01"
        image_dir.mkdir(parents=True)
        self.image_path = image_dir / "image.png"
        self.image_path.write_bytes(_png_bytes())
        write_json(self.run_dir / "manifest.json", {
            "format_version": 2,
            "workflow_version": 18,
            "case_id": "case-1",
            "run_id": "20260101T000000Z_abcdef12",
            "title": "t",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
            "input_mode": "natural_language",
            "status": status,
            "artifacts": {"generation_prompt": "candidates/c01/generation/prompt.md"},
            "models": {"image": {"adapter": "adapter", "model": "gpt-image-2", "quality": "high"}},
            "latest_image": str(self.image_path),
            "image_sha256": "x" * 64,
        })


class IngestTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_from_atelier_run_reads_run_artifacts(self):
        run = _RunFixture(self.root)
        record = from_atelier_run(run.run_dir, tags=["poster", "warm"])
        self.assertEqual(record["source"]["kind"], "atelier")
        self.assertEqual(record["source"]["run_id"], "20260101T000000Z_abcdef12")
        self.assertEqual(record["prompt"], "A vintage city poster")
        self.assertEqual(record["meta"]["model"], "gpt-image-2")
        self.assertEqual(record["meta"]["quality"], "high")
        self.assertEqual(record["image"]["width"], 4)
        self.assertEqual(record["image"]["height"], 6)
        self.assertEqual(len(record["image"]["sha256"]), 64)

    def test_unfinished_run_is_rejected(self):
        run = _RunFixture(self.root, status="awaiting_selection")
        with self.assertRaises(ValueError):
            from_atelier_run(run.run_dir, tags=["poster"])

    def test_ingest_run_copies_media_and_adds_record(self):
        run = _RunFixture(self.root)
        media_root = self.root / "media"
        store = CorpusStore(self.root / "corpus.sqlite3")
        try:
            record = ingest_run(
                store, run.run_dir, tags=["poster", "swiss-style"], media_root=media_root,
            )
            self.assertTrue((media_root / record["id"] / "image.png").is_file())
            self.assertEqual(record["image"]["path"], f"{record['id']}/image.png")
            self.assertEqual(store.get(record["id"])["prompt"], "A vintage city poster")
            self.assertEqual(store.count(), 1)
        finally:
            store.close()


class PromptSessionIngestTests(unittest.TestCase):
    """A prompt session archives the prompt that was actually sent for that image."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        from corpus_atelier.app.service import CorpusAtelierApplication
        from tests.fakes import FakeImageProvider, FakeTextProvider

        self.app = CorpusAtelierApplication(
            runs_root=self.root / "tasks",
            text_provider=FakeTextProvider(),
            image_provider=FakeImageProvider(),
        )
        self.session = self.app.start_from_prompt(
            "A poster of a paper lantern at dusk.", case_id="natural-language",
            settings={"image_quality": "medium", "aspect_ratio": [4, 3]},
        )

    def tearDown(self):
        self.app.close()
        self._tmp.cleanup()

    def _submit(self, action="generate", **kwargs):
        attempt = self.app.prepare_image_action(self.session.run_id, action=action, **kwargs)
        self.app.submit_image_action(
            self.session.run_id, attempt["id"], expected_digest=attempt["request_digest"],
        )
        session = self.app.prompt_session(self.session.run_id)
        return session["image_results"][-1]

    def test_the_exact_sent_prompt_is_archived(self):
        from corpus_atelier.corpus.ingest import from_prompt_session

        image = self._submit()
        record = from_prompt_session(
            self.session.run_dir, tags=["poster", "warm"], image_id=image["id"],
        )
        self.assertEqual(record["source"]["kind"], "atelier")
        self.assertEqual(record["source"]["run_id"], self.session.run_id)
        self.assertEqual(record["prompt"], "A poster of a paper lantern at dusk.")
        self.assertEqual(record["image"]["sha256"], image["sha256"])
        self.assertEqual(record["meta"]["model"], "fake-image")
        self.assertEqual(record["image"]["width"], 94)
        self.assertEqual(record["image"]["height"], 60)

    def test_an_edit_result_archives_the_edit_instruction(self):
        from corpus_atelier.corpus.ingest import from_prompt_session

        source = self._submit()
        edited = self._submit(
            "edit", source_image_id=source["id"],
            edit_instruction="Warm only the lantern light.",
        )
        record = from_prompt_session(
            self.session.run_dir, tags=["poster"], image_id=edited["id"],
        )
        self.assertEqual(record["prompt"], "Warm only the lantern light.")
        self.assertEqual(record["image"]["sha256"], edited["sha256"])

    def test_a_changed_image_is_rejected(self):
        from corpus_atelier.corpus.ingest import from_prompt_session

        image = self._submit()
        path = self.session.run_dir / image["image_path"]
        Image.new("RGB", (8, 8), (1, 2, 3)).save(path, format="PNG")
        with self.assertRaisesRegex(ValueError, "changed after it was generated"):
            from_prompt_session(self.session.run_dir, tags=["poster"], image_id=image["id"])

    def test_ingest_copies_media_and_adds_the_record(self):
        from corpus_atelier.corpus.ingest import ingest_prompt_session

        image = self._submit()
        media_root = self.root / "media"
        store = CorpusStore(self.root / "corpus.sqlite3")
        try:
            record = ingest_prompt_session(
                store, self.session.run_dir, tags=["poster"], media_root=media_root,
                image_id=image["id"],
            )
            self.assertTrue((media_root / record["id"] / "image.png").is_file())
            self.assertEqual(store.get(record["id"])["prompt"],
                             "A poster of a paper lantern at dusk.")
            self.assertEqual(store.count(), 1)
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
