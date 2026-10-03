"""Native brief editing retains drafts and renders revisions beside the dialogue."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from corpus_atelier.providers import OpenAITextProvider
from tests import test_streamlit_app as fixtures


class BriefEditorUITests(unittest.TestCase):
    def test_saved_reply_with_failed_status_has_a_working_retry_control(self):
        with self.workspace(seed=False) as (root, app, run_id, path):
            messages = json.loads(path.read_text(encoding="utf-8"))["messages"]
            manifest_path = path.parent / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest.update(status="failed", error="Reply saved before status update failed")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            app.run()
            app.button(key=f"retry_chat_{run_id}").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(json.loads(manifest_path.read_text(encoding="utf-8"))["status"], "discussing")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["messages"], messages)

    @contextmanager
    def workspace(self, *, seed=True):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, {
                "CORPUS_ATELIER_TASKS_ROOT": directory,
                "CORPUS_ATELIER_PREFERENCES_PATH": str(root / "settings.json"),
                "CORPUS_ATELIER_ENV_PATH": str(root / ".env"), "OPENAI_API_KEY": "sk-test",
            }), patch.object(OpenAITextProvider, "propose", fixtures.StreamlitAppTests._offline_propose):
                app = AppTest.from_file(str(fixtures.APP), default_timeout=10).run()
                app.toggle(key="discuss_first").set_value(True).run()
                app.chat_input(key="new_task_prompt").set_value("设计一张国庆花篮海报。").run()
                run_id = app.session_state["selected_task_id"]
                fixtures.StreamlitAppTests._wait_for_status(app, root, run_id, "discussing")
                path = root / "natural-language" / run_id / "conversation.json"
                if seed:
                    fixtures.StreamlitAppTests._save_initial_brief(app, run_id)
                yield root, app, run_id, path

    def test_save_all_brief_fields_and_use_saved_values_for_next_design(self):
        with self.workspace() as (root, app, run_id, path):
            app.text_area(key=f"brief_edit_{run_id}_purpose").set_value("手动编辑的节庆设计目的。")
            # Simulate an edit and a prepare click arriving in the same rerun.
            app.button(key=f"prepare_round_{run_id}").click().run()
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["rounds"], [])
            app.text_area(key=f"brief_edit_{run_id}_exact_copy").set_value(" 欢度国庆 \n1949-2026").run()
            app.text_area(key=f"brief_edit_{run_id}_constraints").set_value("").run()
            app.text_area(key=f"brief_edit_{run_id}_user_requirements").set_value("花篮必须有提手。").run()
            app.number_input(key=f"brief_edit_{run_id}_width").set_value(2).run()
            app.number_input(key=f"brief_edit_{run_id}_height").set_value(3).run()
            self.assertTrue(app.button(key=f"prepare_round_{run_id}").disabled)
            app.button(key=f"save_brief_{run_id}").click().run()
            self.assertFalse(app.exception)
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["design_brief"]["purpose"], "手动编辑的节庆设计目的。")
            self.assertEqual(saved["design_brief"]["exact_copy"], [" 欢度国庆 ", "1949-2026"])
            self.assertEqual(saved["design_brief"]["constraints"], [])
            self.assertEqual(saved["design_brief"]["canvas"]["aspect_ratio"], {"width": 2, "height": 3})
            self.assertFalse(app.button(key=f"prepare_round_{run_id}").disabled)
            app.button(key=f"prepare_round_{run_id}").click().run()
            child_id = json.loads(path.read_text(encoding="utf-8"))["rounds"][-1]["run_id"]
            fixtures.StreamlitAppTests._wait_for_status(app, root, child_id, "awaiting_approval")
            self.assertEqual(json.loads((root / "natural-language" / child_id / "brief.json").read_text(encoding="utf-8")), saved["design_brief"])

    def test_dirty_draft_survives_followup_without_becoming_stale(self):
        with self.workspace() as (root, app, run_id, path):
            app.text_area(key=f"brief_edit_{run_id}_purpose").set_value("保留这个未保存草稿。").run()
            app.chat_input(key=f"conversation_input_{run_id}").set_value("背景使用暖色。").run()
            fixtures.StreamlitAppTests._wait_for_status(app, root, run_id, "discussing")
            self.assertEqual(app.text_area(key=f"brief_edit_{run_id}_purpose").value, "保留这个未保存草稿。")
            self.assertFalse(app.button(key=f"save_brief_{run_id}").disabled)
            self.assertTrue(app.button(key=f"prepare_round_{run_id}").disabled)
            app.button(key=f"save_brief_{run_id}").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["design_brief"]["purpose"], "保留这个未保存草稿。")

    def test_historical_editor_creates_new_revision_and_keeps_original_snapshot(self):
        with self.workspace() as (_, app, run_id, path):
            original = json.loads(path.read_text(encoding="utf-8"))["design_brief"]
            app.text_area(key=f"brief_edit_{run_id}_purpose").set_value("第二版的目的。").run()
            app.button(key=f"save_brief_{run_id}").click().run()
            app.button(key=f"edit_brief_{run_id}_1").click().run()
            self.assertEqual(app.text_area(key=f"brief_edit_{run_id}_purpose").value, original["purpose"])
            self.assertTrue(app.button(key=f"prepare_round_{run_id}").disabled)
            app.text_area(key=f"brief_edit_{run_id}_purpose").set_value("从第一版继续修改。").run()
            app.button(key=f"save_brief_{run_id}").click().run()
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["revision"], 3)
            self.assertEqual(saved["brief_history"][0]["brief"], original)
            self.assertEqual(saved["brief_history"][-1]["based_on"], 1)

    def test_clean_followup_loads_new_brief_without_stale_editor(self):
        with self.workspace() as (root, app, run_id, _):
            app.chat_input(key=f"conversation_input_{run_id}").set_value("再加一些暖色。").run()
            fixtures.StreamlitAppTests._wait_for_status(app, root, run_id, "discussing")
            self.assertFalse(app.exception)
            self.assertFalse(app.button(key=f"save_brief_{run_id}").disabled)
            self.assertFalse(app.button(key=f"prepare_round_{run_id}").disabled)

    def test_unsaved_draft_survives_switching_away_from_the_conversation(self):
        with self.workspace() as (_, app, run_id, _):
            app.text_area(key=f"brief_edit_{run_id}_purpose").set_value("切换任务后仍保留草稿。").run()
            app.button(key="new_task").click().run()
            app.button(key=f"task_{run_id}").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.text_area(key=f"brief_edit_{run_id}_purpose").value, "切换任务后仍保留草稿。")
            self.assertTrue(app.button(key=f"prepare_round_{run_id}").disabled)

    def test_workspace_views_keep_unsaved_drafts_and_saved_requirements_separate(self):
        with self.workspace() as (root, app, run_id, path):
            original = json.loads(path.read_text(encoding="utf-8"))
            app.text_area(key=f"brief_edit_{run_id}_purpose").set_value("切换对话时保留这份草稿。").run()
            app.segmented_control(key=f"workspace_view_{run_id}").set_value("assistant").run()
            self.assertFalse(app.exception)
            self.assertNotIn(f"save_brief_{run_id}", [button.key for button in app.button])
            app.chat_input(key=f"conversation_input_{run_id}").set_value("描述花篮样式。").run()
            fixtures.StreamlitAppTests._wait_for_status(app, root, run_id, "discussing")
            app.segmented_control(key=f"workspace_view_{run_id}").set_value("design").run()
            self.assertFalse(app.exception)
            self.assertEqual(app.text_area(key=f"brief_edit_{run_id}_purpose").value, "切换对话时保留这份草稿。")
            self.assertEqual(app.text_area(key=f"brief_edit_{run_id}_constraints").value, "")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["design_brief"], original["design_brief"])

    def test_prompt_chat_is_a_continuing_dialogue_without_brief_controls(self):
        with self.workspace(seed=False) as (root, app, run_id, path):
            self.assertEqual(app.text_area(key=f"brief_edit_{run_id}_purpose").value, "")
            self.assertTrue(app.button(key=f"prepare_round_{run_id}").disabled)
            for message in ("只描述花篮，不需要描述花。", "两侧提手竖直，连接的弧度很低。"):
                app.chat_input(key=f"conversation_input_{run_id}").set_value(message).run()
                fixtures.StreamlitAppTests._wait_for_status(app, root, run_id, "discussing")
            self.assertFalse(app.exception)
            self.assertEqual(len(json.loads(path.read_text(encoding="utf-8"))["messages"]), 6)
            self.assertIn("深色藤编花篮，篮身圆鼓，口沿外扩，两侧竖直提把以低弧度横向连接。", [m.value for m in app.markdown])
            controls = [b.key or "" for b in app.button]
            self.assertFalse(any(k.startswith(("add_suggestion_", "dismiss_suggestion_", "refresh_brief_", "load_proposal_")) for k in controls))
