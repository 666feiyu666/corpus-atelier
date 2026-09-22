import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from corpus_atelier.artifacts.store import ArtifactStore
from corpus_atelier.registry import get_profile


class ArtifactTests(unittest.TestCase):
    def test_runs_never_overwrite(self):
        with TemporaryDirectory() as directory:
            store = ArtifactStore(directory)
            args = dict(
                case_id="poster-01",
                brief={"topic": "x"}, profile=get_profile("rhetoric-poster"),
                generation_mode="without_corpus",
            )
            first, first_dir = store.create(**args)
            second, second_dir = store.create(**args)
            self.assertNotEqual(first, second)
            self.assertNotEqual(first_dir, second_dir)
            self.assertEqual(first_dir.parent.name, "poster-01")

    def test_case_id_must_be_a_path_safe_slug(self):
        with TemporaryDirectory() as directory:
            store = ArtifactStore(directory)
            with self.assertRaisesRegex(ValueError, "Case ID"):
                store.create(
                    case_id="../poster-01",
                    brief={"topic": "x"},
                    profile=get_profile("rhetoric-poster"),
                    generation_mode="without_corpus",
                )

    def test_atomic_json_rejects_nan(self):
        with TemporaryDirectory() as directory:
            store = ArtifactStore(directory)
            path = Path(directory)
            with self.assertRaises(ValueError):
                store.json(path, "bad.json", {"value": float("nan")})
            self.assertFalse((path / "bad.json").exists())
