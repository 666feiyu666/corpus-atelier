"""One task's workspace: approval, archive, and design panels."""

from __future__ import annotations

from pathlib import Path
import streamlit as st
from corpus_atelier.app.service import RECOVERABLE_TASK_STATUSES
from corpus_atelier.conversation.service import BUSY_ROUND_STATUSES
from corpus_atelier.conversation.records import ConversationRecord
from corpus_atelier.ui import brief_editor
from corpus_atelier.ui.i18n import fast_path_notice
from corpus_atelier.ui.viewport import render_viewport, viewport_controller
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
from corpus_atelier.ui.brief_view import _render_brief
from corpus_atelier.ui.candidates import (
    _ready_candidates,
    _render_design_details,
    _render_generation_preview,
    _render_generation_receipt,
    _render_image_gallery,
    _selected_candidate_id,
    read_json_artifact,
)
from corpus_atelier.ui.dialogue import (
    _agent_brief_draft,
    _can_prepare_round,
    _conversation_error,
    _render_assistant_panel,
    _render_brief_editor,
    _render_brief_history,
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


def _render_round_picker(summary: RunSummary, conversation: ConversationRecord,
                         rounds: list[RunSummary], *, busy: bool) -> RunSummary | None:
    if not rounds:
        return None
    numbers = {round_.run_id: index for index, round_ in enumerate(rounds, 1)}
    selected_id = st.selectbox(
        _t("design_versions"), options=list(numbers), index=len(rounds) - 1,
        key=f"round_{summary.run_id}_{len(rounds)}",
        format_func=lambda run_id: _t("design_round", number=numbers[run_id]),
    )
    selected = next(round_ for round_ in rounds if round_.run_id == selected_id)
    record = next(record for record in conversation["rounds"] if record["run_id"] == selected_id)
    stale = selected_id != rounds[-1].run_id or record["revision"] != conversation["revision"]
    if stale:
        st.caption(_t("historical_round_hint"))
    _render_task(selected, embedded=True, actions_allowed=not stale and not busy)
    return selected


def _render_design_panel(summary: RunSummary, conversation: ConversationRecord,
                         rounds: list[RunSummary], *, busy: bool, design_busy: bool,
                         fast_round: bool = False) -> RunSummary | None:
    with st.container(height=700, key=f"design_panel_{summary.run_id}", autoscroll=False):
        render_viewport(summary.run_id, conversation, label=_t("return_latest_brief"), controller=viewport_controller())
        st.html('<div id="atelier-latest-brief" aria-hidden="true"></div>')
        questions = conversation["open_questions"]
        if questions:
            # Ask for one clarification at a time instead of listing every question.
            st.caption(_t("single_open_question", question=questions[0]))
            if len(questions) > 1:
                st.caption(_t("more_open_questions", count=len(questions) - 1))
        if fast_round:
            with st.expander(_t("fast_path_confirmed_brief"), expanded=False):
                st.caption(_t("fast_path_confirmed_hint"))
                dirty = _render_brief_editor(summary, conversation, disabled=design_busy)
        else:
            dirty = _render_brief_editor(summary, conversation, disabled=design_busy)
        if st.button(
            _t("prepare_design_round"), type="primary", key=f"prepare_round_{summary.run_id}",
            width="stretch",
            disabled=not _can_prepare_round(summary, conversation, busy=busy, dirty=dirty),
        ):
            try:
                with _app_for_manifest(summary.manifest) as app:
                    result = app.create_conversation_round(summary.run_id)
                    child = app.inspect_task(result.run_id)
                _submit_saved_task(child, _current_credential().value)
                st.rerun(scope="app")
            except Exception as exc:
                _conversation_error(exc)
        selected = _render_round_picker(summary, conversation, rounds, busy=busy)
        _render_brief_history(summary, conversation, disabled=busy or dirty)
        return selected


def _render_conversation_task(summary: RunSummary) -> None:
    """Arrange the workspace; each panel owns its rendering and user actions."""
    try:
        with _app_for_manifest(summary.manifest) as app:
            conversation = app.conversation(summary.run_id)
            rounds = [app.inspect_task(record["run_id"]) for record in conversation["rounds"]]
    except Exception as exc:
        _conversation_error(exc)
        return
    st.subheader(_display_title(summary.manifest.get("title", summary.run_id), limit=44))
    st.caption(_t("conversation_hint"))
    notice = st.session_state.pop("fast_path_notice", None)
    if notice:
        st.info(_t(fast_path_notice(notice)), icon=":material/bolt:")
    view = st.segmented_control(
        _t("workspace_view"), ["split", "design", "assistant"], default="split",
        format_func=lambda value: _t(f"workspace_{value}"), key=f"workspace_view_{summary.run_id}",
        persist_state="session", required=True,
    ) or "split"
    assistant_busy = _task_is_live(summary) or bool(conversation.get("pending"))
    design_busy = any(_task_supervisor().is_running(round_.run_id) or round_.status in BUSY_ROUND_STATUSES
                      for round_ in rounds)
    workspace_busy = assistant_busy or design_busy
    # A fast-path round already confirmed this brief, so the editor stops blocking the page.
    fast_round = bool(rounds) and rounds[-1].manifest.get("approval_policy") == "auto"
    if fast_round:
        st.badge(_t("fast_path_badge"), icon=":material/bolt:", color="blue")
    if view == "split":
        design_column, assistant_column = st.columns([1.5, 1], gap="large", vertical_alignment="top")
    else:
        design_column, assistant_column = st.container(), st.container()
    if brief_editor.draft_key(summary.run_id) not in st.session_state:
        brief_editor.load_draft(
            summary.run_id, conversation, _agent_brief_draft(summary, conversation),
        )
    selected_id = st.session_state.get(f"round_{summary.run_id}_{len(rounds)}", rounds[-1].run_id if rounds else None)
    selected = next((round_ for round_ in rounds if round_.run_id == selected_id), None)
    if view != "assistant":
        with design_column:
            selected = _render_design_panel(summary, conversation, rounds,
                                            busy=workspace_busy, design_busy=design_busy,
                                            fast_round=fast_round)
    if view != "design":
        with assistant_column:
            _render_assistant_panel(summary, conversation, selected, busy=assistant_busy)


def _render_task(summary: RunSummary, *, embedded: bool = False, actions_allowed: bool = True) -> None:
    if summary.manifest.get("is_conversation"):
        _render_conversation_task(summary)
        return
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

        _render_brief(result)

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
