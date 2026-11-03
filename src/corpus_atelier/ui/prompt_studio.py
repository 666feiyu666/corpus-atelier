"""The prompt-centered studio: one entry point and one conversation workspace.

Streamlit only renders durable state and sends explicit user actions. Prompt
revisions, image roles, and provider payloads are decided by the application.
"""

from __future__ import annotations

import streamlit as st

from corpus_atelier.app.state import RunSummary
from corpus_atelier.ui.prompt_chat import _render_prompt_conversation
from corpus_atelier.ui.prompt_editor import (
    _render_prompt_editor,
    _render_revision_history,
    _render_session_images,
)
from corpus_atelier.ui.prompt_images import (
    _render_archive_control,
    _render_image_actions,
    _render_results,
)
from corpus_atelier.ui.session import (
    _app_for_manifest,
    _display_title,
    _saved_tasks,
    _status_label,
    _t,
    _task_is_live,
    _task_supervisor,
)

BUSY_STATUSES = frozenset({"extracting", "discussing_request", "generating_image"})


def _status_badge(status: str) -> None:
    paused = status in BUSY_STATUSES and not _task_supervisor().is_running(
        st.session_state.get("prompt_status_run_id"),
    )
    st.badge(
        _status_label(status),
        icon={
            "prompt_ready": ":material/check_circle:",
            "outcome_unknown": ":material/help:",
            "failed": ":material/error:",
        }.get(status, ":material/progress_activity:"),
        color=(
            "red" if status == "failed"
            else "orange" if status in BUSY_STATUSES or status == "outcome_unknown"
            else "green"
        ),
    )
    if paused:
        st.caption(_t("prompt_status_waiting"))


def _render_prompt_session(summary: RunSummary, *, embedded: bool = False) -> None:
    """Render one prompt session: prompt workspace on the left, chat on the right."""
    st.session_state["prompt_status_run_id"] = summary.run_id
    running = _task_supervisor().is_running(summary.run_id)
    try:
        with _app_for_manifest(summary.manifest) as app:
            if (
                app.inspect_task(summary.run_id).status == "generating_image" and not running
            ):
                app.reconcile_prompt_session(summary.run_id)
            session = app.prompt_session(summary.run_id)
            summary = app.inspect_task(summary.run_id)
    except Exception as exc:
        _prompt_error(exc)
        return
    pending = session.get("pending_turn")
    busy = running or pending is not None or summary.status in BUSY_STATUSES
    with st.container(horizontal=True, vertical_alignment="center"):
        if not embedded:
            st.header(_display_title(summary.manifest.get("title", summary.run_id), limit=52))
        _status_badge(summary.status)
    st.caption(_t("prompt_session_hint"))
    if summary.status == "outcome_unknown":
        st.warning(_t("outcome_unknown_notice"), icon=":material/help:")
    prompt_column, chat_column = st.columns([1.5, 1], gap="large", vertical_alignment="top")
    with prompt_column:
        _render_prompt_editor(summary, session, busy=busy)
        _render_session_images(summary, session)
        _render_revision_history(summary, session, busy=busy)
        _render_image_actions(summary, session, busy=busy)
        _render_results(summary, session, busy=busy)
        _render_archive_control(summary, session)
    with chat_column:
        _render_prompt_conversation(summary, session, busy=busy)


def _render_live_prompt_session(run_id: str) -> None:
    summary = next((task for task in _saved_tasks() if task.run_id == run_id), None)
    if summary is None:
        st.rerun(scope="app")
        return
    _render_prompt_session(summary)
    if not _task_is_live(summary):
        st.rerun(scope="app")
