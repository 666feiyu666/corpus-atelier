"""Streamlit adapter for the Yuliao Gallery graphic-design product."""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from io import BytesIO
from math import ceil
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

import streamlit as st

from corpus_atelier import __version__
from corpus_atelier.application import (
    RECOVERABLE_TASK_STATUSES,
    CorpusAtelierApplication,
)
from corpus_atelier.artifacts.hashing import digest_file
from corpus_atelier.conversation import BUSY_ROUND_STATUSES, load_conversation
from corpus_atelier import brief_editor
from corpus_atelier.conversation_viewport import create_viewport, follow_latest, render_viewport
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
from corpus_atelier.task_supervisor import TaskSupervisor


LOGGER = logging.getLogger(__name__)
_VIEWPORT = create_viewport()
ROOT = Path(__file__).resolve().parents[2]
SHOWCASE_ROOT = Path(
    os.environ.get(
        "CORPUS_ATELIER_SHOWCASE_ROOT",
        Path(__file__).resolve().parent / "assets" / "showcase",
    )
).resolve()
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
    "created": ":material/progress_activity:",
    "interpreting_request": ":material/progress_activity:",
    "designing_directions": ":material/progress_activity:",
    "implementing_designs": ":material/progress_activity:",
    "compiling_candidates": ":material/progress_activity:",
    "awaiting_approval": ":material/approval:",
    "generating_candidates": ":material/progress_activity:",
    "awaiting_selection": ":material/select_check_box:",
    "completed": ":material/check_circle:",
    "rejected": ":material/cancel:",
    "failed": ":material/error:",
}
SHOWCASE_PAGE_SIZE = 4


@dataclass(frozen=True)
class ShowcaseItem:
    image_path: Path
    title: str
    featured: bool
    featured_order: int | None


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


def _showcase_items() -> list[ShowcaseItem]:
    manifest_path = SHOWCASE_ROOT / "manifest.json"
    if not manifest_path.is_file():
        return []
    try:
        manifest = _read_json(manifest_path)
    except (OSError, json.JSONDecodeError):
        return []
    if (
        not isinstance(manifest, dict)
        or manifest.get("format_version") != 1
        or not isinstance(manifest.get("items"), list)
    ):
        return []

    items: list[ShowcaseItem] = []
    for entry in manifest["items"]:
        if not isinstance(entry, dict):
            continue
        relative = entry.get("image")
        titles = entry.get("title")
        if not isinstance(relative, str) or not isinstance(titles, dict):
            continue
        image_path = (SHOWCASE_ROOT / relative).resolve()
        if SHOWCASE_ROOT not in image_path.parents or not image_path.is_file():
            continue
        title = titles.get(_language()) or titles.get("en")
        if not isinstance(title, str) or not title.strip():
            continue
        featured_order = entry.get("featured_order")
        if isinstance(featured_order, bool) or not isinstance(
            featured_order, int
        ):
            featured_order = None
        items.append(ShowcaseItem(
            image_path=image_path,
            title=title.strip(),
            featured=entry.get("featured") is True,
            featured_order=featured_order,
        ))
    return items


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


def _app_for_manifest(
    manifest: dict[str, Any],
) -> CorpusAtelierApplication:
    credential = _current_credential()
    return _application_for_manifest(
        manifest,
        credential.value if credential else None,
    )


def _application_for_manifest(
    manifest: dict[str, Any],
    api_key: str | None,
) -> CorpusAtelierApplication:
    model, effort, image_model, image_quality = _model_settings(manifest)
    return _application(
        model,
        effort,
        image_model,
        image_quality,
        api_key,
    )


@st.cache_resource
def _task_supervisor() -> TaskSupervisor:
    return TaskSupervisor(max_workers=2)


def _run_in_background(
    run_id: str,
    manifest: dict[str, Any],
    api_key: str,
    decision: object | None = None,
) -> None:
    app: CorpusAtelierApplication | None = None
    try:
        app = _application_for_manifest(manifest, api_key)
        if decision is None:
            app.continue_task(run_id)
        else:
            app.resume(run_id, decision)
    except Exception as exc:
        LOGGER.exception("Background task %s failed.", run_id)
        store = _task_store()
        try:
            run_dir = store.find_run(run_id)
            current = store.manifest(run_dir)
            if current.get("status") != "failed":
                store.update(
                    run_dir,
                    "failed",
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
        except Exception:
            LOGGER.exception(
                "Could not persist the failure for task %s.", run_id
            )
    finally:
        if app is not None:
            app.close()


def _submit_saved_task(
    summary: RunSummary,
    api_key: str,
    *,
    decision: object | None = None,
) -> bool:
    manifest = dict(summary.manifest)
    return _task_supervisor().submit(
        summary.run_id,
        lambda: _run_in_background(
            summary.run_id,
            manifest,
            api_key,
            decision,
        ),
    )


def _ensure_recoverable_tasks(tasks: list[RunSummary]) -> None:
    credential = _current_credential()
    if credential is None:
        return
    supervisor = _task_supervisor()
    for task in tasks:
        if (
            task.status in RECOVERABLE_TASK_STATUSES
            and not supervisor.is_running(task.run_id)
        ):
            _submit_saved_task(task, credential.value)


def _task_is_live(task: RunSummary) -> bool:
    if task.manifest.get("is_conversation"):
        conversation = load_conversation(task.run_dir)
        if conversation["rounds"]:
            child_id = conversation["rounds"][-1]["run_id"]
            child_root = _task_store().find_run(child_id)
            child_manifest = _task_store().manifest(child_root)
            if _task_supervisor().is_running(child_id) or (
                child_manifest["status"] in RECOVERABLE_TASK_STATUSES
                and _current_credential() is not None
            ):
                return True
    if _task_supervisor().is_running(task.run_id):
        return True
    return (
        task.status in RECOVERABLE_TASK_STATUSES
        and _current_credential() is not None
    )


def _initialize_state() -> None:
    preferences = load_preferences(PREFERENCES_PATH)
    st.session_state.setdefault("ui_language", preferences["language"])
    if st.session_state.ui_language not in SUPPORTED_LANGUAGES:
        st.session_state.ui_language = DEFAULT_LANGUAGE
    st.session_state.setdefault("session_openai_api_key", None)
    st.session_state.setdefault("settings_dialog_open", False)
    st.session_state.setdefault("selected_task_id", None)
    st.session_state.setdefault("product_view", "home")
    st.session_state.setdefault("showcase_page", 1)
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
    st.session_state.product_view = "home"


def _set_product_view(view: str) -> None:
    st.session_state.product_view = view
    if view == "gallery":
        st.session_state.showcase_page = 1


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


def _task_icon(task: RunSummary) -> str:
    if _task_supervisor().is_running(task.run_id):
        return ":material/progress_activity:"
    if (
        task.status in RECOVERABLE_TASK_STATUSES
        and _current_credential() is None
    ):
        return ":material/pause_circle:"
    return STATUS_ICONS.get(task.status, ":material/pending:")


def _render_task_buttons(tasks: list[RunSummary]) -> None:
    tasks = [task for task in tasks if not task.manifest.get("conversation_parent_id")]
    if not tasks:
        st.caption(_t("no_saved_tasks"))
        return

    active_ids = sorted(_task_supervisor().running_ids())
    if active_ids:
        selectors = ",\n".join(
            f'.st-key-task_{run_id} [data-testid="stIconMaterial"]'
            for run_id in active_ids
        )
        st.html(f"""
            <style>
            @keyframes corpus-atelier-task-spin {{
                to {{ transform: rotate(360deg); }}
            }}
            {selectors} {{
                animation: corpus-atelier-task-spin 0.9s linear infinite;
                display: inline-block;
            }}
            </style>
        """)

    with st.container(height=520, gap="small"):
        for task in tasks:
            title = task.manifest.get("title", task.run_id)
            paused = (
                task.status in RECOVERABLE_TASK_STATUSES
                and not _task_supervisor().is_running(task.run_id)
                and _current_credential() is None
            )
            if st.button(
                title,
                icon=_task_icon(task),
                width="stretch",
                key=f"task_{task.run_id}",
                help=(
                    _t("recovery_waiting_for_key")
                    if paused else _status_label(task.status)
                ),
            ):
                _select_task(task.run_id)
                st.rerun(scope="app")


@st.fragment(run_every="1s")
def _render_live_task_buttons() -> None:
    tasks = _saved_tasks()
    _ensure_recoverable_tasks(tasks)
    _render_task_buttons(tasks)
    if not any(_task_is_live(task) for task in tasks):
        st.rerun(scope="app")


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
            disabled=(
                st.session_state.selected_task_id is None
                and st.session_state.product_view == "home"
            ),
        ):
            _select_task(None)
            st.rerun()

        st.caption(_t("tasks"))
        if any(_task_is_live(task) for task in tasks):
            _render_live_task_buttons()
        else:
            _render_task_buttons(tasks)

        with st.container(key="sidebar_footer"):
            open_settings = st.button(
                _t("settings"),
                icon=":material/settings:",
                width="stretch",
                key="open_settings",
            )
            st.caption(f"v{__version__}")
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


def _render_showcase() -> None:
    st.subheader(_t("showcase_heading"))
    items = _showcase_items()
    if not items:
        st.caption(_t("showcase_preparing"))
        return
    featured = [item for item in items if item.featured]
    featured.sort(key=lambda item: (
        item.featured_order is None,
        item.featured_order if item.featured_order is not None else 0,
    ))
    if len(featured) < SHOWCASE_PAGE_SIZE:
        featured_ids = {item.image_path for item in featured}
        featured.extend(
            item for item in items if item.image_path not in featured_ids
        )
    featured = featured[:SHOWCASE_PAGE_SIZE]

    columns = st.columns(
        len(featured),
        gap="small",
        vertical_alignment="top",
    )
    for column, item in zip(columns, featured, strict=True):
        with column.container(
            border=True,
            height="stretch",
            vertical_alignment="center",
            gap="small",
        ):
            st.image(
                item.image_path,
                caption=item.title,
                width="stretch",
                output_format="PNG",
            )

    if len(items) > len(featured):
        with st.container(horizontal_alignment="right"):
            st.button(
                _t("view_all_designs"),
                icon=":material/grid_view:",
                key="showcase_view_all",
                on_click=_set_product_view,
                args=("gallery",),
            )


def _render_showcase_gallery() -> None:
    st.button(
        _t("back_to_creation"),
        icon=":material/arrow_back:",
        key="showcase_back",
        on_click=_set_product_view,
        args=("home",),
    )
    st.title(_t("gallery_title"))
    st.caption(_t("gallery_tagline"))

    items = _showcase_items()
    if not items:
        st.caption(_t("showcase_preparing"))
        return

    total_pages = ceil(len(items) / SHOWCASE_PAGE_SIZE)
    gallery_slot = st.empty()
    with st.container(horizontal_alignment="center"):
        page = st.pagination(total_pages, key="showcase_page")

    start = (page - 1) * SHOWCASE_PAGE_SIZE
    page_items = items[start:start + SHOWCASE_PAGE_SIZE]
    with gallery_slot.container():
        columns = st.columns(
            len(page_items),
            gap="small",
            vertical_alignment="top",
        )
        for column, item in zip(columns, page_items, strict=True):
            with column.container(
                border=True,
                height="stretch",
                vertical_alignment="center",
                gap="small",
            ):
                st.image(
                    item.image_path,
                    caption=item.title,
                    width="stretch",
                    output_format="PNG",
                )


def _start_task(
    request: str,
    *,
    model: str,
    reasoning_effort: str,
    image_model: str,
    profile: str,
    candidate_count: int,
    discuss_first: bool = False,
    attachments: list[tuple[str, bytes]] | None = None,
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
    summary: RunSummary | None = None
    try:
        job = NaturalLanguageDesignJob(
            case_id=PRODUCT_CASE_ID,
            profile=profile,
            request=request,
            candidate_count=candidate_count,
        )
        if discuss_first or attachments:
            result = app.create_conversation(job, attachments=attachments)
        else:
            result = app.create_request(job)
        summary = app.inspect_task(result.run_id)
    except Exception:
        st.error(_t("create_failed"), icon=":material/error:")
    finally:
        app.close()
    if summary is not None:
        _submit_saved_task(summary, credential.value)
        _select_task(summary.run_id)
        st.rerun()


def _render_new_task() -> None:
    st.title(_t("product_name"))
    st.caption(_t("product_tagline"))
    with st.popover(_t("task_settings"), icon=":material/tune:"):
        model, reasoning, image_model, profile, candidate_count = (
            _render_new_task_settings()
        )

    _render_showcase()
    st.subheader(_t("start_from_request"))
    discuss_first = st.toggle(_t("discuss_first"), key="discuss_first")
    st.caption(_t("reference_upload_hint"))
    submission = st.chat_input(
        _t("request_placeholder"),
        key="new_task_prompt",
        submit_mode="disable",
        accept_file="multiple",
        file_type=["png", "jpg", "jpeg", "webp"],
        max_upload_size=10,
    )
    if submission:
        _start_task(
            _submission_text(submission) or _t("reference_only_request"),
            model=model,
            reasoning_effort=reasoning,
            image_model=image_model,
            profile=profile,
            candidate_count=candidate_count,
            discuss_first=discuss_first,
            attachments=_submission_attachments(submission),
        )


def _render_brief_contents(brief: dict, *, include_requirements: bool = True) -> None:
    fields = ("deliverable", "topic", "article_title", "article_summary", "purpose",
              "audience", "use_context", "setting", "art_direction")
    for key in fields:
        if key in brief:
            st.markdown(f"**{_t(key)}:** {brief[key] or _t('brief_unspecified')}")
    ratio = brief.get("canvas", {}).get("aspect_ratio")
    if ratio:
        st.markdown(f"**{_t('brief_canvas')}:** {ratio['width']}:{ratio['height']}")
    groups = ["exact_copy", "constraints", "preferences"]
    if include_requirements:
        groups.append("user_requirements")
    for key in groups:
        if key not in brief:
            continue
        label = "confirmed_user_requirements" if key == "user_requirements" else key
        st.markdown(f"**{_t(label)}:**")
        if brief[key]:
            for item in brief[key]:
                st.markdown(f"- {item}")
        else:
            st.caption(_t("brief_no_copy" if key == "exact_copy" else "brief_unspecified"))


def _render_brief(result: RunResult) -> None:
    brief = read_json_artifact(result, "brief")
    if brief:
        with st.expander(_t("understood_request"), icon=":material/description:"):
            _render_brief_contents(brief)


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


def _resume(summary: RunSummary, decision: object) -> None:
    credential = _current_credential()
    if credential is None:
        st.error(_t("api_key_missing"), icon=":material/key_off:")
        return
    _submit_saved_task(
        summary,
        credential.value,
        decision=decision,
    )
    st.rerun()


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
    _render_generation_preview(result)
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
                HumanDecision(True, reviewer="streamlit-user"),
            )


def _render_image_gallery(
    summary: RunSummary,
    result: RunResult,
    *,
    selectable: bool,
    active: bool = False,
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
                    disabled=active,
                ):
                    _resume(
                        summary,
                        CandidateSelection(candidate_id, reviewer="streamlit-user"),
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
        disabled=active,
    ):
        _resume(
            summary,
            CandidateSelection(None, reviewer="streamlit-user"),
        )


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


def _submission_text(submission) -> str:
    return submission if isinstance(submission, str) else submission.text


def _submission_attachments(submission) -> list[tuple[str, bytes]]:
    if isinstance(submission, str):
        return []
    return [(file.name, file.getvalue()) for file in submission.files]


def _conversation_error(exc: Exception) -> None:
    st.error(_t("conversation_action_failed"))
    with st.expander(_t("conversation_error_details")):
        st.text(str(exc))


def _render_legacy_followup(summary: RunSummary, *, active: bool) -> None:
    if active or summary.status in RECOVERABLE_TASK_STATUSES:
        return
    st.caption(_t("followup_hint"))
    submission = st.chat_input(
        _t("followup_placeholder"), key=f"followup_{summary.run_id}",
        accept_file="multiple", file_type=["png", "jpg", "jpeg", "webp"],
        max_upload_size=10, submit_mode="disable",
        disabled=_current_credential() is None,
    )
    if not submission:
        return
    try:
        with _app_for_manifest(summary.manifest) as app:
            profile_path = summary.run_dir / "profile.json"
            profile = json.loads(profile_path.read_text(encoding="utf-8"))["name"]
            result = app.create_conversation(NaturalLanguageDesignJob(
                case_id=summary.manifest["case_id"], profile=profile,
                request=_submission_text(submission) or _t("reference_only_request"),
                candidate_count=summary.manifest.get("candidate_limit", 1),
            ), attachments=_submission_attachments(submission), previous_run_id=summary.run_id)
            parent = app.inspect_task(result.run_id)
        _submit_saved_task(parent, _current_credential().value)
        _select_task(parent.run_id)
        st.rerun(scope="app")
    except Exception as exc:
        _conversation_error(exc)


def _render_user_requirements(summary: RunSummary, conversation: dict, *, disabled: bool) -> bool:
    """Render the single authoritative brief editor, without a second contract form."""
    revision = conversation["revision"]
    with st.container(border=True, key=f"brief_workspace_{summary.run_id}"):
        st.subheader(_t("design_contract"))
        st.caption(_t("brief_review_hint"))
        if conversation["design_brief"] is None and brief_editor.draft_key(summary.run_id) not in st.session_state:
            st.info(_t("brief_not_ready"))
            return False
        if brief_editor.draft_key(summary.run_id) not in st.session_state:
            brief_editor.load_draft(summary.run_id, conversation)
        draft = st.session_state[brief_editor.draft_key(summary.run_id)]
        stale = draft["base_revision"] != revision
        if stale:
            st.warning(_t("brief_stale_draft"))
        st.caption(_t("brief_editing_revision", revision=draft["source_revision"]))
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
                            source_suggestion_ids=draft["source_suggestion_ids"],
                        )
                    st.session_state.pop(brief_editor.draft_key(summary.run_id), None)
                    st.toast(_t("brief_saved"))
                    st.rerun(scope="app")
                except Exception as exc:
                    _conversation_error(exc)
            st.button(_t("load_latest_brief"), key=f"load_latest_brief_{summary.run_id}",
                      on_click=brief_editor.load_draft, args=(summary.run_id, conversation),
                      disabled=disabled or conversation["design_brief"] is None)
            if stale and dirty:
                st.button(_t("rebase_brief_draft"), key=f"rebase_brief_{summary.run_id}",
                          on_click=lambda: draft.update(base_revision=revision), disabled=disabled)
    return dirty


def _add_assistant_suggestion(run_id, conversation, suggestion, mode, replacement_index):
    try:
        brief_editor.add_suggestion(run_id, conversation, suggestion, mode=mode,
                                    replacement_index=replacement_index)
        follow_latest(run_id)
    except Exception as exc:
        _conversation_error(exc)


def _load_brief_proposal(run_id, conversation, proposal):
    brief_editor.load_draft(run_id, conversation, proposal["brief"],
                            conversation["brief_revision"])
    st.session_state[brief_editor.field_key(run_id, "open_questions")] = "\n".join(proposal["questions"])
    follow_latest(run_id)


def _render_assistant_suggestion(summary, conversation, suggestion, *, disabled, reply):
    identity = suggestion["id"]
    if suggestion["status"] == "dismissed":
        st.caption(_t("suggestion_dismissed", aspect=suggestion["aspect"]))
        return
    if suggestion["text"] not in reply:
        st.markdown(suggestion["text"])
    st.caption(_t("suggestion_destination", aspect=suggestion["aspect"], field=_t(suggestion["field"])))
    if suggestion.get("images"):
        st.caption(_t("suggestion_source", source=" · ".join(item["name"] for item in suggestion["images"])))
    if brief_editor.draft_key(summary.run_id) not in st.session_state:
        st.caption(_t("brief_not_ready"))
        return
    draft = st.session_state[brief_editor.draft_key(summary.run_id)]
    brief, _ = brief_editor.draft_values(summary.run_id)
    field = suggestion["field"]
    if field not in brief:
        return
    entries = brief[field] if field in brief_editor.LIST_FIELDS else None
    replacement_index = None
    mode = "append" if entries is not None else "replace"
    if entries:
        mode = st.selectbox(_t("suggestion_action"), ["append", "replace"],
                            format_func=lambda value: _t(f"suggestion_{value}"),
                            key=f"suggestion_mode_{identity}", disabled=disabled)
        if mode == "replace":
            replacement_index = st.selectbox(_t("suggestion_replace_entry"), list(range(len(entries))),
                                             format_func=lambda index: entries[index],
                                             key=f"suggestion_target_{identity}", disabled=disabled)
    elif entries is None:
        st.caption(_t("suggestion_replace_text"))
    with st.container(horizontal=True):
        st.button(_t("add_to_brief"), key=f"add_suggestion_{identity}",
                  on_click=_add_assistant_suggestion,
                  args=(summary.run_id, conversation, suggestion, mode, replacement_index),
                  disabled=disabled or draft["base_revision"] != conversation["revision"])
        if st.button(_t("ignore_suggestion"), key=f"dismiss_suggestion_{identity}", disabled=disabled):
            try:
                with _app_for_manifest(summary.manifest) as app:
                    app.dismiss_conversation_suggestion(summary.run_id, identity)
                st.rerun(scope="app")
            except Exception as exc:
                _conversation_error(exc)
    if identity in draft["source_suggestion_ids"]:
        st.caption(_t("suggestion_in_draft"))


def _render_conversation_task(summary: RunSummary) -> None:
    try:
        with _app_for_manifest(summary.manifest) as app:
            conversation = app.conversation(summary.run_id)
            rounds = [app.inspect_task(record["run_id"]) for record in conversation["rounds"]]
    except Exception as exc:
        _conversation_error(exc)
        return
    st.title(summary.manifest.get("title", summary.run_id))
    st.caption(_t("conversation_hint"))
    assistant_busy = _task_is_live(summary) or bool(conversation.get("pending"))
    design_busy = any(_task_supervisor().is_running(r.run_id) or r.status in BUSY_ROUND_STATUSES for r in rounds)
    disabled = assistant_busy or design_busy
    history = {entry["revision"]: entry for entry in conversation["brief_history"]}
    view = st.segmented_control(
        _t("workspace_view"), ["split", "design", "assistant"], default="split",
        format_func=lambda value: _t(f"workspace_{value}"), key=f"workspace_view_{summary.run_id}",
        persist_state="session", required=True,
    ) or "split"
    if view == "split":
        design_column, assistant_column = st.columns([2.2, 1], gap="large", vertical_alignment="top")
    else:
        design_column, assistant_column = st.container(), st.container()
    if conversation["design_brief"] is not None and brief_editor.draft_key(summary.run_id) not in st.session_state:
        brief_editor.load_draft(summary.run_id, conversation)
    dirty = brief_editor.draft_dirty(summary.run_id)
    selected_id = st.session_state.get(f"round_{summary.run_id}_{len(rounds)}", rounds[-1].run_id if rounds else None)
    selected_round = next((r for r in rounds if r.run_id == selected_id), None)
    candidate_id = None
    if view != "assistant":
        with design_column, st.container(height=700, key=f"design_panel_{summary.run_id}", autoscroll=False):
            render_viewport(summary.run_id, conversation, label=_t("return_latest_brief"), controller=_VIEWPORT)
            st.html('<div id="atelier-latest-brief" aria-hidden="true"></div>')
            dirty = _render_user_requirements(summary, conversation, disabled=design_busy)
            latest_revision = conversation["rounds"][-1]["revision"] if rounds else -1
            draft = st.session_state.get(brief_editor.draft_key(summary.run_id), {})
            can_prepare = not (
                disabled or not conversation["effective_request"] or conversation["open_questions"]
                or latest_revision == conversation["revision"] or conversation["design_brief"] is None
                or conversation["brief_revision"] != conversation["revision"] or conversation["content_language"] is None
                or _current_credential() is None or dirty or draft.get("base_revision", conversation["revision"]) != conversation["revision"]
            )
            if st.button(_t("prepare_design_round"), type="primary", key=f"prepare_round_{summary.run_id}", disabled=not can_prepare):
                try:
                    with _app_for_manifest(summary.manifest) as app:
                        result = app.create_conversation_round(summary.run_id)
                        child = app.inspect_task(result.run_id)
                    _submit_saved_task(child, _current_credential().value)
                    st.rerun(scope="app")
                except Exception as exc:
                    _conversation_error(exc)
            if rounds:
                selected_id = st.selectbox(
                    _t("design_versions"), options=[r.run_id for r in rounds], index=len(rounds) - 1,
                    key=f"round_{summary.run_id}_{len(rounds)}",
                    format_func=lambda value: _t("design_round", number=next(i for i, r in enumerate(rounds, 1) if r.run_id == value)),
                )
                selected_round = next(r for r in rounds if r.run_id == selected_id)
                record = next(r for r in conversation["rounds"] if r["run_id"] == selected_id)
                stale = selected_id != rounds[-1].run_id or record["revision"] != conversation["revision"]
                if stale:
                    st.caption(_t("historical_round_hint"))
                _render_task(selected_round, embedded=True, actions_allowed=not stale and not disabled)
            with st.expander(_t("brief_version_history")):
                for revision, snapshot in sorted(history.items(), reverse=True):
                    with st.expander(_t("brief_history_revision", revision=revision)):
                        _render_brief_contents(snapshot["brief"])
                        st.button(_t("edit_historical_brief"), key=f"edit_brief_{summary.run_id}_{revision}",
                                  on_click=lambda entry=snapshot: (brief_editor.load_draft(summary.run_id, conversation, entry["brief"], entry["revision"]), follow_latest(summary.run_id)),
                                  disabled=disabled or dirty)
    if view != "design":
        with assistant_column:
            st.subheader(_t("design_assistant"))
            st.caption(_t("assistant_hint"))
            st.caption(_t("assistant_brief_context", revision=conversation["brief_revision"]))
            if selected_round:
                number = next(i for i, record in enumerate(conversation["rounds"], 1) if record["run_id"] == selected_round.run_id)
                st.caption(_t("feedback_round", number=number, candidate=_t("all_candidates")))
                relative = selected_round.manifest.get("artifacts", {}).get("candidate_index")
                if relative:
                    candidates = json.loads((selected_round.run_dir / relative).read_text(encoding="utf-8"))
                    candidate_id = st.selectbox(_t("feedback_candidate"), options=[None, *[c["candidate_id"] for c in candidates]],
                                                format_func=lambda value: value or _t("all_candidates"), key=f"feedback_candidate_{selected_round.run_id}")
            suggestions = {item["id"]: item for item in conversation["assistant_suggestions"]}
            proposals = {item["id"]: item for item in conversation["brief_proposals"]}
            with st.container(height=460, key=f"assistant_messages_{summary.run_id}", autoscroll=False):
                for message in conversation["messages"]:
                    with st.chat_message(message["role"]):
                        if message.get("kind") in {"brief_edit", "brief_refresh"}:
                            st.caption(_t("brief_edit_event" if message["kind"] == "brief_edit" else "brief_refresh_event"))
                        if message["text"]:
                            st.markdown(message["text"])
                        for attachment in message.get("attachments", []):
                            path = (summary.run_dir / attachment["path"]).resolve()
                            if summary.run_dir in path.parents and path.is_file():
                                st.image(path, caption=attachment["name"], width="stretch")
                        if message.get("feedback_run_id"):
                            number = next((i for i, record in enumerate(conversation["rounds"], 1) if record["run_id"] == message["feedback_run_id"]), None)
                            st.caption(_t("feedback_round", number=number, candidate=message.get("candidate_id") or _t("all_candidates")))
                        for question in message.get("questions", []):
                            st.info(question)
                        for identity in message.get("suggestion_ids", []):
                            if identity in suggestions:
                                _render_assistant_suggestion(summary, conversation, suggestions[identity], disabled=assistant_busy,
                                                             reply=message["text"])
                        proposal = proposals.get(message.get("proposal_id"))
                        if proposal:
                            with st.expander(_t("brief_proposal")):
                                current = conversation["design_brief"] or {}
                                for field, proposed in proposal["brief"].items():
                                    if current.get(field) != proposed:
                                        st.markdown(f"**{_t(field)}:**")
                                        st.json({"before": current.get(field), "after": proposed}, expanded=False)
                                if dirty:
                                    st.caption(_t("proposal_preserve_draft"))
                                st.button(_t("load_brief_proposal"), key=f"load_proposal_{proposal['id']}",
                                          on_click=_load_brief_proposal, args=(summary.run_id, conversation, proposal),
                                          disabled=assistant_busy or dirty or proposal["based_on"] != conversation["revision"])
                render_viewport(summary.run_id, conversation, label=_t("return_latest_brief"), controller=_VIEWPORT,
                                surface="assistant_messages")
            if conversation.get("pending"):
                if summary.status == "failed":
                    st.error(_t("conversation_failed"))
                    if st.button(_t("retry_conversation"), key=f"retry_chat_{summary.run_id}", disabled=_task_is_live(summary) or _current_credential() is None):
                        with _app_for_manifest(summary.manifest) as app:
                            app.retry_conversation(summary.run_id)
                            saved = app.inspect_task(summary.run_id)
                        _submit_saved_task(saved, _current_credential().value)
                        st.rerun(scope="app")
                else:
                    st.info(_t("status.discussing_request"))
            submission = st.chat_input(
                _t("followup_placeholder"), key=f"conversation_input_{summary.run_id}",
                accept_file="multiple", file_type=["png", "jpg", "jpeg", "webp"], max_upload_size=10,
                submit_mode="disable", disabled=assistant_busy or _current_credential() is None,
            )
            if submission:
                try:
                    with _app_for_manifest(summary.manifest) as app:
                        app.queue_conversation_message(summary.run_id, _submission_text(submission), attachments=_submission_attachments(submission),
                                                       feedback_run_id=selected_round.run_id if selected_round else None, candidate_id=candidate_id)
                        saved = app.inspect_task(summary.run_id)
                    _submit_saved_task(saved, _current_credential().value)
                    follow_latest(summary.run_id, "assistant_messages")
                    st.rerun(scope="app")
                except Exception as exc:
                    _conversation_error(exc)
            with st.expander(_t("request_brief_proposal")):
                language = conversation["content_language"]
                languages = list(dict.fromkeys(([None] if language is None else []) + ["zh-CN", "en"] + ([language] if language else [])))
                selected_language = st.selectbox(_t("task_content_language"), languages, index=languages.index(language),
                                                 format_func=lambda value: _t("content_language_auto") if value is None else LANGUAGE_LABELS.get(value, value),
                                                 key=f"brief_language_{summary.run_id}_{conversation['revision']}", disabled=assistant_busy)
                if st.button(_t("refresh_brief"), key=f"refresh_brief_{summary.run_id}", disabled=assistant_busy or _current_credential() is None):
                    try:
                        with _app_for_manifest(summary.manifest) as app:
                            app.refresh_conversation_brief(summary.run_id, expected_revision=conversation["revision"], content_language=selected_language)
                            saved = app.inspect_task(summary.run_id)
                        _submit_saved_task(saved, _current_credential().value)
                        follow_latest(summary.run_id, "assistant_messages")
                        st.rerun(scope="app")
                    except Exception as exc:
                        _conversation_error(exc)


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
            st.title(manifest.get("title", summary.run_id))
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

    if not embedded:
        _render_legacy_followup(summary, active=active)


@st.fragment(run_every="1s")
def _render_live_task(run_id: str) -> None:
    tasks = _saved_tasks()
    summary = next(
        (task for task in tasks if task.run_id == run_id),
        None,
    )
    if summary is None:
        st.rerun(scope="app")
        return
    _ensure_recoverable_tasks(tasks)
    _render_task(summary)
    if not _task_is_live(summary) and not summary.manifest.get("is_conversation"):
        st.rerun(scope="app")


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
    _ensure_recoverable_tasks(tasks)
    known_ids = {task.run_id for task in tasks}
    selected = st.session_state.selected_task_id
    if selected is not None and selected not in known_ids:
        _select_task(None)
        selected = None

    _render_sidebar(tasks)
    if selected is None:
        if st.session_state.product_view == "gallery":
            _render_showcase_gallery()
        else:
            _render_new_task()
        return

    summary = next(task for task in tasks if task.run_id == selected)
    if _task_is_live(summary) or summary.manifest.get("is_conversation"):
        _render_live_task(summary.run_id)
    else:
        _render_task(summary)


main()
