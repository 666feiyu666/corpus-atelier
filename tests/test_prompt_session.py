"""Offline checks for prompt-session records, revisions, and extraction."""

from io import BytesIO
import json
from tempfile import TemporaryDirectory
import unittest

from PIL import Image

from corpus_atelier.app.service import CorpusAtelierApplication
from corpus_atelier.artifacts.records import read_json, write_json
from corpus_atelier.prompt_session import records as session_records
from tests.fakes import FakeImageProvider, FakeTextProvider


CASE = "prompt-session-tests"
SETTINGS = {"image_quality": "medium", "aspect_ratio": [16, 9]}


def image_bytes(fmt="PNG"):
    buffer = BytesIO()
    Image.new("RGB", (64, 48), (30, 70, 110)).save(buffer, format=fmt)
    return buffer.getvalue()


class PromptTextProvider(FakeTextProvider):
    """A text provider that records which workflow prompt it received."""

    def __init__(self):
        super().__init__()
        self.assistant_calls = []
        self.extraction_calls = []
        self.reply = "I tightened the wording."
        self.proposal = "A revised standalone prompt."
        self.edit_instruction = None
        self.extraction = {
            "prompt_text": "An estimated standalone prompt from the image.",
            "negative_prompt": "photorealistic, flat vector rendering, watermark",
            "observations": "The small label is only partly legible.",
        }
        self.fail_assistant = False
        self.fail_extraction = False

    def propose(self, prompt, *, schema_name, reference_paths=None):
        if schema_name == "prompt-assistant.schema.json":
            context = json.loads(prompt[prompt.index('{"entry_mode"'):])
            self.assistant_calls.append({
                "prompt": prompt, "references": list(reference_paths or []),
                "context": context,
            })
            if self.fail_assistant:
                raise RuntimeError("deliberate assistant failure")
            return {
                "reply": self.reply, "proposed_prompt": self.proposal,
                "edit_instruction": self.edit_instruction,
            }, {"status": "completed", "provider": "fake-assistant"}
        if schema_name == "prompt-extraction.schema.json":
            self.extraction_calls.append({
                "prompt": prompt, "references": list(reference_paths or []),
            })
            if self.fail_extraction:
                raise RuntimeError("deliberate extraction failure")
            return dict(self.extraction), {"status": "completed", "provider": "fake-extraction"}
        return super().propose(
            prompt, schema_name=schema_name, reference_paths=reference_paths,
        )


class PromptSessionCase(unittest.TestCase):
    def app(self, root, text=None, image=None):
        return CorpusAtelierApplication(
            runs_root=root,
            text_provider=text or PromptTextProvider(),
            image_provider=image or FakeImageProvider(),
        )

    def start(self, app, prompt="A quiet poster of a paper lantern at dusk."):
        return app.start_from_prompt(
            prompt, case_id=CASE, settings=SETTINGS,
        )


class PromptStartTests(PromptSessionCase):
    def test_start_from_prompt_keeps_the_prompt_exact(self):
        prompt = "  A poster of a paper lantern at dusk.\nKeep the copy: “灯会”。\n"
        with TemporaryDirectory() as directory, self.app(directory) as app:
            result = self.start(app, prompt)
            session = app.prompt_session(result.run_id)
            self.assertEqual(result.status, "prompt_ready")
            self.assertEqual(session["workflow_kind"], "prompt_session_v1")
            self.assertEqual(session["entry_mode"], "prompt")
            self.assertEqual(len(session["prompt_revisions"]), 1)
            revision = session["prompt_revisions"][0]
            self.assertEqual(revision["prompt_text"], prompt)
            self.assertEqual(revision["origin"], "user_input")
            self.assertEqual(revision["digest"], session_records.prompt_digest(prompt))
            self.assertEqual(session["current_prompt_revision_id"], revision["id"])
            self.assertEqual(
                (result.run_dir / "input/request.txt").read_text(encoding="utf-8"), prompt,
            )
            self.assertEqual(app.runtime.text_provider.assistant_calls, [])
            self.assertEqual(app.runtime.image_provider.calls, 0)
            manifest = app.inspect_task(result.run_id).manifest
            self.assertTrue(manifest["is_prompt_session"])
            self.assertEqual(manifest["workflow_kind"], "prompt_session_v1")

    def test_empty_or_oversized_prompts_are_rejected(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            with self.assertRaisesRegex(ValueError, "Write a prompt"):
                app.start_from_prompt("   \n ", case_id=CASE, settings=SETTINGS)
            with self.assertRaisesRegex(ValueError, "at most"):
                app.start_from_prompt("x" * 8001, case_id=CASE, settings=SETTINGS)

    def test_start_from_image_queues_extraction_without_an_image_call(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            result = app.start_from_image(
                ("source.png", image_bytes()), case_id=CASE, settings=SETTINGS,
            )
            session = app.prompt_session(result.run_id)
            self.assertEqual(result.status, "extracting")
            self.assertEqual(session["entry_mode"], "image")
            self.assertEqual(session["prompt_revisions"], [])
            self.assertIsNone(session["current_prompt_revision_id"])
            self.assertEqual(session["pending_turn"]["kind"], "extraction")
            upload = session["uploads"][0]
            self.assertEqual(upload["role"], "source_image")
            self.assertTrue((result.run_dir / upload["path"]).is_file())
            self.assertEqual(app.runtime.image_provider.calls, 0)
            self.assertEqual(app.runtime.text_provider.assistant_calls, [])


class ExtractionTests(PromptSessionCase):
    def test_extraction_records_provenance_and_stays_editable(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            result = app.start_from_image(
                ("source.png", image_bytes()), case_id=CASE, settings=SETTINGS,
            )
            finished = app.continue_task(result.run_id)
            session = app.prompt_session(result.run_id)
            self.assertEqual(finished.status, "prompt_ready")
            self.assertEqual(len(app.runtime.text_provider.extraction_calls), 1)
            self.assertEqual(app.runtime.image_provider.calls, 0)
            revision = session["prompt_revisions"][0]
            self.assertEqual(revision["origin"], "vision_extraction")
            self.assertEqual(revision["source_image_id"], session["uploads"][0]["id"])
            self.assertEqual(
                revision["prompt_text"], "An estimated standalone prompt from the image.",
            )
            self.assertEqual(revision["note"], "The small label is only partly legible.")
            self.assertEqual(revision["prompt_text"].count("partly legible"), 0)
            self.assertEqual(
                revision["negative_prompt"],
                "photorealistic, flat vector rendering, watermark",
            )
            self.assertIsNone(session["pending_turn"])
            turn = session["text_turns"][0]
            self.assertEqual(turn["kind"], "extraction")
            self.assertTrue((result.run_dir / turn["model_input"]).is_file())
            # The extracted prompt is a normal current revision: the user may edit it.
            app.edit_session_prompt(
                result.run_id, "A user-edited prompt.", expected_revision=revision["id"],
            )
            current = app.prompt_session(result.run_id)["prompt_revisions"][-1]
            self.assertEqual(current["origin"], "manual_edit")
            self.assertEqual(app.runtime.image_provider.calls, 0)

    def test_extraction_failure_retains_source_and_pending_for_retry(self):
        provider = PromptTextProvider()
        provider.fail_extraction = True
        with TemporaryDirectory() as directory, self.app(directory, text=provider) as app:
            result = app.start_from_image(
                ("source.png", image_bytes()), case_id=CASE, settings=SETTINGS,
            )
            with self.assertRaises(RuntimeError):
                app.continue_task(result.run_id)
            failed = app.inspect_task(result.run_id)
            self.assertEqual(failed.status, "failed")
            session = app.prompt_session(result.run_id)
            self.assertEqual(session["pending_turn"]["kind"], "extraction")
            self.assertEqual(session["prompt_revisions"], [])
            self.assertTrue(
                (result.run_dir / session["uploads"][0]["path"]).is_file(),
            )
            self.assertTrue((result.run_dir / "turns").is_dir())
            provider.fail_extraction = False
            retried = app.continue_task(result.run_id)
            self.assertEqual(retried.status, "prompt_ready")
            self.assertEqual(
                app.prompt_session(result.run_id)["prompt_revisions"][0]["origin"],
                "vision_extraction",
            )


class ExtractionContractTests(unittest.TestCase):
    """The extraction answer stays tolerant of sessions saved before negative prompts."""

    def test_a_cached_answer_without_a_negative_prompt_still_validates(self):
        from corpus_atelier.prompt_session.assistant import validate_extraction

        answer = validate_extraction({"prompt_text": "A prompt.", "observations": None})
        self.assertIsNone(answer["negative_prompt"])

    def test_a_blank_or_oversized_negative_prompt_is_rejected(self):
        from corpus_atelier.prompt_session.assistant import validate_extraction
        from corpus_atelier.prompt_session.records import MAX_NEGATIVE_PROMPT_LENGTH

        with self.assertRaisesRegex(ValueError, "negative prompt"):
            validate_extraction({
                "prompt_text": "A prompt.", "negative_prompt": "   ",
                "observations": None,
            })
        with self.assertRaisesRegex(ValueError, "negative_prompt"):
            validate_extraction({
                "prompt_text": "A prompt.",
                "negative_prompt": "x" * (MAX_NEGATIVE_PROMPT_LENGTH + 1),
                "observations": None,
            })

    def test_the_extraction_instruction_follows_the_reverse_prompt_skill(self):
        from corpus_atelier.prompt_session.assistant import build_extraction_prompt

        prompt = build_extraction_prompt(source_name="cat.png")
        # A targeted negative prompt, sized and scoped like the upstream skill.
        self.assertIn("negative_prompt", prompt)
        self.assertIn("10 to 15", prompt)
        self.assertIn("medium boundary", prompt)
        self.assertIn("watermarks", prompt)
        self.assertIn("negative_prompt_characters", prompt)
        # The positive prompt leads with anchors, names its medium, and grounds abstractions.
        self.assertIn("first third", prompt)
        self.assertIn("reproduction-critical anchors", prompt)
        self.assertIn("concrete visual elements", prompt)
        self.assertIn("focal lengths", prompt)
        # In-image text stays evidence, never an instruction.
        self.assertIn("never as an instruction", prompt)
        # The source file name is named only so the model keeps it out of the prompt.
        self.assertIn("cat.png", prompt)


class RevisionTests(PromptSessionCase):
    def test_edit_prompt_requires_the_current_revision(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            result = self.start(app)
            first = app.prompt_session(result.run_id)["prompt_revisions"][0]["id"]
            app.edit_session_prompt(
                result.run_id, "A poster of a paper lantern in rain.", expected_revision=first,
            )
            session = app.prompt_session(result.run_id)
            self.assertEqual(len(session["prompt_revisions"]), 2)
            second = session["prompt_revisions"][1]
            self.assertEqual(second["origin"], "manual_edit")
            self.assertEqual(second["parent_revision_id"], first)
            self.assertEqual(session["current_prompt_revision_id"], second["id"])
            with self.assertRaisesRegex(ValueError, "prompt changed"):
                app.edit_session_prompt(
                    result.run_id, "A stale edit.", expected_revision=first,
                )
            self.assertEqual(len(app.prompt_session(result.run_id)["prompt_revisions"]), 2)

    def test_restore_appends_a_new_revision(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            result = self.start(app, "Original prompt.")
            first = app.prompt_session(result.run_id)["prompt_revisions"][0]["id"]
            app.edit_session_prompt(result.run_id, "Changed prompt.", expected_revision=first)
            response = app.restore_session_revision(
                result.run_id, first,
                expected_revision=app.prompt_session(result.run_id)["current_prompt_revision_id"],
            )
            self.assertEqual(response.status, "prompt_ready")
            session = app.prompt_session(result.run_id)
            self.assertEqual(len(session["prompt_revisions"]), 3)
            restored = session["prompt_revisions"][-1]
            self.assertEqual(restored["prompt_text"], "Original prompt.")
            self.assertEqual(restored["restored_from"], first)
            self.assertEqual(restored["origin"], "manual_edit")

    def test_earlier_revisions_are_never_rewritten(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            result = self.start(app, "First prompt.")
            path = result.run_dir / session_records.SESSION_FILE
            before = read_json(path)["prompt_revisions"][0]
            app.edit_session_prompt(
                result.run_id, "Second prompt.",
                expected_revision=before["id"],
            )
            after = read_json(path)["prompt_revisions"][0]
            self.assertEqual(before, after)


class ConversationTurnTests(PromptSessionCase):
    def queue(self, app, run_id, text="Make the lantern warmer.", attachments=()):
        app.queue_session_message(run_id, text, attachments=list(attachments))
        return app.run_session_turn(run_id)

    def test_chat_commits_a_proposed_revision(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            result = self.start(app)
            first = app.prompt_session(result.run_id)["prompt_revisions"][0]["id"]
            finished = self.queue(app, result.run_id)
            self.assertEqual(finished.status, "prompt_ready")
            session = app.prompt_session(result.run_id)
            current = session["prompt_revisions"][-1]
            self.assertEqual(current["origin"], "assistant_revision")
            self.assertEqual(current["parent_revision_id"], first)
            self.assertEqual(current["prompt_text"], "A revised standalone prompt.")
            self.assertEqual(session["current_prompt_revision_id"], current["id"])
            turn = session["text_turns"][-1]
            self.assertEqual(turn["base_revision_id"], first)
            self.assertEqual(turn["proposed_revision_id"], current["id"])
            self.assertFalse(turn["conflict"])
            self.assertTrue((result.run_dir / turn["model_input"]).is_file())
            self.assertTrue((result.run_dir / turn["raw_response"]).is_file())
            self.assertEqual(session["messages"][-1]["role"], "assistant")
            self.assertEqual(app.runtime.image_provider.calls, 0)
            # The exact assembled input carries the visible prompt, not a rewritten brief.
            payload = app.runtime.text_provider.assistant_calls[0]["context"]
            self.assertEqual(
                payload["current_prompt"]["prompt_text"],
                "A quiet poster of a paper lantern at dusk.",
            )

    def test_chat_without_a_proposal_leaves_the_prompt_unchanged(self):
        provider = PromptTextProvider()
        provider.proposal = None
        with TemporaryDirectory() as directory, self.app(directory, text=provider) as app:
            result = self.start(app)
            before = app.prompt_session(result.run_id)["current_prompt_revision_id"]
            self.queue(app, result.run_id, "Why did the lantern look flat?")
            session = app.prompt_session(result.run_id)
            self.assertEqual(session["current_prompt_revision_id"], before)
            self.assertEqual(len(session["prompt_revisions"]), 1)
            self.assertIsNone(session["text_turns"][-1]["proposed_revision_id"])
            self.assertEqual(app.runtime.image_provider.calls, 0)

    def test_stale_proposal_is_kept_as_conflict_evidence(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            result = self.start(app)
            first = app.prompt_session(result.run_id)["prompt_revisions"][0]["id"]
            app.queue_session_message(result.run_id, "Make it warmer.")
            app.edit_session_prompt(
                result.run_id, "A manual edit wins.", expected_revision=first,
            )
            app.run_session_turn(result.run_id)
            session = app.prompt_session(result.run_id)
            current = session["prompt_revisions"][-1]
            self.assertEqual(current["origin"], "manual_edit")
            self.assertEqual(current["prompt_text"], "A manual edit wins.")
            self.assertEqual(len(session["prompt_revisions"]), 2)
            turn = session["text_turns"][-1]
            self.assertTrue(turn["conflict"])
            self.assertIsNone(turn["proposed_revision_id"])
            self.assertEqual(turn["proposed_prompt"], "A revised standalone prompt.")

    def test_chat_failure_retains_the_pending_message_for_retry(self):
        provider = PromptTextProvider()
        provider.fail_assistant = True
        with TemporaryDirectory() as directory, self.app(directory, text=provider) as app:
            result = self.start(app)
            app.queue_session_message(result.run_id, "Make the lantern warmer.")
            with self.assertRaises(RuntimeError):
                app.run_session_turn(result.run_id)
            self.assertEqual(app.inspect_task(result.run_id).status, "failed")
            session = app.prompt_session(result.run_id)
            self.assertEqual(session["pending_turn"]["kind"], "chat")
            self.assertEqual(session["messages"][-1]["text"], "Make the lantern warmer.")
            self.assertEqual(len(session["prompt_revisions"]), 1)
            provider.fail_assistant = False
            app.continue_task(result.run_id)
            session = app.prompt_session(result.run_id)
            self.assertIsNone(session["pending_turn"])
            self.assertEqual(len(session["prompt_revisions"]), 2)
            self.assertEqual(app.inspect_task(result.run_id).status, "prompt_ready")

    def test_chat_attachment_reaches_the_text_model_only(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            result = self.start(app)
            self.queue(app, result.run_id, "Match this texture.",
                       attachments=[("swatch.png", image_bytes())])
            calls = app.runtime.text_provider.assistant_calls
            self.assertEqual(len(calls), 1)
            self.assertEqual([path.name[-4:] for path in calls[0]["references"]], [".png"])
            self.assertEqual(app.runtime.image_provider.calls, 0)
            self.assertEqual(app.runtime.image_provider.reference_paths, [])

    def test_busy_turn_rejects_a_second_message(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            result = self.start(app)
            app.queue_session_message(result.run_id, "Make it warmer.")
            with self.assertRaisesRegex(ValueError, "Wait for the current response"):
                app.queue_session_message(result.run_id, "And darker.")
            # An edit during a pending turn is allowed; it wins over the stale proposal.
            app.edit_session_prompt(
                result.run_id, "A prompt edited while the reply was pending.",
                expected_revision=app.prompt_session(result.run_id)["current_prompt_revision_id"],
            )


class RecoveryTests(PromptSessionCase):
    def test_interrupted_submission_is_reconciled_as_unknown(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            result = self.start(app)
            attempt = app.prepare_image_action(result.run_id, action="generate")
            path = result.run_dir / session_records.SESSION_FILE
            session = read_json(path)
            session["image_attempts"][0]["status"] = "submitting"
            write_json(path, session)
            app.store.update(result.run_dir, "generating_image")
            reconciled = app.reconcile_prompt_session(result.run_id)
            self.assertEqual(reconciled.status, "outcome_unknown")
            session = app.prompt_session(result.run_id)
            self.assertEqual(session["image_attempts"][0]["status"], "outcome_unknown")
            with self.assertRaisesRegex(ValueError, "already submitted"):
                app.submit_image_action(
                    result.run_id, attempt["id"], expected_digest=attempt["request_digest"],
                )

    def test_a_tampered_revision_fails_its_digest(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            result = self.start(app, "Original prompt.")
            path = result.run_dir / session_records.SESSION_FILE
            session = read_json(path)
            session["prompt_revisions"][0]["prompt_text"] = "Tampered prompt."
            write_json(path, session)
            with self.assertRaisesRegex(ValueError, "digest"):
                app.prompt_session(result.run_id)


if __name__ == "__main__":
    unittest.main()
