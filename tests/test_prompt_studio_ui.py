"""Streamlit checks for the prompt-centered entry and its session workspace."""

import gc
from io import BytesIO
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

from PIL import Image
import streamlit as st
from streamlit.testing.v1 import AppTest

from corpus_atelier.app.service import CorpusAtelierApplication
from corpus_atelier.artifacts.records import read_json
from corpus_atelier.prompt_session.records import SESSION_FILE
from corpus_atelier.providers import OpenAIImageProvider, OpenAITextProvider
from tests.fakes import FakeImageProvider
from tests.test_prompt_session import PromptTextProvider


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "src/corpus_atelier/ui/studio.py"
CASE = "natural-language"
SETTINGS = {"image_quality": "medium", "aspect_ratio": [16, 9]}


class _Combined:
    """Enter several context managers as one for concise test setup."""

    def __init__(self, *managers):
        self.managers = managers

    def __enter__(self):
        for manager in self.managers:
            manager.__enter__()
        return self

    def __exit__(self, *exc_info):
        for manager in reversed(self.managers):
            manager.__exit__(*exc_info)
        return False


def image_bytes(fmt="PNG"):
    buffer = BytesIO()
    Image.new("RGB", (64, 48), (30, 70, 110)).save(buffer, format=fmt)
    return buffer.getvalue()


class PromptStudioTests(unittest.TestCase):
    def setUp(self):
        self.text = PromptTextProvider()
        self.image_calls = []
        self.fail_generation = False

    def _propose(self, prompt, *, schema_name, reference_paths=None):
        return self.text.propose(
            prompt, schema_name=schema_name, reference_paths=reference_paths,
        )

    def _generate(self, prompt, *, size, output, reference_paths=None, mask_path=None):
        self.image_calls.append({
            "prompt": prompt, "size": size,
            "reference_paths": [Path(path).name for path in reference_paths or []],
        })
        if self.fail_generation:
            raise RuntimeError("deliberate generation failure")
        return FakeImageProvider().generate(
            prompt, size=size, output=output,
            reference_paths=reference_paths, mask_path=mask_path,
        )

    def patches(self):
        """Both provider methods are patched with bound fakes, not network clients."""
        return (
            patch.object(OpenAITextProvider, "propose", self._propose),
            patch.object(OpenAIImageProvider, "generate", self._generate),
        )

    def provider_patches(self):
        text_patch, image_patch = self.patches()
        return _Combined(text_patch, image_patch)

    @staticmethod
    def environment(directory):
        root = Path(directory)
        return {
            "CORPUS_ATELIER_TASKS_ROOT": directory,
            "CORPUS_ATELIER_PREFERENCES_PATH": str(root / "settings.json"),
            "CORPUS_ATELIER_ENV_PATH": str(root / ".env"),
            "CORPUS_ATELIER_CORPUS_DB": str(root / "corpus.sqlite3"),
            "CORPUS_ATELIER_CORPUS_MEDIA": str(root / "media"),
            "OPENAI_API_KEY": "sk-test",
        }

    @staticmethod
    def application(directory):
        return CorpusAtelierApplication(
            runs_root=directory,
            text_provider=OpenAITextProvider(),
            image_provider=OpenAIImageProvider(),
        )

    def create_session(self, directory, prompt="A quiet poster of a paper lantern.", *, image=False):
        with self.application(directory) as app:
            if image:
                result = app.start_from_image(
                    ("source.png", image_bytes()), case_id=CASE, settings=SETTINGS,
                )
            else:
                result = app.start_from_prompt(prompt, case_id=CASE, settings=SETTINGS)
        return result.run_id

    def generate_result(self, directory, run_id):
        with self.provider_patches(), self.application(directory) as app:
            attempt = app.prepare_image_action(run_id, action="generate")
            app.submit_image_action(
                run_id, attempt["id"], expected_digest=attempt["request_digest"],
            )
            return app.prompt_session(run_id)["image_results"][0]

    @staticmethod
    def editor(app, run_id):
        """The prompt editor bumps its widget key whenever the committed prompt changes."""
        prefix = f"prompt_text_{run_id}_"
        for area in app.text_area:
            if area.key and area.key.startswith(prefix):
                return area
        raise AssertionError("the prompt editor was not rendered")

    @staticmethod
    def wait_status(directory, run_id, status, app=None, timeout=10):
        path = Path(directory) / CASE / run_id / "manifest.json"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if path.is_file():
                value = json.loads(path.read_text(encoding="utf-8"))
                if value["status"] == status:
                    if app is not None:
                        app.run()
                    return value
            time.sleep(0.05)
        raise AssertionError(f"Session {run_id} did not reach {status}")

    @staticmethod
    def session_record(directory, run_id):
        return read_json(Path(directory) / CASE / run_id / SESSION_FILE)

    def test_the_start_screen_offers_two_distinct_entries(self):
        with TemporaryDirectory() as directory:
            with self.provider_patches(), patch.dict(os.environ, self.environment(directory)):
                app = AppTest.from_file(str(APP), default_timeout=10).run()
                self.assertFalse(app.exception)
                self.assertEqual(app.segmented_control(key="prompt_start_mode").value, "prompt")
                self.assertEqual(app.text_area(key="new_session_prompt").value, "")
                self.assertEqual(app.button(key="start_prompt_action").label, "生成图像")
                self.assertNotIn("start_image_action", [button.key for button in app.button])
                app.segmented_control(key="prompt_start_mode").set_value("image").run()
                self.assertFalse(app.exception)
                self.assertIn("start_image_action", [button.key for button in app.button])
                self.assertEqual(app.button(key="start_image_action").label, "提取提示词")
                self.assertTrue(app.button(key="start_image_action").disabled)
                self.assertIn("new_session_source", [item.key for item in app.get("file_uploader")])
            self.assertEqual(self.image_calls, [])
            self.assertEqual(self.text.assistant_calls, [])
            self.assertEqual(self.text.extraction_calls, [])

    def test_generate_from_the_start_screen_sends_the_prompt_exactly(self):
        prompt = "A poster of a paper lantern at dusk.\nExact copy: “灯会”。\n"
        with TemporaryDirectory() as directory:
            with self.provider_patches(), patch.dict(os.environ, self.environment(directory)):
                app = AppTest.from_file(str(APP), default_timeout=10).run()
                app.text_area(key="new_session_prompt").set_value(prompt).run()
                app.button(key="start_prompt_action").click().run()
                run_id = app.session_state["selected_task_id"]
                self.assertIsNotNone(run_id)
                self.wait_status(directory, run_id, "prompt_ready", app)
                session = self.session_record(directory, run_id)
                self.assertEqual(session["entry_mode"], "prompt")
                self.assertEqual(session["prompt_revisions"][0]["prompt_text"], prompt)
                self.assertEqual(session["prompt_revisions"][0]["origin"], "user_input")
                # One click produced exactly one immutable attempt.
                self.assertEqual(len(session["image_attempts"]), 1)
                attempt = session["image_attempts"][0]
                self.assertEqual(attempt["request_text"], prompt)
                self.assertIsNone(attempt["source_image_id"])
                self.assertEqual(attempt["reference_image_ids"], [])
                request = read_json(Path(directory) / CASE / run_id / attempt["request_path"])
                self.assertEqual(request["prompt"], prompt)
                self.assertEqual(len(self.image_calls), 1)
                self.assertEqual(self.image_calls[0]["prompt"], prompt)
                # No brief and no text-model rewrite intervened.
                self.assertEqual(self.text.assistant_calls, [])
                self.assertEqual(self.text.extraction_calls, [])
                self.assertEqual(len(session["image_results"]), 1)
            self.assertFalse(app.exception)
            self.assertGreaterEqual(len(app.get("image")), 1)
            downloads = app.get("download_button")
            self.assertEqual(len(downloads), 1)
            self.assertEqual(downloads[0].label, "下载")

    def test_a_failed_generation_keeps_the_selected_session(self):
        self.fail_generation = True
        with TemporaryDirectory() as directory:
            with self.provider_patches(), patch.dict(os.environ, self.environment(directory)):
                app = AppTest.from_file(str(APP), default_timeout=10).run()
                app.text_area(key="new_session_prompt").set_value("A poster that will fail.").run()
                app.button(key="start_prompt_action").click().run()
                run_id = app.session_state["selected_task_id"]
                self.assertIsNotNone(run_id)
                self.wait_status(directory, run_id, "failed", app)
                session = self.session_record(directory, run_id)
            self.assertEqual(app.session_state["selected_task_id"], run_id)
            self.assertEqual(session["image_attempts"][0]["status"], "failed")
            self.assertEqual(session["image_results"], [])
            self.assertTrue(app.error)
            self.assertIn("prompt_input_" + run_id, [item.key for item in app.chat_input])

    def test_the_workspace_saves_a_prompt_edit_and_offers_history(self):
        with TemporaryDirectory() as directory:
            run_id = self.create_session(directory, "Original prompt.")
            with self.provider_patches(), patch.dict(os.environ, self.environment(directory)):
                app = AppTest.from_file(str(APP), default_timeout=10)
                app.session_state["selected_task_id"] = run_id
                app.run()
                self.assertFalse(app.exception)
                self.editor(app, run_id).set_value("Edited prompt.").run()
                self.assertFalse(app.button(key=f"save_prompt_{run_id}").disabled)
                app.button(key=f"save_prompt_{run_id}").click().run()
                self.assertFalse(app.exception)
                session = self.session_record(directory, run_id)
                self.assertEqual(len(session["prompt_revisions"]), 2)
                current = session["prompt_revisions"][-1]
                self.assertEqual(current["prompt_text"], "Edited prompt.")
                self.assertEqual(current["origin"], "manual_edit")
                self.assertEqual(session["current_prompt_revision_id"], current["id"])
                # The editor now shows the committed prompt and history is reachable.
                self.assertEqual(self.editor(app, run_id).value, "Edited prompt.")
                self.assertEqual(
                    [button.key for button in app.button if button.key.startswith("restore_")],
                    [f"restore_{session['prompt_revisions'][0]['id']}"],
                )
            self.assertGreaterEqual(len(app.code), 1)

    def test_a_chat_turn_proposes_a_visible_revision(self):
        self.text.reply = "I tightened the lantern wording."
        self.text.proposal = "A revised lantern prompt from chat."
        with TemporaryDirectory() as directory:
            run_id = self.create_session(directory, "Original lantern prompt.")
            with self.provider_patches(), patch.dict(os.environ, self.environment(directory)):
                app = AppTest.from_file(str(APP), default_timeout=10)
                app.session_state["selected_task_id"] = run_id
                app.run()
                app.chat_input(key=f"prompt_input_{run_id}").set_value(
                    "Make the lantern warmer."
                ).run()
                self.wait_status(directory, run_id, "prompt_ready", app)
                session = self.session_record(directory, run_id)
            self.assertEqual(len(session["text_turns"]), 1)
            turn = session["text_turns"][0]
            self.assertEqual(turn["reply"], "I tightened the lantern wording.")
            self.assertIsNotNone(turn["proposed_revision_id"])
            current = session["prompt_revisions"][-1]
            self.assertEqual(current["origin"], "assistant_revision")
            self.assertEqual(current["prompt_text"], "A revised lantern prompt from chat.")
            self.assertFalse(turn["conflict"])
            # Chat alone never called the image provider.
            self.assertEqual(self.image_calls, [])
            displayed = [item.value for item in app.markdown]
            self.assertIn("I tightened the lantern wording.", displayed)
            self.assertEqual(
                self.editor(app, run_id).value,
                "A revised lantern prompt from chat.",
            )

    def test_the_workspace_prepares_and_submits_an_edit(self):
        instruction = "Warm only the lantern light; keep the composition."
        with TemporaryDirectory() as directory:
            run_id = self.create_session(directory, "A quiet poster of a paper lantern.")
            source = self.generate_result(directory, run_id)
            with self.provider_patches(), patch.dict(os.environ, self.environment(directory)):
                app = AppTest.from_file(str(APP), default_timeout=10)
                app.session_state["selected_task_id"] = run_id
                app.run()
                self.assertFalse(app.exception)
                app.selectbox(key=f"edit_source_{run_id}").set_value(source["id"]).run()
                app.text_area(key=f"edit_instruction_{run_id}").set_value(instruction).run()
                app.button(key=f"prepare_edit_{run_id}").click().run()
                prepared = app.session_state[f"prepared_{run_id}"]
                self.assertEqual(prepared["action"], "edit")
                self.assertEqual(prepared["request_text"], instruction)
                self.assertEqual(prepared["source_image_id"], source["id"])
                # The exact request is visible next to its submit button.
                self.assertIn(instruction, [code.value for code in app.code])
                app.button(key=f"submit_{prepared['id']}").click().run()
                self.wait_status(directory, run_id, "prompt_ready", app)
                session = self.session_record(directory, run_id)
            self.assertEqual(len(session["image_results"]), 2)
            edited = session["image_results"][-1]
            self.assertEqual(edited["action"], "edit")
            self.assertEqual(edited["parent_image_id"], source["id"])
            self.assertEqual(edited["request_text"], instruction)
            self.assertEqual(self.image_calls[-1]["prompt"], instruction)
            self.assertEqual(len(self.image_calls[-1]["reference_paths"]), 1)
            self.assertTrue(
                (Path(directory) / CASE / run_id / edited["image_path"]).is_file()
            )

    def test_a_duplicate_submit_never_calls_the_provider_twice(self):
        with TemporaryDirectory() as directory:
            run_id = self.create_session(directory, "A poster of a paper lantern.")
            with self.provider_patches(), patch.dict(
                os.environ, self.environment(directory),
            ):
                with self.application(directory) as app:
                    attempt = app.prepare_image_action(run_id, action="generate")
                    app.submit_image_action(
                        run_id, attempt["id"], expected_digest=attempt["request_digest"],
                    )
                    with self.assertRaisesRegex(ValueError, "already submitted"):
                        app.submit_image_action(
                            run_id, attempt["id"], expected_digest=attempt["request_digest"],
                        )
            self.assertEqual(len(self.image_calls), 1)


if __name__ == "__main__":
    unittest.main()
