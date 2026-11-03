import gc
from io import BytesIO
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

from corpus_atelier import __version__
from corpus_atelier.app.service import CorpusAtelierApplication
from corpus_atelier.app.state import NaturalLanguageDesignJob
from corpus_atelier.artifacts.hashing import digest_file
from corpus_atelier.artifacts.records import write_json, write_text
from corpus_atelier.providers import OpenAIImageProvider, OpenAITextProvider
from tests.fakes import FakeImageProvider, FakeTextProvider


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "src/corpus_atelier/ui/studio.py"


class StreamlitAppTests(unittest.TestCase):
    @staticmethod
    def _offline_propose(provider, prompt, *, schema_name, reference_paths=None):
        return FakeTextProvider().propose(
            prompt, schema_name=schema_name, reference_paths=reference_paths,
        )

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

    def _create_extracting_session(self, directory):
        """A prompt session whose entry extraction has not run yet."""
        buffer = BytesIO()
        Image.new("RGB", (64, 48), (12, 34, 56)).save(buffer, format="PNG")
        with CorpusAtelierApplication(
            runs_root=directory,
            text_provider=OpenAITextProvider(),
            image_provider=OpenAIImageProvider(),
        ) as application:
            result = application.start_from_image(
                ("source.png", buffer.getvalue()), case_id="natural-language",
                settings={"image_quality": "medium", "aspect_ratio": [1, 1]},
            )
        return result.run_id

    @staticmethod
    def _open_task(app, run_id):
        app.session_state["selected_task_id"] = run_id
        return app.run()

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
            "workflow_version": 19,
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
        # The studio no longer asks for a design method, a proposal count, or a route;
        # the one general profile and the brief decide both.
        control_keys = {
            widget.key for kind in ("segmented_control", "toggle")
            for widget in app.get(kind) if getattr(widget, "key", None)
        }
        self.assertNotIn("new_task_method", control_keys)
        self.assertNotIn("new_task_candidates", control_keys)
        self.assertNotIn("new_task_mode", control_keys)
        self.assertNotIn("new_task_fast_path", control_keys)
        self.assertEqual(
            app.text_area(key="new_session_prompt").placeholder,
            "描述你想要的画面。这段文字会原样发送给图像模型。",
        )
        self.assertEqual(app.selectbox(key="new_task_ratio").value, (16, 9))
        self.assertEqual(app.segmented_control(key="prompt_start_mode").value, "prompt")
        self.assertEqual(app.button(key="start_prompt_action").label, "生成图像")
        self.assertEqual(app.button(key="start_prompt_only").label, "只保存提示词，暂不生成")
        self.assertFalse(app.get("pills"))
        captions = [caption.value for caption in app.caption]
        self.assertIn("描述你想完成的平面设计。", captions)
        self.assertIn(f"v{__version__}", captions)
        self.assertEqual(len(app.get("image")), 0)
        subheaders = [subheader.value for subheader in app.subheader]
        self.assertIn("说说你想设计什么", subheaders)
        self.assertTrue(all("OpenAI" not in caption for caption in captions))
        self.assertTrue(all("自动保存" not in caption for caption in captions))
        self.assertEqual(app.button(key="open_settings").label, "设置")
        self.assertTrue(app.button(key="new_task").disabled)

    def test_switching_tasks_does_not_interrupt_background_execution(self):
        started = Event()
        release = Event()

        def delayed_run(application, run_id):
            run_dir = application.store.find_run(run_id)
            application.store.update(run_dir, "extracting")
            started.set()
            release.wait(timeout=5)
            application.store.update(run_dir, "prompt_ready")
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
                        "run_prompt_extraction",
                        delayed_run,
                    ),
                ):
                    running_id = self._create_extracting_session(root)
                    app = AppTest.from_file(str(APP), default_timeout=10)
                    self._open_task(app, running_id)
                    self.assertTrue(started.wait(timeout=2))
                    app.run()
                    self.assertNotEqual(running_id, completed_id)
                    running_button = app.button(key=f"task_{running_id}")
                    self.assertEqual(
                        running_button.proto.icon,
                        ":material/progress_activity:",
                    )
                    self.assertFalse(app.get("progress"))

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
                    self.assertEqual(status, "prompt_ready")
                    self.assertEqual(
                        app.session_state["selected_task_id"],
                        completed_id,
                    )
            finally:
                release.set()
                time.sleep(0.5)
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
                app.text_area(key="new_session_prompt").placeholder,
                "Describe the image you want. This text is sent to the image model exactly as written.",
            )
            subheaders = [subheader.value for subheader in app.subheader]
            self.assertIn("What would you like to design?", subheaders)
            self.assertEqual(
                json.loads(settings.read_text(encoding="utf-8")),
                {"language": "en"},
            )

    def test_gallery_browses_the_archived_corpus(self):
        from corpus_atelier.corpus.gallery import (
            import_seed, load_seed, packaged_seed_path,
        )
        from corpus_atelier.corpus.index import CorpusStore

        with TemporaryDirectory() as directory:
            root = Path(directory)
            upstream = root / "upstream"
            media = root / "media"
            seed = load_seed(packaged_seed_path())
            first = seed["records"][0]
            image_path = upstream / first["image_source"]
            image_path.parent.mkdir(parents=True)
            Image.new("RGB", (120, 180), (22, 44, 66)).save(
                image_path,
                format="PNG",
            )
            store = CorpusStore(root / "corpus.sqlite3")
            try:
                import_seed(
                    store,
                    {"format_version": 1, "records": [first]},
                    media_root=media,
                    source_root=upstream,
                )
            finally:
                store.close()
            with patch.dict(os.environ, {
                "CORPUS_ATELIER_TASKS_ROOT": str(root / "tasks"),
                "CORPUS_ATELIER_PREFERENCES_PATH": str(
                    root / "settings.json"
                ),
                "CORPUS_ATELIER_ENV_PATH": str(root / ".env"),
                "CORPUS_ATELIER_CORPUS_DB": str(root / "corpus.sqlite3"),
                "CORPUS_ATELIER_CORPUS_MEDIA": str(media),
            }):
                app = AppTest.from_file(str(APP), default_timeout=10).run()
                app.session_state["product_view_tabs"] = "gallery"
                app.run()

        self.assertFalse(app.exception)
        self.assertIn("gallery_collection", [box.key for box in app.selectbox])
        self.assertGreaterEqual(len(app.get("image")), 1)

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
        sources = {
            path.name: path.read_text(encoding="utf-8")
            for path in sorted(APP.parent.glob("*.py"))
        }
        for name, source in sources.items():
            for term in (
                "experiments/",
                "CorpusExperimentJob",
                "CorpusComparisonJob",
                "render_experiment_page",
                "语料对比实验",
            ):
                self.assertNotIn(term, source, f"{name} still references {term!r}")
        self.assertIn('st.chat_message("user")', sources["task_view.py"])
        self.assertIn('st.chat_message("assistant")', sources["task_view.py"])
        self.assertNotIn(".atelier", sources["studio.py"])
        self.assertIn(
            '".atelier" / "tasks"',
            (ROOT / "src/corpus_atelier/config/paths.py").read_text(encoding="utf-8"),
        )

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
                render_prompts = [
                    code.value for code in app.code
                    if "Render candidate" in code.value
                ]
                self.assertEqual(len(render_prompts), 3)
                self.assertTrue(any(
                    "generation/prompt.md" in code.value for code in app.code
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

    def test_corpus_view_renders_without_error(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(
                os.environ,
                {
                    "CORPUS_ATELIER_TASKS_ROOT": str(root / "tasks"),
                    "CORPUS_ATELIER_PREFERENCES_PATH": str(root / "settings.json"),
                    "CORPUS_ATELIER_ENV_PATH": str(root / ".env"),
                    "CORPUS_ATELIER_CORPUS_DB": str(root / "corpus.sqlite3"),
                    "CORPUS_ATELIER_CORPUS_MEDIA": str(root / "media"),
                    "OPENAI_API_KEY": "sk-test",
                },
            ):
                app = AppTest.from_file(str(APP), default_timeout=10)
                app.session_state["product_view_tabs"] = "corpus"
                app.run()
            self.assertFalse(app.exception)

    def test_archive_control_renders_on_completed_task(self):
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
                        "CORPUS_ATELIER_CORPUS_DB": str(
                            Path(directory) / "corpus.sqlite3"
                        ),
                        "CORPUS_ATELIER_CORPUS_MEDIA": str(
                            Path(directory) / "media"
                        ),
                    },
                ):
                    app = AppTest.from_file(str(APP), default_timeout=10)
                    app.session_state["selected_task_id"] = run_id
                    app.run()

                self.assertFalse(app.exception)
                archive_button = app.button(
                    key=f"archive_confirm_{run_id}"
                )
                self.assertTrue(archive_button.disabled)
            finally:
                st.cache_resource.clear()
                gc.collect()

    def test_sidebar_delete_removes_task(self):
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
                    app = AppTest.from_file(str(APP), default_timeout=10).run()
                    self.assertFalse(app.exception)
                    delete_button = app.button(key=f"delete_{run_id}")
                    self.assertIsNotNone(delete_button)
                    delete_button.click().run()
                    self.assertFalse(app.exception)
                self.assertFalse(
                    (Path(directory) / "natural-language" / run_id).exists()
                )
            finally:
                st.cache_resource.clear()
                gc.collect()


if __name__ == "__main__":
    unittest.main()
