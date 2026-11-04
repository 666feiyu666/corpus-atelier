"""The dev profile must never read or write the daily store."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from corpus_atelier.config.paths import PROJECT_ROOT, resolve_paths

DAILY = (PROJECT_ROOT / ".atelier").resolve()
DEV = (DAILY / "dev").resolve()


def resolve_with(profile: str | None, **extra: str):
    values = {key: value for key, value in extra.items()}
    if profile is not None:
        values["CORPUS_ATELIER_PROFILE"] = profile
    with patch.dict(os.environ, values, clear=False):
        if profile is None:
            os.environ.pop("CORPUS_ATELIER_PROFILE", None)
        return resolve_paths()


class ProfilePathsTests(unittest.TestCase):
    def test_the_default_profile_uses_the_daily_root(self):
        paths = resolve_with(None)
        self.assertEqual(paths.tasks_root, DAILY / "tasks")
        self.assertEqual(paths.corpus_db_path, DAILY / "corpus.sqlite3")
        self.assertEqual(paths.corpus_media_root, DAILY / "corpus-media")
        self.assertEqual(paths.preferences_path, DAILY / "settings.json")

    def test_an_empty_profile_is_the_daily_root(self):
        paths = resolve_with("")
        self.assertEqual(paths.tasks_root, DAILY / "tasks")

    def test_the_dev_profile_moves_every_store_under_dev(self):
        paths = resolve_with("dev")
        self.assertEqual(paths.tasks_root, DEV / "tasks")
        self.assertEqual(paths.corpus_db_path, DEV / "corpus.sqlite3")
        self.assertEqual(paths.corpus_media_root, DEV / "corpus-media")
        self.assertEqual(paths.preferences_path, DEV / "settings.json")

    def test_the_dev_profile_shares_the_credential_file(self):
        paths = resolve_with("dev")
        self.assertEqual(paths.env_path, (PROJECT_ROOT / ".env").resolve())

    def test_the_profile_name_is_case_and_space_insensitive(self):
        paths = resolve_with(" DEV ")
        self.assertEqual(paths.tasks_root, DEV / "tasks")

    def test_an_explicit_variable_still_wins_in_the_dev_profile(self):
        target = PROJECT_ROOT / "custom-dev-tasks"
        paths = resolve_with("dev", CORPUS_ATELIER_TASKS_ROOT=str(target))
        self.assertEqual(paths.tasks_root, target.resolve())
        # The other stores still follow the profile.
        self.assertEqual(paths.corpus_db_path, DEV / "corpus.sqlite3")
