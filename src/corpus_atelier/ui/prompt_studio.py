"""The prompt-centered studio: two entry points and one conversation workspace.

Streamlit only renders durable state and sends explicit user actions. Prompt
revisions, image roles, and provider payloads are decided by the application.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import streamlit as st

from corpus_atelier.app.state import RunSummary
from corpus_atelier.config.models import (
    IMAGE_MODEL_PROFILES,
    IMAGE_QUALITIES,
    TEXT_MODEL_PROFILES,
    get_image_model_profile,
    get_text_model_profile,
)
from corpus_atelier.corpus import FACETS, resolve, tags_of
from corpus_atelier.corpus.ingest import ingest_prompt_session
from corpus_atelier.design_support.canvas import resolve_image_size
from corpus_atelier.config.paths import resolve_paths
from corpus_atelier.prompt_session.records import current_revision, image_record
from corpus_atelier.ui.i18n import translate
from corpus_atelier.ui.session import (
    DEFAULT_PROFILE,
    PRODUCT_CASE_ID,
    _app_for_manifest,
    _application,
    _application_for_manifest,
    _corpus_store,
    _current_credential,
    _display_title,
    _image_model_label,
    _select_task,
    _status_label,
    _submit_saved_task,
    _t,
    _task_is_live,
    _task_supervisor,
    _text_model_label,
)

LOGGER = logging.getLogger(__name__)

RATIO_OPTIONS = ((1, 1), (16, 9), (9, 16), (4, 3), (3, 4), (3, 2), (2, 3))
BUSY_STATUSES = frozenset({"extracting", "discussing_request", "generating_image"})


def _one_line(value: str) -> str:
    return " ".join(str(value).split())


def _settings_values() -> tuple[str, str, str, str, tuple[int, int]]:
    model = st.selectbox(
        _t("text_model"), [profile.model for profile in TEXT_MODEL_PROFILES],
        format_func=_text_model_label, key="new_task_model",
    )
    profile = get_text_model_profile(model)
    if st.session_state.get("new_task_reasoning") not in profile.reasoning_efforts:
        st.session_state.new_task_reasoning = profile.default_reasoning_effort
    reasoning = st.segmented_control(
        _t("reasoning_effort"), list(profile.reasoning_efforts), key="new_task_reasoning",
    )
    image_model = st.selectbox(
        _t("image_model"), [profile.model for profile in IMAGE_MODEL_PROFILES],
        format_func=_image_model_label, key="new_task_image_model",
    )
    image_profile = get_image_model_profile(image_model)
    qualities = [
        quality for quality in IMAGE_QUALITIES
        if quality not in {"xhigh", "max"} or image_profile.supports_max_quality
    ]
    if st.session_state.get("new_task_quality") not in qualities:
        st.session_state.new_task_quality = "medium"
    quality = st.segmented_control(_t("image_quality"), qualities, key="new_task_quality")
    ratio = st.selectbox(
        _t("aspect_ratio_label"), RATIO_OPTIONS,
        format_func=lambda value: f"{value[0]}:{value[1]}", key="new_task_ratio",
    )
    return model, reasoning, image_model, quality, ratio


def _status_badge(status: str) -> None:
    paused = status in BUSY_STATUSES and not _task_supervisor().is_running(
        st.session_state.get("prompt_status_run_id"),
    )
    st.badge(
        _status_label(status),
        icon={
            "prompt_ready": ":material/check_circle:",
            "outcome_unknown": ":material/help:",
            "failed": ":material/error:",
        }.get(status, ":material/progress_activity:"),
        color=(
            "red" if status == "failed"
            else "orange" if status in BUSY_STATUSES or status == "outcome_unknown"
            else "green"
        ),
    )
    if paused:
        st.caption(_t("prompt_status_waiting"))


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


def _create_prompt_session(
    prompt: str, *, model: str, reasoning: str, image_model: str,
    quality: str, ratio: tuple[int, int], references: list[tuple[str, bytes]],
    generate_now: bool,
) -> None:
    credential = _current_credential()
    if credential is None:
        st.error(_t("api_key_missing"), icon=":material/key_off:")
        return
    settings = {"image_quality": quality, "aspect_ratio": list(ratio)}
    app = _application(
        model, reasoning, image_model, quality, api_key=credential.value,
    )
    attempt: dict[str, Any] | None = None
    summary: RunSummary | None = None
    try:
        result = app.start_from_prompt(
            prompt, case_id=PRODUCT_CASE_ID, profile=DEFAULT_PROFILE,
            settings=settings, references=references,
        )
        if generate_now:
            session = app.prompt_session(result.run_id)
            attempt = app.prepare_image_action(
                result.run_id, action="generate",
                reference_image_ids=[upload["id"] for upload in session["uploads"]],
                expected_revision=session["current_prompt_revision_id"],
            )
        summary = app.inspect_task(result.run_id)
    except Exception:
        LOGGER.exception("Could not start the prompt session.")
        st.error(_t("create_failed"), icon=":material/error:")
    finally:
        app.close()
    if summary is None:
        return
    _select_task(summary.run_id)
    if attempt is not None:
        _submit_image_attempt(summary, attempt)
    else:
        st.rerun(scope="app")


def _start_from_image(
    upload, *, model: str, reasoning: str, image_model: str,
    quality: str, ratio: tuple[int, int],
) -> None:
    credential = _current_credential()
    if credential is None:
        st.error(_t("api_key_missing"), icon=":material/key_off:")
        return
    settings = {"image_quality": quality, "aspect_ratio": list(ratio)}
    app = _application(model, reasoning, image_model, quality, api_key=credential.value)
    summary: RunSummary | None = None
    try:
        result = app.start_from_image(
            (upload.name, upload.getvalue()), case_id=PRODUCT_CASE_ID,
            profile=DEFAULT_PROFILE, settings=settings,
        )
        summary = app.inspect_task(result.run_id)
    except Exception:
        LOGGER.exception("Could not start the image-to-prompt session.")
        st.error(_t("create_failed"), icon=":material/error:")
    finally:
        app.close()
    if summary is not None:
        _submit_saved_task(summary, credential.value)
        _select_task(summary.run_id)
        st.rerun(scope="app")


def _render_prompt_start() -> None:
    """The start screen: one prompt entry and one image entry."""
    st.subheader(_t("start_from_request"))
    with st.popover(_t("task_settings"), icon=":material/tune:"):
        model, reasoning, image_model, quality, ratio = _settings_values()
        st.caption(_t("prompt_settings_hint"))
    mode = st.segmented_control(
        _t("start_mode_label"), ["prompt", "image"],
        format_func=lambda value: _t(f"start_mode_{value}"),
        default="prompt", required=True, key="prompt_start_mode",
        persist_state="session",
    ) or "prompt"
    if mode == "prompt":
        prompt = st.text_area(
            _t("prompt_start_label"), key="new_session_prompt", height=170,
            placeholder=_t("prompt_start_placeholder"),
        )
        uploads = st.file_uploader(
            _t("reference_images_upload"), type=["png", "jpg", "jpeg", "webp"],
            accept_multiple_files=True, key="new_session_references",
        )
        st.caption(_t("prompt_send_exact_hint"))
        if st.button(
            _t("generate_image_action"), type="primary", icon=":material/image:",
            key="start_prompt_action", width="stretch",
        ):
            references = [(item.name, item.getvalue()) for item in uploads or []]
            _create_prompt_session(
                prompt or "", model=model, reasoning=reasoning, image_model=image_model,
                quality=quality, ratio=ratio, references=references, generate_now=True,
            )
        if st.button(
            _t("save_prompt_without_image"), key="start_prompt_only",
            help=_t("save_prompt_without_image_hint"), width="stretch",
        ):
            references = [(item.name, item.getvalue()) for item in uploads or []]
            _create_prompt_session(
                prompt or "", model=model, reasoning=reasoning, image_model=image_model,
                quality=quality, ratio=ratio, references=references, generate_now=False,
            )
    else:
        st.caption(_t("extract_prompt_hint"))
        upload = st.file_uploader(
            _t("source_image_label"), type=["png", "jpg", "jpeg", "webp"],
            accept_multiple_files=False, key="new_session_source",
        )
        if st.button(
            _t("extract_prompt_action"), type="primary", icon=":material/visibility:",
            key="start_image_action", width="stretch", disabled=upload is None,
        ):
            _start_from_image(
                upload, model=model, reasoning=reasoning, image_model=image_model,
                quality=quality, ratio=ratio,
            )


def _image_labels(session: dict) -> dict[str, str]:
    names = {}
    for upload in session["uploads"]:
        names[upload["id"]] = upload.get("name") or upload["id"]
    for result in session["image_results"]:
        names[result["id"]] = f"{result.get('label') or _t('result_label')} ({result['id'][-4:]})"
    return names


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
    with st.container(border=True, key=f"prompt_workspace_{summary.run_id}"):
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
            if revision is not None:
                st.caption(_t(
                    "prompt_revision_meta",
                    revision=_revision_number(session, revision["id"]),
                    origin=_t(f"origin_{revision['origin']}"),
                ))
        if revision and revision.get("note"):
            st.caption(f"{_t('prompt_revision_note')} {revision['note']}")


def _revision_number(session: dict, revision_id: str) -> int:
    for index, revision in enumerate(session["prompt_revisions"], 1):
        if revision["id"] == revision_id:
            return index
    return 0


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


def _prompt_error(exc: Exception) -> None:
    st.error(_t("action_failed"))
    with st.expander(_t("error_details")):
        st.text(str(exc))


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
            st.caption(_t("request_references_label") + " " + ", ".join(
                labels.get(image_id, image_id) for image_id in attempt["reference_image_ids"]
            ))
            for image_id in attempt["reference_image_ids"]:
                path = _image_path(summary, session, image_id)
                if path is not None:
                    st.image(str(path), width=140)
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


def _image_path(summary: RunSummary, session: dict, image_id: str) -> Path | None:
    try:
        record = image_record(session, image_id)
    except ValueError:
        return None
    path = (summary.run_dir / record["path"]).resolve()
    return path if summary.run_dir in path.parents and path.is_file() else None


def _render_image_actions(summary: RunSummary, session: dict, *, busy: bool) -> None:
    revision = current_revision(session)
    prepared = st.session_state.get(f"prepared_{summary.run_id}")
    labels = _image_labels(session)
    with st.container(border=True, key=f"image_actions_{summary.run_id}"):
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
                _t("prepare_edit_request"), key=f"prepare_edit_{summary.run_id}",
                disabled=busy, width="stretch", icon=":material/auto_fix_high:",
            ):
                try:
                    with _app_for_manifest(summary.manifest) as app:
                        attempt = app.prepare_image_action(
                            summary.run_id, action="edit", source_image_id=source,
                            edit_instruction=instruction,
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
    with st.container(border=True, key=f"prompt_results_{summary.run_id}"):
        st.subheader(_t("result_history", count=len(results)))
        if not results:
            st.caption(_t("no_results_yet"))
            return
        columns = st.columns(min(3, len(results)))
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


def _render_prompt_conversation(summary: RunSummary, session: dict, *, busy: bool) -> None:
    status = summary.status
    with st.container(border=True, key=f"prompt_chat_{summary.run_id}"):
        st.subheader(_t("design_assistant"))
        st.caption(_t("prompt_assistant_hint"))
        labels = _image_labels(session)
        with st.container(height=420, key=f"prompt_messages_{summary.run_id}", autoscroll=False):
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


def _render_prompt_session(summary: RunSummary, *, embedded: bool = False) -> None:
    """Render one prompt session: prompt workspace on the left, chat on the right."""
    st.session_state["prompt_status_run_id"] = summary.run_id
    running = _task_supervisor().is_running(summary.run_id)
    try:
        with _app_for_manifest(summary.manifest) as app:
            if (
                app.inspect_task(summary.run_id).status == "generating_image" and not running
            ):
                app.reconcile_prompt_session(summary.run_id)
            session = app.prompt_session(summary.run_id)
            summary = app.inspect_task(summary.run_id)
    except Exception as exc:
        _prompt_error(exc)
        return
    pending = session.get("pending_turn")
    busy = running or pending is not None or summary.status in BUSY_STATUSES
    with st.container(horizontal=True, vertical_alignment="center"):
        if not embedded:
            st.header(_display_title(summary.manifest.get("title", summary.run_id), limit=52))
        _status_badge(summary.status)
    st.caption(_t("prompt_session_hint"))
    if summary.status == "outcome_unknown":
        st.warning(_t("outcome_unknown_notice"), icon=":material/help:")
    prompt_column, chat_column = st.columns([1.5, 1], gap="large", vertical_alignment="top")
    with prompt_column:
        _render_prompt_editor(summary, session, busy=busy)
        _render_revision_history(summary, session, busy=busy)
        _render_image_actions(summary, session, busy=busy)
        _render_results(summary, session, busy=busy)
        _render_archive_control(summary, session)
    with chat_column:
        _render_prompt_conversation(summary, session, busy=busy)


@st.fragment(run_every="1s")
def _render_live_prompt_session(run_id: str) -> None:
    from corpus_atelier.ui.session import _saved_tasks

    summary = next((task for task in _saved_tasks() if task.run_id == run_id), None)
    if summary is None:
        st.rerun(scope="app")
        return
    _render_prompt_session(summary)
    if not _task_is_live(summary):
        st.rerun(scope="app")
