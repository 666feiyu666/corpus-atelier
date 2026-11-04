"""Projections: durable records in, browser-safe payloads out.

The rule for every function here is the same: whitelist the fields the interface
needs, drop every local path, and replace it with a route the client may call.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..app.state import RunSummary
from ..prompt_session.records import PromptSessionRecord


API_PREFIX = "/api/v1"


def task_media_url(run_id: str, image_id: str) -> str:
    return f"{API_PREFIX}/tasks/{run_id}/media/{image_id}"


def corpus_media_url(record_id: str) -> str:
    return f"{API_PREFIX}/corpus/media/{record_id}"


def task_view(summary: RunSummary, *, running: bool) -> dict[str, Any]:
    manifest = summary.manifest
    return {
        "run_id": summary.run_id,
        "case_id": manifest.get("case_id"),
        "title": manifest.get("title", summary.run_id),
        "status": summary.status,
        "created_at": manifest.get("created_at"),
        "updated_at": manifest.get("updated_at"),
        "is_prompt_session": bool(manifest.get("is_prompt_session")),
        "prompt_ready": bool(manifest.get("current_prompt_revision_id")),
        "error": manifest.get("error"),
        "error_type": manifest.get("error_type"),
        "running": running,
        "models": _models_view(manifest.get("models")),
    }


def _models_view(models: Any) -> dict[str, Any]:
    models = models if isinstance(models, dict) else {}
    text = models.get("text") if isinstance(models.get("text"), dict) else {}
    image = models.get("image") if isinstance(models.get("image"), dict) else {}
    return {
        "text": {
            "model": text.get("model"),
            "reasoning_effort": text.get("reasoning_effort"),
        },
        "image": {
            "model": image.get("model"),
            "quality": image.get("quality"),
        },
    }


def revision_view(revision: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": revision.get("id"),
        "parent_revision_id": revision.get("parent_revision_id"),
        "prompt_text": revision.get("prompt_text"),
        "origin": revision.get("origin"),
        "digest": revision.get("digest"),
        "created_at": revision.get("created_at"),
        "negative_prompt": revision.get("negative_prompt"),
        "visible_copy": revision.get("visible_copy") or [],
        "uncertainties": revision.get("uncertainties") or [],
        "note": revision.get("note"),
        "restored_from": revision.get("restored_from"),
        "source_image_id": revision.get("source_image_id"),
    }


def message_view(message: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": message.get("id"),
        "role": message.get("role"),
        "text": message.get("text") or "",
        "attachment_ids": message.get("attachment_ids") or [],
        "attachment_names": message.get("attachment_names") or [],
        "created_at": message.get("created_at"),
        "proposed_prompt": message.get("proposed_prompt"),
        "proposed_revision_id": message.get("proposed_revision_id"),
        "edit_instruction": message.get("edit_instruction"),
        "conflict": bool(message.get("conflict")),
        "discrepancies": message.get("discrepancies") or [],
        "in_reply_to": message.get("in_reply_to"),
        "turn_id": message.get("turn_id"),
    }


def upload_view(run_id: str, upload: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": upload.get("id"),
        "name": upload.get("name"),
        "role": upload.get("role"),
        "width": upload.get("width"),
        "height": upload.get("height"),
        "sha256": upload.get("sha256"),
        "created_at": upload.get("created_at"),
        "media_url": task_media_url(run_id, upload["id"]),
    }


def attempt_view(run_id: str, attempt: dict[str, Any]) -> dict[str, Any]:
    mask = attempt.get("mask") or None
    return {
        "id": attempt.get("id"),
        "action": attempt.get("action"),
        "status": attempt.get("status"),
        "request_text": attempt.get("request_text"),
        "edit_instruction": attempt.get("edit_instruction"),
        "request_digest": attempt.get("request_digest"),
        "prompt_revision_id": attempt.get("prompt_revision_id"),
        "source_image_id": attempt.get("source_image_id"),
        "reference_image_ids": attempt.get("reference_image_ids") or [],
        "reference_roles": attempt.get("reference_roles") or [],
        "mask_image_id": attempt.get("mask_image_id"),
        "settings": attempt.get("settings") or {},
        "reference_media_urls": [
            task_media_url(run_id, image_id)
            for image_id in attempt.get("reference_image_ids") or []
        ],
        "mask_media_url": task_media_url(run_id, mask["id"]) if mask else None,
        "result_image_id": attempt.get("result_image_id"),
        "created_at": attempt.get("created_at"),
        "submitted_at": attempt.get("submitted_at"),
        "error": attempt.get("error"),
        "outcome_unknown": bool(attempt.get("outcome_unknown")),
    }


def result_view(run_id: str, result: dict[str, Any], active_id: str | None) -> dict[str, Any]:
    return {
        "id": result.get("id"),
        "label": result.get("label"),
        "action": result.get("action"),
        "prompt_revision_id": result.get("prompt_revision_id"),
        "request_text": result.get("request_text"),
        "parent_image_id": result.get("parent_image_id"),
        "attempt_id": result.get("attempt_id"),
        "is_active": result.get("id") == active_id,
        "created_at": result.get("created_at"),
        "media_url": task_media_url(run_id, result["id"]),
    }


def proposal_view(proposal: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": proposal.get("id"),
        "kind": proposal.get("kind"),
        "base_revision_id": proposal.get("base_revision_id"),
        "prompt_text": proposal.get("prompt_text"),
        "notes": proposal.get("notes"),
        "adopted_revision_id": proposal.get("adopted_revision_id"),
        "created_at": proposal.get("created_at"),
    }


def pending_view(pending: dict[str, Any] | None) -> dict[str, Any] | None:
    if not pending:
        return None
    return {
        "kind": pending.get("kind"),
        "turn_id": pending.get("turn_id"),
        "created_at": pending.get("created_at"),
    }


def session_view(run_id: str, session: PromptSessionRecord) -> dict[str, Any]:
    active_id = session.get("active_image_id")
    return {
        "entry_mode": session.get("entry_mode"),
        "settings": dict(session.get("settings") or {}),
        "current_prompt_revision_id": session.get("current_prompt_revision_id"),
        "prompt_revisions": [
            revision_view(item) for item in session.get("prompt_revisions") or []
        ],
        "messages": [message_view(item) for item in session.get("messages") or []],
        "uploads": [upload_view(run_id, item) for item in session.get("uploads") or []],
        "image_attempts": [
            attempt_view(run_id, item) for item in session.get("image_attempts") or []
        ],
        "image_results": [
            result_view(run_id, item, active_id)
            for item in session.get("image_results") or []
        ],
        "prompt_proposals": [
            proposal_view(item) for item in session.get("prompt_proposals") or []
        ],
        "active_image_id": active_id,
        "pending_turn": pending_view(session.get("pending_turn")),
    }


def record_view(record: dict[str, Any]) -> dict[str, Any]:
    image = record.get("image") or None
    source = record.get("source") or {}
    return {
        "id": record.get("id"),
        "prompt": record.get("prompt"),
        "negative_prompt": record.get("negative_prompt"),
        "tags": record.get("tags") or [],
        "source": {
            "kind": source.get("kind"),
            "run_id": source.get("run_id"),
            "url": source.get("url"),
            "note": source.get("note"),
        },
        "image": (
            {
                "width": image.get("width"),
                "height": image.get("height"),
                "sha256": image.get("sha256"),
                "media_url": corpus_media_url(record["id"]),
            }
            if image
            else None
        ),
        "meta": record.get("meta") or {},
        "translations": record.get("translations") or {},
        "created_at": record.get("created_at"),
    }


def relative_media_path(record: dict[str, Any]) -> str | None:
    """The stored relative media path of one record, for the media route."""
    image = record.get("image") or {}
    path = image.get("path")
    return path if isinstance(path, str) else None


def image_relative_path(record: dict[str, Any]) -> str:
    """The stored relative path of one session image, result or upload."""
    return record.get("path") or record.get("image_path") or ""


def safe_run_file(run_dir: Path, relative: str) -> Path:
    """Resolve a task-owned file, refusing anything outside the run directory."""
    path = (run_dir / relative).resolve(strict=True)
    if run_dir not in path.parents:
        raise ValueError("The artifact is outside its task directory.")
    return path
