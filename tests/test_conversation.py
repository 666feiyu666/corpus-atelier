"""Offline checks for dialogue persistence and user-authored design rounds."""

from io import BytesIO
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PIL import Image

from corpus_atelier.application import CorpusAtelierApplication
from corpus_atelier.language import compile_language_policy
from corpus_atelier.registry import get_profile
from corpus_atelier.state import CandidateSelection, HumanDecision, NaturalLanguageDesignJob
from tests.fakes import FakeImageProvider, FakeTextProvider


class ConversationTextProvider(FakeTextProvider):
    def __init__(self):
        super().__init__()
        self.chat_calls = []
        self.fail = False
        self.reply = "A rounded basket body has an arched handle."
        self.override_brief = None

    def propose(self, prompt, *, schema_name, reference_paths=None):
        if schema_name == "design-assistant.schema.json":
            context = json.loads(prompt[prompt.index('{"effective_request"'):])
            self.chat_calls.append({"prompt": prompt, "references": list(reference_paths or [])})
            if self.fail:
                raise RuntimeError("Temporary conversation failure")
            return {"content_language": context["content_language"] or "en", "language_change_quote": None,
                    "reply": self.reply}, {"status": "completed", "provider": "fake-assistant"}
        value, response = super().propose(prompt, schema_name=schema_name, reference_paths=reference_paths)
        if schema_name.endswith("-brief.schema.json") and self.override_brief is not None:
            value = json.loads(json.dumps(self.override_brief))
        return value, response


def image_bytes(format="PNG"):
    buffer = BytesIO()
    Image.new("RGB", (64, 48), (20, 60, 100)).save(buffer, format=format)
    return buffer.getvalue()


def seed_brief(app, run_id):
    """Save a user fixture explicitly for tests that need a ready design round."""
    value = app.conversation(run_id)
    language = value["content_language"] or value.get("discussion_language") or "en"
    brief, _ = app.runtime.text_provider.propose(
        compile_language_policy(language), schema_name=get_profile(value["profile"]).brief_schema)
    brief["content_language"] = language
    app.save_conversation_brief(run_id, brief, expected_revision=value["revision"])


class ConversationTests(unittest.TestCase):
    def continue_chat(self, app, run_id):
        result = app.continue_task(run_id)
        if app.conversation(run_id)["design_brief"] is None:
            seed_brief(app, run_id)
        return result

    def app(self, root, text=None, image=None):
        return CorpusAtelierApplication(runs_root=root,
            text_provider=text or ConversationTextProvider(), image_provider=image or FakeImageProvider())

    def job(self, request="Design a poster with exact title 读书会."):
        return NaturalLanguageDesignJob("conversation-test", "rhetoric-graphic", request, 1)

    def test_frozen_brief_rejects_a_mismatched_requirement_snapshot(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            root = app.create_conversation(self.job())
            self.continue_chat(app, root.run_id)
            child = app.create_conversation_round(root.run_id)
            path = child.run_dir / "conversation/snapshot.json"
            snapshot = json.loads(path.read_text(encoding="utf-8"))
            snapshot["user_requirements"] = ["An unreviewed change."]
            path.write_text(json.dumps(snapshot), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "confirmed user requirements"):
                app.continue_task(child.run_id)
            self.assertEqual(app.open_task(child.run_id).status, "failed")

    def test_legacy_conversations_load_defaults_without_rewriting_archived_data(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            root = app.create_conversation(self.job())
            self.continue_chat(app, root.run_id)
            path = root.run_dir / "conversation.json"
            legacy = json.loads(path.read_text(encoding="utf-8"))
            for key in ("user_requirements", "suggested_user_requirements",
                        "superseded_user_requirements", "requirement_history", "design_brief",
                        "brief_revision", "requirement_interpretations"):
                legacy.pop(key, None)
            legacy["format_version"] = 1
            path.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
            before = path.read_bytes()
            self.assertEqual(app.conversation(root.run_id)["user_requirements"], [])
            self.assertEqual(path.read_bytes(), before)
            app.queue_conversation_message(root.run_id, "Use blue.")
            self.continue_chat(app, root.run_id)
            current = app.conversation(root.run_id)
            app.save_conversation_brief(root.run_id, {**current["design_brief"], "user_requirements": ["Include a cat."]}, expected_revision=current["revision"])
            self.assertEqual(app.conversation(root.run_id)["format_version"], 8)

    def test_concurrent_messages_do_not_overwrite_each_other(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            root = app.create_conversation(self.job())
            self.continue_chat(app, root.run_id)
            def send(text):
                with self.app(directory) as other:
                    try:
                        other.queue_conversation_message(root.run_id, text)
                        return True
                    except ValueError:
                        return False
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(send, ["Use blue.", "Use green."]))
            self.assertEqual(sorted(results), [False, True])
            self.assertEqual(len(app.conversation(root.run_id)["messages"]), 3)

    def test_interrupted_round_index_update_recovers_link_and_snapshot(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            root = app.create_conversation(self.job())
            self.continue_chat(app, root.run_id)
            with patch.object(app, "_save_conversation", side_effect=RuntimeError("Stopped during index update")):
                with self.assertRaises(RuntimeError):
                    app.create_conversation_round(root.run_id)
            recovered = app.conversation(root.run_id)
            self.assertEqual(len(recovered["rounds"]), 1)
            child_id = recovered["rounds"][0]["run_id"]
            self.assertIn("conversation_snapshot", app.open_task(child_id).artifacts)
            app.continue_task(child_id)
            app.resume(child_id, HumanDecision(True))
            self.assertEqual(app.open_task(child_id).status, "awaiting_selection")

    def test_pending_message_is_recoverable_when_manifest_update_was_interrupted(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            root = app.create_conversation(self.job())
            app.store.update(root.run_dir, "discussing")
            summaries = app.list_tasks()
            self.assertEqual(summaries[0].status, "discussing_request")
            self.continue_chat(app, root.run_id)
            self.assertEqual(app.open_task(root.run_id).status, "discussing")

    def test_windows_record_contention_is_retried_without_losing_data(self):
        from corpus_atelier.artifacts.records import read_json, write_json
        with TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            replace = Path.replace
            attempts = []
            def contend_once(temporary, target):
                attempts.append(target)
                if len(attempts) == 1:
                    raise PermissionError("Sharing violation")
                return replace(temporary, target)
            with patch.object(Path, "replace", contend_once):
                write_json(path, {"revision": 2})
            self.assertEqual(read_json(path), {"revision": 2})
            self.assertEqual(len(attempts), 2)

    def test_reference_feedback_two_rounds_survive_restart_and_generate_from_text(self):
        with TemporaryDirectory() as directory:
            text = ConversationTextProvider()
            image = FakeImageProvider()
            upload = image_bytes("JPEG")
            with self.app(directory, text, image) as app:
                root = app.create_conversation(self.job(), attachments=[("palette.jpg", upload)])
                self.assertEqual(image.calls, 0)
                self.continue_chat(app, root.run_id)
                saved = app.conversation(root.run_id)
                self.assertIn("读书会", saved["messages"][0]["text"])
                path = root.run_dir / saved["messages"][0]["attachments"][0]["path"]
                self.assertEqual(path.read_bytes(), upload)
                self.assertEqual(path.suffix, ".jpg")
                first = app.create_conversation_round(root.run_id)
                planned = app.continue_task(first.run_id)
                self.assertEqual(planned.status, "awaiting_approval")
                self.assertEqual(image.calls, 0)
                generated = app.resume(first.run_id, HumanDecision(True))
                self.assertEqual(generated.status, "awaiting_selection")
                self.assertEqual(image.reference_paths, [])
                app.resume(first.run_id, CandidateSelection("c01"))
                original_prompt = Path(app.open_task(first.run_id).artifacts["generation_prompt"]).read_text(encoding="utf-8")
                app.queue_conversation_message(root.run_id, "Make the title larger and reduce clutter.",
                                               feedback_run_id=first.run_id, candidate_id="c01")

            with self.app(directory, text, image) as app:
                self.continue_chat(app, root.run_id)
                feedback = text.chat_calls[-1]
                self.assertEqual(len(feedback["references"]), 2)
                context = json.loads(feedback["prompt"][feedback["prompt"].index('{"effective_request"'):])
                self.assertEqual(context["previous_round"]["candidates"][0]["generation_prompt"], original_prompt)
                self.assertIn("Make the title larger", feedback["prompt"])
                live = app.conversation(root.run_id)
                app.save_conversation_brief(root.run_id, {**live["design_brief"], "constraints": ["Make the title larger and reduce clutter."]}, expected_revision=live["revision"])
                second = app.create_conversation_round(root.run_id)
                app.continue_task(second.run_id)
                self.assertEqual(json.loads((second.run_dir / "brief.json").read_text(encoding="utf-8")),
                                 app.conversation(root.run_id)["design_brief"])
                app.resume(second.run_id, HumanDecision(True))
                self.assertEqual(image.reference_paths, [])
                self.assertEqual(image.calls, 2)
                saved = app.conversation(root.run_id)
                self.assertEqual([r["run_id"] for r in saved["rounds"]], [first.run_id, second.run_id])
                self.assertTrue(Path(app.open_task(first.run_id).artifacts["image"]).exists())
                self.assertEqual(Path(app.open_task(first.run_id).artifacts["generation_prompt"]).read_text(encoding="utf-8"), original_prompt)
                snapshot = json.loads(Path(app.open_task(second.run_id).artifacts["conversation_snapshot"]).read_text(encoding="utf-8"))
                self.assertEqual(snapshot["revision"], 2)
                message = next(m for m in saved["messages"] if m["text"] == "Make the title larger and reduce clutter.")
                discussion_prompt = (root.run_dir / "conversation-turns" / message["id"] / "dialogue/prompt.md").read_text(encoding="utf-8")
                self.assertIn("Make the title larger", discussion_prompt)
                self.assertEqual(app.conversation(root.run_id)["design_brief"]["constraints"], ["Make the title larger and reduce clutter."])

    def test_failed_reply_retries_saved_message_without_duplicate_turns(self):
        with TemporaryDirectory() as directory:
            text = ConversationTextProvider()
            with self.app(directory, text) as app:
                root = app.create_conversation(self.job(), attachments=[("ref.png", image_bytes())])
                text.fail = True
                with self.assertRaises(RuntimeError):
                    self.continue_chat(app, root.run_id)
                self.assertEqual(app.open_task(root.run_id).status, "failed")
                with self.assertRaises(ValueError):
                    app.queue_conversation_message(root.run_id, "Another message")
            text.fail = False
            with self.app(directory, text) as app:
                app.retry_conversation(root.run_id)
                self.continue_chat(app, root.run_id)
                saved = app.conversation(root.run_id)
                self.assertEqual(len(saved["messages"]), 2)
                self.assertEqual(saved["revision"], 1)
                self.assertIsNone(saved["pending"])
                app.run_conversation(root.run_id)
                self.assertEqual(len(app.conversation(root.run_id)["messages"]), 2)

    def test_only_saved_feedback_invalidates_approval_and_preserves_previous_round(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            root = app.create_conversation(self.job())
            self.continue_chat(app, root.run_id)
            first = app.create_conversation_round(root.run_id)
            app.queue_conversation_message(root.run_id, "Explain the design while it is processing.")
            self.continue_chat(app, root.run_id)
            app.continue_task(first.run_id)
            before = app.conversation(root.run_id)
            app.queue_conversation_message(root.run_id, "Use green instead of blue.")
            self.continue_chat(app, root.run_id)
            self.assertEqual(app.conversation(root.run_id)["revision"], before["revision"])
            changed = {**before["design_brief"], "constraints": ["Use green instead of blue."]}
            app.save_conversation_brief(root.run_id, changed, expected_revision=before["revision"])
            with self.assertRaisesRegex(ValueError, "superseded"):
                app.resume(first.run_id, HumanDecision(True))
            second = app.create_conversation_round(root.run_id)
            self.assertNotEqual(first.run_id, second.run_id)
            self.assertEqual(app.open_task(first.run_id).status, "awaiting_approval")

    def test_legacy_task_can_continue_without_overwriting_graph_artifacts(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            original = app.start_request(self.job())
            index = Path(app.open_task(original.run_id).artifacts["candidate_index"])
            before = index.read_bytes()
            root = app.create_conversation(self.job("Use only its blue palette."), previous_run_id=original.run_id)
            self.continue_chat(app, root.run_id)
            saved = app.conversation(root.run_id)
            self.assertEqual(saved["rounds"][0]["run_id"], original.run_id)
            self.assertEqual(index.read_bytes(), before)
            self.assertEqual(app.inspect_task(original.run_id).manifest["conversation_parent_id"], root.run_id)

    def test_invalid_upload_and_feedback_are_rejected_without_losing_history(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            with self.assertRaises(Exception):
                app.create_conversation(self.job(), attachments=[("bad.png", b"not an image")])
            self.assertEqual(app.list_tasks(), [])
            root = app.create_conversation(self.job(), attachments=[("ref.png", image_bytes())])
            self.continue_chat(app, root.run_id)
            before = app.conversation(root.run_id)
            other = app.start_request(self.job())
            with self.assertRaises(ValueError):
                app.queue_conversation_message(root.run_id, "Feedback", feedback_run_id=other.run_id)
            self.assertEqual(app.conversation(root.run_id), before)
            path = root.run_dir / before["messages"][0]["attachments"][0]["path"]
            path.write_bytes(image_bytes("JPEG"))
            app.queue_conversation_message(root.run_id, "Use more blue.")
            with self.assertRaisesRegex(ValueError, "changed"):
                self.continue_chat(app, root.run_id)
