"""Atomic record primitives."""

from __future__ import annotations

import json
import logging
from pathlib import Path
import time
from uuid import uuid4

LOGGER = logging.getLogger(__name__)


def read_json(path: Path):
    """Read an atomic record, tolerating brief Windows file-sharing contention."""
    for attempt in range(5):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.01 * (attempt + 1))


def _replace_record(temporary: Path, path: Path) -> None:
    for attempt in range(5):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.01 * (attempt + 1))


def write_json(path: Path, value: object) -> None:
    text = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    write_text(path, text)


def write_text(path: Path, value: str) -> None:
    """Replace a complete record and remove temporary files if writing fails."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(value, encoding="utf-8")
        _replace_record(temporary, path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            LOGGER.warning("Could not remove temporary record %s.", temporary, exc_info=True)
