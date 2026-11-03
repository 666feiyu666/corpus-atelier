"""Streamlit checks for the studio shell, settings, and saved-task list."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from streamlit.testing.v1 import AppTest

from corpus_atelier import __version__
from corpus_atelier.app.service import CorpusAtelierApplication
from tests.fakes import FakeImageProvider, FakeTextProvider


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "src/corpus_atelier/ui/studio.py"


def _environment(directory: str) -> dict[str, str]:
    root = Path(directory)
    return {
        "CORPUS_ATELIER_TASKS_ROOT": directory,
        "CORPUS_ATELIER_PREFERENCES_PATH": str(root / "settings.json"),
        "CORPUS_ATELIER_ENV_PATH": str(root / ".env"),
        "CORPUS_ATELIER_CORPUS_DB": str(root / "corpus.sqlite3"),
        "CORPUS_ATELIER_CORPUS_MEDIA": str(root / "media"),
    }


class StreamlitAppTests(unittest.TestCase):
    def test_initial_workspace_uses_the_prompt_entry_and_openai_controls(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, _environment(directory)):
                app = AppTest.from_file(str(APP), default_timeout=10).run()

        self.assertFalse(app.exception)
        # The wordmark lives in the nav bar; the page itself carries the view title.
        self.assertTrue(any("atelier-wordmark" in item.value for item in app.markdown))
        self.assertTrue(any("语聊画廊" in item.value for item in app.markdown))
        self.assertTrue(any(title.value == "设计一版" for title in app.title))
        self.assertEqual(app.selectbox(key="new_task_model").value, "gpt-5.6-luna")
        self.assertEqual(app.selectbox(key="new_task_image_model").value, "gpt-image-2")
        self.assertEqual(app.segmented_control(key="new_task_reasoning").value, "medium")
        self.assertEqual(
            app.text_area(key="new_session_prompt").placeholder,
            "描述你想要的画面。这段文字会原样发送给图像模型。",
        )
        self.assertEqual(app.selectbox(key="new_task_ratio").value, (16, 9))
        self.assertEqual(app.segmented_control(key="prompt_start_mode").value, "prompt")
        self.assertEqual(app.button(key="start_prompt_action").label, "生成图像")
        self.assertEqual(app.button(key="start_prompt_only").label, "只保存提示词，暂不生成")
        captions = [caption.value for caption in app.caption]
        self.assertIn(f"v{__version__}", captions)
        self.assertIn("描述你想完成的平面设计。", captions)
        self.assertEqual(len(app.get("image")), 0)
        self.assertEqual(app.button(key="open_settings").label, "设置")
        self.assertTrue(app.button(key="new_task").disabled)

    def test_settings_switches_language_and_persists_the_preference(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Path(directory) / "settings.json"
            with patch.dict(os.environ, _environment(directory)):
                app = AppTest.from_file(str(APP), default_timeout=10).run()
                app.button(key="open_settings").click().run()
                app.selectbox(key="settings_language").select("en").run()

            self.assertFalse(app.exception)
            self.assertTrue(any("Corpus Atelier" in item.value for item in app.markdown))
            self.assertFalse(any("语聊画廊" in item.value for item in app.markdown))
            self.assertTrue(any(title.value == "New design" for title in app.title))
            self.assertEqual(app.button(key="new_task").label, "New task")
            self.assertEqual(app.button(key="open_settings").label, "Settings")
            self.assertEqual(
                settings.read_text(encoding="utf-8").strip(),
                '{\n  "language": "en"\n}',
            )

    def test_settings_saves_masked_api_key_without_frontend_echo(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            secret = "sk-test-secret-9876"
            with patch.dict(os.environ, _environment(directory)):
                app = AppTest.from_file(str(APP), default_timeout=10).run()
                app.button(key="open_settings").click().run()
                app.text_input(key="settings_openai_api_key").input(secret)
                app.toggle(key="settings_remember_api_key").set_value(True)
                next(button for button in app.button if button.label == "保存").click().run()
                app.button(key="open_settings").click().run()

            self.assertFalse(app.exception)
            self.assertIn('OPENAI_API_KEY="sk-test-secret-9876"',
                          env_file.read_text(encoding="utf-8"))
            captions = [caption.value for caption in app.caption]
            self.assertTrue(any("••••9876" in caption for caption in captions))
            self.assertTrue(all(secret not in caption for caption in captions))

    def test_model_selector_is_allow_listed(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, _environment(directory)):
                app = AppTest.from_file(str(APP), default_timeout=10).run()
                selector = app.selectbox(key="new_task_model")
                self.assertEqual(
                    selector.options,
                    ["GPT-5.6 Luna", "GPT-6 Sol", "GPT-6 Astra"],
                )
                selector.select("gpt-6-sol").run()
                self.assertFalse(app.exception)
                self.assertEqual(app.selectbox(key="new_task_model").value, "gpt-6-sol")
                image_selector = app.selectbox(key="new_task_image_model")
                image_selector.select("gpt-image-2.5-flare").run()
                self.assertFalse(app.exception)
                self.assertEqual(
                    app.selectbox(key="new_task_image_model").value,
                    "gpt-image-2.5-flare",
                )

    def test_gallery_browses_the_archived_corpus(self):
        from corpus_atelier.corpus.gallery import (
            import_seed, load_seed, packaged_seed_path,
        )
        from corpus_atelier.corpus.index import CorpusStore

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            upstream = root / "upstream"
            media = root / "media"
            seed = load_seed(packaged_seed_path())
            first = seed["records"][0]
            image_path = upstream / first["image_source"]
            image_path.parent.mkdir(parents=True)
            Image.new("RGB", (120, 180), (22, 44, 66)).save(image_path, format="PNG")
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
            with patch.dict(os.environ, _environment(directory)):
                app = AppTest.from_file(str(APP), default_timeout=10).run()
                app.session_state["product_view_tabs"] = "gallery"
                app.run()

        self.assertFalse(app.exception)
        self.assertIn("gallery_collection", [box.key for box in app.selectbox])
        self.assertGreaterEqual(len(app.get("image")), 1)

    def test_a_prompt_session_task_can_be_deleted_from_the_sidebar(self):
        with tempfile.TemporaryDirectory() as directory:
            app = CorpusAtelierApplication(
                runs_root=directory,
                image_provider=FakeImageProvider(),
            )
            try:
                created = app.start_from_prompt(
                    "A quiet poster of a paper lantern.",
                    case_id="natural-language",
                    settings={"image_quality": "medium", "aspect_ratio": [1, 1]},
                )
            finally:
                app.close()
            with patch.dict(os.environ, _environment(directory)):
                page = AppTest.from_file(str(APP), default_timeout=10).run()
                self.assertFalse(page.exception)
                page.button(key=f"delete_{created.run_id}").click().run()
                self.assertFalse(page.exception)
            self.assertFalse(created.run_dir.exists())

    def test_the_product_tabs_stay_visible_inside_a_task(self):
        with tempfile.TemporaryDirectory() as directory:
            text_provider = FakeTextProvider()
            text_provider.model = "gpt-5.6-luna"
            image_provider = FakeImageProvider()
            image_provider.model = "gpt-image-2"
            image_provider.quality = "medium"
            app = CorpusAtelierApplication(
                runs_root=directory,
                text_provider=text_provider,
                image_provider=image_provider,
            )
            try:
                created = app.start_from_prompt(
                    "A quiet poster of a paper lantern.",
                    case_id="natural-language",
                    settings={"image_quality": "medium", "aspect_ratio": [1, 1]},
                )
            finally:
                app.close()
            with patch.dict(os.environ, _environment(directory)):
                page = AppTest.from_file(str(APP), default_timeout=10)
                page.session_state["selected_task_id"] = created.run_id
                page.run()
                self.assertFalse(page.exception)
                # The tabs never disappear, and the open task stays selected.
                self.assertEqual(
                    page.segmented_control(key="product_view_tabs").value, "studio",
                )
                page.segmented_control(key="product_view_tabs").set_value("gallery").run()
                self.assertFalse(page.exception)
                self.assertIn(
                    "gallery_collection", [box.key for box in page.selectbox],
                )
                self.assertEqual(
                    page.session_state["selected_task_id"], created.run_id,
                )
                page.segmented_control(key="product_view_tabs").set_value("studio").run()
                self.assertFalse(page.exception)
                self.assertTrue(any(
                    area.key and area.key.startswith(f"prompt_text_{created.run_id}_")
                    for area in page.text_area
                ))

    def test_a_task_from_the_retired_workflow_is_read_only(self):
        run_id = "20260926T150000Z_abcdef12"
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "natural-language" / run_id
            run_dir.mkdir(parents=True)
            (run_dir / "manifest.json").write_text(
                '{"format_version": 2, "case_id": "natural-language", '
                f'"run_id": "{run_id}", "title": "旧任务", '
                '"created_at": "2026-09-26T15:00:00+00:00", '
                '"updated_at": "2026-09-26T15:05:00+00:00", '
                '"input_mode": "natural_language", "status": "completed"}',
                encoding="utf-8",
            )
            with patch.dict(os.environ, _environment(directory)):
                page = AppTest.from_file(str(APP), default_timeout=10)
                page.session_state["selected_task_id"] = run_id
                page.run()

            self.assertFalse(page.exception)
            self.assertIn(
                "这个任务由已移除的分阶段设计流程创建，当前版本无法继续运行它。",
                [info.value for info in page.info],
            )
            self.assertEqual(
                [button.key for button in page.button if button.key == f"delete_retired_{run_id}"],
                [f"delete_retired_{run_id}"],
            )

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
        self.assertNotIn(".atelier", sources["studio.py"])
        self.assertIn(
            '".atelier" / "tasks"',
            (ROOT / "src/corpus_atelier/config/paths.py").read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
