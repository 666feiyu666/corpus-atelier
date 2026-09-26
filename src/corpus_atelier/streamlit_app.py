"""Streamlit adapter for the Yuliao Gallery graphic-design product."""

from __future__ import annotations

import json
import os
import re
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

import streamlit as st

from corpus_atelier.application import CorpusAtelierApplication
from corpus_atelier.artifacts.hashing import digest_file
from corpus_atelier.artifacts.store import ArtifactStore
from corpus_atelier.i18n import (
    DEFAULT_LANGUAGE,
    LANGUAGE_LABELS,
    SUPPORTED_LANGUAGES,
    translate,
)
from corpus_atelier.model_catalog import (
    IMAGE_MODEL_PROFILES,
    TEXT_MODEL_PROFILES,
    get_image_model_profile,
    get_text_model_profile,
    validate_reasoning_effort,
)
from corpus_atelier.providers import OpenAIImageProvider, OpenAITextProvider
from corpus_atelier.settings import (
    ApiCredential,
    load_preferences,
    mask_api_key,
    resolve_openai_api_key,
    save_preferences,
    update_local_openai_api_key,
)
from corpus_atelier.state import (
    CandidateSelection,
    HumanDecision,
    NaturalLanguageDesignJob,
    RunResult,
    RunSummary,
)


ROOT = Path(__file__).resolve().parents[2]
TASKS_ROOT = Path(
    os.environ.get("CORPUS_ATELIER_TASKS_ROOT", ROOT / ".atelier" / "tasks")
).resolve()
ENV_PATH = Path(
    os.environ.get("CORPUS_ATELIER_ENV_PATH", ROOT / ".env")
).resolve()
PREFERENCES_PATH = Path(
    os.environ.get(
        "CORPUS_ATELIER_PREFERENCES_PATH",
        ROOT / ".atelier" / "settings.json",
    )
).resolve()
PRODUCT_CASE_ID = "natural-language"
TERMINAL_STATUSES = {"completed", "rejected", "failed"}
DESIGN_METHODS = {
    "rhetoric-graphic": "method_rhetoric",
    "art-graphic": "method_art",
}
STATUS_ICONS = {
    "awaiting_approval": ":material/approval:",
    "awaiting_selection": ":material/select_check_box:",
    "completed": ":material/check_circle:",
    "rejected": ":material/cancel:",
    "failed": ":material/error:",
}


def _language() -> str:
    return st.session_state.get("ui_language", DEFAULT_LANGUAGE)


def _t(key: str, **values: Any) -> str:
    return translate(_language(), key, **values)


def _status_label(status: str) -> str:
    return _t(f"status.{status}")


def _result_message(result: RunResult) -> str:
    key = f"result.{result.status}"
    value = _t(key)
    return result.message if value == key else value


def _current_credential() -> ApiCredential | None:
    return resolve_openai_api_key(
        st.session_state.get("session_openai_api_key"),
        env_path=ENV_PATH,
    )


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_json_artifact(result: RunResult, name: str) -> Any:
    path = result.artifacts.get(name)
    return _read_json(Path(path)) if path else {}


def read_text_artifact(result: RunResult, name: str) -> str:
    path = result.artifacts.get(name)
    return Path(path).read_text(encoding="utf-8") if path else ""


def _application(
    text_model: str,
    reasoning_effort: str,
    image_model: str,
    image_quality: str = "medium",
    api_key: str | None = None,
) -> CorpusAtelierApplication:
    get_text_model_profile(text_model)
    validate_reasoning_effort(text_model, reasoning_effort)
    get_image_model_profile(image_model)
    return CorpusAtelierApplication(
        runs_root=TASKS_ROOT,
        text_provider=OpenAITextProvider(
            model=text_model,
            reasoning_effort=reasoning_effort,
            api_key=api_key,
        ),
        image_provider=OpenAIImageProvider(
            model=image_model,
            quality=image_quality,
            api_key=api_key,
        ),
    )


def _task_store() -> ArtifactStore:
    return ArtifactStore(TASKS_ROOT)


def _default_text_model() -> str:
    return TEXT_MODEL_PROFILES[0].model


def _default_image_model() -> str:
    return IMAGE_MODEL_PROFILES[0].model


def _text_model_label(model: str) -> str:
    try:
        return get_text_model_profile(model).label
    except ValueError:
        return model


def _image_model_label(model: str) -> str:
    try:
        return get_image_model_profile(model).label
    except ValueError:
        return model


def _model_settings(manifest: dict[str, Any]) -> tuple[str, str, str, str]:
    text = manifest.get("models", {}).get("text", {})
    image = manifest.get("models", {}).get("image", {})
    model = text.get("model", _default_text_model())
    effort = text.get("reasoning_effort", "medium")
    image_model = image.get("model", _default_image_model())
    image_quality = image.get("quality", "medium")
    get_text_model_profile(model)
    validate_reasoning_effort(model, effort)
    get_image_model_profile(image_model)
    return model, effort, image_model, image_quality


def _app_for_manifest(manifest: dict[str, Any]) -> CorpusAtelierApplication:
    model, effort, image_model, image_quality = _model_settings(manifest)
    credential = _current_credential()
    return _application(
        model,
        effort,
        image_model,
        image_quality,
        credential.value if credential else None,
    )


def _initialize_state() -> None:
    preferences = load_preferences(PREFERENCES_PATH)
    st.session_state.setdefault("ui_language", preferences["language"])
    if st.session_state.ui_language not in SUPPORTED_LANGUAGES:
        st.session_state.ui_language = DEFAULT_LANGUAGE
    st.session_state.setdefault("session_openai_api_key", None)
    st.session_state.setdefault("settings_dialog_open", False)
    st.session_state.setdefault("selected_task_id", None)
    st.session_state.setdefault("new_task_model", _default_text_model())
    st.session_state.setdefault("new_task_image_model", _default_image_model())
    st.session_state.setdefault("new_task_reasoning", "medium")
    st.session_state.setdefault("new_task_method", next(iter(DESIGN_METHODS)))
    st.session_state.setdefault("new_task_candidates", 3)


def _saved_tasks() -> list[RunSummary]:
    return [
        RunSummary(
            run_id=manifest["run_id"],
            status=manifest["status"],
            run_dir=run_dir,
            manifest=manifest,
        )
        for run_dir, manifest in _task_store().list_runs()
    ]


def _select_task(run_id: str | None) -> None:
    st.session_state.selected_task_id = run_id


def _test_openai_connection(api_key: str) -> bool:
    """Check the supplied credential without exposing provider details."""
    from openai import OpenAI

    client = OpenAI(api_key=api_key, max_retries=0, timeout=20.0)
    try:
        client.models.list()
        return True
    except Exception:
        return False
    finally:
        client.close()


def _save_language(language: str) -> None:
    save_preferences(PREFERENCES_PATH, {"language": language})
    st.session_state.ui_language = language


def _dismiss_settings_dialog() -> None:
    st.session_state.settings_dialog_open = False


def _show_settings_dialog() -> None:
    @st.dialog(
        _t("settings"),
        icon=":material/settings:",
        on_dismiss=_dismiss_settings_dialog,
    )
    def settings_dialog() -> None:
        selected_language = st.selectbox(
            _t("interface_language"),
            list(SUPPORTED_LANGUAGES),
            index=list(SUPPORTED_LANGUAGES).index(_language()),
            format_func=LANGUAGE_LABELS.__getitem__,
            key="settings_language",
        )
        if selected_language and selected_language != _language():
            try:
                _save_language(selected_language)
                st.session_state.settings_dialog_open = False
                st.rerun()
            except OSError:
                st.error(
                    _t("settings_save_failed"),
                    icon=":material/error:",
                )

        st.subheader(_t("api_configuration"))
        credential = _current_credential()
        if credential:
            st.caption(_t(
                "api_key_configured",
                masked=mask_api_key(credential.value),
            ))
        else:
            st.caption(_t("api_key_missing"))

        with st.form("openai_api_key_form", clear_on_submit=True):
            candidate_key = st.text_input(
                _t("openai_api_key"),
                type="password",
                autocomplete="off",
                placeholder=_t(
                    "api_key_placeholder_configured"
                    if credential else "api_key_placeholder_empty"
                ),
                key="settings_openai_api_key",
            )
            remember_key = st.toggle(
                _t("remember_api_key"),
                help=_t("remember_api_key_help"),
                key="settings_remember_api_key",
            )
            with st.container(horizontal=True):
                save_key = st.form_submit_button(
                    _t("save_api_key"),
                    type="primary",
                    icon=":material/save:",
                )
                test_connection = st.form_submit_button(
                    _t("test_connection"),
                    icon=":material/cable:",
                )

        submitted_key = (candidate_key or "").strip()
        if save_key:
            if not submitted_key:
                st.error(_t("api_key_required"), icon=":material/error:")
            else:
                try:
                    if remember_key:
                        update_local_openai_api_key(ENV_PATH, submitted_key)
                    st.session_state.session_openai_api_key = submitted_key
                    st.session_state.settings_notice = _t(
                        "api_key_saved_local"
                        if remember_key else "api_key_saved_session"
                    )
                    st.session_state.settings_dialog_open = False
                    st.rerun()
                except OSError:
                    st.error(
                        _t("settings_save_failed"),
                        icon=":material/error:",
                    )

        if test_connection:
            key_to_test = submitted_key or (
                credential.value if credential else ""
            )
            if not key_to_test:
                st.error(_t("api_key_required"), icon=":material/error:")
            elif _test_openai_connection(key_to_test):
                st.success(_t("connection_ok"), icon=":material/check_circle:")
            else:
                st.error(
                    _t("connection_failed"),
                    icon=":material/error:",
                )

        if st.button(
            _t("clear_api_key"),
            icon=":material/key_off:",
            key="clear_openai_api_key",
        ):
            try:
                st.session_state.session_openai_api_key = None
                update_local_openai_api_key(ENV_PATH, None)
                remaining = _current_credential()
                st.session_state.settings_notice = _t(
                    "api_key_fallback_environment"
                    if remaining else "api_key_cleared"
                )
                st.session_state.settings_dialog_open = False
                st.rerun()
            except OSError:
                st.error(
                    _t("settings_save_failed"),
                    icon=":material/error:",
                )
        st.caption(_t("api_key_environment_hint"))

    settings_dialog()


def _render_sidebar(tasks: list[RunSummary]) -> None:
    with st.sidebar:
        st.html("""
            <style>
            [data-testid="stSidebarContent"] {
                display: flex;
                flex-direction: column;
                min-height: 100vh;
            }
            [data-testid="stSidebarUserContent"] {
                display: flex;
                flex: 1;
                flex-direction: column;
            }
            [data-testid="stSidebarUserContent"] > div,
            [data-testid="stSidebarUserContent"] > div > [data-testid="stVerticalBlock"] {
                display: flex;
                flex: 1;
                flex-direction: column;
            }
            [data-testid="stSidebarUserContent"]
            [data-testid="stVerticalBlock"]
            > [data-testid="stLayoutWrapper"]:has(.st-key-sidebar_footer) {
                margin-top: auto;
                position: sticky;
                bottom: 0;
                z-index: 2;
                padding-top: 0.75rem;
                background: var(--background-color);
            }
            </style>
        """)
        st.title(_t("product_name"))
        if st.button(
            _t("new_task"),
            type="primary",
            icon=":material/add:",
            width="stretch",
            key="new_task",
        ):
            _select_task(None)
            st.rerun()

        st.caption(_t("tasks"))
        if not tasks:
            st.caption(_t("no_saved_tasks"))
        else:
            with st.container(height=520, gap="small"):
                for task in tasks:
                    manifest = task.manifest
                    title = manifest.get("title", task.run_id)
                    icon = STATUS_ICONS.get(
                        task.status,
                        ":material/pending:",
                    )
                    if st.button(
                        title,
                        icon=icon,
                        width="stretch",
                        key=f"task_{task.run_id}",
                        help=_status_label(task.status),
                    ):
                        _select_task(task.run_id)
                        st.rerun()

        with st.container(key="sidebar_footer"):
            open_settings = st.button(
                _t("settings"),
                icon=":material/settings:",
                width="stretch",
                key="open_settings",
            )
            st.caption("v1.0.0")
        if open_settings:
            st.session_state.settings_dialog_open = True
    if st.session_state.settings_dialog_open:
        _show_settings_dialog()


def _render_new_task_settings() -> tuple[str, str, str, str, int]:
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
    method = st.segmented_control(
        _t("design_method"),
        list(DESIGN_METHODS),
        format_func=lambda value: _t(DESIGN_METHODS[value]),
        key="new_task_method",
    )
    candidates = st.segmented_control(
        _t("candidate_limit"),
        [1, 2, 3],
        key="new_task_candidates",
    )
    return model, reasoning, image_model, method, candidates


def _start_task(
    request: str,
    *,
    model: str,
    reasoning_effort: str,
    image_model: str,
    profile: str,
    candidate_count: int,
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
        api_key=credential.value,
    )
    try:
        with st.chat_message("user"):
            st.markdown(request)
        with st.chat_message("assistant"):
            with st.status(
                _t("planning"),
                type="compact",
                expanded=True,
            ) as status:
                result = app.start_request(NaturalLanguageDesignJob(
                    case_id=PRODUCT_CASE_ID,
                    profile=profile,
                    request=request,
                    candidate_count=candidate_count,
                ))
                status.update(
                    label=_t("proposals_ready"),
                    state="complete",
                    expanded=False,
                )
        _select_task(result.run_id)
        st.rerun()
    except Exception as exc:
        st.error(_t("create_failed"), icon=":material/error:")
    finally:
        app.close()


def _render_new_task() -> None:
    st.title(_t("product_name"))
    st.caption(_t("product_tagline"))
    with st.popover(_t("task_settings"), icon=":material/tune:"):
        model, reasoning, image_model, profile, candidate_count = (
            _render_new_task_settings()
        )

    st.space("medium")
    st.subheader(_t("start_from_request"))
    submission = st.chat_input(
        _t("request_placeholder"),
        key="new_task_prompt",
        submit_mode="disable",
    )
    if submission:
        _start_task(
            submission,
            model=model,
            reasoning_effort=reasoning,
            image_model=image_model,
            profile=profile,
            candidate_count=candidate_count,
        )


def _render_brief(result: RunResult) -> None:
    brief = read_json_artifact(result, "brief")
    if not brief:
        return
    with st.expander(_t("understood_request"), icon=":material/description:"):
        fields = (
            ("deliverable", "deliverable"),
            ("topic", "topic"),
            ("purpose", "purpose"),
            ("audience", "audience"),
            ("use_context", "use_context"),
            ("setting", "setting"),
        )
        for label_key, key in fields:
            if brief.get(key):
                st.markdown(f"**{_t(label_key)}:** {brief[key]}")
        exact_copy = brief.get("exact_copy", [])
        if exact_copy:
            st.markdown(f"**{_t('exact_copy')}:**")
            for item in exact_copy:
                st.markdown(f"- {item}")


def _ready_candidates(result: RunResult) -> list[dict[str, Any]]:
    candidates = read_json_artifact(result, "candidate_index")
    return [
        candidate
        for candidate in candidates
        if candidate.get("status") == "ready"
    ]


def _all_candidates(result: RunResult) -> list[dict[str, Any]]:
    candidates = read_json_artifact(result, "candidate_index")
    return candidates if isinstance(candidates, list) else []


def _selected_candidate_id(result: RunResult) -> str | None:
    selection = read_json_artifact(result, "selection")
    return selection.get("selected_candidate_id") if isinstance(selection, dict) else None


def _ordered_candidates(
    candidates: list[dict[str, Any]], selected_id: str | None,
) -> list[dict[str, Any]]:
    return sorted(
        candidates,
        key=lambda candidate: (
            candidate.get("candidate_id") != selected_id,
            candidate.get("candidate_id", ""),
        ),
    )


def _safe_filename_part(value: str, *, fallback: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", " ".join(value.split()))
    cleaned = cleaned.strip(" ._")
    return (cleaned or fallback)[:56]


def _candidate_filename(
    title: str,
    candidate: dict[str, Any],
    *,
    selected: bool,
) -> str:
    task = _safe_filename_part(title, fallback=_t("file_design_task"))
    candidate_id = candidate.get("candidate_id", "c00")
    suffix = (
        _t("file_final")
        if selected
        else _t("file_candidate", number=candidate_id.removeprefix("c"))
    )
    return f"{_t('export_prefix')}_{task}_{suffix}.png"


def _verified_image_bytes(candidate: dict[str, Any]) -> bytes | None:
    image_path = candidate.get("image_path")
    if not image_path:
        return None
    path = Path(image_path)
    if not path.is_file():
        return None
    expected = candidate.get("image_sha256")
    if expected and digest_file(path) != expected:
        return None
    return path.read_bytes()


def _image_archive(
    title: str,
    candidates: list[dict[str, Any]],
    selected_id: str | None,
) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for candidate in candidates:
            data = _verified_image_bytes(candidate)
            if data is None:
                continue
            archive.writestr(
                _candidate_filename(
                    title,
                    candidate,
                    selected=candidate.get("candidate_id") == selected_id,
                ),
                data,
            )
    return output.getvalue()


def _render_generation_preview(result: RunResult) -> None:
    ready = _ready_candidates(result)
    if not ready:
        return
    columns = st.columns(len(ready), gap="large", vertical_alignment="top")
    for column, candidate in zip(columns, ready, strict=True):
        proposal = candidate.get("proposal", {})
        seed = candidate.get("direction_seed", {})
        with column.container(border=True, height="stretch"):
            st.subheader(seed.get("label", candidate["candidate_id"]))
            st.markdown(
                proposal.get("chosen_direction", _t("proposal_fallback"))
            )
            if proposal.get("design_description"):
                with st.expander(_t("full_visual_description"), expanded=True):
                    st.markdown(proposal["design_description"])
            if proposal.get("design_rationale"):
                st.caption(proposal["design_rationale"])
            request = candidate.get("generation_request", {})
            st.caption(
                " · ".join([
                    _t("image_model_meta", value=request.get("model", _t("not_recorded"))),
                    _t("quality_meta", value=request.get("quality", _t("not_recorded"))),
                    _t("size_meta", value=request.get("size", _t("not_recorded"))),
                ])
            )
            prompt = candidate.get("generation_prompt", "")
            if prompt:
                with st.expander(_t("full_prompt_to_send")):
                    st.code(prompt, language=None, wrap_lines=True)


def _resume(summary: RunSummary, decision: object, message: str) -> None:
    app = _app_for_manifest(summary.manifest)
    try:
        with st.spinner(message):
            app.resume(summary.run_id, decision)
        st.rerun()
    except Exception as exc:
        st.error(_t("operation_failed"), icon=":material/error:")
    finally:
        app.close()


def _render_approval(summary: RunSummary, result: RunResult) -> None:
    st.info(
        _t("approval_notice"),
        icon=":material/approval:",
    )
    _render_generation_preview(result)
    ready_count = len(_ready_candidates(result))
    with st.container(horizontal=True, horizontal_alignment="right"):
        if st.button(
            _t("cancel_generation"),
            icon=":material/close:",
            key=f"cancel_{result.run_id}",
        ):
            _resume(
                summary,
                HumanDecision(False, reviewer="streamlit-user"),
                _t("canceling"),
            )
        if st.button(
            _t("confirm_generate", count=ready_count),
            type="primary",
            icon=":material/image:",
            key=f"approve_{result.run_id}",
        ):
            _resume(
                summary,
                HumanDecision(True, reviewer="streamlit-user"),
                _t("generating_images"),
            )


def _render_image_gallery(
    summary: RunSummary,
    result: RunResult,
    *,
    selectable: bool,
) -> None:
    candidates = _all_candidates(result)
    selected_id = _selected_candidate_id(result)
    successful = _ordered_candidates(
        [candidate for candidate in candidates if candidate.get("status") == "generated"],
        selected_id,
    )
    failed = [candidate for candidate in candidates if candidate.get("status") == "failed"]

    if selectable:
        st.caption(_t("choose_or_discard"))
    elif successful:
        st.subheader(_t("generation_results"))

    if not successful:
        st.info(_t("no_images"))
    else:
        columns = st.columns(len(successful), gap="large", vertical_alignment="top")
        for column, candidate in zip(columns, successful, strict=True):
            candidate_id = candidate.get("candidate_id", "方案")
            is_selected = candidate_id == selected_id
            seed = candidate.get("direction_seed", {})
            proposal = candidate.get("proposal", {})
            with column.container(border=True, height="stretch"):
                with st.container(horizontal=True, vertical_alignment="center"):
                    st.subheader(seed.get("label", candidate_id))
                    if is_selected:
                        st.badge(
                            _t("final_choice"),
                            icon=":material/check_circle:",
                            color="green",
                        )
                    elif not selectable:
                        st.badge(_t("alternative"), color="gray")
                image_data = _verified_image_bytes(candidate)
                if image_data is None:
                    st.error(_t("image_invalid"))
                else:
                    st.image(
                        image_data,
                        caption=proposal.get("chosen_direction", candidate_id),
                        width="stretch",
                    )
                    if proposal.get("design_rationale"):
                        st.caption(proposal["design_rationale"])
                    st.download_button(
                        _t("download_png"),
                        data=image_data,
                        file_name=_candidate_filename(
                            summary.manifest.get("title", result.run_id),
                            candidate,
                            selected=is_selected,
                        ),
                        mime="image/png",
                        icon=":material/download:",
                        on_click="ignore",
                        width="stretch",
                        key=f"download_{result.run_id}_{candidate_id}",
                    )

                if selectable and st.button(
                    _t("choose_proposal"),
                    type="primary",
                    icon=":material/check:",
                    key=f"select_{result.run_id}_{candidate_id}",
                    width="stretch",
                ):
                    _resume(
                        summary,
                        CandidateSelection(candidate_id, reviewer="streamlit-user"),
                        _t("saving_selection"),
                    )

        if len(successful) > 1:
            archive_name = (
                f"{_t('export_prefix')}_"
                f"{_safe_filename_part(summary.manifest.get('title', result.run_id), fallback=_t('file_design_task'))}_"
                f"{_t('file_all_images')}.zip"
            )
            st.download_button(
                _t("download_all"),
                data=_image_archive(
                    summary.manifest.get("title", result.run_id),
                    successful,
                    selected_id,
                ),
                file_name=archive_name,
                mime="application/zip",
                icon=":material/folder_zip:",
                on_click="ignore",
                key=f"download_all_{result.run_id}",
            )

    if failed:
        labels = [
            candidate.get("direction_seed", {}).get(
                "label", candidate.get("candidate_id", _t("unknown_proposal"))
            )
            for candidate in failed
        ]
        st.warning(_t("failed_candidates", labels="、".join(labels)))

    if selectable and st.button(
        _t("discard_all"),
        icon=":material/delete_sweep:",
        key=f"discard_{result.run_id}",
    ):
        _resume(
            summary,
            CandidateSelection(None, reviewer="streamlit-user"),
            _t("saving_selection"),
        )


def _render_selection(summary: RunSummary, result: RunResult) -> None:
    _render_image_gallery(summary, result, selectable=True)


def _render_design_details(result: RunResult) -> None:
    candidates = _all_candidates(result)
    selected_id = _selected_candidate_id(result)
    candidates = _ordered_candidates(
        [
            candidate
            for candidate in candidates
            if candidate.get("proposal") or candidate.get("generation_prompt")
        ],
        selected_id,
    )
    if not candidates:
        return

    with st.expander(_t("design_details"), icon=":material/design_services:"):
        labels = []
        for candidate in candidates:
            label = candidate.get("direction_seed", {}).get(
                "label", candidate.get("candidate_id", _t("design_proposal"))
            )
            if candidate.get("candidate_id") == selected_id:
                label = f"{label} · {_t('final_choice')}"
            labels.append(label)

        for tab, candidate in zip(st.tabs(labels), candidates, strict=True):
            with tab:
                proposal = candidate.get("proposal", {})
                status = candidate.get("status")
                if status == "failed":
                    error = candidate.get("error", {})
                    st.warning(_t(
                        "generation_failed_detail",
                        message=error.get("message", _t("no_failure_reason")),
                    ))

                st.subheader(_t("design_direction"))
                st.markdown(
                    proposal.get("chosen_direction", _t("no_direction"))
                )
                if proposal.get("design_description"):
                    st.subheader(_t("full_visual_description"))
                    st.markdown(proposal["design_description"])
                if proposal.get("design_rationale"):
                    st.subheader(_t("design_rationale"))
                    st.markdown(proposal["design_rationale"])

                request = candidate.get("generation_request", {})
                if request:
                    st.caption(
                        " · ".join([
                            _t("image_model_meta", value=request.get("model", _t("not_recorded"))),
                            _t("quality_meta", value=request.get("quality", _t("not_recorded"))),
                            _t("size_meta", value=request.get("size", _t("not_recorded"))),
                        ])
                    )
                prompt = candidate.get("generation_prompt")
                if prompt:
                    st.subheader(_t("generation_prompt"))
                    st.code(prompt, language=None, wrap_lines=True)


def _status_state(status: str) -> str:
    if status == "failed":
        return "error"
    if status in TERMINAL_STATUSES or status.startswith("awaiting_"):
        return "complete"
    return "running"


def _render_task(summary: RunSummary) -> None:
    manifest = summary.manifest
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
        st.title(manifest.get("title", summary.run_id))
        st.badge(
            _status_label(result.status),
            icon=STATUS_ICONS.get(result.status, ":material/pending:"),
            color=(
                "green" if result.status == "completed"
                else "red" if result.status == "failed"
                else "orange" if result.status.startswith("awaiting_")
                else "gray"
            ),
        )

    model, effort, image_model, _ = _model_settings(manifest)
    st.caption(
        " · ".join([
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
    if request_path:
        with st.chat_message("user"):
            st.markdown(Path(request_path).read_text(encoding="utf-8"))

    with st.chat_message("assistant"):
        with st.status(
            _status_label(result.status),
            state=_status_state(result.status),
            type="compact",
            expanded=False,
        ):
            st.caption(_result_message(result))

        _render_brief(result)

        if result.status == "awaiting_approval":
            _render_approval(summary, result)
        elif result.status == "awaiting_selection":
            _render_selection(summary, result)
        elif result.status == "completed":
            if _selected_candidate_id(result) is None:
                st.info(_t("completed_without_selection"))
            _render_image_gallery(summary, result, selectable=False)
        elif result.status == "rejected":
            st.warning(_t("generation_canceled"))
        elif result.status == "failed":
            st.error(_t("task_failed"))

        if result.status != "awaiting_approval":
            _render_design_details(result)


def main() -> None:
    preferred_language = load_preferences(PREFERENCES_PATH)["language"]
    st.set_page_config(
        page_title=translate(preferred_language, "product_name"),
        page_icon=":material/palette:",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    _initialize_state()
    settings_notice = st.session_state.pop("settings_notice", None)
    if settings_notice:
        st.toast(settings_notice, icon=":material/check_circle:")
    tasks = _saved_tasks()
    known_ids = {task.run_id for task in tasks}
    selected = st.session_state.selected_task_id
    if selected is not None and selected not in known_ids:
        _select_task(None)
        selected = None

    _render_sidebar(tasks)
    if selected is None:
        _render_new_task()
        return

    summary = next(task for task in tasks if task.run_id == selected)
    _render_task(summary)


main()
