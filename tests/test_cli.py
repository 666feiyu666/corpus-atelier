import io
from pathlib import Path
import unittest
from unittest.mock import patch

from corpus_atelier.cli import main


ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def test_profiles(self):
        stream = io.StringIO()
        with patch("sys.stdout", stream):
            self.assertEqual(main(["profiles"]), 0)
        listing = stream.getvalue()
        for name in ("general-graphic", "poster", "article-cover"):
            self.assertIn(name, listing)
        self.assertNotIn("rhetoric", listing)

    def test_validate_never_calls_provider(self):
        stream = io.StringIO()
        with patch("sys.stdout", stream):
            code = main([
                "validate", "--profile", "poster", "--brief",
                str(ROOT / "tests/fixtures/cases/poster-01/brief.json"),
            ])
        self.assertEqual(code, 0)
        self.assertIn("Valid poster brief", stream.getvalue())

    def test_validate_accepts_a_retired_profile_name(self):
        stream = io.StringIO()
        with patch("sys.stdout", stream):
            code = main([
                "validate", "--profile", "rhetoric-poster", "--brief",
                str(ROOT / "tests/fixtures/cases/poster-01/brief.json"),
            ])
        self.assertEqual(code, 0)
        self.assertIn("Valid poster brief", stream.getvalue())
