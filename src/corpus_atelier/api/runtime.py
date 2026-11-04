"""The process-level task runtime: the one owner of background work.

This replaces the two Streamlit-only pieces of the old boundary: the
``@st.cache_resource`` supervisor and the per-render credential lookup. Nothing
here knows about a browser session, and no provider key is ever passed to a
request handler's caller.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, Callable

from ..app.service import RECOVERABLE_TASK_STATUSES, CorpusAtelierApplication
from ..app.state import RunSummary
from ..app.supervisor import TaskSupervisor
from ..artifacts.store import ArtifactStore
from ..config.models import (
    IMAGE_MODEL_PROFILES,
    TEXT_MODEL_PROFILES,
    get_image_model_profile,
    get_text_model_profile,
    validate_reasoning_effort,
)
from ..config.paths import ProductPaths, resolve_paths
from ..config.settings import ApiCredential, resolve_openai_api_key
from ..prompt_session.records import PromptSessionRecord, load_session
from ..providers import OpenAIImageProvider, OpenAITextProvider
from .errors import credential_missing


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelSelection:
    """The providers one task talks through; recorded in the task manifest."""

    text_model: str
    reasoning_effort: str
    image_model: str
    image_quality: str

    @classmethod
    def default(cls) -> "ModelSelection":
        text = TEXT_MODEL_PROFILES[0]
        return cls(
            text_model=text.model,
            reasoning_effort=text.default_reasoning_effort,
            image_model=IMAGE_MODEL_PROFILES[0].model,
            image_quality="medium",
        )

    @classmethod
    def from_manifest(cls, manifest: dict[str, Any]) -> "ModelSelection":
        """A task is bound to the models it was created with."""
        default = cls.default()
        models = manifest.get("models") if isinstance(manifest.get("models"), dict) else {}
        text = models.get("text") if isinstance(models.get("text"), dict) else {}
        image = models.get("image") if isinstance(models.get("image"), dict) else {}
        return cls(
            text_model=text.get("model") or default.text_model,
            reasoning_effort=text.get("reasoning_effort") or default.reasoning_effort,
            image_model=image.get("model") or default.image_model,
            image_quality=image.get("quality") or default.image_quality,
        )

    def merged(self, choice: Any) -> "ModelSelection":
        """Apply a client's optional model choice without inventing values."""
        if choice is None:
            return self
        return ModelSelection(
            text_model=getattr(choice, "text_model", None) or self.text_model,
            reasoning_effort=(
                getattr(choice, "reasoning_effort", None) or self.reasoning_effort
            ),
            image_model=getattr(choice, "image_model", None) or self.image_model,
            image_quality=getattr(choice, "image_quality", None) or self.image_quality,
        )


class TaskRuntime:
    """One per API process: applications, the supervisor, and the credential."""

    def __init__(
        self,
        *,
        paths: ProductPaths | None = None,
        supervisor: TaskSupervisor | None = None,
        providers: Callable[[ModelSelection, str | None], tuple[Any, Any]] | None = None,
    ):
        self.paths = paths or resolve_paths()
        self.supervisor = supervisor or TaskSupervisor(max_workers=2)
        # Tests inject offline providers; production builds the OpenAI adapters.
        self._providers = providers
        self._session_key: str | None = None
        self._key_lock = Lock()

    # --- credential -----------------------------------------------------

    def credential(self) -> ApiCredential | None:
        return resolve_openai_api_key(self._session_key, env_path=self.paths.env_path)

    def require_credential(self) -> ApiCredential:
        credential = self.credential()
        if credential is None:
            raise credential_missing()
        return credential

    def set_session_key(self, value: str | None) -> None:
        """Hold a key for this process only; it is never written to a task."""
        with self._key_lock:
            self._session_key = value

    # --- task files -----------------------------------------------------

    def store(self) -> ArtifactStore:
        return ArtifactStore(self.paths.tasks_root)

    def summary(self, run_id: str) -> RunSummary:
        store = self.store()
        run_dir = store.find_run(run_id)
        manifest = store.manifest(run_dir)
        return RunSummary(
            run_id=run_id,
            status=manifest["status"],
            run_dir=run_dir,
            manifest=manifest,
        )

    def run_dir(self, run_id: str) -> Path:
        return self.store().find_run(run_id)

    def session(self, run_id: str) -> PromptSessionRecord:
        return load_session(self.run_dir(run_id))

    def list_tasks(self) -> list[RunSummary]:
        return [
            RunSummary(
                run_id=manifest["run_id"],
                status=manifest["status"],
                run_dir=run_dir,
                manifest=manifest,
            )
            for run_dir, manifest in self.store().list_runs()
        ]

    # --- applications ---------------------------------------------------

    def application(
        self, selection: ModelSelection, *, api_key: str | None,
    ) -> CorpusAtelierApplication:
        get_text_model_profile(selection.text_model)
        validate_reasoning_effort(selection.text_model, selection.reasoning_effort)
        get_image_model_profile(selection.image_model)
        if self._providers is not None:
            text_provider, image_provider = self._providers(selection, api_key)
        else:
            text_provider = OpenAITextProvider(
                model=selection.text_model,
                reasoning_effort=selection.reasoning_effort,
                api_key=api_key,
            )
            image_provider = OpenAIImageProvider(
                model=selection.image_model,
                quality=selection.image_quality,
                api_key=api_key,
            )
        return CorpusAtelierApplication(
            runs_root=self.paths.tasks_root,
            text_provider=text_provider,
            image_provider=image_provider,
        )

    def application_for(
        self, run_id: str, *, api_key: str | None,
    ) -> CorpusAtelierApplication:
        summary = self.summary(run_id)
        return self.application(ModelSelection.from_manifest(summary.manifest), api_key=api_key)

    # --- background work ------------------------------------------------

    def is_running(self, run_id: str) -> bool:
        return self.supervisor.is_running(run_id)

    def running_ids(self) -> set[str]:
        return self.supervisor.running_ids()

    def schedule(
        self,
        run_id: str,
        work: Callable[[CorpusAtelierApplication], None],
        *,
        api_key: str | None,
    ) -> bool:
        """Run one durable operation off the request thread; False if already running."""
        summary = self.summary(run_id)
        selection = ModelSelection.from_manifest(summary.manifest)

        def runner() -> None:
            app: CorpusAtelierApplication | None = None
            try:
                app = self.application(selection, api_key=api_key)
                work(app)
            except BaseException as exc:  # noqa: BLE001 - every outcome is recorded
                LOGGER.exception("Background task %s failed.", run_id)
                self._persist_failure(run_id, exc)
            finally:
                if app is not None:
                    app.close()

        return self.supervisor.submit(run_id, runner)

    def _persist_failure(self, run_id: str, exc: BaseException) -> None:
        """Persist a lost worker's failure unless the task already recorded it."""
        try:
            store = self.store()
            run_dir = store.find_run(run_id)
            if store.manifest(run_dir).get("status") != "failed":
                store.fail(run_dir, exc if isinstance(exc, Exception) else Exception(str(exc)))
        except Exception:
            LOGGER.exception("Could not persist the failure for task %s.", run_id)

    def reconcile(self, run_id: str) -> None:
        """Turn an interrupted image submission into an unknown remote outcome.

        Called before reporting a task, so a restarted process never presents an
        interrupted image call as safely retryable.
        """
        try:
            summary = self.summary(run_id)
        except (OSError, ValueError):
            return
        if summary.status != "generating_image" or self.is_running(run_id):
            return
        app = self.application_for(run_id, api_key=None)
        try:
            app.reconcile_prompt_session(run_id)
        except Exception:
            LOGGER.exception("Could not reconcile task %s.", run_id)
        finally:
            app.close()

    def resume_recoverable(self) -> int:
        """Resume interrupted text steps once a credential is available."""
        credential = self.credential()
        if credential is None:
            return 0
        resumed = 0
        for summary in self.list_tasks():
            if not summary.manifest.get("is_prompt_session"):
                continue
            if summary.status not in RECOVERABLE_TASK_STATUSES:
                continue
            if self.supervisor.is_running(summary.run_id):
                continue
            run_id = summary.run_id
            scheduled = self.schedule(
                run_id,
                lambda app, run_id=run_id: app.continue_task(run_id),
                api_key=credential.value,
            )
            if scheduled:
                resumed += 1
        return resumed

    def shutdown(self) -> None:
        self.supervisor.shutdown()
