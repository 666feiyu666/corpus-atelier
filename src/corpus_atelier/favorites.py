"""Self-contained snapshots of design conversations and their prompts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from pathlib import Path
import re
import shutil
from typing import Any, Protocol, TypedDict
from uuid import uuid4

from .artifacts.hashing import digest_file
from .artifacts.records import read_json, write_json
from .conversation_records import ConversationRecord
from .state import RunSummary


LOGGER = logging.getLogger(__name__)
FAVORITE_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")
FORMAT_VERSION = 1
COVER_NAME = "cover.png"


class FavoriteSource(Protocol):
    """The read-only application surface a favorite snapshot needs."""

    def inspect_task(self, run_id: str) -> RunSummary: ...

    def conversation(self, run_id: str) -> ConversationRecord: ...


class FavoriteRecord(TypedDict):
    """A frozen copy of one conversation, independent of its source task."""

    format_version: int
    favorite_id: str
    created_at: str
    updated_at: str
    source_run_id: str
    source_case_id: str
    title: str
    note: str
    content_language: str | None
    profile: str
    models: dict[str, Any]
    request: str
    brief: dict[str, Any] | None
    messages: list[dict[str, Any]]
    rounds: list[dict[str, Any]]
    cover_image: str | None
    cover_sha256: str | None


@dataclass(frozen=True)
class FavoriteSummary:
    favorite_id: str
    title: str
    note: str
    created_at: str
    updated_at: str
    source_run_id: str
    content_language: str | None
    round_count: int
    cover_path: Path | None


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_favorite_id(favorite_id: str) -> str:
    if not isinstance(favorite_id, str) or not FAVORITE_ID_PATTERN.fullmatch(favorite_id):
        raise ValueError("Favorite id must be a 32-character lowercase hex string.")
    return favorite_id


def _one_line(value: Any, fallback: str = "") -> str:
    text = " ".join(str(value or "").split())
    return text or fallback


def _total(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _candidate_snapshot(candidate: dict[str, Any]) -> dict[str, Any]:
    proposal = _total(candidate.get("proposal"))
    seed = _total(candidate.get("direction_seed"))
    error = candidate.get("error")
    return {
        "candidate_id": candidate.get("candidate_id"),
        "label": _one_line(seed.get("label"), str(candidate.get("candidate_id") or "")),
        "status": candidate.get("status"),
        "chosen_direction": proposal.get("chosen_direction"),
        "design_description": proposal.get("design_description"),
        "design_rationale": proposal.get("design_rationale"),
        "generation_prompt": candidate.get("generation_prompt"),
        "generation_request": _total(candidate.get("generation_request")),
        "error": _one_line(
            _total(error).get("message") if isinstance(error, dict) else error
        ) or None,
    }


def _message_snapshot(message: dict[str, Any]) -> dict[str, Any]:
    attachments = message.get("attachments")
    return {
        "role": str(message.get("role") or "user"),
        "text": str(message.get("text") or ""),
        "created_at": str(message.get("created_at") or ""),
        "attachments": [
            {"name": _one_line(item.get("name"))}
            for item in attachments or []
            if isinstance(item, dict)
        ],
    }


def _verified_image(candidate: dict[str, Any], run_dir: Path) -> Path | None:
    value = candidate.get("image_path")
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = run_dir / path
    if not path.is_file():
        return None
    expected = candidate.get("image_sha256")
    if expected and digest_file(path) != expected:
        return None
    return path


def _select_cover(rounds: list[tuple[dict[str, Any], list[dict[str, Any]], Path]]) -> Path | None:
    """Prefer the final selection, then the newest generated candidate."""
    for snapshot, candidates, run_dir in reversed(rounds):
        selected = snapshot.get("selected_candidate_id")
        if not selected:
            continue
        for candidate in candidates:
            if candidate.get("candidate_id") == selected:
                cover = _verified_image(candidate, run_dir)
                if cover is not None:
                    return cover
    for _, candidates, run_dir in reversed(rounds):
        for candidate in candidates:
            if candidate.get("status") != "generated":
                continue
            cover = _verified_image(candidate, run_dir)
            if cover is not None:
                return cover
    return None


def _round_snapshot(
    application: FavoriteSource,
    record: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], Path]:
    run_id = str(record.get("run_id") or "")
    summary = application.inspect_task(run_id)
    run_dir = summary.run_dir
    artifacts = summary.manifest.get("artifacts", {})
    brief = None
    if (run_dir / "brief.json").is_file():
        brief = read_json(run_dir / "brief.json")
    candidates: list[dict[str, Any]] = []
    relative = artifacts.get("candidate_index")
    if isinstance(relative, str) and (run_dir / relative).is_file():
        value = read_json(run_dir / relative)
        if isinstance(value, list):
            candidates = [item for item in value if isinstance(item, dict)]
    selected_id = None
    selection_relative = artifacts.get("selection")
    if isinstance(selection_relative, str) and (run_dir / selection_relative).is_file():
        selection = read_json(run_dir / selection_relative)
        if isinstance(selection, dict):
            selected_id = selection.get("selected_candidate_id")
    snapshot = {
        "run_id": run_id,
        "revision": record.get("revision"),
        "created_at": record.get("created_at"),
        "brief": brief if isinstance(brief, dict) else None,
        "selected_candidate_id": selected_id,
        "candidates": [_candidate_snapshot(candidate) for candidate in candidates],
    }
    return snapshot, candidates, run_dir


def capture_favorite(
    application: FavoriteSource,
    run_id: str,
    *,
    favorite_id: str | None = None,
    created_at: str | None = None,
    note: str = "",
) -> tuple[FavoriteRecord, Path | None]:
    """Freeze one conversation, its rounds and every prompt that produced them."""
    summary = application.inspect_task(run_id)
    manifest = summary.manifest
    if not manifest.get("is_conversation"):
        raise ValueError("Only a design conversation can be saved to favorites.")
    conversation = application.conversation(run_id)

    rounds = []
    round_sources = []
    for record in conversation["rounds"]:
        snapshot, candidates, run_dir = _round_snapshot(application, record)
        rounds.append(snapshot)
        round_sources.append((snapshot, candidates, run_dir))

    messages = [
        _message_snapshot(message)
        for message in conversation["messages"]
        if message.get("kind", "discussion") == "discussion"
    ]
    request = next(
        (message["text"].strip() for message in messages
         if message["role"] == "user" and message["text"].strip()),
        "",
    )
    brief = conversation.get("design_brief")
    if not isinstance(brief, dict):
        brief = next(
            (snapshot["brief"] for snapshot in reversed(rounds)
             if isinstance(snapshot["brief"], dict)),
            None,
        )
    cover = _select_cover(round_sources)
    record: FavoriteRecord = {
        "format_version": FORMAT_VERSION,
        "favorite_id": validate_favorite_id(favorite_id) if favorite_id else uuid4().hex,
        "created_at": created_at or now(),
        "updated_at": now(),
        "source_run_id": run_id,
        "source_case_id": str(manifest.get("case_id") or ""),
        "title": _one_line(manifest.get("title"), run_id),
        "note": _one_line(note),
        "content_language": conversation.get("content_language"),
        "profile": conversation["profile"],
        "models": _total(manifest.get("models")),
        "request": request or _one_line(manifest.get("title"), run_id),
        "brief": brief,
        "messages": messages,
        "rounds": rounds,
        "cover_image": COVER_NAME if cover else None,
        "cover_sha256": digest_file(cover) if cover else None,
    }
    return record, cover


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_bytes(data)
        temporary.replace(path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            LOGGER.warning("Could not remove temporary favorite image %s.", temporary)


def _summary(record: FavoriteRecord, directory: Path) -> FavoriteSummary:
    cover = directory / record["cover_image"] if record.get("cover_image") else None
    return FavoriteSummary(
        favorite_id=record["favorite_id"],
        title=record["title"],
        note=record.get("note", ""),
        created_at=record["created_at"],
        updated_at=record["updated_at"],
        source_run_id=record["source_run_id"],
        content_language=record.get("content_language"),
        round_count=len(record.get("rounds", [])),
        cover_path=cover if cover is not None and cover.is_file() else None,
    )


class FavoriteStore:
    """Scan-based storage: one directory per favorite, no shared index file."""

    def __init__(self, root: Path | str = ".atelier/favorites"):
        self.root = Path(root).resolve()

    def _load(self, path: Path) -> FavoriteRecord:
        record = read_json(path)
        if not isinstance(record, dict):
            raise ValueError("The favorite record must be an object.")
        if record.get("format_version") != FORMAT_VERSION:
            raise ValueError("Unsupported favorite format version.")
        favorite_id = validate_favorite_id(record.get("favorite_id"))
        if path.parent.name != favorite_id:
            raise ValueError("The favorite id differs from its directory.")
        for field in ("source_run_id", "title", "created_at", "updated_at"):
            if not isinstance(record.get(field), str):
                raise ValueError(f"The favorite record needs a string {field}.")
        return record

    def _records(self) -> list[tuple[Path, FavoriteRecord]]:
        if not self.root.exists():
            return []
        value = []
        for path in self.root.glob("*/favorite.json"):
            try:
                value.append((path, self._load(path)))
            except (OSError, ValueError) as exc:
                LOGGER.warning("Skipping unreadable favorite %s: %s", path, exc)
        return value

    def list(self) -> list[FavoriteSummary]:
        summaries = [_summary(record, path.parent) for path, record in self._records()]
        summaries.sort(key=lambda item: item.updated_at, reverse=True)
        return summaries

    def read(self, favorite_id: str) -> FavoriteRecord:
        path = self.root / validate_favorite_id(favorite_id) / "favorite.json"
        if not path.is_file():
            raise FileNotFoundError(f"Favorite {favorite_id!r} was not found.")
        return self._load(path)

    def find_by_source(self, run_id: str) -> FavoriteRecord | None:
        for _, record in self._records():
            if record["source_run_id"] == run_id:
                return record
        return None

    def save(self, record: FavoriteRecord, *, cover_path: Path | None = None) -> FavoriteRecord:
        favorite_id = validate_favorite_id(record["favorite_id"])
        directory = self.root / favorite_id
        directory.mkdir(parents=True, exist_ok=True)
        cover_file = directory / COVER_NAME
        if cover_path is not None:
            _write_bytes(cover_file, Path(cover_path).read_bytes())
        elif cover_file.is_file():
            cover_file.unlink()
        write_json(directory / "favorite.json", record)
        return record

    def delete(self, favorite_id: str) -> None:
        directory = (self.root / validate_favorite_id(favorite_id)).resolve()
        if directory.parent != self.root:
            raise ValueError("Favorite path escapes its store.")
        if directory.is_dir():
            shutil.rmtree(directory)
