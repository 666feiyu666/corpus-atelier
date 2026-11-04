"""Task lifecycle, prompt revisions, and conversation turns."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Response

from . import projections
from .deps import RuntimeDep, envelope, mutate, schedule_task
from .errors import conflict, invalid, provider_failed
from .runtime import ModelSelection
from .schemas import (
    CanvasUpdate,
    MessageCreate,
    PromptProposalCreate,
    PromptRestore,
    PromptRevisionCreate,
    ProposalAdopt,
    RefineCreate,
    TaskCreate,
    decode_upload,
)


PRODUCT_CASE_ID = "natural-language"

LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["tasks"])


@router.get("/tasks")
def list_tasks(runtime: RuntimeDep, status: str | None = None) -> dict:
    running = runtime.running_ids()
    tasks = runtime.list_tasks()
    if status:
        tasks = [task for task in tasks if task.status == status]
    return {
        "tasks": [
            projections.task_view(task, running=task.run_id in running) for task in tasks
        ]
    }


@router.post("/tasks", status_code=201)
def create_task(body: TaskCreate, runtime: RuntimeDep) -> dict:
    selection = ModelSelection.default().merged(body.models)
    needs_provider = body.entry_mode == "image" or body.submit_generate
    credential = runtime.require_credential() if needs_provider else runtime.credential()
    api_key = credential.value if credential else None
    app = runtime.application(selection, api_key=api_key)
    try:
        if body.entry_mode == "prompt":
            result = app.start_from_prompt(
                body.prompt_text or "",
                case_id=PRODUCT_CASE_ID,
                settings=body.settings,
                references=[decode_upload(item) for item in body.references],
            )
            run_id = result.run_id
            if body.submit_generate:
                session = app.prompt_session(run_id)
                attempt: dict | None = app.prepare_image_action(
                    run_id,
                    action="generate",
                    reference_image_ids=[item["id"] for item in session["uploads"]],
                    expected_revision=session["current_prompt_revision_id"],
                )
            else:
                attempt = None
        else:
            if body.image is None:  # guarded by TaskCreate, kept for type checkers
                raise invalid("An image is required to start from an image.")
            result = app.start_from_image(
                decode_upload(body.image), case_id=PRODUCT_CASE_ID, settings=body.settings,
            )
            run_id = result.run_id
            attempt = None
    finally:
        app.close()

    if attempt is not None:
        runtime.schedule(
            run_id,
            lambda app, attempt=attempt: app.submit_image_action(
                run_id, attempt["id"], expected_digest=attempt["request_digest"],
            ),
            api_key=api_key or "",
        )
    elif body.entry_mode == "image":
        schedule_task(runtime, run_id, api_key or "")
    return envelope(runtime, run_id)


@router.get("/tasks/{run_id}")
def get_task(run_id: str, runtime: RuntimeDep) -> dict:
    runtime.reconcile(run_id)
    return envelope(runtime, run_id)


@router.delete("/tasks/{run_id}", status_code=204)
def delete_task(run_id: str, runtime: RuntimeDep) -> Response:
    if runtime.is_running(run_id):
        raise conflict("This task is running; wait for it to finish before deleting it.")
    app = runtime.application_for(run_id, api_key=None)
    try:
        app.delete_task(run_id)
    finally:
        app.close()
    return Response(status_code=204)


# --- prompt revisions and proposals ------------------------------------


@router.post("/tasks/{run_id}/prompt-revisions")
def create_prompt_revision(
    run_id: str, body: PromptRevisionCreate, runtime: RuntimeDep,
) -> dict:
    return mutate(
        runtime,
        run_id,
        lambda app: app.edit_session_prompt(
            run_id, body.prompt_text, expected_revision=body.expected_revision,
        ),
    )


@router.post("/tasks/{run_id}/prompt-revisions/{revision_id}/restore")
def restore_prompt_revision(
    run_id: str, revision_id: str, body: PromptRestore, runtime: RuntimeDep,
) -> dict:
    return mutate(
        runtime,
        run_id,
        lambda app: app.restore_session_revision(
            run_id, revision_id, expected_revision=body.expected_revision,
        ),
    )


@router.post("/tasks/{run_id}/prompt-proposals", status_code=201)
def create_prompt_proposal(
    run_id: str, body: PromptProposalCreate, runtime: RuntimeDep,
) -> dict:
    credential = runtime.require_credential()
    app = runtime.application_for(run_id, api_key=credential.value)
    try:
        try:
            proposal = app.prepare_prompt_proposal(
                run_id, body.kind, edit_instruction=body.edit_instruction,
            )
        except ValueError:
            raise
        except Exception:
            LOGGER.exception("Prompt proposal failed for task %s.", run_id)
            raise provider_failed("The text model did not return a usable proposal.") from None
    finally:
        app.close()
    result = envelope(runtime, run_id)
    result["proposal"] = projections.proposal_view(proposal)
    return result


@router.post("/tasks/{run_id}/prompt-proposals/{proposal_id}/adopt")
def adopt_prompt_proposal(
    run_id: str, proposal_id: str, body: ProposalAdopt, runtime: RuntimeDep,
) -> dict:
    return mutate(
        runtime,
        run_id,
        lambda app: app.adopt_prompt_proposal(
            run_id, proposal_id, expected_revision=body.expected_revision,
        ),
    )


@router.post("/tasks/{run_id}/canvas")
def update_canvas(run_id: str, body: CanvasUpdate, runtime: RuntimeDep) -> dict:
    ratio = tuple(body.ratio) if body.ratio is not None else None
    return mutate(runtime, run_id, lambda app: app.set_session_canvas(run_id, ratio))


# --- conversation ------------------------------------------------------


@router.post("/tasks/{run_id}/messages", status_code=202)
def create_message(run_id: str, body: MessageCreate, runtime: RuntimeDep) -> dict:
    credential = runtime.require_credential()
    if runtime.is_running(run_id):
        raise conflict("This task is already running.")
    attachments = [decode_upload(item) for item in body.attachments]
    result = mutate(
        runtime,
        run_id,
        lambda app: app.queue_session_message(run_id, body.text, attachments=attachments),
        api_key=credential.value,
    )
    schedule_task(runtime, run_id, credential.value)
    return result


@router.post("/tasks/{run_id}/continue", status_code=202)
def continue_task(run_id: str, runtime: RuntimeDep) -> dict:
    credential = runtime.require_credential()
    summary = runtime.summary(run_id)
    if not summary.manifest.get("is_prompt_session"):
        raise invalid("This task does not use the prompt-centered workflow.")
    schedule_task(runtime, run_id, credential.value)
    return envelope(runtime, run_id)


@router.post("/tasks/{run_id}/refine-turns", status_code=202)
def create_refine_turn(run_id: str, body: RefineCreate, runtime: RuntimeDep) -> dict:
    credential = runtime.require_credential()
    summary = runtime.summary(run_id)
    if not summary.manifest.get("is_prompt_session"):
        raise invalid("This task does not use the prompt-centered workflow.")
    if runtime.is_running(run_id):
        raise conflict("This task is already running.")
    # Any session may compare a result with an earlier image: that is how a later
    # iteration gets its prompt. The service picks a default reference when the
    # caller names none, and refuses when there is nothing to compare against.
    result = mutate(
        runtime,
        run_id,
        lambda app: app.queue_refine_turn(
            run_id, body.result_image_id, base_image_id=body.base_image_id,
        ),
        api_key=credential.value,
    )
    schedule_task(runtime, run_id, credential.value)
    return result


@router.post("/tasks/{run_id}/reconcile")
def reconcile_task(run_id: str, runtime: RuntimeDep) -> dict:
    runtime.reconcile(run_id)
    return envelope(runtime, run_id)
