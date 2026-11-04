"""Resolve the product's local directories once, independent of module depth.

Paths are resolved on demand rather than at import time so that a caller which
patches the environment (tests, alternate task roots) gets the values it set.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _resolved(name: str, default: Path) -> Path:
    return Path(os.environ.get(name, default)).resolve()


@dataclass(frozen=True)
class ProductPaths:
    """Every local directory and file the product reads or writes."""

    tasks_root: Path
    env_path: Path
    preferences_path: Path
    corpus_db_path: Path
    corpus_media_root: Path


def _atelier_root() -> Path:
    """The local state root, which the dev profile keeps separate.

    ``CORPUS_ATELIER_PROFILE=dev`` moves tasks, preferences, the corpus database,
    and corpus media under ``.atelier/dev`` so a development run can create and
    delete tasks without touching the daily store. The dotenv file stays shared:
    one credential, deliberately. Explicit ``CORPUS_ATELIER_*`` variables still
    win over both.
    """
    root = PROJECT_ROOT / ".atelier"
    profile = os.environ.get("CORPUS_ATELIER_PROFILE", "").strip().lower()
    return root / "dev" if profile == "dev" else root


def resolve_paths() -> ProductPaths:
    """Resolve the product paths against the environment as it is right now."""
    root = _atelier_root()
    return ProductPaths(
        tasks_root=_resolved("CORPUS_ATELIER_TASKS_ROOT", root / "tasks"),
        env_path=_resolved("CORPUS_ATELIER_ENV_PATH", PROJECT_ROOT / ".env"),
        preferences_path=_resolved(
            "CORPUS_ATELIER_PREFERENCES_PATH", root / "settings.json",
        ),
        corpus_db_path=_resolved("CORPUS_ATELIER_CORPUS_DB", root / "corpus.sqlite3"),
        corpus_media_root=_resolved(
            "CORPUS_ATELIER_CORPUS_MEDIA", root / "corpus-media",
        ),
    )
