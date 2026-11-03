"""Immutable prompt-session records for the prompt-centered workflow.

A session owns the visible current prompt (a pointer to one immutable revision),
the conversation, and the image attempts and results produced from frozen
requests. Nothing here talks to a model: these are durable records only.
"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import logging
from pathlib import Path
from typing import Any, TypedDict
from uuid import uuid4

from ..artifacts.records import read_json, write_json


LOGGER = logging.getLogger(__name__)

SESSION_FILE = "prompt-session.json"
FORMAT_VERSION = 1
WORKFLOW_KIND = "prompt_session_v1"

MAX_PROMPT_LENGTH = 8000
MAX_REPLY_LENGTH = 8000
MAX_INSTRUCTION_LENGTH = 2000
MAX_NEGATIVE_PROMPT_LENGTH = 2000

ENTRY_MODES = ("prompt", "image")
PROMPT_ORIGINS = frozenset({
    "user_input", "vision_extraction", "assistant_revision", "manual_edit",
})


class PromptSessionRecord(TypedDict):
    """One prompt-centered session; earlier records are never overwritten."""

    format_version: int
    workflow_kind: str
    entry_mode: str
    settings: dict[str, Any]
    created_at: str
    messages: list[dict[str, Any]]
    prompt_revisions: list[dict[str, Any]]
    current_prompt_revision_id: str | None
    uploads: list[dict[str, Any]]
    text_turns: list[dict[str, Any]]
    image_attempts: list[dict[str, Any]]
    image_results: list[dict[str, Any]]
    active_image_id: str | None
    pending_turn: dict[str, Any] | None


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def prompt_digest(text: str) -> str:
    """Return the content digest bound to one prompt revision or frozen request."""
    return sha256(text.encode("utf-8")).hexdigest()


def canonical_digest(value: object) -> str:
    """Digest of a canonical JSON encoding, used for frozen request identity."""
    import json

    return sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8"),
    ).hexdigest()


def new_session(entry_mode: str, settings: dict[str, Any]) -> PromptSessionRecord:
    if entry_mode not in ENTRY_MODES:
        raise ValueError("A prompt session entry mode must be prompt or image.")
    return {
        "format_version": FORMAT_VERSION,
        "workflow_kind": WORKFLOW_KIND,
        "entry_mode": entry_mode,
        "settings": dict(settings),
        "created_at": now(),
        "messages": [],
        "prompt_revisions": [],
        "current_prompt_revision_id": None,
        "uploads": [],
        "text_turns": [],
        "image_attempts": [],
        "image_results": [],
        "active_image_id": None,
        "pending_turn": None,
    }


def new_revision(
    session: PromptSessionRecord,
    prompt_text: str,
    origin: str,
    *,
    parent_revision_id: str | None = None,
    source_message_id: str | None = None,
    source_image_id: str | None = None,
    source_turn_id: str | None = None,
    note: str | None = None,
    negative_prompt: str | None = None,
    restored_from: str | None = None,
) -> dict[str, Any]:
    """Append one immutable revision and make it current."""
    if origin not in PROMPT_ORIGINS:
        raise ValueError(f"Unsupported prompt revision origin: {origin!r}.")
    if not isinstance(prompt_text, str) or not prompt_text.strip():
        raise ValueError("A prompt revision requires nonempty prompt text.")
    if len(prompt_text) > MAX_PROMPT_LENGTH:
        raise ValueError(f"A prompt must be at most {MAX_PROMPT_LENGTH} characters.")
    if negative_prompt is not None:
        if not isinstance(negative_prompt, str) or not negative_prompt.strip():
            raise ValueError("A negative prompt must be nonempty text or None.")
        if len(negative_prompt) > MAX_NEGATIVE_PROMPT_LENGTH:
            raise ValueError(
                f"A negative prompt must be at most {MAX_NEGATIVE_PROMPT_LENGTH} characters."
            )
    revision = {
        "id": new_id("rev"),
        "parent_revision_id": parent_revision_id,
        "prompt_text": prompt_text,
        "origin": origin,
        "source_message_id": source_message_id,
        "source_image_id": source_image_id,
        "note": note,
        "restored_from": restored_from,
        "negative_prompt": negative_prompt,
        "digest": prompt_digest(prompt_text),
        "created_at": now(),
    }
    session["prompt_revisions"].append(revision)
    session["current_prompt_revision_id"] = revision["id"]
    return revision


def _find(items: list[dict[str, Any]], value: str, *, kind: str) -> dict[str, Any]:
    """Return the one record with this id, or report it missing by its role."""
    for item in items:
        if item.get("id") == value:
            return item
    raise ValueError(f"The {kind} does not exist in this session.")


def find_revision(session: PromptSessionRecord, revision_id: str) -> dict[str, Any]:
    return _find(session["prompt_revisions"], revision_id, kind="prompt revision")


def current_revision(session: PromptSessionRecord) -> dict[str, Any] | None:
    revision_id = session.get("current_prompt_revision_id")
    if revision_id is None:
        return None
    return find_revision(session, revision_id)


def find_upload(session: PromptSessionRecord, upload_id: str) -> dict[str, Any]:
    return _find(session["uploads"], upload_id, kind="selected upload")


def find_attempt(session: PromptSessionRecord, attempt_id: str) -> dict[str, Any]:
    return _find(session["image_attempts"], attempt_id, kind="image attempt")


def find_result(session: PromptSessionRecord, image_id: str) -> dict[str, Any]:
    return _find(session["image_results"], image_id, kind="image result")


def image_record(session: PromptSessionRecord, image_id: str) -> dict[str, Any]:
    """Resolve one selectable image: an uploaded source or a generated result."""
    for upload in session["uploads"]:
        if upload["id"] == image_id:
            return {**upload, "kind": "upload"}
    for result in session["image_results"]:
        if result["id"] == image_id:
            return {**result, "path": result["image_path"], "kind": "result"}
    raise ValueError("The selected image does not exist in this session.")


def _repair_attempts(session: PromptSessionRecord) -> None:
    """An interrupted submission may have reached the provider: never retry it."""
    for attempt in session["image_attempts"]:
        if attempt.get("status") == "submitting":
            attempt["status"] = "outcome_unknown"
            attempt["outcome_unknown"] = True


def _check_revisions(session: PromptSessionRecord, root: Path) -> None:
    for revision in session["prompt_revisions"]:
        if revision.get("digest") != prompt_digest(revision["prompt_text"]):
            raise ValueError(
                f"The prompt revision {revision['id']} in {root.name} does not match its digest."
            )


def load_session(root: Path) -> PromptSessionRecord:
    """Read one session, tolerating legacy fields and repairing interrupted work."""
    value = read_json(root / SESSION_FILE)
    if not isinstance(value, dict):
        raise ValueError("The prompt session record must be an object.")
    defaults: dict[str, Any] = {
        "format_version": FORMAT_VERSION,
        "workflow_kind": WORKFLOW_KIND,
        "entry_mode": "prompt",
        "settings": {},
        "created_at": "",
        "messages": [],
        "prompt_revisions": [],
        "current_prompt_revision_id": None,
        "uploads": [],
        "text_turns": [],
        "image_attempts": [],
        "image_results": [],
        "active_image_id": None,
        "pending_turn": None,
    }
    for field, default in defaults.items():
        value.setdefault(field, default)
    if value["entry_mode"] not in ENTRY_MODES:
        raise ValueError("The prompt session entry mode is not supported.")
    _check_revisions(value, root)
    _repair_attempts(value)
    return value


def save_session(root: Path, value: PromptSessionRecord) -> None:
    write_json(root / SESSION_FILE, value)
