"""Retrieval value normalization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Candidate:
    id: str
    kind: str
    title: str
    text: str
    tags: tuple[str, ...]
    metadata: dict[str, Any]

    def serializable(self) -> dict[str, Any]:
        return {
            "id": self.id, "kind": self.kind, "title": self.title, "text": self.text,
            "tags": list(self.tags), "metadata": self.metadata,
        }
