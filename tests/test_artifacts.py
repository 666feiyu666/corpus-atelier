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
                brief={"topic": "x"}, profile=get_profile("rhetoric-poster"),
                evidence_mode="no-rag", snapshot=Path(directory),
            )
            first, first_dir = store.create(**args)
            second, second_dir = store.create(**args)
            self.assertNotEqual(first, second)
            self.assertNotEqual(first_dir, second_dir)

    def test_atomic_json_rejects_nan(self):
        with TemporaryDirectory() as directory:
            store = ArtifactStore(directory)
            path = Path(directory)
            with self.assertRaises(ValueError):
                store.json(path, "bad.json", {"value": float("nan")})
            self.assertFalse((path / "bad.json").exists())
