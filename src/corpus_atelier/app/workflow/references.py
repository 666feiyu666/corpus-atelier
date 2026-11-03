"""Shape corpus reference slices for prompts without leaking local paths."""

from __future__ import annotations

from typing import Any


def text_references(references: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop local image paths: prompts carry the evidence, not filesystem detail."""
    return [
        {key: value for key, value in reference.items() if key != "image"}
        for reference in references
    ]
