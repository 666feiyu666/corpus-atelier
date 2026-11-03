"""The conversation column: messages, proposals, and the pending turn."""

from __future__ import annotations

import streamlit as st

from corpus_atelier.app.state import RunSummary
from corpus_atelier.ui.prompt_common import (
    _image_labels,
    _image_path,
    _prompt_error,
)
from corpus_atelier.ui.session import (
    _app_for_manifest,
    _current_credential,
    _submit_saved_task,
    _t,
    _task_is_live,
)


def _render_prompt_conversation(summary: RunSummary, session: dict, *, busy: bool) -> None:
    status = summary.status
    with st.container(border=True, key=f"prompt_chat_{summary.run_id}"):
        st.subheader(_t("design_assistant"))
        st.caption(_t("prompt_assistant_hint"))
        labels = _image_labels(session)
        with st.container(height=420, key=f"prompt_messages_{summary.run_id}", autoscroll=False):
            if not session["messages"]:
                st.caption(_t("prompt_chat_empty"))
            for message in session["messages"]:
                with st.chat_message(message["role"]):
                    if message["text"]:
                        st.markdown(message["text"])
                    for image_id in message.get("attachment_ids", []):
                        path = _image_path(summary, session, image_id)
                        if path is not None:
                            st.image(str(path), caption=labels.get(image_id, image_id), width=180)
                    if message.get("proposed_prompt"):
                        if message.get("conflict"):
                            st.warning(
                                _t("prompt_proposal_conflict"),
                                icon=":material/sync_problem:",
                            )
                        with st.expander(_t("proposed_prompt")):
                            st.code(message["proposed_prompt"], language=None, wrap_lines=True)
                    if message.get("edit_instruction"):
                        with st.expander(_t("proposed_edit_instruction")):
                            st.code(message["edit_instruction"], language=None, wrap_lines=True)
        pending = session.get("pending_turn")
        if status == "failed":
            st.error(_t("reply_failed"))
            if st.button(
                _t("retry_reply"), key=f"retry_prompt_{summary.run_id}",
                disabled=_task_is_live(summary) or _current_credential() is None,
            ):
                saved = _retry_pending(summary)
                if saved is not None:
                    st.rerun(scope="app")
        elif pending:
            st.info(_t("prompt_turn_pending"))
        submission = st.chat_input(
            _t("prompt_followup_placeholder"), key=f"prompt_input_{summary.run_id}",
            accept_file="multiple", file_type=["png", "jpg", "jpeg", "webp"],
            max_upload_size=10, submit_mode="disable",
            disabled=busy or pending is not None or _current_credential() is None,
        )
        if submission:
            text = submission if isinstance(submission, str) else submission.text
            files = [] if isinstance(submission, str) else [
                (item.name, item.getvalue()) for item in submission.files
            ]
            try:
                with _app_for_manifest(summary.manifest) as app:
                    app.queue_session_message(summary.run_id, text, attachments=files)
                    saved = app.inspect_task(summary.run_id)
                _submit_saved_task(saved, _current_credential().value)
                st.rerun(scope="app")
            except Exception as exc:
                _prompt_error(exc)


def _retry_pending(summary: RunSummary) -> RunSummary | None:
    credential = _current_credential()
    if credential is None:
        st.error(_t("api_key_missing"), icon=":material/key_off:")
        return None
    try:
        with _app_for_manifest(summary.manifest) as app:
            saved = app.inspect_task(summary.run_id)
        _submit_saved_task(saved, credential.value)
        return saved
    except Exception as exc:
        _prompt_error(exc)
        return None
