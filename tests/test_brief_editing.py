"""User edits are durable, authoritative inputs rather than model suggestions."""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from corpus_atelier.artifacts.records import read_json, write_json
from corpus_atelier.state import HumanDecision, NaturalLanguageDesignJob
from tests import test_conversation as fixtures
from tests.test_conversation import ConversationTextProvider
from tests.test_language import LanguageTextProvider


class BriefEditingTests(unittest.TestCase):
    app = fixtures.ConversationTests.app
    job = fixtures.ConversationTests.job

    def ready(self, app, profile="rhetoric-graphic"):
        task = app.create_conversation(NaturalLanguageDesignJob("brief-edit", profile, "Design a reading poster."))
        app.continue_task(task.run_id)
        return task, app.conversation(task.run_id)

    def test_manual_save_for_every_profile_is_exact_and_makes_no_model_call(self):
        for profile in ("rhetoric-graphic", "art-graphic", "rhetoric-poster", "art-article-cover"):
            with self.subTest(profile=profile), TemporaryDirectory() as directory:
                text = ConversationTextProvider()
                with self.app(directory, text) as app:
                    task, original = self.ready(app, profile)
                    brief = deepcopy(original["design_brief"])
                    brief.update(exact_copy=["  欢度国庆  ", "1949–2026"], constraints=[],
                                 user_requirements=["花篮必须有拱形提手。"])
                    field = "purpose" if "purpose" in brief else "article_summary"
                    brief[field] = "A purpose entered directly by the user."
                    if "canvas" in brief:
                        brief["canvas"]["aspect_ratio"] = {"width": 2, "height": 3}
                    calls = len(text.design_calls) + len(text.chat_calls)
                    app.save_conversation_brief(task.run_id, brief, expected_revision=original["revision"])
                    saved = app.conversation(task.run_id)
                    self.assertEqual(saved["design_brief"], brief)
                    self.assertEqual(saved["user_requirements"], brief["user_requirements"])
                    self.assertEqual(saved["suggested_user_requirements"], brief["user_requirements"])
                    self.assertEqual(len(text.design_calls) + len(text.chat_calls), calls)
                    self.assertEqual(saved["brief_history"][0]["brief"], original["design_brief"])
                    self.assertEqual(saved["brief_history"][-1]["brief"], brief)
                    child = app.create_conversation_round(task.run_id)
                    app.continue_task(child.run_id)
                    self.assertEqual(read_json(child.run_dir / "brief.json"), brief)
                    prompt = Path(app.open_task(child.run_id).artifacts["generation_prompt"]).read_text(encoding="utf-8")
                    self.assertIn("1949–2026", prompt)
                    self.assertIn("花篮必须有拱形提手。", prompt)

    def test_unrelated_discussion_cannot_restore_manually_deleted_or_changed_fields(self):
        with TemporaryDirectory() as directory:
            text = ConversationTextProvider()
            with self.app(directory, text) as app:
                task, original = self.ready(app)
                brief = deepcopy(original["design_brief"])
                brief.update(purpose="A user-authored purpose.", exact_copy=[], constraints=[], preferences=[])
                app.save_conversation_brief(task.run_id, brief, expected_revision=1)
                app.queue_conversation_message(task.run_id, "Make the background warmer.")
                app.continue_task(task.run_id)
                saved = app.conversation(task.run_id)
                for field in ("purpose", "exact_copy", "constraints", "preferences"):
                    self.assertEqual(saved["design_brief"][field], brief[field])
                self.assertEqual(len(saved["brief_history"]), 2)
                self.assertIn('"design_brief"', text.chat_calls[-1]["prompt"])
            with self.app(directory, text) as reopened:
                self.assertEqual(reopened.conversation(task.run_id)["manual_brief_fields"]["exact_copy"], [])

    def test_editing_historical_brief_creates_new_revision_and_invalidates_old_approval(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            task, initial = self.ready(app)
            child = app.create_conversation_round(task.run_id)
            app.continue_task(child.run_id)
            frozen = (child.run_dir / "brief.json").read_bytes()
            edited = deepcopy(initial["design_brief"])
            edited["purpose"] = "A new purpose."
            app.save_conversation_brief(task.run_id, edited, expected_revision=1)
            app.save_conversation_brief(task.run_id, initial["design_brief"], expected_revision=2, source_revision=1)
            saved = app.conversation(task.run_id)
            self.assertEqual(saved["revision"], 3)
            self.assertEqual(saved["brief_history"][-1]["based_on"], 1)
            self.assertEqual(saved["brief_history"][0]["brief"], initial["design_brief"])
            self.assertEqual((child.run_dir / "brief.json").read_bytes(), frozen)
            with self.assertRaisesRegex(ValueError, "superseded"):
                app.resume(child.run_id, HumanDecision(True))

    def test_stale_invalid_and_noop_edits_leave_saved_state_untouched(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            task, initial = self.ready(app)
            app.save_conversation_brief(task.run_id, initial["design_brief"], expected_revision=1)
            self.assertEqual(app.conversation(task.run_id), initial)
            for change, kwargs in (({"purpose": ""}, {}), ({"unknown": "field"}, {}),
                                   ({"user_requirements": [" "]}, {}), ({"content_language": "zh-CN"}, {}),
                                   ({}, {"expected_revision": 0}), ({}, {"source_revision": 999}),
                                   ({}, {"open_questions": [""]})):
                with self.subTest(change=change, kwargs=kwargs), self.assertRaises(ValueError):
                    app.save_conversation_brief(task.run_id, {**initial["design_brief"], **change},
                                                **{"expected_revision": 1, **kwargs})
                self.assertEqual(app.conversation(task.run_id), initial)
            app.queue_conversation_message(task.run_id, "Use a blue background.")
            pending = app.conversation(task.run_id)
            with self.assertRaisesRegex(ValueError, "Wait"):
                app.save_conversation_brief(task.run_id, initial["design_brief"], expected_revision=1)
            self.assertEqual(app.conversation(task.run_id), pending)

    def test_resolving_questions_in_editor_enables_preparation(self):
        with TemporaryDirectory() as directory:
            text = ConversationTextProvider()
            text.questions = ["Which audience is intended?"]
            with self.app(directory, text) as app:
                task, initial = self.ready(app)
                edited = {**initial["design_brief"], "audience": "Workshop attendees."}
                app.save_conversation_brief(task.run_id, edited, expected_revision=1, open_questions=[])
                self.assertEqual(app.create_conversation_round(task.run_id).status, "created")

    def test_promoted_single_round_brief_can_be_used_as_revision_zero_source(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            previous = app.start_request(self.job())
            original = read_json(previous.run_dir / "brief.json")
            task = app.create_conversation(self.job("Continue with warmer colors."), previous_run_id=previous.run_id)
            app.continue_task(task.run_id)
            saved = app.conversation(task.run_id)
            self.assertEqual(saved["brief_history"][0]["revision"], 0)
            language = saved["content_language"] or saved["brief_proposals"][-1]["brief"]["content_language"]
            edited = {**original, "content_language": language, "purpose": "An edited original brief."}
            app.save_conversation_brief(task.run_id, edited, expected_revision=0, source_revision=0)
            self.assertEqual(app.conversation(task.run_id)["brief_history"][-1]["based_on"], 0)
            self.assertEqual(read_json(previous.run_dir / "brief.json"), original)

    def test_legacy_turn_history_is_recovered_without_rewriting_source_files(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            task, initial = self.ready(app)
            app.queue_conversation_message(task.run_id, "Use warmer colors.")
            app.continue_task(task.run_id)
            path = task.run_dir / "conversation.json"
            value = read_json(path)
            del value["brief_history"]
            del value["manual_brief_fields"]
            write_json(path, value)
            before = path.read_bytes()
            recovered = app.conversation(task.run_id)
            self.assertEqual([item["revision"] for item in recovered["brief_history"]], [1])
            self.assertEqual(recovered["brief_history"][0]["brief"], initial["design_brief"])
            self.assertEqual(path.read_bytes(), before)

    def test_explicit_language_refresh_preserves_manual_source_copy_and_ratio(self):
        with TemporaryDirectory() as directory:
            text = LanguageTextProvider()
            with self.app(directory, text) as app:
                task, initial = self.ready(app)
                brief = {**initial["design_brief"], "purpose": "手动确认的设计目的。",
                         "exact_copy": ["  保留原文  "], "canvas": {"aspect_ratio": {"width": 4, "height": 5}}}
                app.save_conversation_brief(task.run_id, brief, expected_revision=1)
                # The fixture also retains exact source data during a language refresh.
                propose = text.propose
                def translated(prompt, *, schema_name, reference_paths=None):
                    value, response = propose(prompt, schema_name=schema_name, reference_paths=reference_paths)
                    if schema_name.endswith("-brief.schema.json"):
                        value.update(exact_copy=brief["exact_copy"], canvas=brief["canvas"])
                    return value, response
                text.propose = translated
                app.refresh_conversation_brief(task.run_id, expected_revision=2, content_language="en")
                app.continue_task(task.run_id)
                pending = app.conversation(task.run_id)
                self.assertEqual(pending["design_brief"], brief)
                app.save_conversation_brief(task.run_id, pending["brief_proposals"][-1]["brief"], expected_revision=pending["revision"])
                saved = app.conversation(task.run_id)
                self.assertEqual(saved["content_language"], "en")
                self.assertEqual(saved["design_brief"]["exact_copy"], brief["exact_copy"])
                self.assertEqual(saved["manual_brief_fields"]["purpose"], saved["design_brief"]["purpose"])
