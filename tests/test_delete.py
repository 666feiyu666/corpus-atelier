"""Permanent task deletion for single-round tasks and prompt sessions."""

import tempfile
import unittest
from pathlib import Path

from corpus_atelier.app.service import CorpusAtelierApplication
from corpus_atelier.artifacts.records import write_json
from tests.fakes import FakeImageProvider, FakeTextProvider


DOOMED_RUN = "20260101T000000Z_aaaaaaaa"
OTHER_RUN = "20260101T000020Z_cccccccc"
CASE = "natural-language"


def _write_task(run_dir: Path, *, run_id: str) -> None:
    run_dir.mkdir(parents=True)
    manifest = {
        "format_version": 2,
        "workflow_version": 19,
        "case_id": CASE,
        "run_id": run_id,
        "title": "task",
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "input_mode": "natural_language",
        "status": "completed",
    }
    write_json(run_dir / "manifest.json", manifest)


class DeleteTaskTests(unittest.TestCase):
    def _app(self, root: Path) -> CorpusAtelierApplication:
        return CorpusAtelierApplication(
            runs_root=root,
            checkpoint_path=root / "_system" / "checkpoints.sqlite3",
            text_provider=FakeTextProvider(),
            image_provider=FakeImageProvider(),
        )

    def test_delete_removes_one_task_and_keeps_the_others(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            doomed = root / CASE / DOOMED_RUN
            keep = root / CASE / OTHER_RUN
            _write_task(doomed, run_id=DOOMED_RUN)
            _write_task(keep, run_id=OTHER_RUN)

            app = self._app(root)
            try:
                deleted = app.delete_task(DOOMED_RUN)
                self.assertEqual(deleted, [DOOMED_RUN])
                self.assertFalse(doomed.exists())
                self.assertTrue(keep.exists())
                self.assertEqual([task.run_id for task in app.list_tasks()], [OTHER_RUN])
            finally:
                app.close()

    def test_delete_removes_a_prompt_session_with_its_attempts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = self._app(root)
            try:
                created = app.start_from_prompt(
                    "A prompt to delete.", case_id=CASE,
                    settings={"image_quality": "medium", "aspect_ratio": [1, 1]},
                )
                attempt = app.prepare_image_action(created.run_id, action="generate")
                self.assertTrue((created.run_dir / attempt["request_path"]).is_file())
                deleted = app.delete_task(created.run_id)
                self.assertEqual(deleted, [created.run_id])
                self.assertFalse(created.run_dir.exists())
                self.assertEqual(app.list_tasks(), [])
            finally:
                app.close()


if __name__ == "__main__":
    unittest.main()
