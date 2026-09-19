"""Validate an immutable Atlas snapshot and referenced local files."""

import json
from pathlib import Path

from ..artifacts.hashing import digest_file
from .source import load_jsonl


def load_snapshot(root: Path | str) -> tuple[dict, list]:
    root = Path(root).resolve(strict=True)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("format_version") != 1:
        raise ValueError("Unsupported Atlas snapshot format.")
    candidates = load_jsonl(root / "knowledge.jsonl", "knowledge")
    candidates += load_jsonl(root / "references.jsonl", "reference")
    for candidate in candidates:
        relative = candidate.metadata.get("file")
        expected = candidate.metadata.get("sha256")
        if relative:
            target = (root / relative).resolve(strict=True)
            if root not in target.parents or not target.is_file():
                raise ValueError(f"Reference {candidate.id} escapes the snapshot.")
            if expected and digest_file(target) != expected:
                raise ValueError(f"Reference {candidate.id} changed since snapshot creation.")
    return manifest, candidates
