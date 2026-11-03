"""Agent-drafted briefs and user-edited generation prompts."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from corpus_atelier.app.service import CorpusAtelierApplication
from corpus_atelier.app.state import DesignJob, HumanDecision, NaturalLanguageDesignJob
from tests.fakes import FakeImageProvider, FakeTextProvider
from tests.test_conversation import ConversationTextProvider, seed_brief


CASES = Path(__file__).resolve().parents[1] / "tests/fixtures/cases"


def brief(case):
    return json.loads((CASES / case / "brief.json").read_text(encoding="utf-8"))


class DraftBriefTests(unittest.TestCase):
    def app(self, directory, text=None):
        return CorpusAtelierApplication(
            runs_root=Path(directory) / "tasks",
            checkpoint_path=":memory:",
            text_provider=text or FakeTextProvider(),
            image_provider=FakeImageProvider(),
        )

    def create(self, app):
        return app.create_conversation(NaturalLanguageDesignJob(
            case_id="brief-draft", profile="rhetoric-graphic",
            request="Make a workplace poster about locking the screen.",
        ))

    def test_draft_is_advisory_and_archived(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            created = self.create(app)
            drafted = app.draft_brief(created.run_id)
            self.assertTrue(drafted["purpose"])
            manifest = app.inspect_task(created.run_id).manifest
            self.assertIn("brief_draft", manifest["artifacts"])
            self.assertIn("brief_draft_prompt", manifest["artifacts"])
            conversation = app.conversation(created.run_id)
            self.assertIsNone(conversation["design_brief"])
            self.assertEqual(conversation["revision"], 0)
            archived = json.loads(
                (created.run_dir / manifest["artifacts"]["brief_draft"]).read_text(encoding="utf-8")
            )
            self.assertEqual(archived, drafted)
            prompt = (created.run_dir / "brief-draft/prompt.md").read_text(encoding="utf-8")
            self.assertIn("# Conversation context", prompt)
            self.assertNotIn("# Previous brief", prompt)

    def test_redraft_includes_the_saved_brief(self):
        with TemporaryDirectory() as directory:
            with self.app(directory, ConversationTextProvider()) as app:
                created = self.create(app)
                app.continue_task(created.run_id)
                seed_brief(app, created.run_id)
                app.draft_brief(created.run_id)
                prompt = (created.run_dir / "brief-draft/prompt.md").read_text(encoding="utf-8")
                self.assertIn("# Previous brief", prompt)
                self.assertIsNotNone(app.conversation(created.run_id)["design_brief"])

    def test_failed_draft_is_recorded_and_does_not_touch_the_brief(self):
        class BrokenProvider(FakeTextProvider):
            def propose(self, prompt, *, schema_name, reference_paths=None):
                if schema_name.endswith("-brief.schema.json"):
                    raise RuntimeError("draft failure")
                return super().propose(
                    prompt, schema_name=schema_name, reference_paths=reference_paths,
                )

        with TemporaryDirectory() as directory, self.app(directory, BrokenProvider()) as app:
            created = self.create(app)
            with self.assertRaisesRegex(RuntimeError, "draft failure"):
                app.draft_brief(created.run_id)
            self.assertTrue((created.run_dir / "brief-draft/error.json").is_file())
            self.assertIsNone(app.conversation(created.run_id)["design_brief"])
            self.assertNotIn(
                "brief_draft",
                app.inspect_task(created.run_id).manifest.get("artifacts", {}),
            )


class PromptOverrideTests(unittest.TestCase):
    def app(self, directory, image=None):
        return CorpusAtelierApplication(
            runs_root=Path(directory) / "tasks",
            checkpoint_path=":memory:",
            text_provider=FakeTextProvider(),
            image_provider=image or FakeImageProvider(),
        )

    def start(self, app):
        return app.start(DesignJob(
            case_id="poster-01", profile="rhetoric-poster", brief=brief("poster-01"),
        ))

    def test_edited_prompt_is_sent_and_recorded(self):
        with TemporaryDirectory() as directory:
            image = FakeImageProvider()
            with self.app(directory, image) as app:
                started = self.start(app)
                edited = "A hand-edited prompt that must reach the renderer."
                result = app.resume(started.run_id, HumanDecision(
                    True, reviewer="test", prompt_overrides={"c01": edited},
                ))
                self.assertEqual(result.status, "awaiting_selection")
                candidates = json.loads(Path(
                    result.artifacts["candidate_index"]
                ).read_text(encoding="utf-8"))
                self.assertEqual(candidates[0]["generation_prompt"], edited)
                prompt_file = (
                    result.run_dir / "candidates/c01/generation/prompt.md"
                ).read_text(encoding="utf-8")
                self.assertEqual(prompt_file, edited)
                preview = json.loads((
                    result.run_dir / "candidates/c01/generation/request-preview.json"
                ).read_text(encoding="utf-8"))
                self.assertEqual(preview["prompt"], edited)
                sent = json.loads(next(result.run_dir.glob(
                    "candidates/c01/generation/attempt_*/request.json"
                )).read_text(encoding="utf-8"))
                self.assertEqual(sent["prompt"], edited)
                decision = json.loads((
                    result.run_dir / "approval/decision.json"
                ).read_text(encoding="utf-8"))
                self.assertEqual(decision["prompt_overrides"]["c01"]["chars"], len(edited))
                self.assertNotIn("prompt_overrides_text", decision)

    def test_approval_without_edits_records_no_overrides(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            started = self.start(app)
            result = app.resume(started.run_id, HumanDecision(True, reviewer="test"))
            self.assertEqual(result.status, "awaiting_selection")
            decision = json.loads((
                result.run_dir / "approval/decision.json"
            ).read_text(encoding="utf-8"))
            self.assertNotIn("prompt_overrides", decision)

    def test_empty_or_unknown_edits_are_rejected(self):
        for overrides, message in (
            ({"c01": "   "}, "must not be empty"),
            ({"c99": "A prompt"}, "Cannot edit the prompt"),
        ):
            with self.subTest(overrides=overrides), TemporaryDirectory() as directory:
                with self.app(directory) as app:
                    started = self.start(app)
                    with self.assertRaisesRegex(ValueError, message):
                        app.resume(started.run_id, HumanDecision(
                            True, reviewer="test", prompt_overrides=overrides,
                        ))

    def test_only_the_edited_candidate_changes(self):
        with TemporaryDirectory() as directory:
            image = FakeImageProvider()
            with self.app(directory, image) as app:
                started = app.start(DesignJob(
                    case_id="poster-02", profile="rhetoric-poster",
                    brief={**brief("poster-01"), "user_requirements": [
                        "Keep the lower-right area clear.",
                    ]},
                    candidate_count=2,
                ))
                original = {
                    candidate["candidate_id"]: candidate["generation_prompt"]
                    for candidate in json.loads(Path(
                        started.artifacts["candidate_index"]
                    ).read_text(encoding="utf-8"))
                }
                edited = "Edited second candidate only."
                result = app.resume(started.run_id, HumanDecision(
                    True, reviewer="test", prompt_overrides={"c02": edited},
                ))
                self.assertEqual(result.status, "awaiting_selection")
                candidates = json.loads(Path(
                    result.artifacts["candidate_index"]
                ).read_text(encoding="utf-8"))
                by_id = {candidate["candidate_id"]: candidate for candidate in candidates}
                self.assertEqual(by_id["c02"]["generation_prompt"], edited)
                self.assertEqual(by_id["c01"]["generation_prompt"], original["c01"])
                decision = json.loads((
                    result.run_dir / "approval/decision.json"
                ).read_text(encoding="utf-8"))
                self.assertEqual(list(decision["prompt_overrides"]), ["c02"])


if __name__ == "__main__":
    unittest.main()
