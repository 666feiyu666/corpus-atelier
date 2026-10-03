"""Conversation records and read-only recovery of archived brief history."""

from copy import deepcopy
from datetime import datetime, timezone
import logging
from pathlib import Path
from typing import Any, TypedDict

from .artifacts.records import read_json
from .artifacts.store import read_manifest


LOGGER = logging.getLogger(__name__)
FORMAT_VERSION = 8


class PendingTurn(TypedDict):
    message_id: str
    context: dict[str, Any]
    images: list[dict[str, str]]


class ConversationRecord(TypedDict):
    """Brief revision changes on user saves; discussion revision counts replies."""

    format_version: int
    profile: str
    content_language: str | None
    discussion_language: str | None
    language_source_request: str
    messages: list[dict[str, Any]]
    effective_request: str
    open_questions: list[str]
    revision: int
    discussion_revision: int
    rounds: list[dict[str, Any]]
    pending: PendingTurn | None
    user_requirements: list[str]
    design_brief: dict[str, Any] | None
    brief_revision: int | None
    brief_history: list[dict[str, Any]]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_conversation(profile: str, request: str, language: str | None) -> ConversationRecord:
    """Start a dialogue with an empty brief that only the user can save."""
    return {
        "format_version": FORMAT_VERSION,
        "profile": profile,
        "content_language": language,
        "discussion_language": language,
        "language_source_request": request,
        "messages": [],
        "effective_request": "",
        "open_questions": [],
        "revision": 0,
        "discussion_revision": 0,
        "rounds": [],
        "pending": None,
        "user_requirements": [],
        "design_brief": None,
        "brief_revision": None,
        "brief_history": [],
    }


def record_brief(value: ConversationRecord, *, origin: str, based_on: int | None = None) -> None:
    value["brief_history"].append({
        "revision": value["brief_revision"],
        "brief": deepcopy(value["design_brief"]),
        "origin": origin,
        "based_on": based_on,
        "created_at": now(),
    })


def _legacy_brief_history(root: Path, value: ConversationRecord) -> list[dict]:
    """Older model-authored turns stored their brief snapshots separately."""
    history = []
    message_id = None
    for message in value["messages"]:
        if message["role"] == "user":
            message_id = message.get("id")
        elif message_id and message.get("revision") is not None:
            path = root / "conversation-turns" / message_id / "brief/brief.json"
            if path.is_file():
                history.append({
                    "revision": message["revision"], "brief": read_json(path),
                    "origin": "assistant", "created_at": message["created_at"],
                })
    if value["design_brief"] is not None and not any(
        entry["revision"] == value["brief_revision"] for entry in history
    ):
        history.append({
            "revision": value["brief_revision"], "brief": deepcopy(value["design_brief"]),
            "origin": "legacy", "created_at": "",
        })
    return history


def _recover_rounds(root: Path, value: ConversationRecord) -> None:
    """A child manifest may have been saved before its parent index update."""
    known_ids = {record["run_id"] for record in value["rounds"]}
    for path in root.parent.glob("*/manifest.json"):
        try:
            manifest = read_manifest(path)
            if manifest.get("conversation_parent_id") != root.name:
                continue
            run_id = manifest["run_id"]
            if run_id not in known_ids:
                value["rounds"].append({
                    "run_id": run_id,
                    "revision": manifest.get("conversation_revision", 0),
                    "created_at": manifest["created_at"],
                })
                known_ids.add(run_id)
        except (OSError, KeyError, ValueError) as exc:
            LOGGER.warning("Skipping unreadable round manifest %s: %s", path, exc)
    value["rounds"].sort(key=lambda record: record["created_at"])


def _recover_round_briefs(root: Path, value: ConversationRecord) -> None:
    known_revisions = {entry["revision"] for entry in value["brief_history"]}
    for record in value["rounds"]:
        if record["revision"] in known_revisions:
            continue
        path = root.parent / record["run_id"] / "brief.json"
        if path.is_file():
            value["brief_history"].append({
                "revision": record["revision"], "brief": read_json(path), "origin": "legacy",
                "created_at": record["created_at"],
            })
            known_revisions.add(record["revision"])
    value["brief_history"].sort(
        key=lambda entry: entry["revision"] if entry["revision"] is not None else -1
    )


def load_conversation(root: Path) -> ConversationRecord:
    """Recover records in memory, preserving archived files and legacy metadata."""
    value = read_json(root / "conversation.json")
    if not isinstance(value, dict):
        raise ValueError("The conversation record must be an object.")
    defaults = {
        "user_requirements": [], "design_brief": None, "brief_revision": None,
        "content_language": None, "discussion_language": None, "discussion_revision": 0,
    }
    for field, default in defaults.items():
        value.setdefault(field, default)
    if "brief_history" not in value:
        value["brief_history"] = _legacy_brief_history(root, value)
    value.setdefault("language_source_request", next(
        (message["text"] for message in value["messages"]
         if message["role"] == "user" and message.get("kind", "discussion") == "discussion"
         and message["text"].strip()), "",
    ))
    _recover_rounds(root, value)
    _recover_round_briefs(root, value)
    return value
