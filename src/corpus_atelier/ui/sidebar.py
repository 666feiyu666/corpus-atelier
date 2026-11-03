"""The task sidebar: task rows, deletion, and settings entry."""

from __future__ import annotations

import logging
import streamlit as st
from corpus_atelier import __version__
from corpus_atelier.app.service import (
    RECOVERABLE_TASK_STATUSES,
    CorpusAtelierApplication,
)
from corpus_atelier.app.state import RunSummary

from corpus_atelier.config.paths import resolve_paths
from corpus_atelier.ui.session import (
    _current_credential,
    _ensure_recoverable_tasks,
    _one_line,
    _saved_tasks,
    _select_task,
    _status_label,
    _t,
    _task_icon,
    _task_is_live,
    _task_row_title,
    _task_supervisor,
)
from corpus_atelier.ui.settings_dialog import _show_settings_dialog
from corpus_atelier.ui.task_view import _render_task

LOGGER = logging.getLogger(__name__)


def _delete_task(task: RunSummary) -> None:
    """Permanently delete one task, then leave its workspace."""
    app = CorpusAtelierApplication(runs_root=resolve_paths().tasks_root)
    try:
        app.delete_task(task.run_id)
    except Exception:
        LOGGER.exception("Could not delete task %s.", task.run_id)
        st.error(_t("delete_failed"), icon=":material/error:")
        return
    finally:
        app.close()
    if st.session_state.selected_task_id == task.run_id:
        _select_task(None)
    st.toast(_t("task_deleted"), icon=":material/delete:")
    st.rerun(scope="app")


def _render_task_buttons(tasks: list[RunSummary]) -> None:
    st.caption(_t("tasks_count", count=len(tasks)))
    if not tasks:
        st.caption(_t("no_saved_tasks"))
        st.caption(_t("tasks_empty_hint"))
        return

    active_ids = sorted(_task_supervisor().running_ids())
    if active_ids:
        selectors = ",\n".join(
            f'.st-key-task_{run_id} [data-testid="stIconMaterial"]'
            for run_id in active_ids
        )
        st.html(f"""
            <style>
            @keyframes corpus-atelier-task-spin {{
                to {{ transform: rotate(360deg); }}
            }}
            {selectors} {{
                animation: corpus-atelier-task-spin 0.9s linear infinite;
                display: inline-block;
            }}
            </style>
        """)

    with st.container(height=520, gap="small"):
        current_day: str | None = None
        for task in tasks:
            title = task.manifest.get("title", task.run_id)
            day = str(
                task.manifest.get("updated_at")
                or task.manifest.get("created_at")
                or ""
            )[:10]
            if day != current_day:
                current_day = day
                st.caption(day or _t("not_recorded"))
            paused = (
                task.status in RECOVERABLE_TASK_STATUSES
                and not _task_supervisor().is_running(task.run_id)
                and _current_credential() is None
            )
            columns = st.columns([5, 1], vertical_alignment="center")
            with columns[0]:
                if st.button(
                    _task_row_title(task),
                    icon=_task_icon(task),
                    width="stretch",
                    key=f"task_{task.run_id}",
                    help=f"{_one_line(title)}\n\n" + (
                        _t("recovery_waiting_for_key")
                        if paused else _status_label(task.status)
                    ),
                ):
                    _select_task(task.run_id)
                    st.rerun(scope="app")
            with columns[1]:
                with st.popover("⋯", key=f"task_menu_{task.run_id}"):
                    st.caption(_t("delete_task_confirm"))
                    if st.button(
                        _t("delete_task_yes"),
                        icon=":material/delete:",
                        key=f"delete_{task.run_id}",
                        width="stretch",
                        disabled=_task_supervisor().is_running(task.run_id),
                    ):
                        _delete_task(task)


@st.fragment(run_every="1s")
def _render_live_task_buttons() -> None:
    tasks = _saved_tasks()
    _ensure_recoverable_tasks(tasks)
    _render_task_buttons(tasks)
    if not any(_task_is_live(task) for task in tasks):
        st.rerun(scope="app")


def _render_sidebar(tasks: list[RunSummary]) -> None:
    with st.sidebar:
        st.html("""
            <style>
            [data-testid="stSidebarContent"] {
                display: flex;
                flex-direction: column;
                min-height: 100vh;
            }
            [data-testid="stSidebarUserContent"] {
                display: flex;
                flex: 1;
                flex-direction: column;
            }
            [data-testid="stSidebarUserContent"] > div,
            [data-testid="stSidebarUserContent"] > div > [data-testid="stVerticalBlock"] {
                display: flex;
                flex: 1;
                flex-direction: column;
            }
            [data-testid="stSidebarUserContent"]
            [data-testid="stVerticalBlock"]
            > [data-testid="stLayoutWrapper"]:has(.st-key-sidebar_footer) {
                margin-top: auto;
                position: sticky;
                bottom: 0;
                z-index: 2;
                padding-top: 0.75rem;
                background: var(--background-color);
            }
            </style>
        """)
        st.title(_t("product_name"))
        if st.button(
            _t("new_task"),
            type="primary",
            icon=":material/add:",
            width="stretch",
            key="new_task",
            disabled=(
                st.session_state.selected_task_id is None
                and st.session_state.product_view == "studio"
            ),
        ):
            _select_task(None)
            st.rerun()

        if any(_task_is_live(task) for task in tasks):
            _render_live_task_buttons()
        else:
            _render_task_buttons(tasks)

        with st.container(key="sidebar_footer"):
            open_settings = st.button(
                _t("settings"),
                icon=":material/settings:",
                width="stretch",
                key="open_settings",
            )
            st.caption(f"v{__version__}")
        if open_settings:
            st.session_state.settings_dialog_open = True
    if st.session_state.settings_dialog_open:
        _show_settings_dialog()


@st.fragment(run_every="1s")
def _render_live_task(run_id: str) -> None:
    tasks = _saved_tasks()
    summary = next(
        (task for task in tasks if task.run_id == run_id),
        None,
    )
    if summary is None:
        st.rerun(scope="app")
        return
    _ensure_recoverable_tasks(tasks)
    _render_task(summary)
    if not _task_is_live(summary):
        st.rerun(scope="app")
