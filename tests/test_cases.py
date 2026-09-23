import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from corpus_atelier.cases import discover_cases


class CaseCatalogTests(unittest.TestCase):
    def test_poster_02_declares_all_required_visible_copy(self):
        brief_path = (
            Path(__file__).parents[1]
            / "experiments"
            / "cases"
            / "poster-02"
            / "brief.json"
        )
        brief = json.loads(brief_path.read_text(encoding="utf-8"))

        self.assertEqual(
            brief["exact_copy"],
            [
                "C306音乐之夜",
                "今晚晚会结束后欢迎来C306房间",
                "11点前结束",
                "无酒精",
                "仅限内部熟人",
                "活动可能随时取消",
                "一时兴起，纯属瞎搞",
                "若有冒犯，敬请谅解",
            ],
        )
        self.assertIn(
            "不得添加exact_copy之外的任何可读文字",
            brief["constraints"],
        )

    def test_discovers_and_validates_a_new_case_directory(self):
        with TemporaryDirectory() as directory:
            case_dir = Path(directory) / "new-case"
            case_dir.mkdir()
            (case_dir / "case.json").write_text(json.dumps({
                "format_version": 1,
                "label": "New case",
                "profile": "art-graphic",
            }), encoding="utf-8")
            (case_dir / "brief.json").write_text(json.dumps({
                "deliverable": "Exhibition card",
                "purpose": "Orient visitors",
                "audience": "Museum visitors",
                "use_context": "Handheld reading",
                "exact_copy": [],
                "constraints": [],
                "preferences": [],
                "canvas": {"aspect_ratio": {"width": 4, "height": 5}},
            }), encoding="utf-8")

            catalog = discover_cases(directory)

            self.assertEqual(list(catalog), ["New case"])
            self.assertEqual(catalog["New case"].case_id, "new-case")
            self.assertEqual(catalog["New case"].profile, "art-graphic")

    def test_brief_without_a_manifest_is_rejected(self):
        with TemporaryDirectory() as directory:
            case_dir = Path(directory) / "unregistered-case"
            case_dir.mkdir()
            (case_dir / "brief.json").write_text("{}", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "no case.json manifest"):
                discover_cases(directory)


if __name__ == "__main__":
    unittest.main()
