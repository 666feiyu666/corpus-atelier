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


def image_bytes(fmt="PNG", size=(64, 48)):
    buffer = BytesIO()
    Image.new("RGB", size, (30, 70, 110)).save(buffer, format=fmt)
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
            "visible_copy": [
                {"text": "灯会", "language": "zh", "uncertain": False},
                {"text": "LANTERN NIGHT", "language": "en", "uncertain": True},
            ],
            "uncertainties": ["The small label is only partly legible."],
            "observations": "The small label is only partly legible.",
        }
        self.refine = {
            "reply": "The result crops the title band and warms the palette.",
            "discrepancies": [
                "The title band is cropped.",
                "The palette is warmer than the source.",
            ],
            "proposed_prompt": (
                "A refined prompt that restores the title band and cools the palette."
            ),
        }
        self.refine_calls = []
        self.prepare = {
            "prompt_text": "An expanded standalone prompt.",
            "notes": "Added lighting and material detail.",
        }
        self.prepare_calls = []
        self.fail_assistant = False
        self.fail_extraction = False
        self.fail_refine = False

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
        if schema_name == "prompt-prepare.schema.json":
            self.prepare_calls.append({
                "prompt": prompt, "references": list(reference_paths or []),
            })
            return dict(self.prepare), {"status": "completed", "provider": "fake-prepare"}
        if schema_name == "prompt-refine.schema.json":
            self.refine_calls.append({
                "prompt": prompt, "references": list(reference_paths or []),
            })
            if self.fail_refine:
                raise RuntimeError("deliberate refinement failure")
            return dict(self.refine), {"status": "completed", "provider": "fake-refine"}
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
            self.assertEqual(
                [item["text"] for item in revision["visible_copy"]],
                ["灯会", "LANTERN NIGHT"],
            )
            self.assertFalse(revision["visible_copy"][0]["uncertain"])
            self.assertTrue(revision["visible_copy"][1]["uncertain"])
            self.assertEqual(
                revision["uncertainties"], ["The small label is only partly legible."],
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

    def test_the_cached_answer_without_the_new_evidence_still_validates(self):
        from corpus_atelier.prompt_session.assistant import validate_extraction

        answer = validate_extraction({"prompt_text": "A prompt.", "observations": None})
        self.assertEqual(answer["visible_copy"], [])
        self.assertEqual(answer["uncertainties"], [])

    def test_blank_copy_or_uncertainty_text_is_rejected(self):
        from corpus_atelier.prompt_session.assistant import validate_extraction

        with self.assertRaisesRegex(ValueError, "visible copy"):
            validate_extraction({
                "prompt_text": "A prompt.", "observations": None,
                "visible_copy": [{"text": "   "}],
            })
        with self.assertRaisesRegex(ValueError, "uncertainty"):
            validate_extraction({
                "prompt_text": "A prompt.", "observations": None,
                "uncertainties": ["  "],
            })

    def test_the_extraction_instruction_follows_the_reverse_prompt_skill(self):
        from corpus_atelier.prompt_session.assistant import build_extraction_prompt

        prompt = build_extraction_prompt(source_name="cat.png")
        # The negative prompt is optional, and targeted when it is returned.
        self.assertIn("negative_prompt is optional", prompt)
        self.assertIn("at most 8", prompt)
        self.assertIn("keep that boundary visible", prompt)
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


class CanvasIntentTests(PromptSessionCase):
    """An image-started session keeps the source canvas unless the user decides otherwise."""

    def test_the_source_canvas_becomes_the_default_output(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            result = app.start_from_image(
                ("source.png", image_bytes()), case_id=CASE,
                settings={"image_quality": "medium", "aspect_ratio": [16, 9]},
            )
            settings = app.prompt_session(result.run_id)["settings"]
            self.assertEqual(settings["source_canvas"], {"width": 64, "height": 48})
            self.assertEqual(settings["canvas_origin"], "source")
            self.assertEqual(settings["aspect_ratio"], [4, 3])
            self.assertIsNotNone(settings["size"])
            width, height = (int(part) for part in settings["size"].split("x"))
            self.assertEqual(width * 3, height * 4)
            self.assertIsNone(settings["canvas_note"])
            self.assertIsNone(settings["requested_canvas"])

    def test_an_unsupported_source_ratio_waits_for_an_explicit_choice(self):
        wide = image_bytes(size=(400, 100))
        with TemporaryDirectory() as directory, self.app(directory) as app:
            result = app.start_from_image(
                ("wide.png", wide), case_id=CASE, settings=SETTINGS,
            )
            app.continue_task(result.run_id)
            settings = app.prompt_session(result.run_id)["settings"]
            self.assertIsNone(settings["size"])
            self.assertIn("1:3 and 3:1", settings["canvas_note"])
            with self.assertRaisesRegex(ValueError, "Choose an output size"):
                app.prepare_image_action(result.run_id, action="generate")
            app.set_session_canvas(result.run_id, (1, 1))
            chosen = app.prompt_session(result.run_id)["settings"]
            self.assertEqual(chosen["canvas_origin"], "user")
            self.assertEqual(chosen["requested_canvas"], {"width": 1, "height": 1})
            self.assertEqual(chosen["aspect_ratio"], [1, 1])
            self.assertIsNotNone(chosen["size"])
            attempt = app.prepare_image_action(result.run_id, action="generate")
            self.assertEqual(attempt["settings"]["size"], chosen["size"])

    def test_restoring_the_source_canvas_drops_the_user_override(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            result = app.start_from_image(
                ("source.png", image_bytes()), case_id=CASE, settings=SETTINGS,
            )
            app.continue_task(result.run_id)
            app.set_session_canvas(result.run_id, (1, 1))
            self.assertEqual(
                app.prompt_session(result.run_id)["settings"]["canvas_origin"], "user",
            )
            app.set_session_canvas(result.run_id)
            restored = app.prompt_session(result.run_id)["settings"]
            self.assertEqual(restored["canvas_origin"], "source")
            self.assertIsNone(restored["requested_canvas"])
            self.assertEqual(restored["aspect_ratio"], [4, 3])

    def test_an_unusable_override_is_rejected(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            result = app.start_from_image(
                ("source.png", image_bytes()), case_id=CASE, settings=SETTINGS,
            )
            with self.assertRaisesRegex(ValueError, "between 1:3 and 3:1"):
                app.set_session_canvas(result.run_id, (8, 1))
            self.assertEqual(
                app.prompt_session(result.run_id)["settings"]["canvas_origin"], "source",
            )


class RefineTests(PromptSessionCase):
    """Comparing the source with a result proposes a new, user-owned revision."""

    @staticmethod
    def _image_session_with_result(app):
        result = app.start_from_image(
            ("source.png", image_bytes()), case_id=CASE, settings=SETTINGS,
        )
        app.continue_task(result.run_id)
        attempt = app.prepare_image_action(result.run_id, action="generate")
        app.submit_image_action(
            result.run_id, attempt["id"], expected_digest=attempt["request_digest"],
        )
        session = app.prompt_session(result.run_id)
        return result.run_id, session["image_results"][0]["id"]

    def test_a_source_comparison_commits_a_new_revision(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            run_id, image_id = self._image_session_with_result(app)
            app.queue_refine_turn(run_id, image_id)
            self.assertEqual(
                app.prompt_session(run_id)["pending_turn"]["kind"], "refine",
            )
            app.continue_task(run_id)
            session = app.prompt_session(run_id)
            self.assertIsNone(session["pending_turn"])
            revision = session["prompt_revisions"][-1]
            self.assertEqual(revision["origin"], "assistant_revision")
            self.assertEqual(
                revision["prompt_text"],
                "A refined prompt that restores the title band and cools the palette.",
            )
            self.assertEqual(
                revision["note"],
                "The title band is cropped.; The palette is warmer than the source.",
            )
            message = session["messages"][-1]
            self.assertEqual(
                message["discrepancies"],
                ["The title band is cropped.", "The palette is warmer than the source."],
            )
            self.assertEqual(len(message["attachment_ids"]), 2)
            calls = app.runtime.text_provider.refine_calls
            self.assertEqual(len(calls), 1)
            self.assertEqual(len(calls[0]["references"]), 2)

    @staticmethod
    def _prompt_session_with_results(app, count):
        """A prompt-started session with `count` generated results."""
        result = app.start_from_prompt(
            "A quiet poster of a paper lantern at dusk.", case_id=CASE, settings=SETTINGS,
        )
        ids = []
        for _ in range(count):
            attempt = app.prepare_image_action(result.run_id, action="generate")
            app.submit_image_action(
                result.run_id, attempt["id"], expected_digest=attempt["request_digest"],
            )
            ids.append(app.prompt_session(result.run_id)["image_results"][-1]["id"])
        return result.run_id, ids

    def test_a_prompt_session_refines_against_an_earlier_result(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            run_id, (first, second) = self._prompt_session_with_results(app, 2)
            app.queue_refine_turn(run_id, second)
            pending = app.prompt_session(run_id)["pending_turn"]
            self.assertEqual(pending["kind"], "refine")
            self.assertEqual(pending["base_image_id"], first)
            app.continue_task(run_id)
            session = app.prompt_session(run_id)
            self.assertEqual(session["prompt_revisions"][-1]["origin"], "assistant_revision")
            message = session["messages"][-1]
            self.assertEqual(message["attachment_ids"], [first, second])
            self.assertEqual(len(app.runtime.text_provider.refine_calls), 1)

    def test_an_explicit_base_can_be_chosen(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            run_id, (first, second) = self._prompt_session_with_results(app, 2)
            app.queue_refine_turn(run_id, second, base_image_id=first)
            self.assertEqual(
                app.prompt_session(run_id)["pending_turn"]["base_image_id"], first,
            )

    def test_refining_needs_something_to_compare_with(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            run_id, (only,) = self._prompt_session_with_results(app, 1)
            with self.assertRaisesRegex(ValueError, "compared with"):
                app.queue_refine_turn(run_id, only)

    def test_a_result_cannot_be_compared_with_itself(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            run_id, (_, second) = self._prompt_session_with_results(app, 2)
            with self.assertRaisesRegex(ValueError, "itself"):
                app.queue_refine_turn(run_id, second, base_image_id=second)

    def test_a_failed_comparison_keeps_the_pending_turn(self):
        provider = PromptTextProvider()
        provider.fail_refine = True
        with TemporaryDirectory() as directory, self.app(directory, text=provider) as app:
            run_id, image_id = self._image_session_with_result(app)
            app.queue_refine_turn(run_id, image_id)
            with self.assertRaises(RuntimeError):
                app.continue_task(run_id)
            session = app.prompt_session(run_id)
            self.assertEqual(session["pending_turn"]["kind"], "refine")
            self.assertEqual(app.inspect_task(run_id).status, "failed")
            provider.fail_refine = False
            app.continue_task(run_id)
            self.assertEqual(app.inspect_task(run_id).status, "prompt_ready")
            self.assertEqual(len(app.prompt_session(run_id)["prompt_revisions"]), 2)


class ProposalTests(PromptSessionCase):
    """A prepared proposal stays visible until the user adopts it."""

    def test_a_proposal_is_visible_but_not_applied(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            result = self.start(app)
            proposal = app.prepare_prompt_proposal(result.run_id, "generate")
            session = app.prompt_session(result.run_id)
            self.assertEqual(len(session["prompt_revisions"]), 1)
            self.assertEqual(proposal["kind"], "generate")
            self.assertEqual(
                proposal["base_revision_id"], session["current_prompt_revision_id"],
            )
            self.assertEqual(session["prompt_proposals"][-1]["id"], proposal["id"])
            self.assertEqual(
                app.runtime.text_provider.prepare_calls[-1]["references"], [],
            )

    def test_an_edit_proposal_carries_the_current_instruction(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            result = self.start(app)
            app.prepare_prompt_proposal(
                result.run_id, "edit", edit_instruction="Warm the lantern light.",
            )
            self.assertIn(
                "Warm the lantern light.",
                app.runtime.text_provider.prepare_calls[-1]["prompt"],
            )

    def test_adopting_a_proposal_adds_a_revision(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            result = self.start(app)
            proposal = app.prepare_prompt_proposal(result.run_id, "generate")
            current = app.prompt_session(result.run_id)["current_prompt_revision_id"]
            app.adopt_prompt_proposal(
                result.run_id, proposal["id"], expected_revision=current,
            )
            session = app.prompt_session(result.run_id)
            revision = session["prompt_revisions"][-1]
            self.assertEqual(revision["origin"], "assistant_revision")
            self.assertEqual(revision["prompt_text"], "An expanded standalone prompt.")
            self.assertEqual(revision["note"], "Added lighting and material detail.")
            self.assertEqual(
                session["prompt_proposals"][-1]["adopted_revision_id"], revision["id"],
            )

    def test_a_stale_or_unknown_proposal_is_rejected(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            result = self.start(app)
            proposal = app.prepare_prompt_proposal(result.run_id, "generate")
            first = app.prompt_session(result.run_id)["current_prompt_revision_id"]
            app.edit_session_prompt(
                result.run_id, "A newer prompt.", expected_revision=first,
            )
            with self.assertRaisesRegex(ValueError, "prompt changed"):
                app.adopt_prompt_proposal(
                    result.run_id, proposal["id"], expected_revision=first,
                )
            with self.assertRaisesRegex(ValueError, "does not exist"):
                app.adopt_prompt_proposal(
                    result.run_id, "prop_unknown",
                    expected_revision=app.prompt_session(result.run_id)["current_prompt_revision_id"],
                )

    def test_an_unknown_kind_is_rejected(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            result = self.start(app)
            with self.assertRaisesRegex(ValueError, "generation or editing"):
                app.prepare_prompt_proposal(result.run_id, "thumbnail")


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
