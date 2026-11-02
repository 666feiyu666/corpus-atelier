"""Permanent task deletion, including conversation rounds."""

import tempfile
import unittest
from pathlib import Path

from corpus_atelier.application import CorpusAtelierApplication
from corpus_atelier.artifacts.records import write_json
from tests.fakes import FakeImageProvider, FakeTextProvider


ROOT_RUN = "20260101T000000Z_aaaaaaaa"
ROUND_RUN = "20260101T000010Z_bbbbbbbb"
OTHER_RUN = "20260101T000020Z_cccccccc"
CASE = "natural-language"


def _write_task(run_dir: Path, *, run_id: str, is_conversation: bool,
                parent: str | None = None) -> None:
    run_dir.mkdir(parents=True)
    manifest = {
        "format_version": 2,
        "workflow_version": 18,
        "case_id": CASE,
        "run_id": run_id,
        "title": "task",
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "input_mode": "natural_language",
        "status": "discussing" if is_conversation else "completed",
    }
    if is_conversation:
        manifest["is_conversation"] = True
    if parent is not None:
        manifest["conversation_parent_id"] = parent
    write_json(run_dir / "manifest.json", manifest)


def _write_conversation(run_dir: Path, *, profile: str = "rhetoric-graphic") -> None:
    write_json(run_dir / "conversation.json", {
        "format_version": 8,
        "profile": profile,
        "content_language": "en",
        "discussion_language": "en",
        "language_source_request": "",
        "messages": [],
        "effective_request": "",
        "open_questions": [],
        "revision": 0,
        "discussion_revision": 0,
        "rounds": [],
        "pending": None,
        "user_requirements": [],
        "design_brief": None,
        "brief_revision": None,
        "brief_history": [],
    })


class DeleteTaskTests(unittest.TestCase):
    def _app(self, root: Path) -> CorpusAtelierApplication:
        return CorpusAtelierApplication(
            runs_root=root,
            checkpoint_path=root / "_system" / "checkpoints.sqlite3",
            text_provider=FakeTextProvider(),
            image_provider=FakeImageProvider(),
        )

    def test_delete_conversation_removes_all_rounds(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case = root / CASE
            root_dir = case / ROOT_RUN
            round_dir = case / ROUND_RUN
            _write_task(root_dir, run_id=ROOT_RUN, is_conversation=True)
            _write_conversation(root_dir)
            _write_task(round_dir, run_id=ROUND_RUN, is_conversation=False, parent=ROOT_RUN)

            app = self._app(root)
            try:
                deleted = app.delete_task(ROOT_RUN)
                self.assertIn(ROOT_RUN, deleted)
                self.assertIn(ROUND_RUN, deleted)
                self.assertFalse(root_dir.exists())
                self.assertFalse(round_dir.exists())
                self.assertEqual(app.list_tasks(), [])
            finally:
                app.close()

    def test_delete_keeps_other_conversations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case = root / CASE
            doomed = case / ROOT_RUN
            keep = case / OTHER_RUN
            _write_task(doomed, run_id=ROOT_RUN, is_conversation=True)
            _write_conversation(doomed)
            _write_task(keep, run_id=OTHER_RUN, is_conversation=True)
            _write_conversation(keep)

            app = self._app(root)
            try:
                app.delete_task(ROOT_RUN)
                self.assertFalse(doomed.exists())
                self.assertTrue(keep.exists())
                remaining = [task.run_id for task in app.list_tasks()]
                self.assertEqual(remaining, [OTHER_RUN])
            finally:
                app.close()

    def test_delete_single_task_without_conversation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir = root / CASE / OTHER_RUN
            _write_task(run_dir, run_id=OTHER_RUN, is_conversation=False)

            app = self._app(root)
            try:
                deleted = app.delete_task(OTHER_RUN)
                self.assertEqual(deleted, [OTHER_RUN])
                self.assertFalse(run_dir.exists())
            finally:
                app.close()


if __name__ == "__main__":
    unittest.main()
