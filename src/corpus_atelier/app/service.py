"""Application service for durable, prompt-centered design sessions.

The service owns every state transition of the saved task: creation, listing,
inspection and deletion. The prompt-session workflow itself lives in
``corpus_atelier.prompt_session`` and is mixed in here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..artifacts.paths import task_path
from ..artifacts.store import ArtifactStore, validate_case_id, validate_run_id
from ..prompt_session.service import PromptSessionMixin
from ..providers import OpenAIImageProvider, OpenAITextProvider
from .state import PromptSessionJob, RunResult, RunSummary


LOGGER = logging.getLogger(__name__)


# Steps a background worker may still be expected to finish after an interruption.
RECOVERABLE_TASK_STATUSES = frozenset({
    "created",
    "discussing_request",
    "extracting",
})


@dataclass(frozen=True)
class Providers:
    """The two model ports one prompt session talks through."""

    text_provider: Any
    image_provider: Any


class CorpusAtelierApplication(PromptSessionMixin):
    """Every durable operation of the prompt-centered design workflow."""

    def __init__(
        self,
        *,
        runs_root: Path | str = ".atelier/tasks",
        text_provider=None,
        image_provider=None,
        status_callback: Callable[[str, str], None] | None = None,
    ):
        self.store = ArtifactStore(runs_root, status_callback=status_callback)
        self.store.root.mkdir(parents=True, exist_ok=True)
        self.runtime = Providers(
            text_provider or OpenAITextProvider(),
            image_provider or OpenAIImageProvider(),
        )

    @staticmethod
    def _provider_record(provider, *, fields: tuple[str, ...]) -> dict:
        record = {
            "adapter": f"{type(provider).__module__}.{type(provider).__name__}",
        }
        for field in fields:
            value = getattr(provider, field, None)
            if value is not None:
                record[field] = value
        return record

    def _models(self) -> dict:
        return {
            "text": self._provider_record(
                self.runtime.text_provider,
                fields=("model", "reasoning_effort"),
            ),
            "image": self._provider_record(
                self.runtime.image_provider,
                fields=("model", "quality"),
            ),
        }

    def close(self) -> None:
        """Release resources; the service holds no long-lived connection."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    @staticmethod
    def _validate_request(request: str) -> str:
        if not isinstance(request, str) or not request.strip():
            raise ValueError("Natural-language design request must not be empty.")
        return request

    @staticmethod
    def _task_title(request: str) -> str:
        title = " ".join(request.split())
        return title if len(title) <= 56 else f"{title[:55]}…"

    def create_request(self, job: PromptSessionJob) -> RunResult:
        """Create one saved task directory and return its identity."""
        self._validate_request(job.request)
        run_id, _ = self.store.create(
            case_id=job.case_id,
            request=job.request,
            title=self._task_title(job.request),
            models=self._models(),
        )
        return self._result(run_id)

    def continue_task(self, run_id: str) -> RunResult:
        """Continue the one pending text step of a saved prompt session."""
        run_dir = self.store.find_run(run_id)
        manifest = self.store.manifest(run_dir)
        if not manifest.get("is_prompt_session"):
            raise ValueError(
                "This task was created by a retired workflow and cannot continue."
            )
        return self.continue_prompt_session(run_id)

    def _assert_model_binding(self, run_dir: Path) -> None:
        expected = self.store.manifest(run_dir).get("models")
        if expected is not None and expected != self._models():
            raise ValueError(
                "Configured models changed after this task was created."
            )

    def list_tasks(self) -> list[RunSummary]:
        return [
            RunSummary(
                run_id=manifest["run_id"],
                status=manifest["status"],
                run_dir=run_dir,
                manifest=manifest,
            )
            for run_dir, manifest in self.store.list_runs()
        ]

    def delete_task(self, run_id: str) -> list[str]:
        """Permanently delete one task directory."""
        self.store.delete(self.store.find_run(run_id))
        return [run_id]

    def inspect_task(self, run_id: str) -> RunSummary:
        run_dir = self.store.find_run(run_id)
        manifest = self.store.manifest(run_dir)
        return RunSummary(
            run_id=run_id,
            status=manifest["status"],
            run_dir=run_dir,
            manifest=manifest,
        )

    def inspect(self, case_id: str, run_id: str) -> RunSummary:
        case_id = validate_case_id(case_id)
        run_id = validate_run_id(run_id)
        run_dir = (self.store.root / case_id / run_id).resolve(strict=True)
        if self.store.root not in run_dir.parents:
            raise ValueError("Run id escapes the task store.")
        manifest = self.store.manifest(run_dir)
        return RunSummary(
            run_id=run_id,
            status=manifest["status"],
            run_dir=run_dir,
            manifest=manifest,
        )

    def _result(self, run_id: str) -> RunResult:
        run_dir = self.store.find_run(run_id)
        manifest = self.store.manifest(run_dir)
        artifacts = {}
        for name, relative in (manifest.get("artifacts") or {}).items():
            try:
                path = task_path(run_dir, relative)
            except (OSError, ValueError):
                continue
            if path.is_file():
                artifacts[name] = str(path)
        messages = {
            "created": "The saved task is ready to start.",
            "prompt_ready": "The current prompt is ready for an explicit image action.",
            "discussing_request": "A reply to the last message is pending.",
            "extracting": "Estimating a prompt from the source image.",
            "generating_image": "The frozen image request is running.",
            "outcome_unknown": (
                "The image request was interrupted before its outcome was known; "
                "prepare a new explicit request to try again."
            ),
            "failed": "The task failed; inspect its saved attempts and error record.",
        }
        return RunResult(
            run_id=run_id,
            status=manifest["status"],
            run_dir=run_dir,
            message=messages.get(manifest["status"], manifest["status"]),
            artifacts=artifacts,
        )
