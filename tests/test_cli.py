import io
import json
import tempfile
import unittest
from unittest.mock import patch

from corpus_atelier.app.service import CorpusAtelierApplication
from corpus_atelier.cli import main


class CliTests(unittest.TestCase):
    def test_inspect_prints_the_saved_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            app = CorpusAtelierApplication(runs_root=directory)
            try:
                created = app.start_from_prompt(
                    "A quiet poster of a paper lantern.",
                    case_id="natural-language",
                    settings={"image_quality": "medium", "aspect_ratio": [1, 1]},
                )
            finally:
                app.close()
            stream = io.StringIO()
            with patch("sys.stdout", stream):
                self.assertEqual(
                    main([
                        "inspect", created.run_id, "--runs-root", directory,
                    ]),
                    0,
                )
            manifest = json.loads(stream.getvalue())
            self.assertEqual(manifest["run_id"], created.run_id)
            self.assertEqual(manifest["status"], "prompt_ready")

    def test_the_api_command_refuses_a_public_host(self):
        with self.assertRaises(SystemExit):
            main(["api", "--host", "0.0.0.0", "--port", "0"])

    def test_the_retired_profile_commands_are_gone(self):
        for command in (["profiles"], ["validate", "--brief", "x.json"]):
            with self.assertRaises(SystemExit):
                with patch("sys.stderr", io.StringIO()):
                    main(command)

    def test_inspect_rejects_an_unknown_run(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError):
                main([
                    "inspect", "20260101T000000Z_aaaaaaaa", "--runs-root", directory,
                ])


if __name__ == "__main__":
    unittest.main()
