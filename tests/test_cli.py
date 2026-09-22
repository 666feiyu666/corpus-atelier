import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from corpus_atelier.cli import main


ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def test_profiles(self):
        stream = io.StringIO()
        with patch("sys.stdout", stream):
            self.assertEqual(main(["profiles"]), 0)
        self.assertIn("rhetoric-poster", stream.getvalue())

    def test_validate_never_calls_provider(self):
        stream = io.StringIO()
        with patch("sys.stdout", stream):
            code = main([
                "validate", "--profile", "rhetoric-poster", "--brief",
                str(ROOT / "experiments/cases/poster-01/brief.json"),
            ])
        self.assertEqual(code, 0)
        self.assertIn("Valid rhetoric-poster brief", stream.getvalue())

    def test_reference_preview_resolves_without_provider_calls(self):
        with TemporaryDirectory() as directory:
            selection = Path(directory) / "selection.json"
            selection.write_text(json.dumps({
                "format_version": 1,
                "reference_id": "mucha-poster-124474277",
            }), encoding="utf-8")
            output = Path(directory) / "output"
            stream = io.StringIO()
            with patch("sys.stdout", stream):
                code = main([
                    "preview-reference",
                    "--reference", str(selection),
                    "--snapshot", str(ROOT / "experiments/atlas-snapshot/mucha-commercial"),
                    "--output", str(output),
                ])
            self.assertEqual(code, 0)
            self.assertTrue((output / "reference-selection.json").is_file())
            package = json.loads(
                (output / "reference-package.json").read_text(encoding="utf-8"))
            self.assertEqual(package["reference"]["id"], "mucha-poster-124474277")
            self.assertNotIn("knowledge", package)
