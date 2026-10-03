"""The prompt assistant only exchanges messages, including earlier image context."""

import json
from tempfile import TemporaryDirectory
import unittest

from corpus_atelier.application import CorpusAtelierApplication
from corpus_atelier.state import NaturalLanguageDesignJob
from tests.fakes import FakeImageProvider
from tests.test_conversation import ConversationTextProvider, image_bytes


class AssistantTests(unittest.TestCase):
    def test_reference_conversation_continues_without_a_brief_or_reupload(self):
        with TemporaryDirectory() as directory:
            text = ConversationTextProvider()
            with CorpusAtelierApplication(runs_root=directory, text_provider=text, image_provider=FakeImageProvider()) as app:
                task = app.create_conversation(
                    NaturalLanguageDesignJob("prompt-chat", "rhetoric-graphic", "Describe the basket in one sentence."),
                    attachments=[("basket.png", image_bytes())])
                app.continue_task(task.run_id)
                app.queue_conversation_message(task.run_id, "No flowers, just the container.")
                app.continue_task(task.run_id)
                text.reply = "A rounded woven body has vertical handle supports joined by a low arch."
                app.queue_conversation_message(task.run_id, "Keep the vertical supports and make the arch lower.")
                app.continue_task(task.run_id)
                saved = app.conversation(task.run_id)
                self.assertEqual(len(saved["messages"]), 6)
                self.assertEqual(saved["messages"][-1]["text"], text.reply)
                self.assertIsNone(saved["design_brief"])
                self.assertEqual(text.design_calls, [])
                self.assertEqual([len(c["references"]) for c in text.chat_calls], [1, 1, 1])
                prompt = text.chat_calls[-1]["prompt"]
                context = json.loads(prompt[prompt.index('{"effective_request"'):])
                self.assertEqual(context["conversation"][-3]["text"], "No flowers, just the container.")
                self.assertEqual(context["image_labels"][0]["name"], "basket.png")
            with CorpusAtelierApplication(runs_root=directory, text_provider=text, image_provider=FakeImageProvider()) as reopened:
                reopened.queue_conversation_message(task.run_id, "Give me a shorter version.")
                reopened.continue_task(task.run_id)
                self.assertEqual(len(reopened.conversation(task.run_id)["messages"]), 8)
                self.assertEqual(len(text.chat_calls[-1]["references"]), 1)

    def test_reply_can_be_an_explanation_or_alternatives_when_requested(self):
        with TemporaryDirectory() as directory:
            text = ConversationTextProvider()
            text.reply = "Version one: a rounded woven basket.\n\nVersion two: a basket with a low handle arch."
            with CorpusAtelierApplication(runs_root=directory, text_provider=text, image_provider=FakeImageProvider()) as app:
                task = app.create_conversation(NaturalLanguageDesignJob("alternatives", "rhetoric-graphic", "Give me two versions."))
                app.continue_task(task.run_id)
                self.assertEqual(app.conversation(task.run_id)["messages"][-1]["text"], text.reply)
                self.assertEqual(text.design_calls, [])
