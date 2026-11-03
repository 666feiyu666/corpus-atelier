"""The start screen: one prompt entry and one image-to-prompt entry."""

from __future__ import annotations

import logging

import streamlit as st

from corpus_atelier.app.state import RunSummary
from corpus_atelier.config.models import (
    IMAGE_MODEL_PROFILES,
    IMAGE_QUALITIES,
    TEXT_MODEL_PROFILES,
    get_image_model_profile,
    get_text_model_profile,
)
from corpus_atelier.ui.prompt_common import _creation_failure
from corpus_atelier.ui.prompt_images import _submit_image_attempt
from corpus_atelier.ui.session import (
    PRODUCT_CASE_ID,
    _application,
    _current_credential,
    _image_model_label,
    _select_task,
    _submit_saved_task,
    _t,
    _text_model_label,
)

LOGGER = logging.getLogger(__name__)

RATIO_OPTIONS = ((1, 1), (16, 9), (9, 16), (4, 3), (3, 4), (3, 2), (2, 3))


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
            prompt, case_id=PRODUCT_CASE_ID,
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
    except Exception as exc:
        _creation_failure(exc, "Could not start the prompt session.")
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
            settings=settings,
        )
        summary = app.inspect_task(result.run_id)
    except Exception as exc:
        _creation_failure(exc, "Could not start the image-to-prompt session.")
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
        actions = st.columns([1, 1], vertical_alignment="center")
        with actions[0]:
            generate_now = st.button(
                _t("generate_image_action"), type="primary", icon=":material/image:",
                key="start_prompt_action", width="stretch",
            )
        with actions[1]:
            save_only = st.button(
                _t("save_prompt_without_image"), key="start_prompt_only",
                help=_t("save_prompt_without_image_hint"), width="stretch",
            )
        if generate_now or save_only:
            references = [(item.name, item.getvalue()) for item in uploads or []]
            _create_prompt_session(
                prompt or "", model=model, reasoning=reasoning, image_model=image_model,
                quality=quality, ratio=ratio, references=references,
                generate_now=generate_now,
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
