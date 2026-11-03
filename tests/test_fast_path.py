"""Offline checks for the fast path: a precise request renders without a review stop."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from corpus_atelier.app.service import CorpusAtelierApplication, FastPathUnavailable
from corpus_atelier.app.state import NaturalLanguageDesignJob
from tests.fakes import FakeImageProvider, FakeTextProvider


class DirectRouteTextProvider(FakeTextProvider):
    """Draft briefs that declare the route this test is exercising."""

    def __init__(self, route="direct", brief=None):
        super().__init__()
        self.route = route
        self.brief = brief

    def propose(self, prompt, *, schema_name, reference_paths=None):
        if schema_name == "design-assistant.schema.json":
            context = json.loads(prompt[prompt.index('{"effective_request"'):])
            return {
                "content_language": context["content_language"] or "en",
                "language_change_quote": None,
                "reply": "Drafted a direct brief for this request.",
            }, {"status": "completed", "provider": "fake-assistant"}
        value, response = super().propose(
            prompt, schema_name=schema_name, reference_paths=reference_paths,
        )
        if schema_name.endswith("-brief.schema.json"):
            if self.brief is not None:
                value = json.loads(json.dumps(self.brief))
            value["execution_route"] = self.route
            value["route_reason"] = "The request already fixes the subject and copy."
            value["content_language"] = "en"
        return value, response


class FastPathTests(unittest.TestCase):
    def app(self, root, text=None, image=None):
        return CorpusAtelierApplication(
            runs_root=root,
            text_provider=text or DirectRouteTextProvider(),
            image_provider=image or FakeImageProvider(),
        )

    def job(self, request="Design a poster with exact title Reading Club."):
        return NaturalLanguageDesignJob("fast-path-test", "rhetoric-graphic", request, 1)

    def test_precise_request_renders_without_an_approval_stop(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            parent = app.create_conversation(self.job())
            app.continue_task(parent.run_id)
            self.assertTrue(app.fast_path_status(parent.run_id)["eligible"] is False)
            round_ = app.start_fast_round(parent.run_id)
            app.continue_task(round_.run_id)
            self.assertEqual(app.open_task(round_.run_id).status, "awaiting_selection")
            decision = json.loads(
                (round_.run_dir / "approval/decision.json").read_text(encoding="utf-8")
            )
            self.assertTrue(decision["approved"])
            self.assertTrue(decision["auto"])
            self.assertEqual(decision["reviewer"], "fast-path")
            conversation = app.conversation(parent.run_id)
            self.assertEqual(conversation["design_brief"]["execution_route"], "direct")
            self.assertEqual(conversation["brief_history"][-1]["origin"], "fast-path")

    def test_round_brief_is_saved_before_the_round_starts(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            parent = app.create_conversation(self.job())
            app.continue_task(parent.run_id)
            round_ = app.start_fast_round(parent.run_id)
            conversation = app.conversation(parent.run_id)
            self.assertEqual(conversation["brief_revision"], conversation["revision"])
            manifest = json.loads((round_.run_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["approval_policy"], "auto")
            self.assertEqual(manifest["conversation_parent_id"], parent.run_id)

    def test_staged_request_starts_a_round_and_pauses_at_its_preview(self):
        with TemporaryDirectory() as directory:
            with self.app(directory, text=DirectRouteTextProvider(route="staged")) as app:
                parent = app.create_conversation(self.job())
                app.continue_task(parent.run_id)
                app.draft_brief(parent.run_id)
                self.assertEqual(app.fast_path_status(parent.run_id),
                                 {"eligible": True, "reason": None})
                round_ = app.start_fast_round(parent.run_id)
                # The brief is confirmed without review, but a staged round still asks
                # for its generation preview before rendering.
                app.continue_task(round_.run_id)
                self.assertEqual(app.open_task(round_.run_id).status, "awaiting_approval")
                conversation = app.conversation(parent.run_id)
                self.assertEqual(conversation["brief_history"][-1]["origin"], "fast-path")
                self.assertEqual(
                    conversation["design_brief"]["execution_route"], "staged",
                )

    def test_open_questions_block_the_fast_path(self):
        brief = {
            "content_language": "en",
            "deliverable": "A4 poster",
            "purpose": "Announce a reading club.",
            "audience": "Neighbours.",
            "use_context": "Pinned in a bookshop window.",
            "exact_copy": ["READING CLUB"],
            "constraints": [],
            "preferences": [],
            "canvas": {"aspect_ratio": {"width": 3, "height": 4}},
        }
        with TemporaryDirectory() as directory:
            with self.app(directory, text=DirectRouteTextProvider(brief=brief)) as app:
                parent = app.create_conversation(self.job())
                app.continue_task(parent.run_id)
                app.draft_brief(parent.run_id)
                app.save_conversation_brief(
                    parent.run_id, brief, expected_revision=0,
                    open_questions=["Which reading club is this for?"],
                )
                with self.assertRaises(FastPathUnavailable) as caught:
                    app.start_fast_round(parent.run_id, redraft=False)
                self.assertEqual(caught.exception.reason, "open_questions")

    def test_failed_candidate_falls_back_to_explicit_approval(self):
        with TemporaryDirectory() as directory:
            with self.app(directory, image=FakeImageProvider(fail=True)) as app:
                parent = app.create_conversation(self.job())
                app.continue_task(parent.run_id)
                round_ = app.start_fast_round(parent.run_id)
                with self.assertRaises(RuntimeError):
                    app.continue_task(round_.run_id)
                self.assertEqual(app.open_task(round_.run_id).status, "failed")


if __name__ == "__main__":
    unittest.main()
