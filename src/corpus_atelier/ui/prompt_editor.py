"""The prompt workspace: the editable prompt, its images, and its revision history."""

from __future__ import annotations

import streamlit as st

from corpus_atelier.app.state import RunSummary
from corpus_atelier.prompt_session.records import current_revision
from corpus_atelier.ui.prompt_common import (
    _image_path,
    _prompt_error,
    _revision_number,
)
from corpus_atelier.ui.session import _app_for_manifest, _t


def _render_prompt_editor(summary: RunSummary, session: dict, *, busy: bool) -> None:
    revision = current_revision(session)
    key = f"prompt_editor_{summary.run_id}"
    if key not in st.session_state or st.session_state[key].get("base") not in {
        None, *(item["id"] for item in session["prompt_revisions"]),
    }:
        st.session_state[key] = {
            "base": revision["id"] if revision else None,
            "version": 0,
        }
    draft = st.session_state[key]
    stale = draft["base"] != (revision["id"] if revision else None)
    if stale:
        # Follow a newer revision (for example an accepted chat proposal) unless the
        # user has typed into this draft; a local edit must never be overwritten.
        base = next(
            (item for item in session["prompt_revisions"] if item["id"] == draft["base"]),
            None,
        )
        widget = st.session_state.get(f"prompt_text_{summary.run_id}_{draft['version']}")
        locally_edited = base is not None and widget is not None and widget != base["prompt_text"]
        if not locally_edited:
            draft = {"base": revision["id"] if revision else None, "version": draft["version"] + 1}
            st.session_state[key] = draft
            stale = False
    with st.container(key=f"prompt_workspace_{summary.run_id}"):
        st.subheader(_t("current_prompt"))
        if stale:
            st.warning(_t("prompt_stale_draft"), icon=":material/sync_problem:")
        widget_key = f"prompt_text_{summary.run_id}_{draft['version']}"
        text = st.text_area(
            _t("current_prompt"), value=revision["prompt_text"] if revision else "",
            key=widget_key, height=220, label_visibility="collapsed",
            disabled=busy,
        )
        dirty = revision is not None and text != revision["prompt_text"]
        changed = text != (revision["prompt_text"] if revision else "")
        with st.container(horizontal=True):
            if st.button(
                _t("save_prompt"), type="primary", key=f"save_prompt_{summary.run_id}",
                disabled=busy or stale or not changed,
            ):
                try:
                    with _app_for_manifest(summary.manifest) as app:
                        app.edit_session_prompt(
                            summary.run_id, text, expected_revision=draft["base"],
                        )
                    st.session_state[key] = {"base": None, "version": draft["version"] + 1}
                    st.toast(_t("prompt_saved"))
                    st.rerun(scope="app")
                except Exception as exc:
                    _prompt_error(exc)
            if st.button(
                _t("reload_prompt"), key=f"reload_prompt_{summary.run_id}",
                disabled=busy or not (stale or dirty),
            ):
                st.session_state[key] = {"base": None, "version": draft["version"] + 1}
                st.rerun(scope="app")
            if st.button(
                _t("prepare_prompt"), key=f"prepare_prompt_{summary.run_id}",
                disabled=busy or revision is None, icon=":material/auto_awesome:",
            ):
                with st.spinner(_t("prepare_prompt_running")):
                    try:
                        with _app_for_manifest(summary.manifest) as app:
                            proposal = app.prepare_prompt_proposal(
                                summary.run_id, "generate",
                            )
                        st.session_state[f"proposal_{summary.run_id}"] = proposal
                        st.rerun(scope="app")
                    except Exception as exc:
                        _prompt_error(exc)
            if revision is not None:
                st.caption(_t(
                    "prompt_revision_meta",
                    revision=_revision_number(session, revision["id"]),
                    origin=_t(f"origin_{revision['origin']}"),
                ))
        proposal = st.session_state.get(f"proposal_{summary.run_id}")
        if proposal:
            st.caption(_t("prompt_proposal_label"))
            st.code(proposal["prompt_text"], language=None, wrap_lines=True)
            if proposal.get("notes"):
                st.caption(proposal["notes"])
            with st.container(horizontal=True):
                if st.button(
                    _t("adopt_proposal"), key=f"adopt_{proposal['id']}",
                    type="primary", disabled=busy,
                ):
                    try:
                        with _app_for_manifest(summary.manifest) as app:
                            app.adopt_prompt_proposal(
                                summary.run_id, proposal["id"],
                                expected_revision=session.get("current_prompt_revision_id"),
                            )
                        st.session_state.pop(f"proposal_{summary.run_id}", None)
                        st.toast(_t("proposal_adopted"))
                        st.rerun(scope="app")
                    except Exception as exc:
                        _prompt_error(exc)
                if st.button(
                    _t("dismiss_proposal"), key=f"dismiss_{proposal['id']}",
                    disabled=busy,
                ):
                    st.session_state.pop(f"proposal_{summary.run_id}", None)
                    st.rerun(scope="app")
        if revision and revision.get("note"):
            st.caption(f"{_t('prompt_revision_note')} {revision['note']}")
        if revision and revision.get("negative_prompt"):
            st.caption(_t("prompt_negative_label"))
            st.code(revision["negative_prompt"], language=None, wrap_lines=True)
        visible_copy = (revision or {}).get("visible_copy") or []
        if visible_copy:
            st.caption(_t("extraction_visible_copy"))
            for item in visible_copy:
                st.code(item["text"], language=None, wrap_lines=True)
                notes = [item.get("language") or ""]
                if item.get("uncertain"):
                    notes.append(_t("copy_uncertain"))
                detail = "  ".join(note for note in notes if note)
                if detail:
                    st.caption(detail)
        uncertainties = (revision or {}).get("uncertainties") or []
        if uncertainties:
            st.caption(_t("extraction_uncertainties"))
            for item in uncertainties:
                st.markdown(f"- {item}")


def _render_session_images(summary: RunSummary, session: dict) -> None:
    """Show the images this session saved, with their role and the prompt's source."""
    uploads = session["uploads"]
    if not uploads:
        return
    revision = current_revision(session)
    source_id = (revision or {}).get("source_image_id")
    with st.expander(
        _t("session_images_title", count=len(uploads)), expanded=source_id is not None,
    ):
        columns = st.columns(min(3, len(uploads)))
        for index, upload in enumerate(uploads):
            path = _image_path(summary, session, upload["id"])
            with columns[index % len(columns)]:
                if path is not None:
                    st.image(str(path), width="stretch")
                st.caption(upload.get("name") or upload["id"])
                role = _t(f"upload_role_{upload.get('role', 'reference')}")
                st.caption(
                    f"{role} · {_t('current_prompt_source')}"
                    if upload["id"] == source_id else role
                )


def _render_revision_history(summary: RunSummary, session: dict, *, busy: bool) -> None:
    revisions = session["prompt_revisions"]
    if len(revisions) < 2:
        return
    current = session.get("current_prompt_revision_id")
    with st.expander(_t("prompt_revision_history", count=len(revisions))):
        for revision in reversed(revisions):
            label = _t(
                "prompt_revision_line",
                revision=_revision_number(session, revision["id"]),
                origin=_t(f"origin_{revision['origin']}"),
            )
            st.markdown(f"**{label}**")
            st.code(revision["prompt_text"], language=None, wrap_lines=True)
            if revision.get("negative_prompt"):
                st.caption(_t("prompt_negative_label"))
                st.code(revision["negative_prompt"], language=None, wrap_lines=True)
            if revision["id"] != current:
                if st.button(
                    _t("restore_revision"), key=f"restore_{revision['id']}",
                    disabled=busy, icon=":material/history:",
                ):
                    try:
                        with _app_for_manifest(summary.manifest) as app:
                            app.restore_session_revision(
                                summary.run_id, revision["id"],
                                expected_revision=current,
                            )
                        st.session_state[f"prompt_editor_{summary.run_id}"] = {
                            "base": revision["id"], "version": (
                                st.session_state.get(
                                    f"prompt_editor_{summary.run_id}", {},
                                ).get("version", 0) + 1
                            ),
                        }
                        st.rerun(scope="app")
                    except Exception as exc:
                        _prompt_error(exc)
