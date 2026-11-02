"""Traceable corpus record: prompt-image pair + closed labels + provenance.

A record always knows where it came from (``source``): an atelier run id, an
import URL, or a manual note. That provenance is what keeps the corpus
* traceable * rather than a loose pile of prompts.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TypedDict
from uuid import uuid4

from ..design_support.validation import validate
from .taxonomy import normalize_tags


class ImageRef(TypedDict, total=False):
    path: str
    sha256: str
    width: int | None
    height: int | None


class SourceRef(TypedDict):
    kind: str  # "atelier" | "import" | "manual"
    run_id: str | None
    url: str | None
    note: str | None


class MetaRef(TypedDict, total=False):
    model: str | None
    quality: str | None
    size: str | None
    output_format: str | None


class CorpusRecord(TypedDict, total=False):
    id: str
    prompt: str
    tags: list[str]
    source: SourceRef
    created_at: str
    negative_prompt: str | None
    image: ImageRef | None
    meta: MetaRef
    translations: dict[str, str | None]


def utcnow_iso() -> str:
    """ISO-8601 UTC timestamp used for record ``created_at``."""
    return datetime.now(timezone.utc).isoformat()


def new_record(
    *,
    prompt: str,
    tags: list[str],
    source_kind: str,
    negative_prompt: str | None = None,
    image: ImageRef | None = None,
    source_run_id: str | None = None,
    source_url: str | None = None,
    source_note: str | None = None,
    meta: MetaRef | None = None,
    translations: dict[str, str | None] | None = None,
    record_id: str | None = None,
    created_at: str | None = None,
) -> CorpusRecord:
    """Build a valid record with defaults, then normalize it."""
    record: CorpusRecord = {
        "id": record_id or uuid4().hex,
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "image": image,
        "tags": list(tags),
        "source": {
            "kind": source_kind,
            "run_id": source_run_id,
            "url": source_url,
            "note": source_note,
        },
        "meta": dict(meta or {}),
        "translations": dict(translations or {}),
        "created_at": created_at or utcnow_iso(),
    }
    return normalize_record(record)


def normalize_record(record: CorpusRecord) -> CorpusRecord:
    """Validate the schema, then canonicalize labels (dedup, reject unknown)."""
    validate(record, "corpus-record.schema.json")
    result = dict(record)
    result["tags"] = normalize_tags(result["tags"])
    return result
