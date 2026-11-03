"""Ingest: archiving a finished prompt-session result into the corpus."""

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from corpus_atelier.corpus.index import CorpusStore


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
