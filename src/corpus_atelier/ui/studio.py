"""Streamlit entry point: state bootstrap, product navigation, and both views."""

from __future__ import annotations

import logging
import streamlit as st
from corpus_atelier.ui.i18n import translate
from corpus_atelier.config.settings import load_preferences

from corpus_atelier.config.paths import resolve_paths
from corpus_atelier.ui.nav import _render_nav
from corpus_atelier.ui.session import (
    _delete_task,
    _display_title,
    _ensure_recoverable_tasks,
    _initialize_state,
    _saved_tasks,
    _select_task,
    _status_label,
    _sync_product_view_tabs,
    _t,
    _task_is_live,
)
from corpus_atelier.ui.sidebar import _render_sidebar
from corpus_atelier.ui.gallery import _render_gallery
from corpus_atelier.ui.prompt_start import _render_prompt_start
from corpus_atelier.ui.prompt_studio import (
    _render_live_prompt_session,
    _render_prompt_session,
)

LOGGER = logging.getLogger(__name__)

# A running image request keeps the page in its live fragment even though it is
# not a recoverable text step: the fragment stops refreshing once it settles.
LIVE_IMAGE_STATUSES = frozenset({"generating_image", "extracting"})


def _render_studio() -> None:
    """The start screen: one prompt entry and one image-to-prompt entry."""
    st.title(_t("studio_title"))
    st.caption(_t("product_tagline"))
    _render_prompt_start()


def _render_retired_task(summary) -> None:
    """A task saved by the retired staged workflow stays readable, never resumable."""
    st.header(_display_title(summary.manifest.get("title", summary.run_id), limit=48))
    st.badge(_status_label(summary.status), icon=":material/history:", color="gray")
    st.info(_t("retired_task_notice"), icon=":material/history_toggle_off:")
    st.caption(_t("retired_task_delete_hint"))
    if st.button(
        _t("delete_task_yes"),
        icon=":material/delete:",
        key=f"delete_retired_{summary.run_id}",
    ):
        _delete_task(summary)


def _render_selected_task(summary) -> None:
    if not summary.manifest.get("is_prompt_session"):
        _render_retired_task(summary)
    elif _task_is_live(summary) or summary.status in LIVE_IMAGE_STATUSES:
        _render_live_prompt_session(summary.run_id)
    else:
        _render_prompt_session(summary)


def main() -> None:
    preferred_language = load_preferences(resolve_paths().preferences_path)["language"]
    st.set_page_config(
        page_title=translate(preferred_language, "product_name"),
        page_icon=":material/palette:",
        layout="wide",
        # "auto" keeps the task list expanded on desktop and collapsed on phones.
        initial_sidebar_state="auto",
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
    view = _render_nav()
    if view == "gallery":
        _render_gallery()
        return
    if selected is None:
        _render_studio()
        return
    _render_selected_task(next(task for task in tasks if task.run_id == selected))


main()
