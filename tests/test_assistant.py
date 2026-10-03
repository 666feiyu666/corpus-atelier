"""Discussion proposals cannot become design instructions without a user save."""

from copy import deepcopy
from tempfile import TemporaryDirectory
import unittest

from corpus_atelier.artifacts.records import read_json
from corpus_atelier.state import HumanDecision
from tests import test_conversation as fixtures
from tests.test_conversation import ConversationTextProvider, image_bytes


class AssistantTests(unittest.TestCase):
    app = fixtures.ConversationTests.app
    job = fixtures.ConversationTests.job

    def ready(self, app):
        task = app.create_conversation(self.job())
        app.continue_task(task.run_id)
        return task, app.conversation(task.run_id)

    def test_reference_observation_is_archived_without_rewriting_or_blocking_the_brief(self):
        with TemporaryDirectory() as directory:
            provider = ConversationTextProvider()
            with self.app(directory, provider) as app:
                task, before = self.ready(app)
                frozen = (task.run_dir / "brief.json").read_bytes()
                provider.suggested_requirements = ["UNADOPTED_REFERENCE_TEXTURE_125."]
                provider.questions = ["Would you also like the reference background?"]
                app.queue_conversation_message(task.run_id, "Describe only the basket style.",
                                               attachments=[("basket.png", image_bytes())])
                calls = len(provider.design_calls)
                app.continue_task(task.run_id)
                after = app.conversation(task.run_id)
                self.assertEqual(len(provider.design_calls), calls)
                for field in ("design_brief", "revision", "brief_revision", "brief_history", "open_questions", "user_requirements", "effective_request"):
                    self.assertEqual(after[field], before[field], field)
                self.assertEqual((task.run_dir / "brief.json").read_bytes(), frozen)
                suggestion = after["assistant_suggestions"][0]
                self.assertEqual(suggestion["status"], "proposed")
                self.assertEqual(suggestion["images"][0]["name"], "basket.png")
                self.assertEqual(suggestion["source_quote"], "Describe only the basket style.")
                child = app.create_conversation_round(task.run_id)
                app.continue_task(child.run_id)
                self.assertNotIn("UNADOPTED_REFERENCE_TEXTURE_125", (child.run_dir / "candidates/c01/generation/prompt.md").read_text(encoding="utf-8"))
                self.assertNotIn("Reference findings", (child.run_dir / "request/user-request.txt").read_text(encoding="utf-8") if (child.run_dir / "request/user-request.txt").exists() else "")

    def test_edited_adoption_is_exact_and_is_the_only_value_forwarded_to_generation(self):
        with TemporaryDirectory() as directory:
            provider = ConversationTextProvider()
            with self.app(directory, provider) as app:
                task, before = self.ready(app)
                provider.suggested_requirements = ["UNEDITED_REFERENCE_DESCRIPTION_125."]
                app.queue_conversation_message(task.run_id, "Describe this shape.")
                app.continue_task(task.run_id)
                suggestion = app.conversation(task.run_id)["assistant_suggestions"][0]
                edited = deepcopy(before["design_brief"])
                edited["user_requirements"] = ["USER_EDITED_LIGHT_BASKET_125."]
                app.save_conversation_brief(task.run_id, edited, expected_revision=before["revision"],
                                            source_suggestion_ids=[suggestion["id"]])
                after = app.conversation(task.run_id)
                self.assertEqual(after["brief_history"][-1]["source_suggestion_ids"], [suggestion["id"]])
                self.assertEqual(after["assistant_suggestions"][0]["text"], "UNEDITED_REFERENCE_DESCRIPTION_125.")
                child = app.create_conversation_round(task.run_id)
                app.continue_task(child.run_id)
                prompt = (child.run_dir / "candidates/c01/generation/prompt.md").read_text(encoding="utf-8")
                self.assertIn("USER_EDITED_LIGHT_BASKET_125", prompt)
                self.assertNotIn("UNEDITED_REFERENCE_DESCRIPTION_125", prompt)
                provider.suggested_requirements = None
                app.queue_conversation_message(task.run_id, "Explain the result.")
                app.continue_task(task.run_id)
                self.assertEqual(app.conversation(task.run_id)["design_brief"], edited)

    def test_dismissal_survives_restart_and_does_not_advance_design_revision(self):
        with TemporaryDirectory() as directory:
            provider = ConversationTextProvider()
            with self.app(directory, provider) as app:
                task, before = self.ready(app)
                provider.suggested_requirements = ["Do not use the reference handle."]
                app.queue_conversation_message(task.run_id, "Describe the handle to exclude.")
                app.continue_task(task.run_id)
                identity = app.conversation(task.run_id)["assistant_suggestions"][0]["id"]
                app.dismiss_conversation_suggestion(task.run_id, identity)
            with self.app(directory, provider) as app:
                after = app.conversation(task.run_id)
                self.assertEqual(after["assistant_suggestions"][0]["status"], "dismissed")
                self.assertEqual(after["revision"], before["revision"])
                self.assertEqual(after["design_brief"], before["design_brief"])
                provider.suggested_requirements = None
                app.queue_conversation_message(task.run_id, "Continue discussing.")
                app.continue_task(task.run_id)
                self.assertIn('"status": "dismissed"', provider.chat_calls[-1]["prompt"])

    def test_discussion_keeps_an_existing_approval_valid_until_the_user_saves(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            task, before = self.ready(app)
            child = app.create_conversation_round(task.run_id)
            app.continue_task(child.run_id)
            snapshot = (child.run_dir / "conversation/snapshot.json").read_bytes()
            app.queue_conversation_message(task.run_id, "Explain the basket style.")
            app.continue_task(task.run_id)
            self.assertEqual(app.conversation(task.run_id)["revision"], before["revision"])
            self.assertEqual((child.run_dir / "conversation/snapshot.json").read_bytes(), snapshot)
            self.assertEqual(app.resume(child.run_id, HumanDecision(True)).status, "awaiting_selection")

    def test_invalid_source_or_target_never_changes_the_saved_contract(self):
        for change in ({"source_images": [99]}, {"source_quote": "invented quotation"},
                       {"field": "article_title"}, {"text": "first line\nsecond line"}):
            with self.subTest(change=change), TemporaryDirectory() as directory:
                provider = ConversationTextProvider()
                provider.suggested_requirements = ["A suggested shape."]
                propose = provider.propose
                def invalid(prompt, *, schema_name, reference_paths=None):
                    answer, response = propose(prompt, schema_name=schema_name, reference_paths=reference_paths)
                    if schema_name == "design-assistant.schema.json":
                        answer["suggestions"][0].update(change)
                    return answer, response
                provider.propose = invalid
                with self.app(directory, provider) as app:
                    task, before = self.ready(app)
                    app.queue_conversation_message(task.run_id, "Describe a shape.")
                    with self.assertRaises(ValueError):
                        app.continue_task(task.run_id)
                    self.assertEqual(app.conversation(task.run_id)["design_brief"], before["design_brief"])

    def test_reference_only_first_turn_does_not_adopt_its_observation(self):
        with TemporaryDirectory() as directory:
            provider = ConversationTextProvider()
            provider.suggested_requirements = ["UNADOPTED_FIRST_REFERENCE_125."]
            with self.app(directory, provider) as app:
                task = app.create_conversation(self.job(), attachments=[("basket.png", image_bytes())])
                app.continue_task(task.run_id)
                saved = app.conversation(task.run_id)
                self.assertEqual(len(saved["messages"]), 2)
                self.assertEqual(saved["revision"], 1)
                self.assertTrue(saved["assistant_suggestions"])
                self.assertNotIn("UNADOPTED_FIRST_REFERENCE_125", str(saved["design_brief"]))
                intake = next(task.run_dir.glob("conversation-turns/*/brief/prompt.md")).read_text(encoding="utf-8")
                self.assertNotIn("adopt the blue palette", intake)

    def test_scoped_positive_and_negative_observations_keep_distinct_image_sources(self):
        with TemporaryDirectory() as directory:
            provider = ConversationTextProvider()
            propose = provider.propose
            def observations(prompt, *, schema_name, reference_paths=None):
                answer, response = propose(prompt, schema_name=schema_name, reference_paths=reference_paths)
                if schema_name == "design-assistant.schema.json":
                    answer["reply"] = "A redundant introduction and unrelated explanation."
                    answer["suggestions"] = [
                        {"field": "preferences", "text": "Rounded body and arched handle.", "aspect": "Basket shape",
                         "direction": "describe", "source_quote": "Describe the first basket", "source_images": [1]},
                        {"field": "constraints", "text": "Do not adopt the second image's gold trim.", "aspect": "Excluded trim",
                         "direction": "exclude", "source_quote": "exclude the second trim", "source_images": [2]},
                    ]
                return answer, response
            provider.propose = observations
            with self.app(directory, provider) as app:
                task, before = self.ready(app)
                app.queue_conversation_message(task.run_id, "Describe the first basket; exclude the second trim.",
                                               attachments=[("first.png", image_bytes()), ("second.png", image_bytes())])
                app.continue_task(task.run_id)
                after = app.conversation(task.run_id)
                self.assertEqual(after["design_brief"], before["design_brief"])
                self.assertEqual([s["images"][0]["name"] for s in after["assistant_suggestions"]], ["first.png", "second.png"])
                self.assertEqual(after["assistant_suggestions"][1]["direction"], "exclude")
                self.assertEqual(after["messages"][-1]["text"], "Rounded body and arched handle.\n\nDo not adopt the second image's gold trim.")
