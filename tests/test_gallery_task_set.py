import json
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GALLERY = ROOT / "gallery" / "v1.0.1"


class GalleryTaskSetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(
            (GALLERY / "task-set.json").read_text(encoding="utf-8")
        )
        cls.tasks = cls.manifest["tasks"]

    def test_gallery_has_sixteen_distinct_scenarios(self):
        self.assertEqual(len(self.tasks), 16)
        self.assertEqual(len({task["id"] for task in self.tasks}), 16)
        self.assertEqual(len({task["deliverable"] for task in self.tasks}), 16)
        self.assertEqual(len({task["request_file"] for task in self.tasks}), 16)

    def test_language_and_profile_distribution_is_balanced(self):
        self.assertEqual(
            Counter(task["language"] for task in self.tasks),
            Counter({"zh-CN": 8, "en": 8}),
        )
        self.assertEqual(
            Counter(task["profile"] for task in self.tasks),
            Counter({"art-graphic": 8, "rhetoric-graphic": 8}),
        )

    def test_each_task_has_gallery_metadata_and_a_request(self):
        required = {
            "id",
            "label",
            "language",
            "deliverable",
            "aspect_ratio",
            "medium",
            "information_density",
            "profile",
            "request_file",
        }
        tasks_root = (GALLERY / "tasks").resolve()
        for task in self.tasks:
            with self.subTest(task=task["id"]):
                self.assertTrue(required.issubset(task))
                request_path = (GALLERY / task["request_file"]).resolve()
                request_path.relative_to(tasks_root)
                self.assertTrue(request_path.is_file())
                self.assertTrue(request_path.read_text(encoding="utf-8").strip())

    def test_gallery_launcher_fixes_generation_to_one_candidate(self):
        self.assertEqual(self.manifest["default_candidates"], 1)
        launcher = (GALLERY / "run-task.ps1").read_text(encoding="utf-8")
        self.assertIn("--candidates 1", launcher)
        self.assertNotIn("$Candidates", launcher)
        self.assertNotIn("ValidateSet(1, 2, 3)", launcher)


if __name__ == "__main__":
    unittest.main()
