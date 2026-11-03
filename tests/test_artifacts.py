import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from corpus_atelier.artifacts.store import ArtifactStore


REQUEST = "A poster of a paper lantern at dusk."


class ArtifactTests(unittest.TestCase):
    def test_runs_never_overwrite(self):
        with TemporaryDirectory() as directory:
            store = ArtifactStore(directory)
            args = dict(case_id="poster-01", request=REQUEST)
            first, first_dir = store.create(**args)
            second, second_dir = store.create(**args)
            self.assertNotEqual(first, second)
            self.assertNotEqual(first_dir, second_dir)
            self.assertEqual(first_dir.parent.name, "poster-01")
            self.assertEqual(
                (first_dir / "input/request.txt").read_text(encoding="utf-8"),
                REQUEST,
            )

    def test_case_id_must_be_a_path_safe_slug(self):
        with TemporaryDirectory() as directory:
            store = ArtifactStore(directory)
            with self.assertRaisesRegex(ValueError, "Case ID"):
                store.create(case_id="../poster-01", request=REQUEST)

    def test_atomic_json_rejects_nan(self):
        with TemporaryDirectory() as directory:
            store = ArtifactStore(directory)
            path = Path(directory)
            with self.assertRaises(ValueError):
                store.json(path, "bad.json", {"value": float("nan")})
            self.assertFalse((path / "bad.json").exists())

    def test_status_callback_failure_does_not_undo_the_saved_status(self):
        def fail_callback(run_id, status):
            raise RuntimeError(f"{run_id}: {status}")

        with TemporaryDirectory() as directory:
            store = ArtifactStore(directory, status_callback=fail_callback)
            _, run_dir = store.create(case_id="poster-01", request=REQUEST)
            with self.assertLogs(
                "corpus_atelier.artifacts.store",
                level="ERROR",
            ):
                manifest = store.update(run_dir, "extracting")

            self.assertEqual(manifest["status"], "extracting")
            saved = json.loads(
                (run_dir / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(saved["status"], "extracting")

    def test_the_manifest_records_the_request_and_models(self):
        with TemporaryDirectory() as directory:
            store = ArtifactStore(directory)
            models = {"text": {"model": "fake-text"}, "image": {"model": "fake-image"}}
            _, run_dir = store.create(
                case_id="natural-language", request=REQUEST, models=models,
            )
            manifest = store.manifest(run_dir)
            self.assertEqual(manifest["status"], "created")
            self.assertEqual(manifest["models"], models)
            self.assertEqual(manifest["artifacts"]["user_request"], "input/request.txt")
            self.assertNotIn("profile", manifest)


if __name__ == "__main__":
    unittest.main()
