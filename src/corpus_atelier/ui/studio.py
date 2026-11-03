"""Streamlit entry point: state bootstrap, product tabs, and the studio page."""

from __future__ import annotations

import logging
import streamlit as st
from corpus_atelier.ui.i18n import translate
from corpus_atelier.config.models import (
    IMAGE_MODEL_PROFILES,
    IMAGE_QUALITIES,
    TEXT_MODEL_PROFILES,
    get_image_model_profile,
    get_text_model_profile,
)
from corpus_atelier.config.settings import load_preferences
from corpus_atelier.app.service import CorpusAtelierApplication, FastPathUnavailable
from corpus_atelier.app.state import NaturalLanguageDesignJob, RunSummary

from corpus_atelier.config.paths import resolve_paths
from corpus_atelier.ui.viewport import register_viewport
from corpus_atelier.ui.session import (
    DEFAULT_CANDIDATE_LIMIT,
    DEFAULT_GENERATION_MODE,
    DEFAULT_PROFILE,
    PRODUCT_CASE_ID,
    _application,
    _current_credential,
    _ensure_recoverable_tasks,
    _image_model_label,
    _initialize_state,
    _saved_tasks,
    _select_task,
    _submission_attachments,
    _submission_text,
    _submit_saved_task,
    _sync_product_view_tabs,
    _t,
    _task_is_live,
    _text_model_label,
)
from corpus_atelier.ui.sidebar import _render_live_task, _render_sidebar
from corpus_atelier.ui.task_view import _render_task
from corpus_atelier.ui.gallery import _render_gallery

LOGGER = logging.getLogger(__name__)


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


def _render_new_task_settings() -> tuple[str, str, str, str, bool]:
    model_ids = [profile.model for profile in TEXT_MODEL_PROFILES]
    model = st.selectbox(
        _t("text_model"),
        model_ids,
        format_func=_text_model_label,
        key="new_task_model",
    )
    profile = get_text_model_profile(model)
    if st.session_state.new_task_reasoning not in profile.reasoning_efforts:
        st.session_state.new_task_reasoning = profile.default_reasoning_effort
    reasoning = st.segmented_control(
        _t("reasoning_effort"),
        list(profile.reasoning_efforts),
        key="new_task_reasoning",
    )
    image_model = st.selectbox(
        _t("image_model"),
        [profile.model for profile in IMAGE_MODEL_PROFILES],
        format_func=_image_model_label,
        key="new_task_image_model",
    )
    image_profile = get_image_model_profile(image_model)
    qualities = [
        quality for quality in IMAGE_QUALITIES
        if quality not in {"xhigh", "max"} or image_profile.supports_max_quality
    ]
    if st.session_state.get("new_task_quality") not in qualities:
        st.session_state.new_task_quality = "medium"
    image_quality = st.segmented_control(
        _t("image_quality"),
        qualities,
        key="new_task_quality",
    )
    fast_path = st.toggle(
        _t("fast_path_toggle"),
        value=True,
        key="new_task_fast_path",
        help=_t("fast_path_help"),
    )
    return model, reasoning, image_model, image_quality, fast_path


def _start_task(
    request: str,
    *,
    model: str,
    reasoning_effort: str,
    image_model: str,
    image_quality: str,
    fast_path: bool = False,
    attachments: list[tuple[str, bytes]] | None = None,
    reference_images: list[tuple[str, bytes]] | None = None,
    mask: tuple[str, bytes] | None = None,
) -> None:
    if not request.strip():
        st.error(_t("request_required"))
        return
    credential = _current_credential()
    if credential is None:
        st.error(_t("api_key_missing"), icon=":material/key_off:")
        return
    app = _application(
        model,
        reasoning_effort,
        image_model,
        image_quality,
        api_key=credential.value,
    )
    summary: RunSummary | None = None
    try:
        job = NaturalLanguageDesignJob(
            case_id=PRODUCT_CASE_ID,
            profile=DEFAULT_PROFILE,
            request=request,
            candidate_count=DEFAULT_CANDIDATE_LIMIT,
            generation_mode=DEFAULT_GENERATION_MODE,
            reference_images=tuple(reference_images or ()),
            mask=mask,
        )
        result = app.create_conversation(job, attachments=attachments)
        if fast_path:
            summary = _start_fast_round(app, result.run_id)
        else:
            with st.spinner(_t("drafting_brief")):
                try:
                    app.draft_brief(result.run_id)
                except Exception:
                    LOGGER.warning(
                        "Draft brief failed for %s; the user can still fill it in.",
                        result.run_id, exc_info=True,
                    )
            summary = app.inspect_task(result.run_id)
    except Exception:
        st.error(_t("create_failed"), icon=":material/error:")
    finally:
        app.close()
    if summary is not None:
        _submit_saved_task(summary, credential.value)
        _select_task(summary.run_id)
        st.rerun()


def _start_fast_round(app: CorpusAtelierApplication, run_id: str) -> RunSummary:
    """Draft, confirm, and start one round in a single step.

    Anything that still needs a decision — a direction exploration, an open
    question, a missing language — raises FastPathUnavailable, and the ordinary
    review flow resumes with the reason shown on the task page.
    """
    with st.spinner(_t("fast_path_working")):
        try:
            app.continue_task(run_id)
            app.draft_brief(run_id)
            round_result = app.start_fast_round(run_id)
        except FastPathUnavailable as exc:
            LOGGER.info("Fast path kept the review flow for %s (%s).", run_id, exc.reason)
            st.session_state["fast_path_notice"] = exc.reason
            return app.inspect_task(run_id)
        except Exception:
            LOGGER.warning(
                "Fast path failed for %s; the review flow resumes.", run_id, exc_info=True,
            )
            st.session_state["fast_path_notice"] = "failed"
            return app.inspect_task(run_id)
    return app.inspect_task(round_result.run_id)


def _render_studio() -> None:
    st.title(_t("product_name"))
    st.caption(_t("product_tagline"))
    st.subheader(_t("start_from_request"))
    st.caption(_t("reference_upload_hint"))
    with st.popover(_t("task_settings"), icon=":material/tune:"):
        (
            model, reasoning, image_model, image_quality, fast_path,
        ) = _render_new_task_settings()
        st.divider()
        st.caption(_t("generation_inputs_hint"))
        reference_files = st.file_uploader(
            _t("reference_images_label"),
            type=["png", "jpg", "jpeg", "webp"],
            accept_multiple_files=True,
            key="new_task_references",
        )
        mask_file = st.file_uploader(
            _t("mask_label"),
            type=["png"],
            key="new_task_mask",
        )
    submission = st.chat_input(
        _t("request_placeholder"),
        key="new_task_prompt",
        submit_mode="disable",
        accept_file="multiple",
        file_type=["png", "jpg", "jpeg", "webp"],
        max_upload_size=10,
    )
    if submission:
        references = [
            (upload.name, upload.getvalue()) for upload in reference_files or []
        ]
        mask = (
            (mask_file.name, mask_file.getvalue()) if mask_file is not None else None
        )
        try:
            _start_task(
                _submission_text(submission) or _t("reference_only_request"),
                model=model,
                reasoning_effort=reasoning,
                image_model=image_model,
                image_quality=image_quality,
                fast_path=fast_path,
                attachments=_submission_attachments(submission),
                reference_images=references,
                mask=mask,
            )
        except ValueError as exc:
            st.error(str(exc), icon=":material/error:")


def main() -> None:
    register_viewport()
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
    if summary.manifest.get("is_conversation") or _task_is_live(summary):
        _render_live_task(summary.run_id)
    else:
        _render_task(summary)


main()
