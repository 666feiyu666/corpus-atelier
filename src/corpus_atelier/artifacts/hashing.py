"""Stable content digests used to bind approval to reviewed content."""

import hashlib
import json
from pathlib import Path
from typing import Any


def digest_json(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def digest_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
