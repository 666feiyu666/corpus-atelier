import io
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

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

    def test_request_command_uses_the_natural_language_entrypoint(self):
        application = Mock()
        application.start_request.return_value = SimpleNamespace(
            run_id="test-run",
            status="completed",
            message="completed",
            artifacts={},
        )
        stream = io.StringIO()

        with (
            patch(
                "corpus_atelier.cli.CorpusAtelierApplication",
                return_value=application,
            ),
            patch("sys.stdout", stream),
        ):
            code = main([
                "request",
                "--text", "请做一张适合办公室工位的电脑壁纸。",
            ])

        self.assertEqual(code, 0)
        job = application.start_request.call_args.args[0]
        self.assertEqual(job.case_id, "natural-language")
        self.assertEqual(job.profile, "rhetoric-graphic")
        self.assertEqual(job.request, "请做一张适合办公室工位的电脑壁纸。")
