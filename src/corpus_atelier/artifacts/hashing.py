"""Stable content digests used to bind approval to approved content."""

import hashlib
from pathlib import Path


def digest_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
