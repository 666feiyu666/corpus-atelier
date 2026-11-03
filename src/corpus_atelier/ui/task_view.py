"""One task's workspace: approval, archive, and design panels."""

from __future__ import annotations

from pathlib import Path
import streamlit as st
from corpus_atelier.app.service import RECOVERABLE_TASK_STATUSES
from corpus_atelier.corpus import FACETS, resolve, tags_of
from corpus_atelier.corpus.ingest import ingest_run
from corpus_atelier.app.state import HumanDecision, RunResult, RunSummary

from corpus_atelier.config.paths import resolve_paths
from corpus_atelier.ui.session import (
    _app_for_manifest,
    _corpus_store,
    _current_credential,
    _display_title,
    _image_model_label,
    _model_settings,
    _result_message,
    _resume,
    _status_label,
    _status_state,
    _submit_saved_task,
    _t,
    _task_icon,
    _task_is_live,
    _task_supervisor,
    _text_model_label,
)
from corpus_atelier.ui.candidates import (
    _ready_candidates,
    _render_design_details,
    _render_generation_preview,
    _render_generation_receipt,
    _render_image_gallery,
    _selected_candidate_id,
    read_json_artifact,
)


def _archive_to_corpus(summary: RunSummary, tags: list[str]) -> None:
    store = _corpus_store()
    try:
        ingest_run(
            store,
            summary.run_dir,
            tags=tags,
            media_root=resolve_paths().corpus_media_root,
        )
    finally:
        store.close()


def _render_archive_control(summary: RunSummary) -> None:
    with st.popover(_t("archive_to_corpus"), icon=":material/bookmark_add:"):
        tag_options = [tag.id for facet in FACETS for tag in tags_of(facet)]
        tags = st.multiselect(
            _t("corpus_tags_label"),
            tag_options,
            key=f"archive_tags_{summary.run_id}",
            format_func=lambda tag_id: resolve(tag_id).zh,
        )
        if st.button(
            _t("archive_confirm"),
            key=f"archive_confirm_{summary.run_id}",
            disabled=not tags,
        ):
            try:
                _archive_to_corpus(summary, tags)
            except Exception:
                st.error(_t("archive_failed"), icon=":material/error:")
            else:
                st.toast(_t("corpus_archived"), icon=":material/check_circle:")


def _tag_label(tag_id: str) -> str:
    try:
        return resolve(tag_id).zh
    except ValueError:
        return tag_id


def _render_corpus_references(result: RunResult) -> None:
    """Show the archived cases the direction stage leaned on, with their images."""
    plan = read_json_artifact(result, "direction_plan")
    if not isinstance(plan, dict):
        return
    references = plan.get("corpus_references") or []
    if not references:
        return
    images = plan.get("corpus_reference_images") or []
    with st.expander(_t("corpus_references_title", count=len(references))):
        for index, reference in enumerate(references):
            left, right = st.columns([1, 3], vertical_alignment="top")
            with left:
                relative = images[index] if index < len(images) else None
                path = resolve_paths().corpus_media_root / relative if relative else None
                if path is not None and path.is_file():
                    st.image(str(path), width="stretch", output_format="PNG")
            with right:
                st.markdown(f"**{reference.get('note') or reference['id']}**")
                tags = reference.get("tags") or []
                if tags:
                    st.caption(" · ".join(_tag_label(tag_id) for tag_id in tags))
                url = reference.get("url")
                if url:
                    st.caption(url)
                st.code(reference.get("prompt") or "", language=None, wrap_lines=True)


def _render_approval(
    summary: RunSummary,
    result: RunResult,
    *,
    active: bool,
) -> None:
    st.info(
        _t("approval_notice"),
        icon=":material/approval:",
    )
    _render_corpus_references(result)
    overrides = _render_generation_preview(result, editable=True, active=active)
    ready_count = len(_ready_candidates(result))
    with st.container(horizontal=True, horizontal_alignment="right"):
        if st.button(
            _t("cancel_generation"),
            icon=":material/close:",
            key=f"cancel_{result.run_id}",
            disabled=active,
        ):
            _resume(
                summary,
                HumanDecision(False, reviewer="streamlit-user"),
            )
        if st.button(
            _t("confirm_generate", count=ready_count),
            type="primary",
            icon=":material/image:",
            key=f"approve_{result.run_id}",
            disabled=active,
        ):
            _resume(
                summary,
                HumanDecision(
                    True, reviewer="streamlit-user",
                    prompt_overrides=overrides or None,
                ),
            )


def _render_task(summary: RunSummary, *, embedded: bool = False, actions_allowed: bool = True) -> None:
    manifest = summary.manifest
    running = _task_supervisor().is_running(summary.run_id)
    active = running or not actions_allowed
    recovery_paused = (
        summary.status in RECOVERABLE_TASK_STATUSES and not running
    )
    try:
        app = _app_for_manifest(manifest)
        try:
            result = app.open_task(summary.run_id)
        finally:
            app.close()
    except Exception as exc:
        st.error(_t("open_task_failed"), icon=":material/error:")
        return

    with st.container(horizontal=True, vertical_alignment="center"):
        if not embedded:
            st.header(_display_title(manifest.get("title", summary.run_id), limit=52))
        st.badge(
            (
                _t("recovery_paused")
                if recovery_paused else _status_label(result.status)
            ),
            icon=(
                ":material/pause_circle:"
                if recovery_paused else _task_icon(summary)
            ),
            color=(
                "green" if result.status == "completed"
                else "red" if result.status == "failed"
                else "orange" if (
                    result.status.startswith("awaiting_") or recovery_paused
                )
                else "gray"
            ),
        )

    model, effort, image_model, _ = _model_settings(manifest)
    st.caption(
        _t("meta_separator").join([
            _text_model_label(model),
            _t("image_model_meta", value=_image_model_label(image_model)),
            f"{_t('reasoning_effort')} {effort}",
            _t(
                "updated_at",
                value=manifest.get(
                    "updated_at",
                    manifest.get("created_at", _t("not_recorded")),
                ),
            ),
        ])
    )

    request_path = result.artifacts.get("user_request")
    if request_path and not embedded:
        with st.chat_message("user"):
            st.markdown(Path(request_path).read_text(encoding="utf-8"))

    with st.chat_message("assistant"):
        if recovery_paused:
            st.warning(
                _t("recovery_waiting_for_key"),
                icon=":material/pause_circle:",
            )
        else:
            task_status = st.status(
                _status_label(result.status),
                state=(
                    "running" if running else _status_state(result.status)
                ),
                type="compact",
                expanded=False,
            )
            task_status.caption(_result_message(result))

        if result.status == "awaiting_approval":
            _render_approval(summary, result, active=active)
        elif result.status == "awaiting_selection":
            _render_image_gallery(
                summary,
                result,
                selectable=True,
                active=active,
            )
            _render_generation_receipt(result)
        elif result.status == "completed":
            if _selected_candidate_id(result) is None:
                st.info(_t("completed_without_selection"))
            _render_image_gallery(summary, result, selectable=False)
            _render_generation_receipt(result)
            _render_archive_control(summary)
        elif result.status == "rejected":
            st.warning(_t("generation_canceled"))
        elif result.status == "failed":
            st.error(_t("task_failed"))

        if result.status != "awaiting_approval":
            _render_design_details(result)
