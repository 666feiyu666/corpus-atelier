"""Offline checks for conversation persistence and text-only design rounds."""

from io import BytesIO
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PIL import Image

from corpus_atelier.application import CorpusAtelierApplication
from corpus_atelier.state import CandidateSelection, HumanDecision, NaturalLanguageDesignJob
from tests.fakes import FakeImageProvider, FakeTextProvider


class ConversationTextProvider(FakeTextProvider):
    def __init__(self):
        super().__init__()
        self.chat_calls = []
        self.fail = False
        self.questions = []
        self.suggested_requirements = None
        self.fail_brief = False
        self.interpretations = {}
        self.bad_sources = False
        self.override_brief = None

    def propose(self, prompt, *, schema_name, reference_paths=None):
        if schema_name != "design-conversation.schema.json":
            if schema_name.endswith("-brief.schema.json") and self.fail_brief:
                raise RuntimeError("Temporary brief synthesis failure")
            value, response = super().propose(prompt, schema_name=schema_name, reference_paths=reference_paths)
            if schema_name.endswith("-brief.schema.json") and self.override_brief is not None:
                value = json.loads(json.dumps(self.override_brief))
            return value, response
        self.chat_calls.append({"prompt": prompt, "references": list(reference_paths or [])})
        if self.fail:
            raise RuntimeError("Temporary conversation failure")
        context = json.loads(prompt[prompt.index('{"effective_request"'):])
        value = {
            "reply": "已更新设计需求。",
            "effective_request": context["effective_request"] + "\n" + context["conversation"][-1]["text"],
            "reference_notes": ["Reference 1: adopt the blue palette; reject its composition."],
            "open_questions": self.questions,
            "suggested_user_requirements": (context["user_requirements"] if context["pending_kind"] == "requirements_update"
                                             else self.suggested_requirements
                                             if self.suggested_requirements is not None
                                             else context["suggested_user_requirements"]),
            "requirement_interpretations": [
                {"source": "Changed source" if self.bad_sources else source,
                 "interpretation": self.interpretations.get(source, source)}
                for source in context["user_requirements"]
            ],
        }
        return value, {"status": "completed", "provider": "fake-conversation"}


def image_bytes(format="PNG"):
    buffer = BytesIO()
    Image.new("RGB", (64, 48), (20, 60, 100)).save(buffer, format=format)
    return buffer.getvalue()


class ConversationTests(unittest.TestCase):
    def app(self, root, text=None, image=None):
        return CorpusAtelierApplication(runs_root=root,
            text_provider=text or ConversationTextProvider(), image_provider=image or FakeImageProvider())

    def job(self, request="Design a poster with exact title 读书会."):
        return NaturalLanguageDesignJob("conversation-test", "rhetoric-graphic", request, 1)

    def confirm_requirements(self, app, run_id, requirements):
        revision = app.conversation(run_id)["revision"]
        result = app.update_user_requirements(run_id, requirements, expected_revision=revision)
        if result.status == "discussing_request":
            app.continue_task(run_id)

    def test_live_brief_exists_before_design_for_every_profile(self):
        for profile in ("rhetoric-graphic", "art-graphic", "rhetoric-poster", "art-article-cover"):
            with self.subTest(profile=profile), TemporaryDirectory() as directory, self.app(directory) as app:
                root = app.create_conversation(NaturalLanguageDesignJob("live-brief", profile, "Design a reading club graphic."))
                app.continue_task(root.run_id)
                saved = app.conversation(root.run_id)
                self.assertEqual(saved["rounds"], [])
                self.assertEqual(saved["brief_revision"], saved["revision"])
                brief = json.loads(Path(app.open_task(root.run_id).artifacts["brief"]).read_text(encoding="utf-8"))
                self.assertEqual(brief, saved["design_brief"])
                self.assertIn("constraints", brief)

    def test_specific_basket_style_retains_source_and_freezes_the_reviewed_brief(self):
        source = "花篮必须是浅色藤编的椭圆篮，带一个拱形提手。"
        interpretation = "篮体为椭圆形，使用浅色藤编材质，上方设置单个拱形提手。"
        with TemporaryDirectory() as directory:
            text = ConversationTextProvider()
            image = FakeImageProvider()
            with self.app(directory, text, image) as app:
                root = app.create_conversation(self.job("Design a flower basket event poster."))
                app.continue_task(root.run_id)
                initial = app.conversation(root.run_id)["design_brief"]
                text.override_brief = {
                    **initial, "purpose": "Promote the flower basket workshop.",
                    "exact_copy": ["花篮工坊 · 秋日限定"],
                    "constraints": [interpretation],
                    "canvas": {"aspect_ratio": {"width": 4, "height": 5}},
                }
                text.interpretations[source] = interpretation
                self.confirm_requirements(app, root.run_id, [source])
                reviewed = app.conversation(root.run_id)
                self.assertEqual(reviewed["user_requirements"], [source])
                self.assertEqual(reviewed["requirement_interpretations"], [{"source": source, "interpretation": interpretation}])
                self.assertIn(interpretation, reviewed["design_brief"]["constraints"])
                calls_before_round = len(text.design_calls)
                text.override_brief = {**initial, "exact_copy": ["Unexpected new title"]}
                child = app.create_conversation_round(root.run_id)
                self.assertEqual(json.loads((child.run_dir / "brief.json").read_text(encoding="utf-8")), reviewed["design_brief"])
                app.continue_task(child.run_id)
                self.assertEqual([call["schema_name"] for call in text.design_calls[calls_before_round:]],
                                 ["design-direction-plan.schema.json", "graphic-design-proposal.schema.json", "image-spec.schema.json"])
                prompt = (child.run_dir / "candidates/c01/generation/prompt.md").read_text(encoding="utf-8")
                self.assertIn(source, prompt)
                self.assertIn("花篮工坊 · 秋日限定", prompt)
                self.assertNotIn("Unexpected new title", prompt)
                self.assertEqual(image.calls, 0)
                app.resume(child.run_id, HumanDecision(True))
                self.assertEqual(image.calls, 1)
                frozen_bytes = (child.run_dir / "brief.json").read_bytes()
                app.queue_conversation_message(root.run_id, "Use a different background.")
                app.continue_task(root.run_id)
                self.assertEqual((child.run_dir / "brief.json").read_bytes(), frozen_bytes)

    def test_failed_brief_update_retries_without_repeating_reply_or_losing_previous_brief(self):
        with TemporaryDirectory() as directory:
            text = ConversationTextProvider()
            with self.app(directory, text) as app:
                root = app.create_conversation(self.job())
                app.continue_task(root.run_id)
                previous = app.conversation(root.run_id)["design_brief"]
                app.queue_conversation_message(root.run_id, "Use a warmer palette.")
                text.fail_brief = True
                with self.assertRaisesRegex(RuntimeError, "brief synthesis"):
                    app.continue_task(root.run_id)
                self.assertEqual(app.conversation(root.run_id)["design_brief"], previous)
                self.assertEqual(app.open_task(root.run_id).status, "failed")
                calls_after_failure = len(text.chat_calls)
            text.fail_brief = False
            with self.app(directory, text) as app:
                app.retry_conversation(root.run_id)
                app.continue_task(root.run_id)
                saved = app.conversation(root.run_id)
                self.assertEqual(len(text.chat_calls), calls_after_failure)
                self.assertEqual(len(saved["messages"]), 4)
                self.assertEqual(saved["brief_revision"], saved["revision"])
                self.assertIsNone(saved["pending"])

    def test_requirement_interpretation_cannot_rewrite_the_original_source(self):
        with TemporaryDirectory() as directory:
            text = ConversationTextProvider()
            with self.app(directory, text) as app:
                root = app.create_conversation(self.job())
                app.continue_task(root.run_id)
                previous = app.conversation(root.run_id)["design_brief"]
                app.update_user_requirements(root.run_id, ["花篮必须是藤编的。"], expected_revision=1)
                text.bad_sources = True
                with self.assertRaisesRegex(ValueError, "original user requirements"):
                    app.continue_task(root.run_id)
                self.assertEqual(app.conversation(root.run_id)["user_requirements"], ["花篮必须是藤编的。"])
                self.assertEqual(app.conversation(root.run_id)["design_brief"], previous)
                with self.assertRaisesRegex(ValueError, "Wait"):
                    app.create_conversation_round(root.run_id)
                text.bad_sources = False
                app.retry_conversation(root.run_id)
                app.continue_task(root.run_id)
                self.assertEqual(app.conversation(root.run_id)["requirement_interpretations"][0]["source"], "花篮必须是藤编的。")

    def test_ambiguous_specific_requirements_remain_visible_and_block_preparation(self):
        with TemporaryDirectory() as directory:
            text = ConversationTextProvider()
            with self.app(directory, text) as app:
                root = app.create_conversation(self.job())
                app.continue_task(root.run_id)
                text.questions = ["花篮的 xxx 样式具体指什么？"]
                self.confirm_requirements(app, root.run_id, ["花篮必须是 xxx 样式。"])
                saved = app.conversation(root.run_id)
                self.assertEqual(saved["user_requirements"], ["花篮必须是 xxx 样式。"])
                self.assertEqual(saved["open_questions"], text.questions)
                with self.assertRaisesRegex(ValueError, "outstanding design questions"):
                    app.create_conversation_round(root.run_id)

    def test_frozen_brief_rejects_a_mismatched_requirement_snapshot(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            root = app.create_conversation(self.job())
            app.continue_task(root.run_id)
            child = app.create_conversation_round(root.run_id)
            path = child.run_dir / "conversation/snapshot.json"
            snapshot = json.loads(path.read_text(encoding="utf-8"))
            snapshot["user_requirements"] = ["An unreviewed change."]
            path.write_text(json.dumps(snapshot), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "confirmed user requirements"):
                app.continue_task(child.run_id)
            self.assertEqual(app.open_task(child.run_id).status, "failed")

    def test_confirmed_requirements_survive_discussion_and_reach_every_generation_stage(self):
        requirements = ["画面中必须有一只猫。", "Keep the subject in the lower right corner."]
        with TemporaryDirectory() as directory:
            text = ConversationTextProvider()
            image = FakeImageProvider()
            with self.app(directory, text, image) as app:
                root = app.create_conversation(self.job())
                app.continue_task(root.run_id)
                self.confirm_requirements(app, root.run_id, requirements)
                reviewed = app.conversation(root.run_id)["design_brief"]
                brief_call_count = sum(call["schema_name"].endswith("-brief.schema.json") for call in text.design_calls)
                first = app.create_conversation_round(root.run_id)
                app.continue_task(first.run_id)
                brief = json.loads((first.run_dir / "brief.json").read_text(encoding="utf-8"))
                self.assertEqual(brief, reviewed)
                self.assertEqual(sum(call["schema_name"].endswith("-brief.schema.json") for call in text.design_calls), brief_call_count)
                self.assertFalse((first.run_dir / "intake").exists())
                # The fake brief synthesis omits this field; the frozen contract must still survive.
                self.assertEqual(brief["user_requirements"], requirements)
                plan = json.loads((first.run_dir / "design-direction/plan.json").read_text(encoding="utf-8"))
                self.assertEqual(plan["shared_invariants"]["user_requirements"], requirements)
                for relative in (
                    "design-direction/prompt.md",
                    "candidates/c01/design-implementation/prompt.md",
                    "candidates/c01/image-spec/prompt.md", "candidates/c01/generation/prompt.md",
                ):
                    prompt = (first.run_dir / relative).read_text(encoding="utf-8")
                    for requirement in requirements:
                        self.assertIn(requirement, prompt)
                self.assertEqual(image.calls, 0)
                app.resume(first.run_id, HumanDecision(True))
                self.assertEqual(image.calls, 1)
                app.queue_conversation_message(root.run_id, "Use a warmer palette.")

            with self.app(directory, text, image) as app:
                app.continue_task(root.run_id)
                saved = app.conversation(root.run_id)
                self.assertEqual(saved["user_requirements"], requirements)
                second = app.create_conversation_round(root.run_id)
                app.continue_task(second.run_id)
                snapshot = json.loads((second.run_dir / "conversation/snapshot.json").read_text(encoding="utf-8"))
                self.assertEqual(snapshot["user_requirements"], requirements)
                self.assertEqual(snapshot["requirement_history"][0]["requirements"], requirements)
                final_prompt = (second.run_dir / "candidates/c01/generation/prompt.md").read_text(encoding="utf-8")
                self.assertIn(requirements[0], final_prompt)

    def test_suggestions_require_confirmation_and_contract_edits_invalidate_old_approval(self):
        with TemporaryDirectory() as directory:
            text = ConversationTextProvider()
            with self.app(directory, text) as app:
                root = app.create_conversation(self.job())
                app.continue_task(root.run_id)
                self.confirm_requirements(app, root.run_id, ["Include exactly one cat."])
                first = app.create_conversation_round(root.run_id)
                app.continue_task(first.run_id)
                snapshot_path = first.run_dir / "conversation/snapshot.json"
                original_snapshot = snapshot_path.read_bytes()
                text.suggested_requirements = ["Include exactly one dog."]
                app.queue_conversation_message(root.run_id, "Replace the cat with a dog.")
                app.continue_task(root.run_id)
                saved = app.conversation(root.run_id)
                self.assertEqual(saved["user_requirements"], ["Include exactly one cat."])
                text.suggested_requirements = None
                app.queue_conversation_message(root.run_id, "Use a warm palette, too.")
                app.continue_task(root.run_id)
                saved = app.conversation(root.run_id)
                self.assertEqual(saved["suggested_user_requirements"], ["Include exactly one dog."])
                with self.assertRaisesRegex(ValueError, "Confirm or reject"):
                    app.create_conversation_round(root.run_id)
                self.confirm_requirements(app, root.run_id, saved["suggested_user_requirements"])
                with self.assertRaisesRegex(ValueError, "superseded"):
                    app.resume(first.run_id, HumanDecision(True))
                second = app.create_conversation_round(root.run_id)
                app.continue_task(second.run_id)
                prompt = (second.run_dir / "candidates/c01/generation/prompt.md").read_text(encoding="utf-8")
                self.assertIn("Include exactly one dog.", prompt)
                self.assertNotIn("Include exactly one cat.", prompt)
                message_id = app.conversation(root.run_id)["messages"][-2]["id"]
                intake = (root.run_dir / "conversation-turns" / message_id / "brief/prompt.md").read_text(encoding="utf-8")
                self.assertIn('"superseded_user_requirements"', intake)
                self.assertIn("Include exactly one cat.", intake)
                self.assertEqual(snapshot_path.read_bytes(), original_snapshot)

    def test_rejecting_suggestions_and_deleting_requirements_are_durable(self):
        with TemporaryDirectory() as directory:
            text = ConversationTextProvider()
            text.suggested_requirements = ["Include a brand logo."]
            with self.app(directory, text) as app:
                root = app.create_conversation(self.job())
                app.continue_task(root.run_id)
                self.assertEqual(app.conversation(root.run_id)["user_requirements"], [])
                self.confirm_requirements(app, root.run_id, [])
                self.confirm_requirements(app, root.run_id, ["Include one cat."])
                self.confirm_requirements(app, root.run_id, [])
            with self.app(directory, text) as app:
                saved = app.conversation(root.run_id)
                self.assertEqual(saved["user_requirements"], [])
                self.assertEqual(saved["suggested_user_requirements"], [])
                self.assertEqual(saved["superseded_user_requirements"], ["Include a brand logo.", "Include one cat."])
                child = app.create_conversation_round(root.run_id)
                app.continue_task(child.run_id)
                brief = json.loads((child.run_dir / "brief.json").read_text(encoding="utf-8"))
                self.assertEqual(brief["user_requirements"], [])
                prompt = (child.run_dir / "candidates/c01/generation/prompt.md").read_text(encoding="utf-8")
                self.assertNotIn("Include one cat.", prompt)
                self.assertNotIn("Include a brand logo.", prompt)

    def test_stale_invalid_and_busy_requirement_edits_do_not_overwrite_state(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            root = app.create_conversation(self.job())
            with self.assertRaisesRegex(ValueError, "Wait"):
                app.update_user_requirements(root.run_id, ["Include a cat."], expected_revision=0)
            app.continue_task(root.run_id)
            self.confirm_requirements(app, root.run_id, ["Include a cat."])
            before = app.conversation(root.run_id)
            for invalid in ([""], ["   "], ["x", "x"], [None], "one requirement"):
                with self.assertRaises(ValueError):
                    app.update_user_requirements(root.run_id, invalid, expected_revision=before["revision"])
            with self.assertRaisesRegex(ValueError, "Reload"):
                app.update_user_requirements(root.run_id, [], expected_revision=1)
            self.assertEqual(app.conversation(root.run_id), before)
            app.update_user_requirements(root.run_id, ["Include a cat."], expected_revision=before["revision"])
            self.assertEqual(app.conversation(root.run_id), before)
            app.create_conversation_round(root.run_id)
            with self.assertRaisesRegex(ValueError, "Wait"):
                app.update_user_requirements(root.run_id, [], expected_revision=before["revision"])

    def test_legacy_conversations_load_defaults_without_rewriting_archived_data(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            root = app.create_conversation(self.job())
            app.continue_task(root.run_id)
            path = root.run_dir / "conversation.json"
            legacy = json.loads(path.read_text(encoding="utf-8"))
            for key in ("user_requirements", "suggested_user_requirements",
                        "superseded_user_requirements", "requirement_history", "design_brief",
                        "brief_revision", "requirement_interpretations"):
                del legacy[key]
            legacy["format_version"] = 1
            path.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
            before = path.read_bytes()
            self.assertEqual(app.conversation(root.run_id)["user_requirements"], [])
            self.assertEqual(path.read_bytes(), before)
            app.queue_conversation_message(root.run_id, "Use blue.")
            app.continue_task(root.run_id)
            self.confirm_requirements(app, root.run_id, ["Include a cat."])
            self.assertEqual(app.conversation(root.run_id)["format_version"], 3)

    def test_concurrent_messages_do_not_overwrite_each_other(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            root = app.create_conversation(self.job())
            app.continue_task(root.run_id)
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
            app.continue_task(root.run_id)
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
            app.continue_task(root.run_id)
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
                app.continue_task(root.run_id)
                saved = app.conversation(root.run_id)
                self.assertIn("读书会", saved["effective_request"])
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
                app.continue_task(root.run_id)
                feedback = text.chat_calls[-1]
                self.assertEqual(len(feedback["references"]), 2)
                context = json.loads(feedback["prompt"][feedback["prompt"].index('{"effective_request"'):])
                self.assertEqual(context["previous_round"]["candidates"][0]["generation_prompt"], original_prompt)
                self.assertIn("Make the title larger", feedback["prompt"])
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
                message_id = saved["messages"][-2]["id"]
                intake_prompt = (root.run_dir / "conversation-turns" / message_id / "brief/prompt.md").read_text(encoding="utf-8")
                self.assertIn("Make the title larger", intake_prompt)
                self.assertIn("Reference 1: adopt the blue palette", intake_prompt)

    def test_failed_reply_retries_saved_message_without_duplicate_turns(self):
        with TemporaryDirectory() as directory:
            text = ConversationTextProvider()
            with self.app(directory, text) as app:
                root = app.create_conversation(self.job(), attachments=[("ref.png", image_bytes())])
                text.fail = True
                with self.assertRaises(RuntimeError):
                    app.continue_task(root.run_id)
                self.assertEqual(app.open_task(root.run_id).status, "failed")
                with self.assertRaises(ValueError):
                    app.queue_conversation_message(root.run_id, "Another message")
            text.fail = False
            with self.app(directory, text) as app:
                app.retry_conversation(root.run_id)
                app.continue_task(root.run_id)
                saved = app.conversation(root.run_id)
                self.assertEqual(len(saved["messages"]), 2)
                self.assertEqual(saved["revision"], 1)
                self.assertIsNone(saved["pending"])
                app.run_conversation(root.run_id)
                self.assertEqual(len(app.conversation(root.run_id)["messages"]), 2)

    def test_new_feedback_invalidates_approval_and_preserves_previous_round(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            root = app.create_conversation(self.job())
            app.continue_task(root.run_id)
            first = app.create_conversation_round(root.run_id)
            with self.assertRaises(ValueError):
                app.queue_conversation_message(root.run_id, "Too early")
            app.continue_task(first.run_id)
            with self.assertRaises(ValueError):
                app.create_conversation_round(root.run_id)
            app.queue_conversation_message(root.run_id, "Use green instead of blue.")
            with self.assertRaisesRegex(ValueError, "superseded"):
                app.resume(first.run_id, HumanDecision(True))
            app.continue_task(root.run_id)
            with self.assertRaisesRegex(ValueError, "superseded"):
                app.resume(first.run_id, HumanDecision(True))
            second = app.create_conversation_round(root.run_id)
            self.assertNotEqual(first.run_id, second.run_id)
            self.assertEqual(app.open_task(first.run_id).status, "awaiting_approval")

    def test_required_questions_block_round_until_answered(self):
        with TemporaryDirectory() as directory:
            text = ConversationTextProvider()
            text.questions = ["参考图里你希望采用哪个要素？"]
            with self.app(directory, text) as app:
                root = app.create_conversation(self.job())
                app.continue_task(root.run_id)
                with self.assertRaises(ValueError):
                    app.create_conversation_round(root.run_id)
                text.questions = []
                app.queue_conversation_message(root.run_id, "Use only its palette.")
                app.continue_task(root.run_id)
                self.assertEqual(app.create_conversation_round(root.run_id).status, "created")

    def test_legacy_task_can_continue_without_overwriting_graph_artifacts(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            original = app.start_request(self.job())
            index = Path(app.open_task(original.run_id).artifacts["candidate_index"])
            before = index.read_bytes()
            root = app.create_conversation(self.job("Use only its blue palette."), previous_run_id=original.run_id)
            app.continue_task(root.run_id)
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
            app.continue_task(root.run_id)
            before = app.conversation(root.run_id)
            other = app.start_request(self.job())
            with self.assertRaises(ValueError):
                app.queue_conversation_message(root.run_id, "Feedback", feedback_run_id=other.run_id)
            self.assertEqual(app.conversation(root.run_id), before)
            path = root.run_dir / before["messages"][0]["attachments"][0]["path"]
            path.write_bytes(image_bytes("JPEG"))
            app.queue_conversation_message(root.run_id, "Use more blue.")
            with self.assertRaisesRegex(ValueError, "changed"):
                app.continue_task(root.run_id)
