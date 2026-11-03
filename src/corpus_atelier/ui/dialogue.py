"""The design dialogue: assistant messages, brief editor, and history."""

from __future__ import annotations

from typing import Any
import streamlit as st
from corpus_atelier.artifacts.records import read_json
from corpus_atelier.conversation.records import ConversationRecord
from corpus_atelier.ui import brief_editor
from corpus_atelier.ui.viewport import (
    follow_latest,
    render_viewport,
    viewport_controller,
)
from corpus_atelier.app.state import RunSummary

from corpus_atelier.ui.session import (
    _app_for_manifest,
    _current_credential,
    _submission_attachments,
    _submission_text,
    _submit_saved_task,
    _t,
    _task_is_live,
)
from corpus_atelier.ui.brief_view import _render_brief_contents


def _conversation_error(exc: Exception) -> None:
    st.error(_t("conversation_action_failed"))
    with st.expander(_t("conversation_error_details")):
        st.text(str(exc))


def _agent_brief_draft(summary: RunSummary,
                       conversation: ConversationRecord) -> dict[str, Any] | None:
    """Return the brief drafted when the task was created, if it is still usable."""
    if conversation["design_brief"] is not None:
        return None
    relative = (summary.manifest.get("artifacts") or {}).get("brief_draft")
    if not relative:
        return None
    path = summary.run_dir / relative
    if not path.is_file():
        return None
    try:
        return read_json(path)
    except (OSError, ValueError):
        return None


def _load_agent_brief(summary: RunSummary, conversation: ConversationRecord) -> None:
    brief = _agent_brief_draft(summary, conversation)
    if brief is not None:
        brief_editor.load_draft(summary.run_id, conversation, brief)


def _render_brief_editor(summary: RunSummary, conversation: ConversationRecord, *, disabled: bool) -> bool:
    """Render the single authoritative brief editor, without a second contract form."""
    revision = conversation["revision"]
    with st.container(border=True, key=f"brief_workspace_{summary.run_id}"):
        st.subheader(_t("design_contract"))
        st.caption(_t("brief_review_hint"))
        st.caption(_t("brief_audience_hint"))
        agent_draft = _agent_brief_draft(summary, conversation)
        if brief_editor.draft_key(summary.run_id) not in st.session_state:
            brief_editor.load_draft(summary.run_id, conversation, agent_draft)
        draft = st.session_state[brief_editor.draft_key(summary.run_id)]
        stale = draft["base_revision"] != revision
        if stale:
            st.warning(_t("brief_stale_draft"))
        st.caption(_t("brief_editing_revision", revision=draft["source_revision"]) if draft["source_revision"] is not None else _t("brief_new_draft"))
        if agent_draft is not None:
            st.caption(_t("agent_brief_hint"))
        with st.expander(_t("brief_saved_preview")):
            if conversation["design_brief"]:
                _render_brief_contents(conversation["design_brief"])
        with st.expander(_t("brief_edit_fields"), expanded=not conversation["rounds"]):
            brief_editor.render_fields(summary.run_id, disabled=disabled, translate=_t)
        dirty = brief_editor.draft_dirty(summary.run_id)
        if dirty:
            st.info(_t("brief_unsaved_hint"))
        with st.container(horizontal=True):
            if st.button(_t("save_brief"), key=f"save_brief_{summary.run_id}", type="primary",
                         disabled=disabled or stale or bool(conversation.get("pending"))):
                try:
                    edited_brief, questions = brief_editor.draft_values(summary.run_id)
                    with _app_for_manifest(summary.manifest) as app:
                        app.save_conversation_brief(
                            summary.run_id, edited_brief, expected_revision=draft["base_revision"],
                            source_revision=draft["source_revision"], open_questions=questions,
                        )
                    st.session_state.pop(brief_editor.draft_key(summary.run_id), None)
                    st.toast(_t("brief_saved"))
                    st.rerun(scope="app")
                except Exception as exc:
                    _conversation_error(exc)
            if agent_draft is not None:
                st.button(_t("reload_agent_brief"), key=f"reload_agent_brief_{summary.run_id}",
                          on_click=_load_agent_brief, args=(summary, conversation), disabled=disabled)
            st.button(_t("load_latest_brief"), key=f"load_latest_brief_{summary.run_id}",
                      on_click=brief_editor.load_draft, args=(summary.run_id, conversation),
                      disabled=disabled or conversation["design_brief"] is None)
            if stale and dirty:
                st.button(_t("rebase_brief_draft"), key=f"rebase_brief_{summary.run_id}",
                          on_click=_rebase_brief_draft, args=(summary.run_id, revision), disabled=disabled)
    return dirty


def _rebase_brief_draft(run_id: str, revision: int) -> None:
    st.session_state[brief_editor.draft_key(run_id)]["base_revision"] = revision


def _edit_historical_brief(run_id: str, conversation: ConversationRecord, snapshot: dict) -> None:
    brief_editor.load_draft(run_id, conversation, snapshot["brief"], snapshot["revision"])
    follow_latest(run_id)


def _render_brief_history(summary: RunSummary, conversation: ConversationRecord, *, disabled: bool) -> None:
    history_by_revision = {entry["revision"]: entry for entry in conversation["brief_history"]}
    history = sorted(history_by_revision.values(),
                     key=lambda entry: entry["revision"] if entry["revision"] is not None else -1,
                     reverse=True)
    with st.expander(_t("brief_version_history")):
        for snapshot in history:
            revision = snapshot["revision"]
            with st.expander(_t("brief_history_revision", revision=revision)):
                _render_brief_contents(snapshot["brief"])
                st.button(
                    _t("edit_historical_brief"), key=f"edit_brief_{summary.run_id}_{revision}",
                    on_click=_edit_historical_brief, args=(summary.run_id, conversation, snapshot),
                    disabled=disabled,
                )


def _can_prepare_round(summary: RunSummary, conversation: ConversationRecord, *, busy: bool, dirty: bool) -> bool:
    draft = st.session_state[brief_editor.draft_key(summary.run_id)]
    current_saved_brief = (conversation["design_brief"] is not None
                           and conversation["brief_revision"] == conversation["revision"])
    current_draft = draft["base_revision"] == conversation["revision"] and not dirty
    already_prepared = bool(conversation["rounds"] and
                            conversation["rounds"][-1]["revision"] == conversation["revision"])
    return (
        current_saved_brief and current_draft and not already_prepared and not busy
        and bool(conversation["effective_request"]) and not conversation["open_questions"]
        and conversation["content_language"] is not None and _current_credential() is not None
    )


def _render_assistant_messages(summary: RunSummary, conversation: ConversationRecord) -> None:
    round_numbers = {record["run_id"]: index for index, record in enumerate(conversation["rounds"], 1)}
    with st.container(height=460, key=f"assistant_messages_{summary.run_id}", autoscroll=False):
        for message in conversation["messages"]:
            if message.get("kind", "discussion") != "discussion":
                continue
            with st.chat_message(message["role"]):
                if message["text"]:
                    st.markdown(message["text"])
                    if message["role"] == "assistant":
                        with st.expander(_t("copy_reply"), icon=":material/content_copy:"):
                            st.code(message["text"], language=None, wrap_lines=True)
                for attachment in message.get("attachments", []):
                    path = (summary.run_dir / attachment["path"]).resolve()
                    if summary.run_dir in path.parents and path.is_file():
                        st.image(path, caption=attachment["name"], width="stretch")
                if message.get("feedback_run_id"):
                    st.caption(_t("feedback_round", number=round_numbers.get(message["feedback_run_id"]),
                                  candidate=message.get("candidate_id") or _t("all_candidates")))
        render_viewport(summary.run_id, conversation, label=_t("return_latest_brief"),
                        controller=viewport_controller(), surface="assistant_messages")


def _render_feedback_picker(selected: RunSummary | None, conversation: ConversationRecord) -> str | None:
    if selected is None:
        return None
    number = next(index for index, record in enumerate(conversation["rounds"], 1)
                  if record["run_id"] == selected.run_id)
    st.caption(_t("feedback_round", number=number, candidate=_t("all_candidates")))
    relative = selected.manifest.get("artifacts", {}).get("candidate_index")
    if not relative:
        return None
    candidates = read_json(selected.run_dir / relative)
    return st.selectbox(
        _t("feedback_candidate"), options=[None, *[candidate["candidate_id"] for candidate in candidates]],
        format_func=lambda value: value or _t("all_candidates"), key=f"feedback_candidate_{selected.run_id}",
    )


def _render_assistant_panel(summary: RunSummary, conversation: ConversationRecord,
                            selected: RunSummary | None, *, busy: bool) -> None:
    with st.container(border=True, key=f"assistant_panel_{summary.run_id}"):
        st.subheader(_t("design_assistant"))
        st.caption(_t("assistant_hint"))
        candidate_id = _render_feedback_picker(selected, conversation)
        _render_assistant_messages(summary, conversation)
        if summary.status == "failed":
            st.error(_t("conversation_failed"))
            if st.button(_t("retry_conversation"), key=f"retry_chat_{summary.run_id}",
                         disabled=_task_is_live(summary) or _current_credential() is None):
                try:
                    with _app_for_manifest(summary.manifest) as app:
                        app.retry_conversation(summary.run_id)
                        saved = app.inspect_task(summary.run_id)
                    if saved.status == "discussing_request":
                        _submit_saved_task(saved, _current_credential().value)
                    st.rerun(scope="app")
                except Exception as exc:
                    _conversation_error(exc)
        elif conversation.get("pending"):
            st.info(_t("status.discussing_request"))
        submission = st.chat_input(
            _t("followup_placeholder"), key=f"conversation_input_{summary.run_id}",
            accept_file="multiple", file_type=["png", "jpg", "jpeg", "webp"], max_upload_size=10,
            submit_mode="disable", disabled=busy or _current_credential() is None,
        )
        if submission:
            try:
                with _app_for_manifest(summary.manifest) as app:
                    app.queue_conversation_message(
                        summary.run_id, _submission_text(submission), attachments=_submission_attachments(submission),
                        feedback_run_id=selected.run_id if selected else None, candidate_id=candidate_id,
                    )
                    saved = app.inspect_task(summary.run_id)
                _submit_saved_task(saved, _current_credential().value)
                follow_latest(summary.run_id, "assistant_messages")
                st.rerun(scope="app")
            except Exception as exc:
                _conversation_error(exc)
