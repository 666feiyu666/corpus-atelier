"""Fault injection at durable record boundaries, without provider API calls."""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from corpus_atelier.application import CorpusAtelierApplication
from corpus_atelier.artifacts.records import read_json, write_json, write_text
from corpus_atelier.state import NaturalLanguageDesignJob
from tests.fakes import FakeImageProvider
from tests.test_conversation import ConversationTextProvider, seed_brief


class RecoveryTests(unittest.TestCase):
    def app(self, root, text=None):
        return CorpusAtelierApplication(runs_root=root, text_provider=text or ConversationTextProvider(),
                                        image_provider=FakeImageProvider())

    def create(self, app):
        return app.create_conversation(NaturalLanguageDesignJob("recovery", "rhetoric-graphic", "Describe a basket."))

    def test_invalid_candidate_counts_are_rejected_before_task_creation(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            for count in (True, 1.0, "1", 0, 4):
                with self.subTest(count=count), self.assertRaisesRegex(ValueError, "Candidate limit"):
                    app.create_request(NaturalLanguageDesignJob("recovery", "rhetoric-graphic", "Describe a basket.", count))
            self.assertEqual(app.list_tasks(), [])

    def test_bad_conversation_does_not_block_the_task_list(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            healthy, damaged = self.create(app), self.create(app)
            path = damaged.run_dir / "conversation.json"
            path.write_text("{", encoding="utf-8")
            with self.assertLogs("corpus_atelier.artifacts.store", level="WARNING"):
                tasks = {task.run_id: task for task in app.list_tasks()}
            self.assertEqual(tasks[damaged.run_id].status, "failed")
            self.assertEqual(tasks[healthy.run_id].status, "discussing_request")
            self.assertEqual(path.read_text(encoding="utf-8"), "{")
            self.assertIsNotNone(app.conversation(healthy.run_id)["pending"])

    def test_bad_sibling_manifests_do_not_block_a_healthy_conversation(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            healthy, damaged = self.create(app), self.create(app)
            path = damaged.run_dir / "manifest.json"
            original = read_json(path)
            invalid = [[], None, {**original, "status": None}, {**original, "updated_at": 123},
                       {**original, "artifacts": []}, {**original, "run_id": healthy.run_id}]
            for value in invalid:
                with self.subTest(value=value):
                    write_json(path, value)
                    with self.assertLogs(level="WARNING"):
                        self.assertEqual([task.run_id for task in app.list_tasks()], [healthy.run_id])
                        self.assertIsNotNone(app.conversation(healthy.run_id)["pending"])

    def test_invalid_reply_cache_is_archived_and_can_be_replaced(self):
        for source in ("{", '{"reply": "incomplete"}'):
            with self.subTest(source=source), TemporaryDirectory() as directory:
                text = ConversationTextProvider()
                with self.app(directory, text) as app:
                    task = self.create(app)
                    pending = app.conversation(task.run_id)["pending"]
                    folder = task.run_dir / "conversation-turns" / pending["message_id"] / "dialogue"
                    folder.mkdir(parents=True)
                    (folder / "answer.json").write_text(source, encoding="utf-8")
                    app.store.update(task.run_dir, "failed", error="Invalid cache")
                    app.retry_conversation(task.run_id)
                    with self.assertLogs("corpus_atelier.assistant", level="WARNING"):
                        result = app.continue_task(task.run_id)
                    self.assertEqual(result.status, "discussing")
                    self.assertEqual(len(text.chat_calls), 1)
                    self.assertEqual(len(app.conversation(task.run_id)["messages"]), 2)
                    archived, = folder.glob("answer.invalid-*.json")
                    self.assertEqual(archived.read_text(encoding="utf-8"), source)

    def test_retry_after_reply_commit_failure_reuses_the_validated_answer(self):
        with TemporaryDirectory() as directory:
            text = ConversationTextProvider()
            with self.app(directory, text) as app:
                task = self.create(app)
                with patch.object(app, "_save_conversation", side_effect=OSError("Commit unavailable")):
                    with self.assertRaisesRegex(OSError, "Commit unavailable"):
                        app.continue_task(task.run_id)
                self.assertIsNotNone(app.conversation(task.run_id)["pending"])
            with self.app(directory, text) as reopened:
                reopened.retry_conversation(task.run_id)
                reopened.continue_task(task.run_id)
                self.assertEqual(len(text.chat_calls), 1)
                self.assertEqual(len(reopened.conversation(task.run_id)["messages"]), 2)

    def test_retry_after_final_status_failure_does_not_repeat_the_saved_reply(self):
        with TemporaryDirectory() as directory:
            text = ConversationTextProvider()
            with self.app(directory, text) as app:
                task = self.create(app)
                update = app.store.update

                def fail_final_status(root, status, **details):
                    if status == "discussing":
                        raise OSError("Status unavailable")
                    return update(root, status, **details)

                with patch.object(app.store, "update", side_effect=fail_final_status):
                    with self.assertRaisesRegex(OSError, "Status unavailable"):
                        app.continue_task(task.run_id)
                self.assertIsNone(app.conversation(task.run_id)["pending"])
                result = app.retry_conversation(task.run_id)
                self.assertEqual(result.status, "discussing")
                self.assertEqual(len(text.chat_calls), 1)
                self.assertEqual(len(app.conversation(task.run_id)["messages"]), 2)

    def test_failure_record_write_does_not_mask_the_provider_error(self):
        with TemporaryDirectory() as directory:
            text = ConversationTextProvider()
            text.fail = True
            with self.app(directory, text) as app:
                task = self.create(app)
                update = app.store.update

                def fail_error_record(root, status, **details):
                    if status == "failed":
                        raise OSError("Failure record unavailable")
                    return update(root, status, **details)

                with patch.object(app.store, "update", side_effect=fail_error_record):
                    with self.assertLogs("corpus_atelier.artifacts.store", level="ERROR"):
                        with self.assertRaisesRegex(RuntimeError, "Temporary conversation failure"):
                            app.continue_task(task.run_id)

    def test_interrupted_brief_publication_is_repaired_without_another_revision(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            task = self.create(app)
            app.continue_task(task.run_id)
            seed_brief(app, task.run_id)
            previous = app.conversation(task.run_id)
            brief = {**previous["design_brief"], "purpose": "A revised user-authored purpose."}
            save_json = app.store.json

            def fail_publication(root, relative, value):
                if root == task.run_dir and relative == "brief.json":
                    raise OSError("Publication unavailable")
                return save_json(root, relative, value)

            with patch.object(app.store, "json", side_effect=fail_publication):
                with self.assertRaisesRegex(OSError, "Publication unavailable"):
                    app.save_conversation_brief(task.run_id, brief, expected_revision=previous["revision"])
            saved = app.conversation(task.run_id)
            app.save_conversation_brief(task.run_id, brief, expected_revision=saved["revision"])
            self.assertEqual(read_json(task.run_dir / "brief.json"), brief)
            self.assertEqual(app.conversation(task.run_id), saved)
            files = [task.run_dir / name for name in ("conversation.json", "brief.json", "manifest.json")]
            before = [path.read_bytes() for path in files]
            app.save_conversation_brief(task.run_id, brief, expected_revision=saved["revision"])
            self.assertEqual([path.read_bytes() for path in files], before)

    def test_interrupted_brief_manifest_update_is_repaired_on_the_same_save(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            task = self.create(app)
            app.continue_task(task.run_id)
            seed_brief(app, task.run_id)
            previous = app.conversation(task.run_id)
            brief = {**previous["design_brief"], "content_language": "zh-CN"}
            with patch.object(app.store, "update", side_effect=OSError("Manifest unavailable")):
                with self.assertRaisesRegex(OSError, "Manifest unavailable"):
                    app.save_conversation_brief(task.run_id, brief, expected_revision=previous["revision"])
            saved = app.conversation(task.run_id)
            app.save_conversation_brief(task.run_id, brief, expected_revision=saved["revision"])
            self.assertEqual(app.store.manifest(task.run_dir)["content_language"], "zh-CN")
            self.assertEqual(app.conversation(task.run_id)["revision"], saved["revision"])

    def test_legacy_metadata_is_read_only_and_is_not_created_for_new_dialogues(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            task = self.create(app)
            value = app.conversation(task.run_id)
            legacy = {"manual_brief_fields": {"purpose": "Archived purpose"},
                      "requirement_interpretations": [{"source": "Archived source"}],
                      "suggested_user_requirements": ["Archived suggestion"]}
            self.assertTrue(legacy.keys().isdisjoint(value))
            path = task.run_dir / "conversation.json"
            write_json(path, {**value, **deepcopy(legacy)})
            before = path.read_bytes()
            loaded = app.conversation(task.run_id)
            for field, archived in legacy.items():
                self.assertEqual(loaded[field], archived)
            self.assertEqual(path.read_bytes(), before)

    def test_failed_atomic_writes_preserve_the_original_and_remove_temporary_files(self):
        for writer, value in ((write_text, "new"), (write_json, {"new": True})):
            with self.subTest(writer=writer), TemporaryDirectory() as directory:
                path = Path(directory) / "record.json"
                path.write_text("original", encoding="utf-8")
                with patch("corpus_atelier.artifacts.records._replace_record", side_effect=OSError("Replace unavailable")):
                    with self.assertRaisesRegex(OSError, "Replace unavailable"):
                        writer(path, value)
                self.assertEqual(path.read_text(encoding="utf-8"), "original")
                self.assertEqual(list(Path(directory).glob("*.tmp")), [])
