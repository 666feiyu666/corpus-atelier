"""Discussion receives the brief and exact model input for the chosen result."""

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from corpus_atelier.application import CorpusAtelierApplication
from corpus_atelier.artifacts.records import read_json, write_json
from corpus_atelier.state import HumanDecision, NaturalLanguageDesignJob
from tests.fakes import FakeImageProvider
from tests.test_conversation import ConversationTextProvider, image_bytes, seed_brief


class DiscussionContextTests(unittest.TestCase):
    def app(self, root, text, image):
        return CorpusAtelierApplication(runs_root=root, text_provider=text, image_provider=image)

    def ready(self, app, *, count=1, attachments=None):
        parent = app.create_conversation(
            NaturalLanguageDesignJob("discussion", "rhetoric-graphic", "Design a basket poster.", count, "en"),
            attachments=attachments,
        )
        app.continue_task(parent.run_id)
        seed_brief(app, parent.run_id)
        child = app.create_conversation_round(parent.run_id)
        app.continue_task(child.run_id)
        return parent, child

    def candidate(self, child, candidate_id="c01"):
        return next(candidate for candidate in read_json(child.run_dir / "candidates/index.json")
                    if candidate["candidate_id"] == candidate_id)

    def discuss(self, app, parent, child, text, *, candidate_id=None):
        app.queue_conversation_message(parent.run_id, "How should I correct the handle?",
                                       feedback_run_id=child.run_id, candidate_id=candidate_id)
        app.continue_task(parent.run_id)
        prompt = text.chat_calls[-1]["prompt"]
        return json.loads(prompt[prompt.index('{"effective_request"'):])

    def test_historical_result_uses_its_frozen_brief_and_actual_input_after_restart(self):
        with TemporaryDirectory() as directory:
            text, image = ConversationTextProvider(), FakeImageProvider()
            with self.app(directory, text, image) as app:
                parent, first = self.ready(app)
                app.resume(first.run_id, HumanDecision(True))
                original = deepcopy(app.conversation(parent.run_id)["design_brief"])
                candidate = self.candidate(first)
                request_path = first.run_dir / candidate["generation_artifacts"]["request"]
                actual_prompt = read_json(request_path)["prompt"]
                index = read_json(first.run_dir / "candidates/index.json")
                index[0]["generation_prompt"] = "An obsolete candidate-index description."
                write_json(first.run_dir / "candidates/index.json", index)
                latest = {**original, "purpose": "A different current purpose.",
                          "user_requirements": ["Use a lower handle arch."]}
                app.save_conversation_brief(parent.run_id, latest, expected_revision=1)
                second = app.create_conversation_round(parent.run_id)
                app.continue_task(second.run_id)
                files = [first.run_dir / "conversation/snapshot.json", first.run_dir / "brief.json",
                         first.run_dir / "candidates/index.json", request_path, Path(candidate["image_path"])]
                before = [path.read_bytes() for path in files]
                saved = app.conversation(parent.run_id)
                app.queue_conversation_message(parent.run_id, "How should I correct the handle?",
                                               feedback_run_id=first.run_id, candidate_id="c01")
            with self.app(directory, text, image) as app:
                app.continue_task(parent.run_id)
                prompt = text.chat_calls[-1]["prompt"]
                context = json.loads(prompt[prompt.index('{"effective_request"'):])
                self.assertEqual(context["design_brief"], latest)
                self.assertEqual(context["brief_revision"], 2)
                self.assertEqual(context["previous_round"]["run_id"], first.run_id)
                self.assertEqual(context["previous_round"]["design_brief"], original)
                self.assertEqual(context["previous_round"]["brief_revision"], 1)
                selected, = context["previous_round"]["candidates"]
                self.assertEqual(selected["generation_prompt"], actual_prompt)
                self.assertEqual(selected["prompt_stage"], "generation_input")
                self.assertEqual(selected["prompt_source"], candidate["generation_artifacts"]["request"])
                label, = context["image_labels"]
                self.assertEqual((label["round_id"], label["candidate_id"]), (first.run_id, "c01"))
                current = app.conversation(parent.run_id)
                for field in ("revision", "design_brief", "brief_history"):
                    self.assertEqual(current[field], saved[field])
                self.assertEqual([path.read_bytes() for path in files], before)
                self.assertEqual(image.calls, 1)

    def test_each_candidate_image_is_paired_with_its_own_generation_input(self):
        with TemporaryDirectory() as directory:
            text, image = ConversationTextProvider(), FakeImageProvider()
            with self.app(directory, text, image) as app:
                parent, child = self.ready(app, count=2, attachments=[("basket.png", image_bytes())])
                app.resume(child.run_id, HumanDecision(True))
                context = self.discuss(app, parent, child, text)
                labels = [label for label in context["image_labels"] if label.get("round_id")]
                self.assertEqual([label["index"] for label in labels], [2, 3])
                self.assertEqual([label["candidate_id"] for label in labels], ["c01", "c02"])
                references = text.chat_calls[-1]["references"]
                for label in labels:
                    candidate_id = label["candidate_id"]
                    record = next(record for record in context["previous_round"]["candidates"]
                                  if record["candidate_id"] == candidate_id)
                    request = read_json(child.run_dir / self.candidate(child, candidate_id)["generation_artifacts"]["request"])
                    self.assertEqual(record["generation_prompt"], request["prompt"])
                    self.assertEqual(references[label["index"] - 1].relative_to(child.run_dir).parts[1], candidate_id)
                selected = self.discuss(app, parent, child, text, candidate_id="c02")
                self.assertEqual([record["candidate_id"] for record in selected["previous_round"]["candidates"]], ["c02"])
                self.assertEqual(len(text.chat_calls[-1]["references"]), 2)

    def test_prepared_prompt_is_marked_as_preview_without_claiming_a_generated_image(self):
        with TemporaryDirectory() as directory:
            text, image = ConversationTextProvider(), FakeImageProvider()
            with self.app(directory, text, image) as app:
                parent, child = self.ready(app)
                context = self.discuss(app, parent, child, text, candidate_id="c01")
                record, = context["previous_round"]["candidates"]
                self.assertEqual(record["prompt_stage"], "generation_preview")
                self.assertEqual(record["generation_prompt"], (child.run_dir / "candidates/c01/generation/prompt.md").read_text(encoding="utf-8"))
                self.assertEqual(context["image_labels"], [])
                self.assertEqual(text.chat_calls[-1]["references"], [])
                self.assertEqual(image.calls, 0)

    def test_processing_round_still_supplies_the_brief_with_no_invented_prompt(self):
        with TemporaryDirectory() as directory:
            text, image = ConversationTextProvider(), FakeImageProvider()
            with self.app(directory, text, image) as app:
                parent = app.create_conversation(NaturalLanguageDesignJob("processing", "rhetoric-graphic", "A basket.", content_language="en"))
                app.continue_task(parent.run_id)
                seed_brief(app, parent.run_id)
                child = app.create_conversation_round(parent.run_id)
                context = self.discuss(app, parent, child, text)
                self.assertEqual(context["previous_round"]["design_brief"], app.conversation(parent.run_id)["design_brief"])
                self.assertEqual(context["previous_round"]["candidates"], [])
                self.assertEqual(context["image_labels"], [])

    def test_failed_attempt_supplies_its_input_without_claiming_a_result(self):
        with TemporaryDirectory() as directory:
            text, image = ConversationTextProvider(), FakeImageProvider(fail=True)
            with self.app(directory, text, image) as app:
                parent, child = self.ready(app)
                with self.assertRaisesRegex(RuntimeError, "All candidate generations failed"):
                    app.resume(child.run_id, HumanDecision(True))
                context = self.discuss(app, parent, child, text, candidate_id="c01")
                record, = context["previous_round"]["candidates"]
                self.assertEqual(record["status"], "failed")
                self.assertEqual(record["prompt_stage"], "generation_input")
                request = read_json(child.run_dir / record["prompt_source"])
                self.assertEqual(record["generation_prompt"], request["prompt"])
                self.assertEqual(context["image_labels"], [])
                self.assertEqual(text.chat_calls[-1]["references"], [])
                self.assertEqual(image.calls, 1)

    def test_promoted_standalone_round_uses_its_archived_brief(self):
        with TemporaryDirectory() as directory:
            text, image = ConversationTextProvider(), FakeImageProvider()
            with self.app(directory, text, image) as app:
                child = app.start_request(NaturalLanguageDesignJob("legacy", "rhetoric-graphic", "A basket poster.", content_language="en"))
                app.resume(child.run_id, HumanDecision(True))
                original = read_json(child.run_dir / "brief.json")
                parent = app.create_conversation(NaturalLanguageDesignJob("legacy", "rhetoric-graphic", "Describe the handle.", content_language="en"),
                                                 previous_run_id=child.run_id)
                app.continue_task(parent.run_id)
                context = self.discuss(app, parent, child, text, candidate_id="c01")
                self.assertEqual(context["previous_round"]["design_brief"], original)
                self.assertEqual(context["previous_round"]["brief_source"], "brief.json")
                self.assertEqual(context["previous_round"]["brief_revision"], 0)
                self.assertEqual(context["previous_round"]["candidates"][0]["prompt_stage"], "generation_input")

    def test_missing_actual_input_is_not_replaced_by_the_preview_for_an_existing_image(self):
        with TemporaryDirectory() as directory:
            text, image = ConversationTextProvider(), FakeImageProvider()
            with self.app(directory, text, image) as app:
                parent, child = self.ready(app)
                app.resume(child.run_id, HumanDecision(True))
                request = child.run_dir / self.candidate(child)["generation_artifacts"]["request"]
                request.unlink()
                context = self.discuss(app, parent, child, text, candidate_id="c01")
                record, = context["previous_round"]["candidates"]
                self.assertIsNone(record["generation_prompt"])
                self.assertEqual(record["prompt_stage"], "unavailable")
                self.assertEqual(len(context["image_labels"]), 1)
