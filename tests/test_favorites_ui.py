"""Favorites and start-from-favorite in the Streamlit interface."""

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from corpus_atelier.artifacts.records import read_json
from corpus_atelier.favorites import FavoriteStore
from tests.test_favorites import _brief, _write_conversation


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "src/corpus_atelier/streamlit_app.py"


def _environment(root: Path) -> dict[str, str]:
    return {
        "CORPUS_ATELIER_TASKS_ROOT": str(root / "tasks"),
        "CORPUS_ATELIER_FAVORITES_ROOT": str(root / "favorites"),
        "CORPUS_ATELIER_PREFERENCES_PATH": str(root / "settings.json"),
        "CORPUS_ATELIER_ENV_PATH": str(root / ".env"),
        "OPENAI_API_KEY": "sk-test",
    }


class FavoriteUITests(unittest.TestCase):
    def test_favorite_then_reuse_from_the_favorites_tab(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            tasks = root / "tasks"
            favorites = root / "favorites"
            run_id = _write_conversation(tasks)
            with patch.dict(os.environ, _environment(root)):
                app = AppTest.from_file(str(APP), default_timeout=30)
                app.session_state["selected_task_id"] = run_id
                app.run()

                self.assertFalse(app.exception)
                self.assertEqual(
                    app.button(key=f"favorite_{run_id}").label,
                    "收藏这次对话",
                )
                app.button(key=f"favorite_{run_id}").click().run()
                self.assertFalse(app.exception)
                self.assertEqual(
                    app.button(key=f"favorite_{run_id}").label,
                    "更新收藏",
                )

                summaries = FavoriteStore(favorites).list()
                self.assertEqual(len(summaries), 1)
                favorite_id = summaries[0].favorite_id
                self.assertIsNotNone(summaries[0].cover_path)

                app.button(key="new_task").click().run()
                app.segmented_control(key="product_view_tabs").set_value(
                    "favorites"
                ).run()
                self.assertFalse(app.exception)
                self.assertIn("收藏夹", [title.value for title in app.title])
                self.assertTrue(app.button(key=f"favorite_view_{favorite_id}"))
                self.assertTrue(app.button(key=f"favorite_start_{favorite_id}"))

                app.button(key=f"favorite_view_{favorite_id}").click().run()
                self.assertFalse(app.exception)
                tabs = [tab.label for tab in app.tabs]
                self.assertIn("Brief", tabs)
                self.assertIn("对话", tabs)
                self.assertIn("提示词", tabs)
                downloads = [
                    button.label for button in app.get("download_button")
                ]
                self.assertIn("下载提示词（Markdown）", downloads)

                app.button(key="favorite_detail_start").click().run()
                self.assertFalse(app.exception)
                new_id = app.session_state["selected_task_id"]
                self.assertNotEqual(new_id, run_id)
                conversation = read_json(
                    tasks / "natural-language" / new_id / "conversation.json"
                )
                self.assertEqual(conversation["revision"], 1)
                self.assertEqual(conversation["design_brief"], _brief())
                self.assertEqual(len(conversation["messages"]), 1)
                self.assertEqual(
                    conversation["messages"][0]["text"],
                    "设计一张国庆花艺海报",
                )

    def test_favorites_tab_shows_an_empty_state(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, _environment(root)):
                app = AppTest.from_file(str(APP), default_timeout=20).run()
                app.segmented_control(key="product_view_tabs").set_value(
                    "favorites"
                ).run()

            self.assertFalse(app.exception)
            captions = [caption.value for caption in app.caption]
            self.assertIn("还没有收藏。", captions)
            self.assertIn("打开一个对话，点右上角的收藏按钮。", captions)
