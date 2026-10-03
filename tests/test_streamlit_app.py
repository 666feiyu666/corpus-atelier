import gc
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import time
import unittest
from unittest.mock import patch

from PIL import Image
import streamlit as st
from streamlit.testing.v1 import AppTest

from corpus_atelier.application import CorpusAtelierApplication
from corpus_atelier.artifacts.hashing import digest_file
from corpus_atelier.artifacts.records import write_json, write_text
from corpus_atelier.providers import OpenAITextProvider
from tests.fakes import FakeTextProvider


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "src/corpus_atelier/streamlit_app.py"


class StreamlitAppTests(unittest.TestCase):
    @staticmethod
    def _offline_propose(provider, prompt, *, schema_name, reference_paths=None):
        if schema_name == "design-conversation.schema.json":
            context = json.loads(prompt[prompt.index('{"effective_request"'):])
            return {
                "content_language": context["content_language"] or "zh-CN",
                "language_change_quote": None,
                "reply": "已理解你的需求，可以准备下一轮设计。",
                "effective_request": context["effective_request"] + context["conversation"][-1]["text"],
                "reference_notes": [], "open_questions": [],
                "suggested_user_requirements": context["suggested_user_requirements"],
                "requirement_interpretations": [
                    {"source": source, "interpretation": source}
                    for source in context["user_requirements"]
                ],
            }, {"status": "completed"}
        return FakeTextProvider().propose(prompt, schema_name=schema_name, reference_paths=reference_paths)

    @staticmethod
    def _wait_for_status(app, root, run_id, status):
        path = root / "natural-language" / run_id / "manifest.json"
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if path.exists() and json.loads(path.read_text(encoding="utf-8"))["status"] == status:
                app.run()
                return
            time.sleep(0.05)
        raise AssertionError(f"Task {run_id} did not reach {status}")

    def test_discussion_rounds_and_saved_history_in_the_interface(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, {
                "CORPUS_ATELIER_TASKS_ROOT": directory,
                "CORPUS_ATELIER_PREFERENCES_PATH": str(root / "settings.json"),
                "CORPUS_ATELIER_ENV_PATH": str(root / ".env"),
                "OPENAI_API_KEY": "sk-test",
            }), patch.object(OpenAITextProvider, "propose", self._offline_propose):
                app = AppTest.from_file(str(APP), default_timeout=10).run()
                app.toggle(key="discuss_first").set_value(True).run()
                app.chat_input(key="new_task_prompt").set_value("设计一张读书会海报。").run()
                parent_id = app.session_state["selected_task_id"]
                self._wait_for_status(app, root, parent_id, "discussing")
                self.assertFalse(app.exception)
                conversation_path = root / "natural-language" / parent_id / "conversation.json"
                conversation = json.loads(conversation_path.read_text(encoding="utf-8"))
                self.assertEqual(conversation["rounds"], [])
                self.assertIsNotNone(conversation["design_brief"])
                displayed = [item.value for item in app.markdown]
                self.assertIn(f"**目的:** {conversation['design_brief']['purpose']}", displayed)
                self.assertIn("**画面比例:** 16:9", displayed)
                self.assertIn("**已有约束:**", displayed)
                self.assertIn("**设计偏好:**", displayed)
                self.assertFalse(app.button(key=f"prepare_round_{parent_id}").disabled)
                app.button(key=f"prepare_round_{parent_id}").click().run()
                conversation = json.loads(conversation_path.read_text(encoding="utf-8"))
                child_id = conversation["rounds"][-1]["run_id"]
                self._wait_for_status(app, root, child_id, "awaiting_approval")
                self.assertFalse(app.exception)
                self.assertFalse(app.button(key=f"approve_{child_id}").disabled)
                self.assertNotIn(f"task_{child_id}", [button.key for button in app.button])
                app.chat_input(key=f"conversation_input_{parent_id}").set_value("标题更突出一点。").run()
                self._wait_for_status(app, root, parent_id, "discussing")
                self.assertTrue(app.button(key=f"approve_{child_id}").disabled)
                self.assertFalse(app.button(key=f"prepare_round_{parent_id}").disabled)
                reopened = AppTest.from_file(str(APP), default_timeout=10).run()
                reopened.button(key=f"task_{parent_id}").click().run()
                self.assertFalse(reopened.exception)
                self.assertIn("标题更突出一点。", [item.value for item in reopened.markdown])
                self.assertIsNotNone(reopened.chat_input(key=f"conversation_input_{parent_id}"))

    def test_existing_design_can_be_promoted_to_a_conversation_in_the_interface(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, {
                "CORPUS_ATELIER_TASKS_ROOT": directory,
                "CORPUS_ATELIER_PREFERENCES_PATH": str(root / "settings.json"),
                "CORPUS_ATELIER_ENV_PATH": str(root / ".env"),
                "OPENAI_API_KEY": "sk-test",
            }), patch.object(OpenAITextProvider, "propose", self._offline_propose):
                app = AppTest.from_file(str(APP), default_timeout=10).run()
                app.chat_input(key="new_task_prompt").set_value("设计一张读书会海报。").run()
                original_id = app.session_state["selected_task_id"]
                self._wait_for_status(app, root, original_id, "awaiting_approval")
                app.chat_input(key=f"followup_{original_id}").set_value("改成绿色。").run()
                parent_id = app.session_state["selected_task_id"]
                self.assertNotEqual(parent_id, original_id)
                self._wait_for_status(app, root, parent_id, "discussing")
                self.assertFalse(app.exception)
                with CorpusAtelierApplication(runs_root=root) as application:
                    conversation = application.conversation(parent_id)
                self.assertEqual(conversation["rounds"][0]["run_id"], original_id)
                self.assertIn("改成绿色。", conversation["effective_request"])
                self.assertTrue(app.button(key=f"approve_{original_id}").disabled)

    def test_contract_editor_persists_changes_and_invalidates_old_designs(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, {
                "CORPUS_ATELIER_TASKS_ROOT": directory,
                "CORPUS_ATELIER_PREFERENCES_PATH": str(root / "settings.json"),
                "CORPUS_ATELIER_ENV_PATH": str(root / ".env"),
                "OPENAI_API_KEY": "sk-test",
            }), patch.object(OpenAITextProvider, "propose", self._offline_propose):
                app = AppTest.from_file(str(APP), default_timeout=10).run()
                app.toggle(key="discuss_first").set_value(True).run()
                app.chat_input(key="new_task_prompt").set_value("设计一张读书会海报。").run()
                parent_id = app.session_state["selected_task_id"]
                self._wait_for_status(app, root, parent_id, "discussing")
                path = root / "natural-language" / parent_id / "conversation.json"
                app.text_area(key=f"requirements_{parent_id}_1").set_value("必须有一只猫。\n标题放在顶部。")
                app.button(key=f"confirm_requirements_{parent_id}").click().run()
                self._wait_for_status(app, root, parent_id, "discussing")
                saved = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(saved["user_requirements"], ["必须有一只猫。", "标题放在顶部。"])
                self.assertEqual(saved["design_brief"]["user_requirements"], saved["user_requirements"])
                app.button(key=f"prepare_round_{parent_id}").click().run()
                child_id = json.loads(path.read_text(encoding="utf-8"))["rounds"][-1]["run_id"]
                self._wait_for_status(app, root, child_id, "awaiting_approval")
                brief = json.loads((root / "natural-language" / child_id / "brief.json").read_text(encoding="utf-8"))
                self.assertEqual(brief["user_requirements"], saved["user_requirements"])
                self.assertFalse(app.button(key=f"approve_{child_id}").disabled)
                app.text_area(key=f"requirements_{parent_id}_{saved['revision']}").set_value("必须有一只狗。")
                app.button(key=f"confirm_requirements_{parent_id}").click().run()
                self._wait_for_status(app, root, parent_id, "discussing")
                revision = json.loads(path.read_text(encoding="utf-8"))["revision"]
                self.assertTrue(app.button(key=f"approve_{child_id}").disabled)
                self.assertFalse(app.button(key=f"prepare_round_{parent_id}").disabled)
                reopened = AppTest.from_file(str(APP), default_timeout=10).run()
                reopened.button(key=f"task_{parent_id}").click().run()
                self.assertEqual(reopened.text_area(key=f"requirements_{parent_id}_{revision}").value, "必须有一只狗。")
                reopened.text_area(key=f"requirements_{parent_id}_{revision}").set_value("")
                reopened.button(key=f"confirm_requirements_{parent_id}").click().run()
                self._wait_for_status(reopened, root, parent_id, "discussing")
                self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["user_requirements"], [])
                self.assertFalse(reopened.exception)

    def test_contract_suggestions_can_be_edited_confirmed_or_rejected_in_the_interface(self):
        suggestions = ["必须有一只猫。"]
        def propose(provider, prompt, *, schema_name, reference_paths=None):
            value, response = self._offline_propose(provider, prompt, schema_name=schema_name,
                                                    reference_paths=reference_paths)
            if (schema_name == "design-conversation.schema.json"
                    and json.loads(prompt[prompt.index('{"effective_request"'):])["pending_kind"] != "requirements_update"):
                value["suggested_user_requirements"] = list(suggestions)
            return value, response

        with TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, {
                "CORPUS_ATELIER_TASKS_ROOT": directory,
                "CORPUS_ATELIER_PREFERENCES_PATH": str(root / "settings.json"),
                "CORPUS_ATELIER_ENV_PATH": str(root / ".env"),
                "OPENAI_API_KEY": "sk-test",
            }), patch.object(OpenAITextProvider, "propose", propose):
                app = AppTest.from_file(str(APP), default_timeout=10).run()
                app.toggle(key="discuss_first").set_value(True).run()
                app.chat_input(key="new_task_prompt").set_value("海报必须有一只猫。").run()
                parent_id = app.session_state["selected_task_id"]
                self._wait_for_status(app, root, parent_id, "discussing")
                path = root / "natural-language" / parent_id / "conversation.json"
                self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["user_requirements"], [])
                self.assertTrue(app.button(key=f"prepare_round_{parent_id}").disabled)
                self.assertEqual(app.text_area(key=f"requirements_{parent_id}_1").value, suggestions[0])
                app.text_area(key=f"requirements_{parent_id}_1").set_value("必须有两只猫。")
                app.button(key=f"confirm_requirements_{parent_id}").click().run()
                self._wait_for_status(app, root, parent_id, "discussing")
                self.assertFalse(app.button(key=f"prepare_round_{parent_id}").disabled)
                suggestions[:] = ["必须有一只狗。"]
                app.chat_input(key=f"conversation_input_{parent_id}").set_value("考虑把猫换成狗。").run()
                self._wait_for_status(app, root, parent_id, "discussing")
                self.assertTrue(app.button(key=f"prepare_round_{parent_id}").disabled)
                app.button(key=f"keep_requirements_{parent_id}").click().run()
                self._wait_for_status(app, root, parent_id, "discussing")
                self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["user_requirements"], ["必须有两只猫。"])
                self.assertFalse(app.button(key=f"prepare_round_{parent_id}").disabled)
                self.assertFalse(app.exception)

    def test_legacy_conversation_can_build_a_visible_brief_before_preparing_a_design(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, {
                "CORPUS_ATELIER_TASKS_ROOT": directory,
                "CORPUS_ATELIER_PREFERENCES_PATH": str(root / "settings.json"),
                "CORPUS_ATELIER_ENV_PATH": str(root / ".env"),
                "OPENAI_API_KEY": "sk-test",
            }), patch.object(OpenAITextProvider, "propose", self._offline_propose):
                app = AppTest.from_file(str(APP), default_timeout=10).run()
                app.toggle(key="discuss_first").set_value(True).run()
                app.chat_input(key="new_task_prompt").set_value("设计一张读书会海报。").run()
                parent_id = app.session_state["selected_task_id"]
                self._wait_for_status(app, root, parent_id, "discussing")
                path = root / "natural-language" / parent_id / "conversation.json"
                legacy = json.loads(path.read_text(encoding="utf-8"))
                for key in ("design_brief", "brief_revision", "requirement_interpretations"):
                    del legacy[key]
                legacy["format_version"] = 2
                write_json(path, legacy)
                app.run()
                self.assertTrue(app.button(key=f"prepare_round_{parent_id}").disabled)
                self.assertFalse(app.button(key=f"refresh_brief_{parent_id}").disabled)
                app.button(key=f"refresh_brief_{parent_id}").click().run()
                self._wait_for_status(app, root, parent_id, "discussing")
                saved = json.loads(path.read_text(encoding="utf-8"))
                self.assertIsNotNone(saved["design_brief"])
                self.assertEqual(saved["rounds"], [])
                self.assertFalse(app.button(key=f"prepare_round_{parent_id}").disabled)
                self.assertFalse(app.exception)

    def test_content_language_refresh_is_independent_of_interface_language(self):
        from tests.test_language import LanguageTextProvider

        text = LanguageTextProvider()

        def propose(provider, prompt, *, schema_name, reference_paths=None):
            return text.propose(prompt, schema_name=schema_name, reference_paths=reference_paths)

        with TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, {
                "CORPUS_ATELIER_TASKS_ROOT": directory,
                "CORPUS_ATELIER_PREFERENCES_PATH": str(root / "settings.json"),
                "CORPUS_ATELIER_ENV_PATH": str(root / ".env"),
                "OPENAI_API_KEY": "sk-test",
            }), patch.object(OpenAITextProvider, "propose", propose):
                app = AppTest.from_file(str(APP), default_timeout=10).run()
                app.toggle(key="discuss_first").set_value(True).run()
                app.chat_input(key="new_task_prompt").set_value("设计一张国庆花篮海报。").run()
                parent_id = app.session_state["selected_task_id"]
                self._wait_for_status(app, root, parent_id, "discussing")
                path = root / "natural-language" / parent_id / "conversation.json"
                saved = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(saved["content_language"], "zh-CN")
                self.assertIn("**目的:** 以写实广式插花传递国庆祝福。", [item.value for item in app.markdown])
                app.session_state["ui_language"] = "en"
                app.run()
                self.assertIn("**Purpose:** 以写实广式插花传递国庆祝福。", [item.value for item in app.markdown])
                self.assertEqual(json.loads(path.read_text(encoding="utf-8")), saved)
                app.selectbox(key=f"brief_language_{parent_id}_{saved['revision']}").set_value("en").run()
                self.assertEqual(json.loads(path.read_text(encoding="utf-8")), saved)
                app.button(key=f"refresh_brief_{parent_id}").click().run()
                self._wait_for_status(app, root, parent_id, "discussing")
                refreshed = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(refreshed["content_language"], "en")
                self.assertEqual(refreshed["design_brief"]["exact_copy"], saved["design_brief"]["exact_copy"])
                self.assertIn("**Purpose:** Convey a National Day greeting through photorealistic Guang-style floral arranging.", [item.value for item in app.markdown])
                self.assertFalse(app.exception)

    @staticmethod
    def _completed_task(root: str) -> str:
        run_id = "20260926T150000Z_abcdef12"
        run_dir = Path(root) / "natural-language" / run_id
        title = "欲望与哲学治疗文章封面"
        candidates = []
        for number in (1, 2, 3):
            candidate_id = f"c{number:02d}"
            image_path = (
                run_dir / "candidates" / candidate_id
                / "generation" / "attempt_01" / "image.png"
            )
            image_path.parent.mkdir(parents=True, exist_ok=True)
            Image.new(
                "RGB", (120, 80), (30 * number, 40 * number, 50 * number)
            ).save(image_path, format="PNG")
            candidates.append({
                "candidate_id": candidate_id,
                "status": "generated",
                "direction_seed": {"label": f"设计方向 {number}"},
                "proposal": {
                    "chosen_direction": f"第 {number} 个完整设计方向。",
                    "design_description": f"第 {number} 个完整视觉描述。",
                    "design_rationale": f"第 {number} 个设计理由。",
                },
                "generation_prompt": f"Render candidate {candidate_id} exactly.",
                "generation_request": {
                    "model": "gpt-image-2",
                    "quality": "medium",
                    "size": "1536x1024",
                },
                "image_path": str(image_path.resolve()),
                "image_sha256": digest_file(image_path),
            })

        write_json(run_dir / "candidates" / "index.json", candidates)
        write_json(run_dir / "selection" / "decision.json", {
            "selected_candidate_id": "c02",
            "selected_image_sha256": candidates[1]["image_sha256"],
        })
        write_text(run_dir / "input" / "request.txt", "设计一张文章封面。")
        write_json(run_dir / "manifest.json", {
            "format_version": 2,
            "workflow_version": 18,
            "case_id": "natural-language",
            "run_id": run_id,
            "title": title,
            "created_at": "2026-09-26T15:00:00+00:00",
            "updated_at": "2026-09-26T15:05:00+00:00",
            "status": "completed",
            "models": {
                "text": {
                    "adapter": "test.TextProvider",
                    "model": "gpt-5.6-luna",
                    "reasoning_effort": "medium",
                },
                "image": {
                    "adapter": "test.ImageProvider",
                    "model": "gpt-image-2",
                    "quality": "medium",
                },
            },
            "artifacts": {
                "user_request": "input/request.txt",
                "candidate_index": "candidates/index.json",
                "selection": "selection/decision.json",
                "image": "candidates/c02/generation/attempt_01/image.png",
            },
            "latest_image": str(Path(candidates[1]["image_path"])),
        })
        return run_id

    def test_initial_workspace_uses_chat_input_and_openai_model_controls(self):
        with TemporaryDirectory() as directory:
            settings = Path(directory) / "settings.json"
            env_file = Path(directory) / ".env"
            with patch.dict(os.environ, {
                "CORPUS_ATELIER_TASKS_ROOT": directory,
                "CORPUS_ATELIER_PREFERENCES_PATH": str(settings),
                "CORPUS_ATELIER_ENV_PATH": str(env_file),
            }):
                app = AppTest.from_file(str(APP), default_timeout=10).run()

        self.assertFalse(app.exception)
        self.assertTrue(any(title.value == "语聊画廊" for title in app.title))
        self.assertEqual(
            app.selectbox(key="new_task_model").value,
            "gpt-5.6-luna",
        )
        self.assertEqual(
            app.selectbox(key="new_task_image_model").value,
            "gpt-image-2",
        )
        self.assertEqual(
            app.segmented_control(key="new_task_reasoning").value,
            "medium",
        )
        self.assertEqual(
            app.segmented_control(key="new_task_candidates").value,
            3,
        )
        self.assertEqual(
            app.chat_input(key="new_task_prompt").placeholder,
            "描述你的设计需求……",
        )
        self.assertFalse(app.get("pills"))
        captions = [caption.value for caption in app.caption]
        self.assertIn("描述你想完成的平面设计。", captions)
        self.assertNotIn("设计示例正在准备中。", captions)
        self.assertIn("v1.2.3", captions)
        self.assertEqual(len(app.get("image")), 4)
        subheaders = [subheader.value for subheader in app.subheader]
        self.assertIn("看看它能做什么", subheaders)
        self.assertIn("说说你想设计什么", subheaders)
        self.assertEqual(
            app.button(key="showcase_view_all").label,
            "查看全部设计",
        )
        self.assertTrue(all("OpenAI" not in caption for caption in captions))
        self.assertTrue(all("自动保存" not in caption for caption in captions))
        self.assertEqual(app.button(key="open_settings").label, "设置")
        self.assertTrue(app.button(key="new_task").disabled)

    def test_submission_selects_the_created_task_even_when_execution_fails(self):
        def fail_after_creation(application, run_id):
            run_dir = application.store.find_run(run_id)
            application.store.update(
                run_dir,
                "failed",
                error_type="RuntimeError",
                error="deliberate test failure",
            )
            raise RuntimeError("deliberate test failure")

        with TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch.dict(os.environ, {
                    "CORPUS_ATELIER_TASKS_ROOT": directory,
                    "CORPUS_ATELIER_PREFERENCES_PATH": str(
                        root / "settings.json"
                    ),
                    "CORPUS_ATELIER_ENV_PATH": str(root / ".env"),
                    "OPENAI_API_KEY": "sk-test",
                }),
                patch.object(
                    CorpusAtelierApplication,
                    "run_request",
                    fail_after_creation,
                ),
            ):
                app = AppTest.from_file(str(APP), default_timeout=10).run()
                app.chat_input(key="new_task_prompt").set_value(
                    "设计一张读书会公告。"
                ).run()
                run_id = app.session_state["selected_task_id"]
                self._wait_for_status(app, root, run_id, "failed")
                deadline = time.monotonic() + 5
                while f"followup_{run_id}" not in [item.key for item in app.chat_input]:
                    if time.monotonic() >= deadline:
                        self.fail("The failed task did not expose its follow-up input")
                    time.sleep(0.05)
                    app.run()

            self.assertFalse(app.exception)
            run_id = app.session_state["selected_task_id"]
            self.assertIsNotNone(run_id)
            self.assertIsNotNone(app.chat_input(key=f"followup_{run_id}"))
            self.assertFalse(app.button(key="new_task").disabled)
            self.assertIn(
                "任务执行失败，请查看任务记录。",
                [error.value for error in app.error],
            )
            manifest_path = next(root.glob("*/*/manifest.json"))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["run_id"], run_id)
            self.assertEqual(manifest["status"], "failed")

    def test_switching_tasks_does_not_interrupt_background_execution(self):
        started = Event()
        release = Event()

        def delayed_run(application, run_id):
            run_dir = application.store.find_run(run_id)
            application.store.update(run_dir, "interpreting_request")
            started.set()
            release.wait(timeout=5)
            application.store.update(run_dir, "awaiting_approval")
            return application.open_task(run_id)

        with TemporaryDirectory() as directory:
            root = Path(directory)
            completed_id = self._completed_task(directory)
            try:
                with (
                    patch.dict(os.environ, {
                        "CORPUS_ATELIER_TASKS_ROOT": directory,
                        "CORPUS_ATELIER_PREFERENCES_PATH": str(
                            root / "settings.json"
                        ),
                        "CORPUS_ATELIER_ENV_PATH": str(root / ".env"),
                        "OPENAI_API_KEY": "sk-test",
                    }),
                    patch.object(
                        CorpusAtelierApplication,
                        "run_request",
                        delayed_run,
                    ),
                ):
                    app = AppTest.from_file(
                        str(APP), default_timeout=10
                    ).run()
                    app.chat_input(key="new_task_prompt").set_value(
                        "设计一张读书会公告。"
                    ).run()
                    self.assertTrue(started.wait(timeout=2))
                    app.run()

                    running_id = app.session_state["selected_task_id"]
                    self.assertNotEqual(running_id, completed_id)
                    running_button = app.button(key=f"task_{running_id}")
                    self.assertEqual(
                        running_button.proto.icon,
                        ":material/progress_activity:",
                    )
                    self.assertFalse(app.get("progress"))
                    self.assertIn(
                        "running",
                        [status.state for status in app.get("status")],
                    )

                    app.button(
                        key=f"task_{completed_id}"
                    ).click().run()
                    self.assertEqual(
                        app.session_state["selected_task_id"],
                        completed_id,
                    )
                    self.assertTrue(
                        app.button(key=f"task_{running_id}").proto.icon
                        == ":material/progress_activity:"
                    )

                    release.set()
                    manifest_path = (
                        root / "natural-language" / running_id
                        / "manifest.json"
                    )
                    deadline = time.monotonic() + 2
                    status = None
                    while time.monotonic() < deadline:
                        status = json.loads(
                            manifest_path.read_text(encoding="utf-8")
                        )["status"]
                        if status == "awaiting_approval":
                            break
                        time.sleep(0.01)
                    self.assertEqual(status, "awaiting_approval")
                    self.assertEqual(
                        app.session_state["selected_task_id"],
                        completed_id,
                    )
            finally:
                release.set()
                st.cache_resource.clear()
                gc.collect()

    def test_settings_switches_language_and_persists_the_preference(self):
        with TemporaryDirectory() as directory:
            settings = Path(directory) / "settings.json"
            env_file = Path(directory) / ".env"
            with patch.dict(os.environ, {
                "CORPUS_ATELIER_TASKS_ROOT": directory,
                "CORPUS_ATELIER_PREFERENCES_PATH": str(settings),
                "CORPUS_ATELIER_ENV_PATH": str(env_file),
            }):
                app = AppTest.from_file(str(APP), default_timeout=10).run()
                app.button(key="open_settings").click().run()
                app.selectbox(key="settings_language").select("en").run()

            self.assertFalse(app.exception)
            self.assertTrue(any(
                title.value == "Corpus Atelier" for title in app.title
            ))
            self.assertFalse(any(
                title.value == "语聊画廊" for title in app.title
            ))
            self.assertEqual(app.button(key="new_task").label, "New task")
            self.assertEqual(app.button(key="open_settings").label, "Settings")
            self.assertEqual(
                app.chat_input(key="new_task_prompt").placeholder,
                "Describe your design request…",
            )
            subheaders = [subheader.value for subheader in app.subheader]
            self.assertIn("See what it can create", subheaders)
            self.assertIn("What would you like to design?", subheaders)
            self.assertEqual(
                json.loads(settings.read_text(encoding="utf-8")),
                {"language": "en"},
            )

    def test_showcase_renders_packaged_manifest_images(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            showcase = root / "showcase"
            showcase.mkdir()
            image_path = showcase / "poster.png"
            Image.new("RGB", (120, 180), (22, 44, 66)).save(
                image_path,
                format="PNG",
            )
            write_json(showcase / "manifest.json", {
                "format_version": 1,
                "items": [{
                    "image": "poster.png",
                    "title": {
                        "zh-CN": "实验海报",
                        "en": "Experiment poster",
                    },
                }],
            })
            with patch.dict(os.environ, {
                "CORPUS_ATELIER_TASKS_ROOT": str(root / "tasks"),
                "CORPUS_ATELIER_PREFERENCES_PATH": str(
                    root / "settings.json"
                ),
                "CORPUS_ATELIER_ENV_PATH": str(root / ".env"),
                "CORPUS_ATELIER_SHOWCASE_ROOT": str(showcase),
            }):
                app = AppTest.from_file(str(APP), default_timeout=10).run()

        self.assertFalse(app.exception)
        self.assertEqual(len(app.get("image")), 1)
        captions = [caption.value for caption in app.caption]
        self.assertNotIn("设计示例正在准备中。", captions)

    def test_showcase_opens_paginated_gallery_and_returns(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            showcase = root / "showcase"
            showcase.mkdir()
            items = []
            for number in range(6):
                image_name = f"design-{number + 1}.png"
                Image.new(
                    "RGB",
                    (120, 80),
                    (20 * number, 30 * number, 40 * number),
                ).save(showcase / image_name, format="PNG")
                items.append({
                    "image": image_name,
                    "featured": number < 4,
                    "featured_order": 4 - number if number < 4 else None,
                    "title": {
                        "zh-CN": f"设计 {number + 1}",
                        "en": f"Design {number + 1}",
                    },
                })
            write_json(showcase / "manifest.json", {
                "format_version": 1,
                "items": items,
            })
            with patch.dict(os.environ, {
                "CORPUS_ATELIER_TASKS_ROOT": str(root / "tasks"),
                "CORPUS_ATELIER_PREFERENCES_PATH": str(
                    root / "settings.json"
                ),
                "CORPUS_ATELIER_ENV_PATH": str(root / ".env"),
                "CORPUS_ATELIER_SHOWCASE_ROOT": str(showcase),
            }):
                app = AppTest.from_file(str(APP), default_timeout=10).run()
                self.assertEqual(len(app.get("image")), 4)
                self.assertEqual(
                    [image.proto.imgs[0].caption for image in app.get("image")],
                    ["设计 4", "设计 3", "设计 2", "设计 1"],
                )
                app.button(key="showcase_view_all").click().run()

                self.assertFalse(app.exception)
                self.assertEqual(app.session_state["product_view"], "gallery")
                self.assertTrue(any(
                    title.value == "设计画廊" for title in app.title
                ))
                self.assertEqual(len(app.get("image")), 4)
                self.assertEqual(app.get("pagination")[0].value, 1)
                self.assertEqual(
                    app.button(key="showcase_back").label,
                    "返回创作",
                )
                self.assertFalse(app.button(key="new_task").disabled)

                app.session_state["showcase_page"] = 2
                app.run()
                self.assertFalse(app.exception)
                self.assertEqual(len(app.get("image")), 2)

                app.button(key="showcase_back").click().run()
                self.assertFalse(app.exception)
                self.assertEqual(app.session_state["product_view"], "home")
                self.assertEqual(len(app.get("image")), 4)
                self.assertEqual(
                    app.chat_input(key="new_task_prompt").placeholder,
                    "描述你的设计需求……",
                )

    def test_settings_saves_masked_api_key_without_frontend_echo(self):
        with TemporaryDirectory() as directory:
            settings = Path(directory) / "settings.json"
            env_file = Path(directory) / ".env"
            secret = "sk-test-secret-9876"
            with patch.dict(os.environ, {
                "CORPUS_ATELIER_TASKS_ROOT": directory,
                "CORPUS_ATELIER_PREFERENCES_PATH": str(settings),
                "CORPUS_ATELIER_ENV_PATH": str(env_file),
            }):
                app = AppTest.from_file(str(APP), default_timeout=10).run()
                app.button(key="open_settings").click().run()
                app.text_input(key="settings_openai_api_key").input(secret)
                app.toggle(key="settings_remember_api_key").set_value(True)
                next(
                    button for button in app.button if button.label == "保存"
                ).click().run()
                app.button(key="open_settings").click().run()

            self.assertFalse(app.exception)
            self.assertIn(
                'OPENAI_API_KEY="sk-test-secret-9876"',
                env_file.read_text(encoding="utf-8"),
            )
            captions = [caption.value for caption in app.caption]
            self.assertTrue(any("••••9876" in caption for caption in captions))
            self.assertTrue(all(".env" not in caption for caption in captions))
            self.assertTrue(all("Git" not in caption for caption in captions))
            self.assertTrue(all("来源" not in caption for caption in captions))
            remember = app.toggle(key="settings_remember_api_key")
            self.assertEqual(remember.label, "记住 API Key")
            self.assertNotIn(".env", remember.help)
            self.assertNotIn("Git", remember.help)
            self.assertEqual(
                app.button(key="clear_openai_api_key").label,
                "移除已保存的 API Key",
            )
            self.assertEqual(
                app.text_input(key="settings_openai_api_key").value,
                "",
            )
            self.assertTrue(all(secret not in caption for caption in captions))

    def test_product_source_is_detached_from_experiments(self):
        source = APP.read_text(encoding="utf-8")
        for term in (
            "experiments/",
            "CorpusExperimentJob",
            "CorpusComparisonJob",
            "render_experiment_page",
            "语料对比实验",
        ):
            self.assertNotIn(term, source)
        self.assertIn('st.chat_message("user")', source)
        self.assertIn('st.chat_message("assistant")', source)
        self.assertIn('ROOT / ".atelier" / "tasks"', source)

    def test_model_selector_is_allow_listed(self):
        with TemporaryDirectory() as directory, patch.dict(os.environ, {
            "CORPUS_ATELIER_TASKS_ROOT": directory,
            "CORPUS_ATELIER_PREFERENCES_PATH": str(
                Path(directory) / "settings.json"
            ),
            "CORPUS_ATELIER_ENV_PATH": str(Path(directory) / ".env"),
        }):
            app = AppTest.from_file(str(APP), default_timeout=10).run()
            selector = app.selectbox(key="new_task_model")
            self.assertEqual(
                selector.options,
                ["GPT-5.6 Luna", "GPT-6 Sol", "GPT-6 Astra"],
            )
            selector.select("gpt-6-sol").run()
            self.assertFalse(app.exception)
            self.assertEqual(
                app.selectbox(key="new_task_model").value,
                "gpt-6-sol",
            )
            image_selector = app.selectbox(key="new_task_image_model")
            self.assertEqual(
                image_selector.options,
                [
                    "GPT Image 2",
                    "GPT Image 2.5 Sunburst",
                    "GPT Image 2.5 Flare",
                ],
            )
            image_selector.select("gpt-image-2.5-flare").run()
            self.assertFalse(app.exception)
            self.assertEqual(
                app.selectbox(key="new_task_image_model").value,
                "gpt-image-2.5-flare",
            )

    def test_completed_task_shows_all_images_downloads_and_design_details(self):
        with TemporaryDirectory() as directory:
            run_id = self._completed_task(directory)
            try:
                with patch.dict(
                    os.environ,
                    {
                        "CORPUS_ATELIER_TASKS_ROOT": directory,
                        "CORPUS_ATELIER_PREFERENCES_PATH": str(
                            Path(directory) / "settings.json"
                        ),
                        "CORPUS_ATELIER_ENV_PATH": str(
                            Path(directory) / ".env"
                        ),
                    },
                ):
                    app = AppTest.from_file(str(APP), default_timeout=10)
                    app.session_state["selected_task_id"] = run_id
                    app.run()

                self.assertFalse(app.exception)
                self.assertFalse(app.button(key="new_task").disabled)
                self.assertEqual(len(app.get("image")), 3)
                self.assertTrue(any(
                    subheader.value == "本次生成结果" for subheader in app.subheader
                ))
                self.assertIn(
                    "设计方案与提示词",
                    [status.label for status in app.get("status")],
                )
                self.assertIn("最终选择", app.get("tab")[0].label)
                self.assertEqual(len(app.code), 3)
                self.assertTrue(all(
                    "Render candidate" in code.value for code in app.code
                ))
                self.assertNotIn(
                    "任务 artifacts",
                    [status.label for status in app.get("status")],
                )
                self.assertNotIn(str(Path(directory).resolve()), str(app))

                downloads = app.get("download_button")
                self.assertEqual(len(downloads), 4)
                self.assertEqual(
                    [download.label for download in downloads].count("下载 PNG"),
                    3,
                )
                self.assertTrue(downloads[0].key.endswith("_c02"))
                self.assertTrue(all(
                    download.proto.url.endswith(".png")
                    and download.proto.ignore_rerun
                    for download in downloads[:3]
                ))
                self.assertIn(
                    "下载全部图片",
                    [download.label for download in downloads],
                )
                self.assertTrue(downloads[-1].proto.url.endswith(".zip"))
                self.assertTrue(downloads[-1].proto.ignore_rerun)
            finally:
                st.cache_resource.clear()
                gc.collect()


if __name__ == "__main__":
    unittest.main()
