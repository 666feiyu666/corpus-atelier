import gc
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PIL import Image
import streamlit as st
from streamlit.testing.v1 import AppTest

from corpus_atelier.artifacts.hashing import digest_file
from corpus_atelier.artifacts.records import write_json, write_text


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "src/corpus_atelier/streamlit_app.py"


class StreamlitAppTests(unittest.TestCase):
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
            "描述你的设计需求",
        )
        self.assertFalse(app.get("pills"))
        captions = [caption.value for caption in app.caption]
        self.assertIn("描述你想完成的平面设计。", captions)
        self.assertIn("v1.0.0", captions)
        self.assertTrue(all("OpenAI" not in caption for caption in captions))
        self.assertTrue(all("自动保存" not in caption for caption in captions))
        self.assertEqual(app.button(key="open_settings").label, "设置")

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
                "Describe your design request",
            )
            self.assertEqual(
                json.loads(settings.read_text(encoding="utf-8")),
                {"language": "en"},
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
