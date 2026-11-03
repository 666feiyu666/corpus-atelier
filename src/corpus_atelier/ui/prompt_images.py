"""The image side of one session: uploads, frozen requests, results, archiving."""

from __future__ import annotations

import logging
from io import BytesIO
from typing import Any

import streamlit as st

from corpus_atelier.app.state import RunSummary
from corpus_atelier.config.paths import resolve_paths
from corpus_atelier.corpus import FACETS, resolve, tags_of
from corpus_atelier.corpus.ingest import ingest_prompt_session
from corpus_atelier.prompt_session.attempts import REFERENCE_ROLES
from corpus_atelier.prompt_session.records import current_revision
from corpus_atelier.ui.prompt_common import (
    RATIO_OPTIONS,
    _image_labels,
    _image_path,
    _prompt_error,
    _revision_number,
)
from corpus_atelier.ui.session import (
    _app_for_manifest,
    _application_for_manifest,
    _corpus_store,
    _current_credential,
    _submit_saved_task,
    _task_supervisor,
    _t,
)

LOGGER = logging.getLogger(__name__)


def _submit_image_attempt(summary: RunSummary, attempt: dict[str, Any]) -> None:
    """Submit one frozen attempt in the background; the service records the outcome."""
    credential = _current_credential()
    if credential is None:
        st.error(_t("api_key_missing"), icon=":material/key_off:")
        return
    run_id = summary.run_id
    manifest = dict(summary.manifest)

    def work() -> None:
        app = _application_for_manifest(manifest, credential.value)
        try:
            app.submit_image_action(
                run_id, attempt["id"], expected_digest=attempt["request_digest"],
            )
        except Exception:
            # The attempt record already carries the failure or unknown outcome.
            LOGGER.warning("Image attempt %s did not complete.", attempt["id"], exc_info=True)
        finally:
            app.close()

    _task_supervisor().submit(run_id, work)
    st.session_state.pop(f"prepared_{run_id}", None)
    st.rerun(scope="app")


def _render_request_panel(
    summary: RunSummary, attempt: dict[str, Any], session: dict, *, busy: bool,
) -> None:
    """Show the frozen request next to the submit button that would send it."""
    stale = attempt["prompt_revision_id"] != session.get("current_prompt_revision_id")
    labels = _image_labels(session)
    with st.container(border=True, key=f"request_{attempt['id']}"):
        st.caption(_t("exact_request_label"))
        st.code(attempt["request_text"], language=None, wrap_lines=True)
        st.caption(_t(
            "request_meta", model=attempt["settings"].get("model"),
            size=attempt["settings"].get("size"),
            quality=attempt["settings"].get("quality"),
        ))
        if attempt["reference_image_ids"]:
            st.caption(_t("request_references_label"))
            roles = {
                item["image_id"]: item["role"]
                for item in attempt.get("reference_roles") or []
            }
            for index, image_id in enumerate(attempt["reference_image_ids"], start=1):
                path = _image_path(summary, session, image_id)
                with st.container(horizontal=True, vertical_alignment="center"):
                    if path is not None:
                        st.image(str(path), width=120)
                    role = roles.get(image_id)
                    caption = f"{index}. {labels.get(image_id, image_id)}"
                    if role:
                        caption = f"{caption}  {_t(f'reference_role_{role}')}"
                    st.caption(caption)
        if attempt.get("mask"):
            mask_path = _image_path(summary, session, attempt["mask"]["id"])
            if mask_path is not None:
                st.image(str(mask_path), width=120, caption=_t("request_mask_label"))
            st.caption(_t("mask_convention"))
        if stale:
            st.warning(_t("request_stale"), icon=":material/sync_problem:")
        with st.container(horizontal=True):
            if st.button(
                _t("submit_request"), type="primary", key=f"submit_{attempt['id']}",
                disabled=busy or stale,
                icon=":material/edit:" if attempt["action"] == "edit" else ":material/image:",
            ):
                _submit_image_attempt(summary, attempt)
            if st.button(
                _t("discard_request"), key=f"discard_{attempt['id']}", disabled=busy,
            ):
                try:
                    with _app_for_manifest(summary.manifest) as app:
                        app.discard_image_action(summary.run_id, attempt["id"])
                    st.session_state.pop(f"prepared_{summary.run_id}", None)
                    st.rerun(scope="app")
                except Exception as exc:
                    _prompt_error(exc)


def _apply_edit_instruction(key: str, text: str) -> None:
    """Write a prepared instruction into the edit box before its next render."""
    st.session_state[key] = text


def _mask_overlay(summary: RunSummary, session: dict, source_id: str, mask_id: str) -> bytes | None:
    """Preview the mask over its source: red marks the pixels that will be regenerated."""
    source = _image_path(summary, session, source_id)
    mask = _image_path(summary, session, mask_id)
    if source is None or mask is None:
        return None
    from PIL import Image

    with Image.open(source) as base_image, Image.open(mask) as mask_image:
        base = base_image.convert("RGB")
        alpha = mask_image.convert("RGBA").getchannel("A").resize(base.size)
        overlay = Image.new("RGB", base.size, (196, 64, 48))
        highlight = Image.composite(overlay, base, alpha.point(lambda value: 255 - value))
        buffer = BytesIO()
        highlight.save(buffer, format="PNG")
        return buffer.getvalue()


def _ratio_text(ratio) -> str:
    if not ratio or len(ratio) != 2:
        return ""
    return f"{ratio[0]}:{ratio[1]}"


def _render_canvas_control(summary: RunSummary, session: dict, *, busy: bool) -> None:
    """Show the source canvas, the resolved output size, and an explicit fallback."""
    settings = session["settings"]
    source = settings.get("source_canvas")
    size = settings.get("size")
    origin = settings.get("canvas_origin")
    with st.container(key=f"canvas_control_{summary.run_id}"):
        st.subheader(_t("canvas_label"))
        if source:
            st.caption(_t(
                "canvas_source", width=source["width"], height=source["height"],
                ratio=_ratio_text(settings.get("aspect_ratio")),
            ))
        if size:
            st.caption(_t("canvas_output", size=size))
        else:
            st.warning(
                _t("canvas_unavailable", reason=settings.get("canvas_note") or ""),
                icon=":material/aspect_ratio:",
            )
        if origin == "user" and source and st.button(
            _t("canvas_restore_source"), key=f"canvas_restore_{summary.run_id}",
            disabled=busy, icon=":material/restart_alt:",
        ):
            try:
                with _app_for_manifest(summary.manifest) as app:
                    app.set_session_canvas(summary.run_id)
                st.rerun(scope="app")
            except Exception as exc:
                _prompt_error(exc)
        with st.expander(_t("canvas_choose_ratio"), expanded=size is None):
            current = settings.get("requested_canvas")
            default_ratio = (
                (current["width"], current["height"]) if current
                else tuple(settings.get("aspect_ratio") or (1, 1))
            )
            index = RATIO_OPTIONS.index(default_ratio) if default_ratio in RATIO_OPTIONS else 0
            choice = st.selectbox(
                _t("canvas_choose_ratio"), list(RATIO_OPTIONS), index=index,
                format_func=_ratio_text, key=f"canvas_ratio_{summary.run_id}",
                disabled=busy, label_visibility="collapsed",
            )
            if st.button(
                _t("canvas_apply"), key=f"canvas_apply_{summary.run_id}", disabled=busy,
            ):
                try:
                    with _app_for_manifest(summary.manifest) as app:
                        app.set_session_canvas(summary.run_id, choice)
                except Exception as exc:
                    _prompt_error(exc)
                else:
                    st.toast(_t("canvas_applied"))
                    st.rerun(scope="app")


def _render_image_actions(summary: RunSummary, session: dict, *, busy: bool) -> None:
    revision = current_revision(session)
    prepared = st.session_state.get(f"prepared_{summary.run_id}")
    labels = _image_labels(session)
    with st.container(key=f"image_actions_{summary.run_id}"):
        st.subheader(_t("prompt_image_actions"))
        st.caption(_t("prompt_image_actions_hint"))
        options = list(labels)
        uploads = st.file_uploader(
            _t("add_image_upload"), type=["png", "jpg", "jpeg", "webp"],
            accept_multiple_files=True, key=f"prompt_uploads_{summary.run_id}",
        )
        if uploads and st.button(
            _t("add_image_as_reference"), key=f"add_upload_{summary.run_id}",
            disabled=busy,
        ):
            try:
                with _app_for_manifest(summary.manifest) as app:
                    for upload in uploads:
                        app.attach_session_upload(
                            summary.run_id, (upload.name, upload.getvalue()),
                            role="reference",
                        )
                st.rerun(scope="app")
            except Exception as exc:
                _prompt_error(exc)
        references = st.multiselect(
            _t("selected_references_label"), options,
            format_func=lambda image_id: labels.get(image_id, image_id),
            key=f"prompt_refs_{summary.run_id}", disabled=busy,
        )
        reference_roles = {}
        for index, image_id in enumerate(references, start=1):
            reference_roles[image_id] = st.selectbox(
                _t(
                    "reference_role_label", index=index,
                    name=labels.get(image_id, image_id),
                ),
                list(REFERENCE_ROLES),
                format_func=lambda role: _t(f"reference_role_{role}"),
                key=f"reference_role_{summary.run_id}_{image_id}",
                disabled=busy,
            )
        generate_label = (
            _t("action_regenerate") if session["image_results"] else _t("action_generate")
        )
        if st.button(
            _t("prepare_generate_request"), key=f"prepare_generate_{summary.run_id}",
            disabled=busy or revision is None, width="stretch", icon=":material/edit_note:",
            help=generate_label,
        ):
            try:
                with _app_for_manifest(summary.manifest) as app:
                    attempt = app.prepare_image_action(
                        summary.run_id, action="generate",
                        reference_image_ids=references,
                        reference_roles=reference_roles,
                        expected_revision=session.get("current_prompt_revision_id"),
                    )
                st.session_state[f"prepared_{summary.run_id}"] = attempt
                st.rerun(scope="app")
            except Exception as exc:
                _prompt_error(exc)
        if prepared is not None and prepared["action"] == "generate":
            _render_request_panel(summary, prepared, session, busy=busy)

        st.divider()
        st.caption(_t("edit_selected_hint"))
        sources = list(session["image_results"]) + list(session["uploads"])
        if sources:
            source = st.selectbox(
                _t("edit_source_image"), [item["id"] for item in sources],
                format_func=lambda image_id: labels.get(image_id, image_id),
                key=f"edit_source_{summary.run_id}", disabled=busy,
            )
            instruction = st.text_area(
                _t("edit_instruction_label"), key=f"edit_instruction_{summary.run_id}",
                height=90, disabled=busy, placeholder=_t("edit_instruction_placeholder"),
            )
            if st.button(
                _t("prepare_edit_instruction"),
                key=f"prepare_edit_instruction_{summary.run_id}", disabled=busy,
                icon=":material/auto_awesome:",
            ):
                with st.spinner(_t("prepare_prompt_running")):
                    try:
                        with _app_for_manifest(summary.manifest) as app:
                            proposal = app.prepare_prompt_proposal(
                                summary.run_id, "edit", edit_instruction=instruction,
                            )
                        st.session_state[f"edit_proposal_{summary.run_id}"] = proposal
                        st.rerun(scope="app")
                    except Exception as exc:
                        _prompt_error(exc)
            edit_proposal = st.session_state.get(f"edit_proposal_{summary.run_id}")
            if edit_proposal:
                st.caption(_t("prompt_proposal_label"))
                st.code(edit_proposal["prompt_text"], language=None, wrap_lines=True)
                with st.container(horizontal=True):
                    st.button(
                        _t("adopt_edit_proposal"),
                        key=f"adopt_edit_{edit_proposal['id']}",
                        disabled=busy,
                        on_click=_apply_edit_instruction,
                        args=(
                            f"edit_instruction_{summary.run_id}",
                            edit_proposal["prompt_text"],
                        ),
                    )
                    if st.button(
                        _t("dismiss_proposal"),
                        key=f"dismiss_edit_{edit_proposal['id']}",
                        disabled=busy,
                    ):
                        st.session_state.pop(f"edit_proposal_{summary.run_id}", None)
                        st.rerun(scope="app")
            mask_upload = st.file_uploader(
                _t("mask_upload_label"), type=["png"], accept_multiple_files=False,
                key=f"edit_mask_upload_{summary.run_id}", disabled=busy,
            )
            if mask_upload and st.button(
                _t("mask_add"), key=f"add_mask_{summary.run_id}", disabled=busy,
            ):
                try:
                    with _app_for_manifest(summary.manifest) as app:
                        app.attach_session_upload(
                            summary.run_id,
                            (mask_upload.name, mask_upload.getvalue()),
                            role="mask",
                        )
                    st.rerun(scope="app")
                except Exception as exc:
                    _prompt_error(exc)
            masks = [item for item in session["uploads"] if item.get("role") == "mask"]
            mask_id = None
            if masks:
                mask_id = st.selectbox(
                    _t("mask_select_label"), [None, *[item["id"] for item in masks]],
                    index=1,
                    format_func=lambda value: (
                        _t("mask_none") if value is None else labels.get(value, value)
                    ),
                    key=f"edit_mask_{summary.run_id}", disabled=busy,
                )
                if mask_id:
                    preview = _mask_overlay(summary, session, source, mask_id)
                    if preview is not None:
                        st.image(preview, caption=_t("mask_preview"), width="stretch")
                    st.caption(_t("mask_convention"))
            if st.button(
                _t("prepare_edit_request"), key=f"prepare_edit_{summary.run_id}",
                disabled=busy, width="stretch", icon=":material/auto_fix_high:",
            ):
                try:
                    with _app_for_manifest(summary.manifest) as app:
                        attempt = app.prepare_image_action(
                            summary.run_id, action="edit", source_image_id=source,
                            edit_instruction=instruction, mask_image_id=mask_id,
                            expected_revision=session.get("current_prompt_revision_id"),
                        )
                    st.session_state[f"prepared_{summary.run_id}"] = attempt
                    st.rerun(scope="app")
                except Exception as exc:
                    _prompt_error(exc)
            if prepared is not None and prepared["action"] == "edit":
                _render_request_panel(summary, prepared, session, busy=busy)
        else:
            st.caption(_t("edit_requires_image"))


def _render_results(summary: RunSummary, session: dict, *, busy: bool) -> None:
    results = session["image_results"]
    with st.container(key=f"prompt_results_{summary.run_id}"):
        st.subheader(_t("result_history", count=len(results)))
        if not results:
            st.caption(_t("no_results_yet"))
            return
        columns = st.columns(min(2, len(results)))
        for index, image in enumerate(results):
            path = _image_path(summary, session, image["id"])
            with columns[index % len(columns)]:
                if path is not None:
                    st.image(str(path), width="stretch")
                active = image["id"] == session.get("active_image_id")
                st.caption(
                    (_t("active_result") + " · " if active else "")
                    + _t(
                        "result_meta",
                        revision=_revision_number(session, image["prompt_revision_id"]),
                        action=_t(f"action_{image['action']}"),
                    )
                )
                if image.get("parent_image_id"):
                    st.caption(_t(
                        "result_parent_meta",
                        source=_t("result_label") + f" {image['parent_image_id'][-4:]}",
                    ))
                st.code(image["request_text"], language=None, wrap_lines=True)
                with st.container(horizontal=True):
                    if not active and st.button(
                        _t("select_result"), key=f"select_{image['id']}", disabled=busy,
                    ):
                        try:
                            with _app_for_manifest(summary.manifest) as app:
                                app.select_prompt_result(summary.run_id, image["id"])
                            st.rerun(scope="app")
                        except Exception as exc:
                            _prompt_error(exc)
                    if st.button(
                        _t("edit_this_image"), key=f"edit_this_{image['id']}",
                        disabled=busy, icon=":material/auto_fix_high:",
                    ):
                        st.session_state[f"edit_source_{summary.run_id}"] = image["id"]
                        st.rerun(scope="app")
                    if session["entry_mode"] == "image" and st.button(
                        _t("refine_against_source"), key=f"refine_{image['id']}",
                        disabled=busy, icon=":material/compare:",
                    ):
                        credential = _current_credential()
                        if credential is None:
                            st.error(_t("api_key_missing"), icon=":material/key_off:")
                        else:
                            try:
                                with _app_for_manifest(summary.manifest) as app:
                                    app.queue_refine_turn(summary.run_id, image["id"])
                                    saved = app.inspect_task(summary.run_id)
                                _submit_saved_task(saved, credential.value)
                                st.rerun(scope="app")
                            except Exception as exc:
                                _prompt_error(exc)
                if path is not None:
                    st.download_button(
                        _t("download_image"), data=path.read_bytes(),
                        file_name=f"{summary.run_id}-{image['id']}.png",
                        mime="image/png", key=f"download_{image['id']}",
                    )


def _render_archive_control(summary: RunSummary, session: dict) -> None:
    if not session["image_results"]:
        return
    with st.popover(_t("archive_to_corpus"), icon=":material/bookmark_add:"):
        options = [image["id"] for image in session["image_results"]]
        labels = _image_labels(session)
        image_id = st.selectbox(
            _t("archive_image_label"), options,
            format_func=lambda value: labels.get(value, value),
            key=f"archive_image_{summary.run_id}",
        )
        tag_options = [tag.id for facet in FACETS for tag in tags_of(facet)]
        tags = st.multiselect(
            _t("corpus_tags_label"), tag_options,
            key=f"archive_tags_{summary.run_id}",
            format_func=lambda tag_id: resolve(tag_id).zh,
        )
        if st.button(
            _t("archive_confirm"), key=f"archive_confirm_{summary.run_id}",
            disabled=not tags,
        ):
            store = _corpus_store()
            try:
                ingest_prompt_session(
                    store, summary.run_dir, tags=tags, image_id=image_id,
                    media_root=resolve_paths().corpus_media_root,
                )
            except Exception:
                LOGGER.exception("Could not archive the prompt-session result.")
                st.error(_t("archive_failed"), icon=":material/error:")
            else:
                st.toast(_t("corpus_archived"), icon=":material/check_circle:")
            finally:
                store.close()
