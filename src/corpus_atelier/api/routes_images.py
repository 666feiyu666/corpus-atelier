"""Uploads, session media, frozen image attempts, and result selection."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field

from ..artifacts.paths import verified_image
from ..media import content_type, mask_overlay
from ..prompt_session.records import find_attempt, image_record
from .deps import RuntimeDep, envelope, mutate
from .errors import conflict, not_found
from .runtime import TaskRuntime
from .schemas import AttemptPrepare, AttemptSubmit, Upload, decode_upload


router = APIRouter(prefix="/api/v1", tags=["images"])


class UploadCreate(BaseModel):
    """One archived image; every later action refers to it by id."""

    name: str = Field(min_length=1, max_length=255)
    data_base64: str = Field(min_length=1)
    role: Literal["reference", "mask", "discussion", "source_image"] = "reference"


def _session_image(runtime: TaskRuntime, run_id: str, image_id: str) -> tuple[Path, str]:
    """Resolve one session image, refusing anything outside the run or changed."""
    summary = runtime.summary(run_id)
    session = runtime.session(run_id)
    try:
        record = image_record(session, image_id)
    except ValueError:
        raise not_found("That image does not exist in this session.") from None
    relative = record.get("path") or record.get("image_path") or ""
    try:
        path = verified_image(summary.run_dir, relative, record["sha256"])
    except (OSError, ValueError):
        raise not_found("That image is no longer available.") from None
    return path, content_type(path)


@router.post("/tasks/{run_id}/uploads", status_code=201)
def create_upload(run_id: str, body: UploadCreate, runtime: RuntimeDep) -> dict:
    image = decode_upload(Upload(name=body.name, data_base64=body.data_base64))
    return mutate(
        runtime,
        run_id,
        lambda app: app.attach_session_upload(run_id, image, role=body.role),
    )


@router.get("/tasks/{run_id}/media/{image_id}")
def read_media(run_id: str, image_id: str, runtime: RuntimeDep) -> Response:
    path, media_type = _session_image(runtime, run_id, image_id)
    return Response(
        content=path.read_bytes(),
        media_type=media_type,
        headers={"Cache-Control": "private, max-age=0, must-revalidate"},
    )


@router.get("/tasks/{run_id}/mask-preview")
def read_mask_preview(
    run_id: str,
    runtime: RuntimeDep,
    mask_id: str = Query(min_length=1),
    source_id: str = Query(min_length=1),
) -> Response:
    source, _ = _session_image(runtime, run_id, source_id)
    mask, _ = _session_image(runtime, run_id, mask_id)
    try:
        overlay = mask_overlay(source, mask)
    except Exception:
        raise conflict("The mask does not match the source image dimensions.") from None
    return Response(
        content=overlay,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=0, must-revalidate"},
    )


@router.post("/tasks/{run_id}/image-attempts", status_code=201)
def prepare_attempt(run_id: str, body: AttemptPrepare, runtime: RuntimeDep) -> dict:
    app = runtime.application_for(run_id, api_key=None)
    try:
        attempt = app.prepare_image_action(
            run_id,
            action=body.action,
            edit_instruction=body.edit_instruction,
            source_image_id=body.source_image_id,
            reference_image_ids=body.reference_image_ids,
            reference_roles=body.reference_roles,
            mask_image_id=body.mask_image_id,
            expected_revision=body.expected_revision,
        )
    finally:
        app.close()
    from . import projections

    result = envelope(runtime, run_id)
    result["attempt"] = projections.attempt_view(run_id, attempt)
    return result


def _require_submittable(
    runtime: TaskRuntime, run_id: str, attempt_id: str, expected_digest: str,
) -> dict:
    """The fast pre-check; the durable check still runs inside the service call."""
    session = runtime.session(run_id)
    try:
        attempt = find_attempt(session, attempt_id)
    except ValueError:
        raise not_found("That image request does not exist in this session.") from None
    if attempt["status"] != "prepared":
        raise conflict(
            "This image request was already submitted. Prepare a new request to try again."
        )
    if attempt["request_digest"] != expected_digest:
        raise conflict(
            "This image request changed. Review the exact request before submitting."
        )
    if attempt["prompt_revision_id"] != session.get("current_prompt_revision_id"):
        raise conflict(
            "The prompt changed after this request was prepared. Prepare the image action again."
        )
    return attempt


@router.post("/tasks/{run_id}/image-attempts/{attempt_id}/submit", status_code=202)
def submit_attempt(
    run_id: str, attempt_id: str, body: AttemptSubmit, runtime: RuntimeDep,
) -> dict:
    credential = runtime.require_credential()
    attempt = _require_submittable(runtime, run_id, attempt_id, body.expected_digest)
    scheduled = runtime.schedule(
        run_id,
        lambda app: app.submit_image_action(
            run_id, attempt["id"], expected_digest=body.expected_digest,
        ),
        api_key=credential.value,
    )
    if not scheduled:
        raise conflict("This task is already running.")
    return envelope(runtime, run_id)


@router.delete("/tasks/{run_id}/image-attempts/{attempt_id}")
def discard_attempt(run_id: str, attempt_id: str, runtime: RuntimeDep) -> dict:
    return mutate(runtime, run_id, lambda app: app.discard_image_action(run_id, attempt_id))


@router.post("/tasks/{run_id}/results/{image_id}/select")
def select_result(run_id: str, image_id: str, runtime: RuntimeDep) -> dict:
    return mutate(runtime, run_id, lambda app: app.select_prompt_result(run_id, image_id))
