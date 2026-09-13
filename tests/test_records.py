"""Sequential allocation preserves existing runs and concurrent attempts."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from graphic_design_helper.records import new_attempt, save_experiment, start_run


class RecordNamingTests(unittest.TestCase):
    def test_existing_runs_gaps_and_snapshot_namespace(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "legacy" / "run_99").mkdir(parents=True)
            (root / "run_01").mkdir()
            (root / "run_03").write_text("Reserved name", encoding="utf-8")
            run = start_run({"purpose": "Pause"}, output_dir=root)
            self.assertEqual(run.name, "run_04")
            self.assertEqual((root / "run_03").read_text(), "Reserved name")
            self.assertIn("created_at", json.loads((run / "run.json").read_text()))
            snapshot = save_experiment({"note": "Review"}, output_dir=root)
            self.assertEqual(snapshot.name, "snapshot_01")
            self.assertEqual(start_run({}, output_dir=root).name, "run_05")
            self.assertEqual(new_attempt(run / "designer").name, "attempt_01")
            self.assertEqual(new_attempt(run / "designer").name, "attempt_02")
            self.assertEqual(new_attempt(run / "image").name, "attempt_01")

    def test_concurrent_attempts_do_not_overwrite_existing_content(self):
        with TemporaryDirectory() as tmp:
            first = new_attempt(tmp)
            marker = first / "response.json"
            marker.write_text("preserved", encoding="utf-8")
            with ThreadPoolExecutor(max_workers=8) as pool:
                paths = list(pool.map(lambda _: new_attempt(tmp), range(16)))
            self.assertEqual(len(set(paths)), 16)
            self.assertNotIn(first, paths)
            self.assertEqual(marker.read_text(), "preserved")
            self.assertEqual({p.name for p in paths},
                             {f"attempt_{i:02d}" for i in range(2, 18)})
