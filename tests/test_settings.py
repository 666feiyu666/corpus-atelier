import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from corpus_atelier.settings import (
    load_preferences,
    mask_api_key,
    resolve_openai_api_key,
    save_preferences,
    update_local_openai_api_key,
)


class ProductSettingsTests(unittest.TestCase):
    def test_preferences_are_validated_and_persisted(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            self.assertEqual(load_preferences(path), {"language": "zh-CN"})

            save_preferences(path, {"language": "en"})

            self.assertEqual(load_preferences(path), {"language": "en"})
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                {"language": "en"},
            )

    def test_api_key_precedence_is_session_then_local_then_environment(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            update_local_openai_api_key(path, "sk-local-1234")

            session = resolve_openai_api_key(
                "sk-session-1234",
                env_path=path,
                environment={"OPENAI_API_KEY": "sk-environment-1234"},
            )
            local = resolve_openai_api_key(
                None,
                env_path=path,
                environment={"OPENAI_API_KEY": "sk-environment-1234"},
            )
            update_local_openai_api_key(path, None)
            environment = resolve_openai_api_key(
                None,
                env_path=path,
                environment={"OPENAI_API_KEY": "sk-environment-1234"},
            )

            self.assertEqual((session.value, session.source), (
                "sk-session-1234", "session",
            ))
            self.assertEqual((local.value, local.source), (
                "sk-local-1234", "local",
            ))
            self.assertEqual((environment.value, environment.source), (
                "sk-environment-1234", "environment",
            ))

    def test_updating_dotenv_preserves_unrelated_configuration(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text(
                "OTHER_SETTING=keep\nOPENAI_API_KEY=old\n",
                encoding="utf-8",
            )

            update_local_openai_api_key(path, "sk-new-5678")
            saved = path.read_text(encoding="utf-8")

            self.assertIn("OTHER_SETTING=keep", saved)
            self.assertIn('OPENAI_API_KEY="sk-new-5678"', saved)
            self.assertNotIn("old", saved)
            self.assertEqual(mask_api_key("sk-new-5678"), "••••5678")

            update_local_openai_api_key(path, None)
            cleared = path.read_text(encoding="utf-8")
            self.assertIn("OTHER_SETTING=keep", cleared)
            self.assertNotIn("OPENAI_API_KEY", cleared)


if __name__ == "__main__":
    unittest.main()
