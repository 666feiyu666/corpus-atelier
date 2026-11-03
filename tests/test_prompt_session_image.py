"""Offline checks for frozen image actions, lineage, and stale-submit guards."""

from io import BytesIO
import json
import unittest
from tempfile import TemporaryDirectory

from PIL import Image

from corpus_atelier.app.service import CorpusAtelierApplication
from corpus_atelier.artifacts.records import read_json
from tests.fakes import FakeImageProvider
from tests.test_prompt_session import CASE, SETTINGS, PromptTextProvider


def image_bytes(fmt="PNG", color=(30, 70, 110)):
    buffer = BytesIO()
    Image.new("RGB", (64, 48), color).save(buffer, format=fmt)
    return buffer.getvalue()


class TimeoutImageProvider(FakeImageProvider):
    """Simulate a request that may have reached the provider before it failed."""

    def generate(self, prompt, *, size, output, reference_paths=None, mask_path=None):
        self.calls += 1
        raise TimeoutError("the image request timed out")


class ImageActionCase(unittest.TestCase):
    def app(self, root, image=None):
        return CorpusAtelierApplication(
            runs_root=root, text_provider=PromptTextProvider(),
            image_provider=image or FakeImageProvider(),
        )

    def start(self, app, prompt="A quiet poster of a paper lantern at dusk."):
        return app.start_from_prompt(prompt, case_id=CASE, settings=SETTINGS)

    def submit(self, app, run_id, attempt):
        return app.submit_image_action(
            run_id, attempt["id"], expected_digest=attempt["request_digest"],
        )


class GenerateTests(ImageActionCase):
    def test_the_prompt_reaches_the_provider_byte_for_byte(self):
        prompt = "  Poster: a paper lantern at dusk.\nExact copy: “灯会”  \n"
        with TemporaryDirectory() as directory, self.app(directory) as app:
            result = self.start(app, prompt)
            attempt = app.prepare_image_action(result.run_id, action="generate")
            self.assertEqual(attempt["request_text"], prompt)
            self.assertIsNone(attempt["source_image_id"])
            self.assertEqual(attempt["reference_image_ids"], [])
            self.assertEqual(attempt["status"], "prepared")
            request = read_json(result.run_dir / attempt["request_path"])
            self.assertEqual(request["prompt"], prompt)
            self.assertEqual(request["operation"], "generation")
            self.assertEqual(
                (result.run_dir / "image-attempts" / attempt["id"] / "prompt.md")
                .read_text(encoding="utf-8"),
                prompt,
            )
            submitted = self.submit(app, result.run_id, attempt)
            self.assertEqual(submitted.status, "prompt_ready")
            self.assertEqual(app.runtime.image_provider.calls, 1)
            session = app.prompt_session(result.run_id)
            self.assertEqual(len(session["image_results"]), 1)
            image = session["image_results"][0]
            self.assertEqual(image["attempt_id"], attempt["id"])
            self.assertEqual(image["request_text"], prompt)
            self.assertEqual(image["prompt_revision_id"], attempt["prompt_revision_id"])
            self.assertIsNone(image["parent_image_id"])
            self.assertTrue((result.run_dir / image["path" if "path" in image else "image_path"]).is_file())
            self.assertEqual(session["active_image_id"], image["id"])
            manifest = app.inspect_task(result.run_id).manifest
            self.assertEqual(manifest["image_sha256"], image["sha256"])

    def test_a_second_submit_of_the_same_attempt_is_rejected(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            result = self.start(app)
            attempt = app.prepare_image_action(result.run_id, action="generate")
            self.submit(app, result.run_id, attempt)
            with self.assertRaisesRegex(ValueError, "already submitted"):
                self.submit(app, result.run_id, attempt)
            self.assertEqual(app.runtime.image_provider.calls, 1)

    def test_a_mismatched_digest_is_rejected(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            result = self.start(app)
            attempt = app.prepare_image_action(result.run_id, action="generate")
            with self.assertRaisesRegex(ValueError, "request changed"):
                app.submit_image_action(
                    result.run_id, attempt["id"], expected_digest="0" * 64,
                )
            self.assertEqual(app.runtime.image_provider.calls, 0)

    def test_a_prompt_edit_after_preparation_makes_the_submit_stale(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            result = self.start(app)
            attempt = app.prepare_image_action(result.run_id, action="generate")
            app.edit_session_prompt(
                result.run_id, "A newer prompt.",
                expected_revision=app.prompt_session(result.run_id)["current_prompt_revision_id"],
            )
            with self.assertRaisesRegex(ValueError, "prompt changed after this request"):
                self.submit(app, result.run_id, attempt)
            self.assertEqual(app.runtime.image_provider.calls, 0)
            with self.assertRaisesRegex(ValueError, "prompt changed after this request was prepared"):
                app.prepare_image_action(
                    result.run_id, action="generate",
                    expected_revision=attempt["prompt_revision_id"],
                )

    def test_regenerate_creates_a_sibling_without_an_implicit_source(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            result = self.start(app)
            first = app.prepare_image_action(result.run_id, action="generate")
            self.submit(app, result.run_id, first)
            second = app.prepare_image_action(result.run_id, action="generate")
            self.submit(app, result.run_id, second)
            session = app.prompt_session(result.run_id)
            self.assertEqual(len(session["image_results"]), 2)
            self.assertEqual(app.runtime.image_provider.calls, 2)
            self.assertEqual(app.runtime.image_provider.reference_paths, [])
            prompts = {image["request_text"] for image in session["image_results"]}
            self.assertEqual(prompts, {"A quiet poster of a paper lantern at dusk."})
            for image in session["image_results"]:
                self.assertIsNone(image["parent_image_id"])
            self.assertEqual(session["active_image_id"], session["image_results"][-1]["id"])
            # The first result keeps its own request and revision link.
            self.assertNotEqual(
                session["image_results"][0]["attempt_id"],
                session["image_results"][1]["attempt_id"],
            )

    def test_no_implicit_source_image_is_ever_accepted(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            result = self.start(app)
            first = app.prepare_image_action(result.run_id, action="generate")
            self.submit(app, result.run_id, first)
            image_id = app.prompt_session(result.run_id)["image_results"][0]["id"]
            with self.assertRaisesRegex(ValueError, "never sends an implicit source image"):
                app.prepare_image_action(
                    result.run_id, action="generate", source_image_id=image_id,
                )


class ReferenceSelectionTests(ImageActionCase):
    def test_an_uploaded_image_is_sent_only_when_explicitly_selected(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            result = start_with_attachment(app)
            upload = app.prompt_session(result.run_id)["uploads"][0]
            plain = app.prepare_image_action(result.run_id, action="generate")
            self.assertEqual(plain["reference_image_ids"], [])
            self.submit(app, result.run_id, plain)
            self.assertEqual(app.runtime.image_provider.reference_paths, [])
            selected = app.prepare_image_action(
                result.run_id, action="generate", reference_image_ids=[upload["id"]],
            )
            self.assertEqual(selected["reference_image_ids"], [upload["id"]])
            self.assertEqual(len(selected["references"]), 1)
            self.submit(app, result.run_id, selected)
            self.assertEqual(len(app.runtime.image_provider.reference_paths), 1)
            request = read_json(result.run_dir / selected["request_path"])
            self.assertEqual(request["operation"], "reference_generation")
            self.assertEqual(request["references"][0]["sha256"], upload["sha256"])

    def test_more_than_three_references_are_rejected(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            result = self.start(app)
            ids = []
            for index in range(4):
                app.queue_session_message(
                    result.run_id, f"Attachment {index}.",
                    attachments=[(f"swatch-{index}.png", image_bytes(color=(index * 10, 20, 30)))],
                )
                ids = [
                    item["id"] for item in app.prompt_session(result.run_id)["uploads"]
                ]
                app.run_session_turn(result.run_id)
            with self.assertRaisesRegex(ValueError, "at most 3 reference images"):
                app.prepare_image_action(
                    result.run_id, action="generate", reference_image_ids=ids,
                )


def start_with_attachment(app, prompt="A poster with this texture."):
    result = app.start_from_prompt(prompt, case_id=CASE, settings=SETTINGS)
    app.queue_session_message(
        result.run_id, "Use this texture.", attachments=[("swatch.png", image_bytes())],
    )
    app.run_session_turn(result.run_id)
    return result


class EditTests(ImageActionCase):
    def test_edit_sends_the_selected_source_image_and_visible_instruction(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            result = self.start(app)
            first = app.prepare_image_action(result.run_id, action="generate")
            self.submit(app, result.run_id, first)
            source = app.prompt_session(result.run_id)["image_results"][0]
            instruction = "Warm the lantern light and keep the composition."
            attempt = app.prepare_image_action(
                result.run_id, action="edit", source_image_id=source["id"],
                edit_instruction=instruction,
            )
            self.assertEqual(attempt["request_text"], instruction)
            self.assertEqual(attempt["edit_instruction"], instruction)
            self.assertEqual(attempt["reference_image_ids"], [source["id"]])
            self.assertEqual(attempt["references"][0]["sha256"], source["sha256"])
            request = read_json(result.run_dir / attempt["request_path"])
            self.assertEqual(request["prompt"], instruction)
            self.assertEqual(request["operation"], "reference_generation")
            self.submit(app, result.run_id, attempt)
            session = app.prompt_session(result.run_id)
            edited = session["image_results"][-1]
            self.assertEqual(edited["parent_image_id"], source["id"])
            self.assertEqual(edited["action"], "edit")
            self.assertEqual(edited["request_text"], instruction)
            # The source revision of the edit is the current prompt, not the instruction.
            self.assertEqual(
                edited["prompt_revision_id"], session["current_prompt_revision_id"],
            )
            self.assertEqual(len(app.runtime.image_provider.reference_paths), 1)

    def test_edit_requires_a_source_image_and_an_instruction(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            result = self.start(app)
            first = app.prepare_image_action(result.run_id, action="generate")
            self.submit(app, result.run_id, first)
            source_id = app.prompt_session(result.run_id)["image_results"][0]["id"]
            with self.assertRaisesRegex(ValueError, "Choose the image to edit"):
                app.prepare_image_action(
                    result.run_id, action="edit", edit_instruction="Brighten it.",
                )
            with self.assertRaisesRegex(ValueError, "edit instruction"):
                app.prepare_image_action(
                    result.run_id, action="edit", source_image_id=source_id,
                    edit_instruction="   ",
                )

    def test_masks_keep_the_provider_input_validation(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            result = start_with_attachment(app)
            session = app.prompt_session(result.run_id)
            upload_id = session["uploads"][0]["id"]
            with self.assertRaisesRegex(ValueError, "exactly one reference image"):
                app.prepare_image_action(
                    result.run_id, action="generate", mask_image_id=upload_id,
                )


class FailureTests(ImageActionCase):
    def test_a_failed_attempt_retains_its_frozen_request(self):
        with TemporaryDirectory() as directory, self.app(directory, image=FakeImageProvider(fail=True)) as app:
            result = self.start(app)
            attempt = app.prepare_image_action(result.run_id, action="generate")
            with self.assertRaises(RuntimeError):
                self.submit(app, result.run_id, attempt)
            session = app.prompt_session(result.run_id)
            saved = session["image_attempts"][0]
            self.assertEqual(saved["status"], "failed")
            self.assertEqual(saved["error"]["type"], "RuntimeError")
            self.assertEqual(saved["request_text"], "A quiet poster of a paper lantern at dusk.")
            self.assertTrue((result.run_dir / saved["request_path"]).is_file())
            self.assertEqual(session["image_results"], [])
            self.assertEqual(app.inspect_task(result.run_id).status, "failed")
            with self.assertRaisesRegex(ValueError, "already submitted"):
                self.submit(app, result.run_id, attempt)

    def test_a_timeout_is_recorded_as_an_unknown_outcome(self):
        with TemporaryDirectory() as directory, self.app(directory, image=TimeoutImageProvider()) as app:
            result = self.start(app)
            attempt = app.prepare_image_action(result.run_id, action="generate")
            with self.assertRaises(TimeoutError):
                self.submit(app, result.run_id, attempt)
            session = app.prompt_session(result.run_id)
            self.assertEqual(session["image_attempts"][0]["status"], "outcome_unknown")
            self.assertEqual(app.inspect_task(result.run_id).status, "outcome_unknown")
            # Nothing retries the same attempt; the user must prepare a new explicit request.
            with self.assertRaisesRegex(ValueError, "already submitted"):
                self.submit(app, result.run_id, attempt)
            self.assertEqual(app.runtime.image_provider.calls, 1)

    def test_a_discarded_preparation_never_calls_the_provider(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            result = self.start(app)
            attempt = app.prepare_image_action(result.run_id, action="generate")
            app.discard_image_action(result.run_id, attempt["id"])
            with self.assertRaisesRegex(ValueError, "already submitted"):
                self.submit(app, result.run_id, attempt)
            self.assertEqual(app.runtime.image_provider.calls, 0)


class SelectionTests(ImageActionCase):
    def test_selecting_a_result_leaves_other_results_untouched(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            result = self.start(app)
            for _ in range(2):
                attempt = app.prepare_image_action(result.run_id, action="generate")
                self.submit(app, result.run_id, attempt)
            before = app.prompt_session(result.run_id)["image_results"]
            app.select_prompt_result(result.run_id, before[0]["id"])
            session = app.prompt_session(result.run_id)
            self.assertEqual(session["active_image_id"], before[0]["id"])
            self.assertEqual(session["image_results"], before)
            self.assertEqual(len(session["image_attempts"]), 2)

    def test_a_later_prompt_edit_does_not_rewrite_earlier_results(self):
        with TemporaryDirectory() as directory, self.app(directory) as app:
            result = self.start(app, "First prompt.")
            attempt = app.prepare_image_action(result.run_id, action="generate")
            self.submit(app, result.run_id, attempt)
            image = app.prompt_session(result.run_id)["image_results"][0]
            app.edit_session_prompt(
                result.run_id, "Second prompt.",
                expected_revision=app.prompt_session(result.run_id)["current_prompt_revision_id"],
            )
            session = app.prompt_session(result.run_id)
            self.assertEqual(session["image_results"][0], image)
            self.assertEqual(session["image_results"][0]["request_text"], "First prompt.")
            self.assertNotEqual(
                session["current_prompt_revision_id"], image["prompt_revision_id"],
            )
            self.assertEqual(
                (result.run_dir / attempt["request_path"]).read_text(encoding="utf-8"),
                json.dumps(read_json(result.run_dir / attempt["request_path"]),
                           ensure_ascii=False, indent=2) + "\n",
            )


if __name__ == "__main__":
    unittest.main()
