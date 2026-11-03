"""Streamlit entry point: state bootstrap, product tabs, and the studio page."""

from __future__ import annotations

import logging
import streamlit as st
from corpus_atelier.ui.i18n import translate
from corpus_atelier.config.settings import load_preferences

from corpus_atelier.config.paths import resolve_paths
from corpus_atelier.ui.session import (
    _ensure_recoverable_tasks,
    _initialize_state,
    _saved_tasks,
    _select_task,
    _sync_product_view_tabs,
    _t,
    _task_is_live,
)
from corpus_atelier.ui.sidebar import _render_live_task, _render_sidebar
from corpus_atelier.ui.task_view import _render_task
from corpus_atelier.ui.gallery import _render_gallery
from corpus_atelier.ui.prompt_studio import (
    _render_live_prompt_session,
    _render_prompt_session,
    _render_prompt_start,
)

LOGGER = logging.getLogger(__name__)

# A running image request keeps the page in its live fragment even though it is
# not a recoverable text step: the fragment stops refreshing once it settles.
LIVE_IMAGE_STATUSES = frozenset({"generating_image", "extracting"})


def _render_product_tabs() -> str:
    """Top-level product navigation: chat studio and corpus gallery."""
    view = st.segmented_control(
        _t("view_switch"),
        ["studio", "gallery"],
        format_func=lambda value: _t(f"view_{value}"),
        key="product_view_tabs",
        persist_state="session",
        required=True,
        label_visibility="collapsed",
        width="stretch",
    ) or "studio"
    st.session_state.product_view = view
    return view


def _render_studio() -> None:
    """The start screen: one prompt entry and one image-to-prompt entry."""
    st.title(_t("product_name"))
    st.caption(_t("product_tagline"))
    _render_prompt_start()


def main() -> None:
    preferred_language = load_preferences(resolve_paths().preferences_path)["language"]
    st.set_page_config(
        page_title=translate(preferred_language, "product_name"),
        page_icon=":material/palette:",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    _initialize_state()
    _sync_product_view_tabs()
    settings_notice = st.session_state.pop("settings_notice", None)
    if settings_notice:
        st.toast(settings_notice, icon=":material/check_circle:")
    tasks = _saved_tasks()
    _ensure_recoverable_tasks(tasks)
    known_ids = {task.run_id for task in tasks}
    selected = st.session_state.selected_task_id
    if selected is not None and selected not in known_ids:
        _select_task(None)
        selected = None

    _render_sidebar(tasks)
    if selected is None:
        view = _render_product_tabs()
        if view == "gallery":
            _render_gallery()
        else:
            _render_studio()
        return

    summary = next(task for task in tasks if task.run_id == selected)
    if summary.manifest.get("is_prompt_session"):
        if _task_is_live(summary) or summary.status in LIVE_IMAGE_STATUSES:
            _render_live_prompt_session(summary.run_id)
        else:
            _render_prompt_session(summary)
    elif _task_is_live(summary):
        _render_live_task(summary.run_id)
    else:
        _render_task(summary)


main()
