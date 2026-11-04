"""Shared route dependencies and the one response envelope."""

from __future__ import annotations

from typing import Annotated, Callable

from fastapi import Depends, Request

from ..app.service import CorpusAtelierApplication
from . import projections
from .errors import conflict
from .runtime import TaskRuntime


def get_runtime(request: Request) -> TaskRuntime:
    return request.app.state.runtime


RuntimeDep = Annotated[TaskRuntime, Depends(get_runtime)]


def envelope(runtime: TaskRuntime, run_id: str) -> dict:
    """The one shape every task mutation returns: the task and its session."""
    summary = runtime.summary(run_id)
    session = None
    if summary.manifest.get("is_prompt_session"):
        session = projections.session_view(run_id, runtime.session(run_id))
    return {
        "task": projections.task_view(summary, running=runtime.is_running(run_id)),
        "session": session,
    }


def mutate(
    runtime: TaskRuntime,
    run_id: str,
    work: Callable[[CorpusAtelierApplication], None],
    *,
    api_key: str | None = None,
) -> dict:
    """Run one durable service call in a short-lived application."""
    app = runtime.application_for(run_id, api_key=api_key)
    try:
        work(app)
    finally:
        app.close()
    return envelope(runtime, run_id)


def schedule_task(runtime: TaskRuntime, run_id: str, api_key: str) -> None:
    """Start the pending text step; a task that is already running is a conflict."""
    scheduled = runtime.schedule(
        run_id, lambda app: app.continue_task(run_id), api_key=api_key,
    )
    if not scheduled:
        raise conflict("This task is already running.")
