"""Durable design conversations whose generation rounds remain text-only."""

from __future__ import annotations

from copy import deepcopy
from functools import wraps
from io import BytesIO
import json
from pathlib import Path
from threading import Lock, RLock
from uuid import uuid4
from weakref import WeakValueDictionary

from PIL import Image

from .artifacts.hashing import digest_file
from .artifacts.records import read_json, write_json
from .artifacts.paths import verified_image
from .conversation_records import (
    FORMAT_VERSION, ConversationRecord, load_conversation, new_conversation, now, record_brief,
)
from .design_support.validation import validate
from .language import validate_content_language
from .registry import get_profile
from .state import NaturalLanguageDesignJob, RunResult, RunSummary


BUSY_ROUND_STATUSES = frozenset({
    "created", "interpreting_request", "designing", "designing_directions",
    "implementing_designs", "compiling_candidates", "generating_candidates",
})

_LOCKS = WeakValueDictionary()
_LOCKS_GUARD = Lock()


def serialized_conversation(method):
    """Serialize mutations across application instances in the local server."""
    @wraps(method)
    def wrapped(self, run_id, *args, **kwargs):
        root = self.store.find_run(run_id)
        parent_id = self.store.manifest(root).get("conversation_parent_id")
        key = str(self.store.find_run(parent_id) if parent_id else root)
        with _LOCKS_GUARD:
            lock = _LOCKS.get(key)
            if lock is None:
                lock = RLock()
                _LOCKS[key] = lock
        with lock:
            return method(self, run_id, *args, **kwargs)
    return wrapped


def validate_attachments(attachments: list[tuple[str, bytes]]) -> list[tuple[str, bytes]]:
    """Validate uploads without changing the archived source bytes."""
    if len(attachments) > 3:
        raise ValueError("Attach at most three reference images per message.")
    normalized = []
    for name, data in attachments:
        if len(data) > 10 * 1024 * 1024:
            raise ValueError("Each reference image must be at most 10 MB.")
        with Image.open(BytesIO(data)) as image:
            if image.format not in {"PNG", "JPEG", "WEBP"}:
                raise ValueError("Reference images must be PNG, JPEG, or WebP.")
            if image.width * image.height > 20_000_000:
                raise ValueError("Reference images must be at most 20 megapixels.")
            image.load()
            normalized.append((Path(name).name, data))
    return normalized


class ConversationMixin:
    """Application methods kept separate from the single-round graph runtime."""

    def conversation(self, run_id: str) -> ConversationRecord:
        root = self.store.find_run(run_id)
        return load_conversation(root)

    def _save_conversation(self, root: Path, value: ConversationRecord) -> None:
        write_json(root / "conversation.json", value)

    @serialized_conversation
    def save_conversation_brief(self, run_id: str, brief: dict, *, expected_revision: int,
                                source_revision: int | None = None,
                                open_questions: list[str] | None = None) -> RunResult:
        """Make a user-edited brief authoritative without invoking a model."""
        root, value = self._conversation_idle(run_id)
        if expected_revision != value["revision"]:
            raise ValueError("The brief changed. Review the latest version before saving your draft.")
        if source_revision is not None and not any(
                item["revision"] == source_revision for item in value["brief_history"]):
            raise ValueError("The source brief revision does not exist.")
        brief = deepcopy(validate(brief, get_profile(value["profile"]).brief_schema))
        language = validate_content_language(brief.get("content_language"))
        if not language:
            raise ValueError("Establish the brief's task content language before saving.")
        requirements = brief.get("user_requirements", [])
        if any(not item.strip() for item in requirements):
            raise ValueError("User requirements must be distinct, nonempty strings.")
        questions = value["open_questions"] if open_questions is None else open_questions
        if not isinstance(questions, list) or any(not isinstance(q, str) or not q.strip() for q in questions):
            raise ValueError("Open questions must be nonempty strings.")
        if brief == value["design_brief"] and questions == value["open_questions"]:
            self._sync_saved_brief(root, value)
            return self._result(run_id)
        value["revision"] += 1
        value.update(design_brief=brief, brief_revision=value["revision"], format_version=FORMAT_VERSION,
                     user_requirements=list(requirements),
                     open_questions=list(questions), content_language=language)
        value["effective_request"] = "User-confirmed design brief:\n" + json.dumps(brief, ensure_ascii=False)
        record_brief(value, origin="user", based_on=(
            source_revision if source_revision is not None else expected_revision))
        self._save_conversation(root, value)
        self._sync_saved_brief(root, value, refresh_manifest=True)
        return self._result(run_id)

    def _sync_saved_brief(self, root: Path, value: ConversationRecord, *, refresh_manifest: bool = False) -> None:
        """Publish derived artifacts after the authoritative brief record is saved."""
        brief = value["design_brief"]
        if brief is None:
            return
        try:
            saved_brief = read_json(root / "brief.json")
        except (OSError, ValueError):
            saved_brief = None
        changed = saved_brief != brief
        if changed:
            self.store.json(root, "brief.json", brief)
        manifest = self.store.manifest(root)
        artifacts = {**manifest.get("artifacts", {}), "brief": "brief.json"}
        if (refresh_manifest or changed or manifest.get("artifacts") != artifacts
                or manifest.get("content_language") != value["content_language"]
                or manifest["status"] != "discussing" or manifest.get("error") is not None):
            self.store.update(root, "discussing", error=None, artifacts=artifacts,
                              content_language=value["content_language"])


    def _conversation_idle(self, run_id: str) -> tuple[Path, ConversationRecord]:
        root = self.store.find_run(run_id)
        value = self.conversation(run_id)
        if value.get("pending"):
            raise ValueError("Wait for the current conversation response or retry it.")
        self._assert_model_binding(root)
        for round_record in value["rounds"]:
            if self.inspect_task(round_record["run_id"]).status in BUSY_ROUND_STATUSES:
                raise ValueError("Wait for the current design round to finish processing.")
        return root, value

    def create_conversation(self, job: NaturalLanguageDesignJob, *,
                            attachments: list[tuple[str, bytes]] | None = None,
                            previous_run_id: str | None = None) -> RunResult:
        normalized = validate_attachments(list(attachments or []))
        self._validate_request(job.request)
        previous = None
        if previous_run_id is not None:
            previous = self.inspect_task(previous_run_id)
            if previous.manifest.get("is_conversation") or previous.manifest.get("conversation_parent_id"):
                raise ValueError("This task already belongs to a conversation.")
            if previous.status in BUSY_ROUND_STATUSES:
                raise ValueError("Wait for the design task to finish processing.")
            self._assert_model_binding(previous.run_dir)
        value = new_conversation(job.profile, job.request, validate_content_language(job.content_language))
        if previous is not None:
            self._import_previous_round(value, previous, job)
        result = self.create_request(job, is_conversation=True, conversation_state=value)
        self.store.update(result.run_dir, "discussing", is_conversation=True,
                          title=previous.manifest["title"] if previous else self._task_title(job.request))
        if previous:
            self.store.update(previous.run_dir, previous.status, conversation_parent_id=result.run_id)
        self._queue_message(result.run_id, job.request, normalized)
        return self._result(result.run_id)

    def _import_previous_round(self, value: ConversationRecord, previous: RunSummary,
                               job: NaturalLanguageDesignJob) -> None:
        """Promote an existing single-round task without changing its frozen brief."""
        artifacts = previous.manifest.get("artifacts", {})
        request_path = artifacts.get("user_request")
        original = (previous.run_dir / request_path).read_text(encoding="utf-8") if request_path else ""
        value["messages"].append({
            "role": "user", "text": original, "attachments": [], "created_at": now(),
        })
        value["effective_request"] = original
        value["language_source_request"] = original or job.request
        value["content_language"] = job.content_language or previous.manifest.get("content_language")
        if artifacts.get("brief"):
            value["design_brief"] = read_json(previous.run_dir / artifacts["brief"])
            value["brief_revision"] = 0
            value["user_requirements"] = value["design_brief"].get("user_requirements", [])
            value["brief_history"].append({
                "revision": 0, "brief": deepcopy(value["design_brief"]),
                "origin": "legacy", "created_at": previous.manifest["created_at"],
            })
        value["rounds"].append({
            "run_id": previous.run_id, "revision": 0, "created_at": previous.manifest["created_at"],
        })


    def _round_context(self, run_id: str, candidate_id: str | None = None) -> tuple[dict, list[Path]]:
        summary = self.inspect_task(run_id)
        relative = summary.manifest.get("artifacts", {}).get("candidate_index")
        if not relative:
            return {"run_id": run_id, "candidates": []}, []
        candidates = read_json(summary.run_dir / relative)
        if candidate_id is not None and candidate_id not in {c["candidate_id"] for c in candidates}:
            raise ValueError("The feedback candidate does not exist in this round.")
        selected_id = candidate_id
        images = []
        records = []
        for candidate in candidates:
            if selected_id is not None and candidate["candidate_id"] != selected_id:
                continue
            record = {key: candidate.get(key) for key in (
                "candidate_id", "proposal", "generation_prompt", "status",
            )}
            if candidate.get("image_path"):
                path = verified_image(summary.run_dir, candidate["image_path"], candidate.get("image_sha256"))
                images.append(path)
                record["image_label"] = f"Previous result image {len(images)}"
            records.append(record)
        return {"run_id": run_id, "candidates": records}, images

    @serialized_conversation
    def queue_conversation_message(self, run_id: str, text: str, *,
                                   attachments: list[tuple[str, bytes]] | None = None,
                                   feedback_run_id: str | None = None,
                                   candidate_id: str | None = None) -> RunResult:
        return self._queue_message(run_id, text, validate_attachments(list(attachments or [])),
                                   feedback_run_id=feedback_run_id, candidate_id=candidate_id)

    def _queue_message(self, run_id: str, text: str, normalized: list[tuple[str, bytes]], *,
                       feedback_run_id: str | None = None, candidate_id: str | None = None) -> RunResult:
        if not isinstance(text, str) or (not text.strip() and not normalized):
            raise ValueError("Send a message or attach a reference image.")
        root = self.store.find_run(run_id)
        value = self.conversation(run_id)
        if value.get("pending"):
            raise ValueError("Wait for the current conversation response or retry it.")
        self._assert_model_binding(root)
        if feedback_run_id is None and value["rounds"]:
            feedback_run_id = value["rounds"][-1]["run_id"]
        context, images = {}, []
        if feedback_run_id is not None:
            if feedback_run_id not in {r["run_id"] for r in value["rounds"]}:
                raise ValueError("Feedback must refer to a round of this conversation.")
            context, images = self._round_context(feedback_run_id, candidate_id)
        message_id = uuid4().hex
        attached = []
        for index, (name, data) in enumerate(normalized, 1):
            with Image.open(BytesIO(data)) as image:
                suffix = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp"}[image.format]
            relative = f"references/{message_id}/{index}.{suffix}"
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            attached.append({"name": name, "path": relative, "sha256": digest_file(target)})
        value["messages"].append({
            "id": message_id, "role": "user", "text": text,
            "attachments": attached, "feedback_run_id": feedback_run_id,
            "candidate_id": candidate_id, "created_at": now(),
        })
        value["pending"] = {
            "message_id": message_id, "context": context,
            "images": [{"path": str(path), "sha256": digest_file(path)} for path in images],
        }
        self._save_conversation(root, value)
        self.store.update(root, "discussing_request", error=None)
        return self._result(run_id)

    @serialized_conversation
    def run_conversation(self, run_id: str) -> RunResult:
        root = self.store.find_run(run_id)
        self._assert_model_binding(root)
        value = self.conversation(run_id)
        pending = value.get("pending")
        if not pending:
            self.store.update(root, "discussing", error=None)
            return self._result(run_id)
        from .assistant import run_assistant_turn
        return run_assistant_turn(self, run_id, root, value, pending)

    @serialized_conversation
    def retry_conversation(self, run_id: str) -> RunResult:
        root = self.store.find_run(run_id)
        self._assert_model_binding(root)
        value = self.conversation(run_id)
        if self.store.manifest(root)["status"] != "failed":
            raise ValueError("There is no failed conversation response to retry.")
        if value.get("pending"):
            self.store.update(root, "discussing_request", error=None)
        elif value["messages"] and value["messages"][-1]["role"] == "assistant":
            # The reply committed before the manifest update failed; no model call is needed.
            self._sync_saved_brief(root, value)
            self.store.update(root, "discussing", error=None)
        else:
            raise ValueError("There is no failed conversation response to retry.")
        return self._result(run_id)

    @serialized_conversation
    def create_conversation_round(self, run_id: str) -> RunResult:
        root, value = self._conversation_idle(run_id)
        if not value["effective_request"]:
            raise ValueError("Write and save a design brief before preparing a round.")
        if value["open_questions"]:
            raise ValueError("Answer the outstanding design questions before preparing a round.")
        if value["design_brief"] is None or value["brief_revision"] != value["revision"]:
            raise ValueError("Update and review the current design brief before preparing a round.")
        if value["content_language"] is None:
            raise ValueError("Select the brief's task content language in the editor before saving.")
        if value["design_brief"].get("content_language") != value["content_language"]:
            raise ValueError("The current design brief does not match the task content language.")
        validate(value["design_brief"], get_profile(value["profile"]).brief_schema)
        if value["design_brief"].get("user_requirements", []) != value["user_requirements"]:
            raise ValueError("The current design brief does not match the confirmed user requirements.")
        if value["rounds"] and value["rounds"][-1]["revision"] == value["revision"]:
            raise ValueError("Edit and save the brief before preparing another round.")
        manifest = self.store.manifest(root)
        request = "Saved design brief:\n" + json.dumps(value["design_brief"], ensure_ascii=False)
        child = self.create_request(NaturalLanguageDesignJob(
            case_id=manifest["case_id"], profile=value["profile"], request=request,
            candidate_count=manifest["candidate_limit"],
            content_language=value["content_language"],
        ), conversation_parent_id=run_id, conversation_revision=value["revision"],
           conversation_snapshot=value)
        round_record = {"run_id": child.run_id, "revision": value["revision"], "created_at": now()}
        value["rounds"].append(round_record)
        self._save_conversation(root, value)
        self.store.update(root, "discussing")
        return self._result(child.run_id)
