"""Application, task, and session plumbing shared by the studio views."""

from __future__ import annotations

import logging
from typing import Any
import streamlit as st
from corpus_atelier.app.service import (
    RECOVERABLE_TASK_STATUSES,
    CorpusAtelierApplication,
)
from corpus_atelier.artifacts.store import ArtifactStore
from corpus_atelier.ui.i18n import translate
from corpus_atelier.config.languages import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES
from corpus_atelier.config.paths import resolve_paths
from corpus_atelier.config.models import (
    IMAGE_MODEL_PROFILES,
    TEXT_MODEL_PROFILES,
    get_image_model_profile,
    get_text_model_profile,
    validate_reasoning_effort,
)
from corpus_atelier.providers import OpenAIImageProvider, OpenAITextProvider
from corpus_atelier.corpus.index import CorpusStore
from corpus_atelier.config.settings import (
    ApiCredential,
    load_preferences,
    resolve_openai_api_key,
    save_preferences,
)
from corpus_atelier.app.state import RunResult, RunSummary
from corpus_atelier.app.supervisor import TaskSupervisor

LOGGER = logging.getLogger(__name__)


PRODUCT_CASE_ID = "natural-language"


TERMINAL_STATUSES = {"completed", "rejected", "failed"}


# The studio runs one general design profile with one route policy: the brief decides
# whether a round explores directions, and the direct route renders a single image.
DEFAULT_PROFILE = "general-graphic"
DEFAULT_CANDIDATE_LIMIT = 3
DEFAULT_GENERATION_MODE = "auto"


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


def _language() -> str:
    return st.session_state.get("ui_language", DEFAULT_LANGUAGE)


def _t(key: str, **values: Any) -> str:
    return translate(_language(), key, **values)


def _one_line(value: str) -> str:
    return " ".join(str(value).split())


def _display_title(value: str, *, limit: int) -> str:
    """Keep one readable line for headings and list rows; full text stays in help."""
    text = _one_line(value)
    if len(text) <= limit:
        return text
    return text[:limit].rstrip("，,、;；:： ") + "…"


def _task_row_title(task: RunSummary) -> str:
    limit = 11 if _language() == "zh-CN" else 22
    return _display_title(task.manifest.get("title", task.run_id), limit=limit)


def _status_label(status: str) -> str:
    return _t(f"status.{status}")


def _result_message(result: RunResult) -> str:
    key = f"result.{result.status}"
    value = _t(key)
    return result.message if value == key else value


def _current_credential() -> ApiCredential | None:
    return resolve_openai_api_key(
        st.session_state.get("session_openai_api_key"),
        env_path=resolve_paths().env_path,
    )


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
    paths = resolve_paths()
    return CorpusAtelierApplication(
        runs_root=paths.tasks_root,
        corpus_db_path=paths.corpus_db_path,
        corpus_media_root=paths.corpus_media_root,
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
    return ArtifactStore(resolve_paths().tasks_root)


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
                store.fail(run_dir, exc)
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
    if _task_supervisor().is_running(task.run_id):
        return True
    return (
        task.status in RECOVERABLE_TASK_STATUSES
        and _current_credential() is not None
    )


def _initialize_state() -> None:
    preferences = load_preferences(resolve_paths().preferences_path)
    st.session_state.setdefault("ui_language", preferences["language"])
    if st.session_state.ui_language not in SUPPORTED_LANGUAGES:
        st.session_state.ui_language = DEFAULT_LANGUAGE
    st.session_state.setdefault("session_openai_api_key", None)
    st.session_state.setdefault("settings_dialog_open", False)
    st.session_state.setdefault("selected_task_id", None)
    st.session_state.setdefault("product_view", "studio")
    st.session_state.setdefault("product_view_tabs", "studio")
    st.session_state.setdefault("product_view_pending", None)
    st.session_state.setdefault("new_task_model", _default_text_model())
    st.session_state.setdefault("new_task_image_model", _default_image_model())
    st.session_state.setdefault("new_task_reasoning", "medium")
    st.session_state.setdefault("new_task_quality", "medium")
    st.session_state.setdefault("new_task_ratio", (16, 9))


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
    st.session_state.product_view = "studio"
    st.session_state["product_view_pending"] = "studio"


def _sync_product_view_tabs() -> None:
    """Apply programmatic view changes before the tabs widget is rendered."""
    pending = st.session_state.pop("product_view_pending", None)
    if pending is not None:
        st.session_state["product_view_tabs"] = pending


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
    save_preferences(resolve_paths().preferences_path, {"language": language})
    st.session_state.ui_language = language


def _task_icon(task: RunSummary) -> str:
    if _task_supervisor().is_running(task.run_id):
        return ":material/progress_activity:"
    if (
        task.status in RECOVERABLE_TASK_STATUSES
        and _current_credential() is None
    ):
        return ":material/pause_circle:"
    return STATUS_ICONS.get(task.status, ":material/pending:")


def _corpus_store() -> CorpusStore:
    db_path = resolve_paths().corpus_db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return CorpusStore(db_path)


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
