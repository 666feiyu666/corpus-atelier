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


def resolve_paths() -> ProductPaths:
    """Resolve the product paths against the environment as it is right now."""
    return ProductPaths(
        tasks_root=_resolved(
            "CORPUS_ATELIER_TASKS_ROOT", PROJECT_ROOT / ".atelier" / "tasks",
        ),
        env_path=_resolved("CORPUS_ATELIER_ENV_PATH", PROJECT_ROOT / ".env"),
        preferences_path=_resolved(
            "CORPUS_ATELIER_PREFERENCES_PATH",
            PROJECT_ROOT / ".atelier" / "settings.json",
        ),
        corpus_db_path=_resolved(
            "CORPUS_ATELIER_CORPUS_DB", PROJECT_ROOT / ".atelier" / "corpus.sqlite3",
        ),
        corpus_media_root=_resolved(
            "CORPUS_ATELIER_CORPUS_MEDIA",
            PROJECT_ROOT / ".atelier" / "corpus-media",
        ),
    )
