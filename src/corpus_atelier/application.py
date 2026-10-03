"""UI-neutral application service for durable, approval-gated design tasks."""

from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Callable

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from .artifacts.paths import task_path
from .artifacts.records import read_json
from .artifacts.store import ArtifactStore, validate_case_id, validate_run_id
from .conversation import ConversationMixin, serialized_conversation
from .design_support.validation import validate, validate_candidate_count
from .graphs import build_graph
from .language import bind_brief_language, validate_content_language
from .providers import OpenAIImageProvider, OpenAITextProvider
from .registry import get_profile
from .state import (
    AtelierState,
    DesignJob,
    NaturalLanguageDesignJob,
    RunResult,
    RunSummary,
)
from .workflow_runtime import WorkflowRuntime


RECOVERABLE_TASK_STATUSES = frozenset({
    "discussing_request",
    "created",
    "interpreting_request",
    "designing_directions",
    "implementing_designs",
    "compiling_candidates",
    "generating_candidates",
})


class CorpusAtelierApplication(ConversationMixin):
    def __init__(
        self,
        *,
        runs_root: Path | str = ".atelier/tasks",
        checkpoint_path: Path | str | None = None,
        text_provider=None,
        image_provider=None,
        status_callback: Callable[[str, str], None] | None = None,
    ):
        self.store = ArtifactStore(
            runs_root,
            status_callback=status_callback,
        )
        self.store.root.mkdir(parents=True, exist_ok=True)
        self.runtime = WorkflowRuntime(
            self.store,
            text_provider or OpenAITextProvider(),
            image_provider or OpenAIImageProvider(),
        )
        if checkpoint_path is None:
            checkpoint_path = self.store.root / "_system" / "checkpoints.sqlite3"
        if str(checkpoint_path) == ":memory:":
            checkpoint_target = ":memory:"
        else:
            checkpoint_path = Path(checkpoint_path).resolve()
            checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            checkpoint_target = str(checkpoint_path)
        self._checkpoint_connection = sqlite3.connect(
            checkpoint_target,
            check_same_thread=False,
        )
        self.checkpointer = SqliteSaver(self._checkpoint_connection)
        self.checkpointer.setup()
        self.graph = build_graph(self.runtime, self.checkpointer)

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
        connection = getattr(self, "_checkpoint_connection", None)
        if connection is not None:
            connection.close()
            self._checkpoint_connection = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def _invoke_graph(self, run_id: str, run_dir: Path, input_value: AtelierState | Command | None) -> RunResult:
        config = {"configurable": {"thread_id": run_id}}
        try:
            self.graph.invoke(input_value, config=config)
        except Exception as exc:
            self.store.fail(run_dir, exc)
            raise
        return self._result(run_id)

    @staticmethod
    def _validate_request(request: str) -> str:
        if not isinstance(request, str) or not request.strip():
            raise ValueError("Natural-language design request must not be empty.")
        return request

    @staticmethod
    def _task_title(request: str) -> str:
        title = " ".join(request.split())
        return title if len(title) <= 56 else f"{title[:55]}…"

    def start(self, job: DesignJob) -> RunResult:
        profile = get_profile(job.profile)
        candidate_count = validate_candidate_count(job.candidate_count)
        content_language = validate_content_language(job.content_language or job.brief.get("content_language"))
        brief = validate(bind_brief_language(job.brief, content_language), profile.brief_schema)
        run_id, run_dir = self.store.create(
            case_id=job.case_id,
            brief=brief,
            profile=profile,
            title=job.case_id,
            models=self._models(),
            candidate_limit=candidate_count,
            content_language=content_language,
        )
        state = {
            "case_id": job.case_id,
            "run_id": run_id,
            "run_dir": str(run_dir),
            "profile": profile.name,
            "brief": brief,
            "content_language": content_language,
            "candidate_limit": candidate_count,
            "status": "created",
        }
        return self._invoke_graph(run_id, run_dir, state)

    def create_request(self, job: NaturalLanguageDesignJob, *,
                       is_conversation: bool = False,
                       conversation_parent_id: str | None = None,
                       conversation_revision: int | None = None,
                       conversation_state: dict | None = None,
                       conversation_snapshot: dict | None = None) -> RunResult:
        self._validate_request(job.request)
        content_language = validate_content_language(job.content_language)
        if conversation_state is not None:
            content_language = validate_content_language(conversation_state.get("content_language"))
        candidate_count = validate_candidate_count(job.candidate_count)
        profile = get_profile(job.profile)
        run_id, run_dir = self.store.create(
            case_id=job.case_id,
            request=job.request,
            profile=profile,
            title=self._task_title(job.request),
            models=self._models(),
            candidate_limit=candidate_count,
            is_conversation=is_conversation,
            conversation_parent_id=conversation_parent_id,
            conversation_revision=conversation_revision,
            conversation_state=conversation_state,
            conversation_snapshot=conversation_snapshot,
            content_language=content_language,
        )
        return self._result(run_id)

    def run_request(self, run_id: str) -> RunResult:
        run_dir = self.store.find_run(run_id)
        manifest = self.store.manifest(run_dir)
        if manifest["status"] != "created":
            raise ValueError("This natural-language task has already started.")
        try:
            state = self._load_request_state(run_dir, manifest)
        except Exception as exc:
            self.store.fail(run_dir, exc)
            raise
        return self._invoke_graph(run_id, run_dir, state)

    def _load_request_state(self, run_dir: Path, manifest: dict) -> AtelierState:
        if manifest.get("input_mode") != "natural_language":
            raise ValueError("Only natural-language tasks can use run_request().")
        self._assert_model_binding(run_dir)
        profile = get_profile(read_json(run_dir / "profile.json")["name"])
        request_relative = manifest.get("artifacts", {}).get("user_request")
        if not isinstance(request_relative, str):
            raise ValueError("Natural-language task request is missing.")
        request = self._validate_request(task_path(run_dir, request_relative).read_text(encoding="utf-8"))
        state: AtelierState = {
            "case_id": manifest["case_id"],
            "run_id": manifest["run_id"],
            "run_dir": str(run_dir),
            "profile": profile.name,
            "user_request": request,
            "content_language": validate_content_language(manifest.get("content_language")),
            "candidate_limit": validate_candidate_count(manifest.get("candidate_limit")),
            "status": "created",
        }
        snapshot_relative = manifest.get("artifacts", {}).get("conversation_snapshot")
        if snapshot_relative:
            snapshot = read_json(task_path(run_dir, snapshot_relative))
            self._bind_conversation_snapshot(state, snapshot, manifest)
        return state

    def _bind_conversation_snapshot(self, state: AtelierState, snapshot: dict, manifest: dict) -> None:
        """Use the reviewed brief as graph input and verify its revision and language."""
        if not isinstance(snapshot, dict):
            raise ValueError("The conversation snapshot must be an object.")
        language = state["content_language"]
        snapshot_language = validate_content_language(snapshot.get("content_language"))
        if snapshot_language and language and snapshot_language != language:
            raise ValueError("The saved task language differs from the conversation snapshot.")
        language = language or snapshot_language
        if "user_requirements" in snapshot:
            state["user_requirements"] = snapshot["user_requirements"]
            state["superseded_user_requirements"] = snapshot.get("superseded_user_requirements", [])
        if snapshot.get("design_brief") is not None:
            if snapshot.get("brief_revision") != manifest.get("conversation_revision"):
                raise ValueError("The saved design brief belongs to a different conversation revision.")
            brief = validate(snapshot["design_brief"], get_profile(state["profile"]).brief_schema)
            if brief.get("content_language") and language and brief["content_language"] != language:
                raise ValueError("The saved brief differs from the task content language.")
            language = language or brief.get("content_language")
            if brief.get("user_requirements", []) != snapshot.get("user_requirements", []):
                raise ValueError("The saved design brief changed the confirmed user requirements.")
            state.pop("user_request")
            state["brief"] = brief
            run_dir = Path(state["run_dir"])
            self.store.json(run_dir, "brief.json", brief)
            self.store.register(run_dir, brief="brief.json")
        state["content_language"] = language

    def start_request(self, job: NaturalLanguageDesignJob) -> RunResult:
        created = self.create_request(job)
        return self.run_request(created.run_id)

    def continue_task(self, run_id: str) -> RunResult:
        """Continue a saved task from its latest durable graph checkpoint."""
        run_dir = self.store.find_run(run_id)
        manifest = self.store.manifest(run_dir)
        if manifest.get("is_conversation"):
            return self.run_conversation(run_id)
        if manifest["status"] == "created":
            return self.run_request(run_id)
        if manifest["status"] not in RECOVERABLE_TASK_STATUSES:
            raise ValueError("This task is not in a recoverable running state.")
        self._assert_model_binding(run_dir)
        config = {"configurable": {"thread_id": run_id}}
        try:
            checkpoint = self.graph.get_state(config)
            if not checkpoint.values or not checkpoint.next:
                raise ValueError(
                    "This task does not have a resumable workflow checkpoint."
                )
        except Exception as exc:
            self.store.fail(run_dir, exc)
            raise
        return self._invoke_graph(run_id, run_dir, None)

    def _assert_model_binding(self, run_dir: Path) -> None:
        expected = self.store.manifest(run_dir).get("models")
        if expected is not None and expected != self._models():
            raise ValueError(
                "Configured models changed after this task was created."
            )

    @serialized_conversation
    def resume(self, run_id: str, decision: object) -> RunResult:
        run_dir = self.store.find_run(run_id)
        manifest = self.store.manifest(run_dir)
        if manifest["status"] not in {"awaiting_approval", "awaiting_selection"}:
            raise ValueError("This task is not waiting for a user decision.")
        parent_id = manifest.get("conversation_parent_id")
        if parent_id and manifest["status"] == "awaiting_approval":
            conversation = self.conversation(parent_id)
            latest = conversation["rounds"][-1]
            if (conversation.get("pending") or latest["run_id"] != run_id
                    or latest["revision"] != conversation["revision"]):
                raise ValueError("This design round is superseded by newer conversation requirements.")
        self._assert_model_binding(run_dir)
        if not hasattr(decision, "to_dict"):
            raise TypeError("A resumable decision must provide to_dict().")
        return self._invoke_graph(run_id, run_dir, Command(resume=decision.to_dict()))

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

    def open_task(self, run_id: str) -> RunResult:
        return self._result(run_id)

    def _result(self, run_id: str) -> RunResult:
        run_dir = self.store.find_run(run_id)
        manifest = self.store.manifest(run_dir)
        summary = RunSummary(
            run_id=run_id,
            status=manifest["status"],
            run_dir=run_dir,
            manifest=manifest,
        )
        registered = summary.manifest.get("artifacts", {})
        paths = {
            "manifest": summary.run_dir / "manifest.json",
            "proposal": summary.run_dir / "design/proposal.json",
            "presentation": summary.run_dir / "design/presentation.md",
            "generation_prompt": summary.run_dir / "generation/prompt.md",
            "image": Path(summary.manifest.get("latest_image", "")),
            "review": (
                summary.run_dir
                / registered.get("review", "review/review.json")
            ),
        }
        for name, relative in registered.items():
            paths[name] = summary.run_dir / relative

        artifacts = {
            name: str(path.resolve())
            for name, path in paths.items()
            if str(path) and path.is_file()
        }
        messages = {
            "awaiting_approval": (
                "Review the saved design proposals and exact image requests."
            ),
            "awaiting_selection": (
                "Review the generated candidates and select one or discard all."
            ),
            "rejected": "Image generation was cancelled; the task remains saved.",
            "completed": "The task completed and its artifacts were saved.",
            "failed": "The task failed; inspect its saved attempts and error record.",
        }
        return RunResult(
            run_id=run_id,
            status=summary.status,
            run_dir=summary.run_dir,
            message=messages.get(summary.status, summary.status),
            artifacts=artifacts,
        )
