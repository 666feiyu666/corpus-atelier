"""Application operations for the prompt-centered image workflow.

Every durable state transition lives here: the Streamlit layer renders state and
sends user actions, and never decides prompt versions, image roles, or provider
payloads. The image provider executes only an explicitly prepared, frozen
request whose digest the user was shown.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..artifacts.paths import verified_image
from ..artifacts.records import read_json
from ..app.locking import serialized_run as serialized_session
from ..app.state import PromptSessionJob, RunResult
from .assistant import (
    ASSISTANT_SCHEMA,
    EXTRACTION_SCHEMA,
    build_extraction_prompt,
    build_turn_prompt,
    label_images,
    validate_extraction,
    validate_turn_answer,
)
from .attempts import ImageAttemptMixin
from .records import (
    FORMAT_VERSION,
    SESSION_FILE,
    WORKFLOW_KIND,
    PromptSessionRecord,
    current_revision,
    find_revision,
    find_upload,
    image_record,
    load_session,
    new_id,
    new_revision,
    new_session,
    now,
    save_session,
)
from .uploads import MAX_REFERENCES, UploadMixin, validate_upload
from .validation import validate_prompt_text, validate_session_settings

LOGGER = logging.getLogger(__name__)


class PromptSessionMixin(UploadMixin, ImageAttemptMixin):
    """Prompt-session creation, revisions, conversation, and extraction."""


    def prompt_session(self, run_id: str) -> PromptSessionRecord:
            root = self.store.find_run(run_id)
            return load_session(root)


    def _prompt_session(self, run_id: str) -> tuple[Path, PromptSessionRecord, dict]:
            root = self.store.find_run(run_id)
            manifest = self.store.manifest(root)
            if not manifest.get("is_prompt_session"):
                raise ValueError("This task does not use the prompt-centered workflow.")
            return root, load_session(root), manifest


    def _save(self, root: Path, session: PromptSessionRecord) -> None:
            save_session(root, session)


    def _require_idle(self, session: PromptSessionRecord) -> None:
            """A pending chat turn does not block an edit; a running image call does."""
            for attempt in session["image_attempts"]:
                if attempt["status"] == "submitting":
                    raise ValueError("An image request is still running for this session.")


    @staticmethod
    def _attempt_dir(root: Path, attempt_id: str) -> Path:
            return root / "image-attempts" / attempt_id


    def _create_session(
            self, *, request_text: str, entry_mode: str, case_id: str,
            settings: dict | None,
        ) -> tuple[str, Path, PromptSessionRecord]:
            resolved = validate_session_settings(settings)
            provider_quality = getattr(self.runtime.image_provider, "quality", None)
            if provider_quality is not None:
                resolved["image_quality"] = provider_quality
            result = self.create_request(
                PromptSessionJob(case_id=case_id, request=request_text),
            )
            root = result.run_dir
            session = new_session(entry_mode, resolved)
            self._save(root, session)
            self.store.register(root, prompt_session=SESSION_FILE)
            self.store.update(
                root, "prompt_ready", is_prompt_session=True, workflow_kind=WORKFLOW_KIND,
                prompt_session_settings=resolved, error=None,
            )
            return result.run_id, root, session


    def start_from_prompt(
            self, prompt_text: str, *, case_id: str,
            settings: dict | None = None,
            references: list[tuple[str, bytes]] | None = None,
        ) -> RunResult:
            """Create a session whose revision 1 is the prompt the user just typed."""
            text = validate_prompt_text(prompt_text)
            for name, data in list(references or []):
                validate_upload(name, data)
            run_id, root, session = self._create_session(
                request_text=text, entry_mode="prompt", case_id=case_id,
                settings=settings,
            )
            new_revision(session, text, "user_input")
            for name, data in list(references or []):
                self._archive_upload(root, session, name, data, role="reference")
            self._save(root, session)
            return self._result(run_id)


    def start_from_image(
            self, image: tuple[str, bytes], *, case_id: str,
            settings: dict | None = None,
        ) -> RunResult:
            """Archive one source image and queue a vision extraction; no image call."""
            name, data = image
            validate_upload(name, data)
            run_id, root, session = self._create_session(
                request_text=f"Extract an estimated prompt from the uploaded image {Path(name).name}",
                entry_mode="image", case_id=case_id, settings=settings,
            )
            upload = self._archive_upload(root, session, name, data, role="source_image")
            session["pending_turn"] = {
                "kind": "extraction", "turn_id": new_id("turn"), "upload_id": upload["id"],
                "created_at": now(),
            }
            self._save(root, session)
            self.store.update(root, "extracting", error=None)
            return self._result(run_id)


    @serialized_session
    def edit_session_prompt(
            self, run_id: str, prompt_text: str, *, expected_revision: str,
        ) -> RunResult:
            """Make a user-edited prompt authoritative as a new revision."""
            root, session, _ = self._prompt_session(run_id)
            self._require_idle(session)
            current = session.get("current_prompt_revision_id")
            if expected_revision != current:
                raise ValueError("The prompt changed. Review the current prompt before saving.")
            text = validate_prompt_text(prompt_text)
            if current is not None and text == find_revision(session, current)["prompt_text"]:
                return self._result(run_id)
            new_revision(session, text, "manual_edit", parent_revision_id=current)
            self._save(root, session)
            self.store.update(root, "prompt_ready", error=None)
            return self._result(run_id)


    @serialized_session
    def restore_session_revision(
            self, run_id: str, revision_id: str, *, expected_revision: str,
        ) -> RunResult:
            """Restore an earlier revision as a new revision, keeping history intact."""
            root, session, _ = self._prompt_session(run_id)
            self._require_idle(session)
            current = session.get("current_prompt_revision_id")
            if expected_revision != current:
                raise ValueError("The prompt changed. Review the current prompt before restoring.")
            target = find_revision(session, revision_id)
            if target["id"] == current:
                return self._result(run_id)
            new_revision(
                session, target["prompt_text"], "manual_edit",
                parent_revision_id=current, restored_from=target["id"],
            )
            self._save(root, session)
            self.store.update(root, "prompt_ready", error=None)
            return self._result(run_id)


    @serialized_session
    def queue_session_message(
            self, run_id: str, text: str, *, attachments: list[tuple[str, bytes]] | None = None,
        ) -> RunResult:
            """Save the user message and its base revision before any model call."""
            root, session, _ = self._prompt_session(run_id)
            self._assert_model_binding(root)
            if session.get("pending_turn"):
                raise ValueError("Wait for the current response, or retry it.")
            if len(attachments or []) > MAX_REFERENCES:
                raise ValueError(f"Attach at most {MAX_REFERENCES} images per message.")
            if not isinstance(text, str) or (not text.strip() and not attachments):
                raise ValueError("Send a message or attach an image.")
            uploads = [
                self._archive_upload(root, session, name, data, role="discussion")
                for name, data in list(attachments or [])
            ]
            message_id = new_id("msg")
            session["messages"].append({
                "id": message_id, "role": "user", "text": text,
                "attachment_ids": [upload["id"] for upload in uploads],
                "attachment_names": [upload["name"] for upload in uploads],
                "created_at": now(),
            })
            session["pending_turn"] = {
                "kind": "chat", "turn_id": new_id("turn"), "message_id": message_id,
                "base_revision_id": session["current_prompt_revision_id"], "created_at": now(),
            }
            self._save(root, session)
            self.store.update(root, "discussing_request", error=None)
            return self._result(run_id)


    def _turn_images(
            self, root: Path, session: PromptSessionRecord, message: dict,
        ) -> tuple[list[Path], list[dict[str, Any]]]:
            """Only explicitly attached or active images reach the text model."""
            image_ids = list(message.get("attachment_ids") or [])
            active = session.get("active_image_id")
            if active and active not in image_ids:
                image_ids.append(active)
            image_ids = image_ids[:MAX_REFERENCES]
            paths, names = [], {}
            for image_id in image_ids:
                record = image_record(session, image_id)
                paths.append(verified_image(root, record["path"], record["sha256"]))
                names[image_id] = record.get("name") or record.get("label") or image_id
            return paths, label_images(session, image_ids, names)


    @serialized_session
    def run_session_turn(self, run_id: str) -> RunResult:
            """Commit one assistant reply and, when appropriate, one prompt revision."""
            root, session, _ = self._prompt_session(run_id)
            pending = session.get("pending_turn") or {}
            if pending.get("kind") != "chat":
                raise ValueError("There is no pending conversation turn to answer.")
            self._assert_model_binding(root)
            turn_id = pending["turn_id"]
            message = next(
                (item for item in session["messages"] if item.get("id") == pending.get("message_id")),
                None,
            )
            if message is None:
                raise ValueError("The pending turn has no matching user message.")
            base_revision_id = pending.get("base_revision_id")
            base_revision = find_revision(session, base_revision_id) if base_revision_id else None
            turn_dir = root / "turns" / turn_id
            self.store.update(root, "discussing_request", error=None)
            try:
                self.store.text(turn_dir, "message.txt", message["text"])
                answer = self._turn_answer(root, session, turn_dir, message, base_revision)
                revision = self._commit_turn(session, answer, turn_id, message)
                self.store.json(turn_dir, "answer.json", answer)
                self._save(root, session)
                self.store.update(
                    root, "prompt_ready", error=None,
                    current_prompt_revision_id=session["current_prompt_revision_id"],
                )
            except Exception as exc:
                self.store.json(turn_dir, "error.json", {
                    "status": "failed", "error_type": type(exc).__name__, "message": str(exc),
                })
                self.store.fail(root, exc)
                raise
            return self._result(run_id)


    def _turn_answer(
            self, root: Path, session: PromptSessionRecord, turn_dir: Path, message: dict,
            base_revision: dict | None,
        ) -> dict[str, Any]:
            cached = turn_dir / "answer.json"
            if cached.is_file():
                try:
                    return validate_turn_answer(read_json(cached))
                except (OSError, ValueError):
                    LOGGER.warning("Ignoring an invalid cached turn answer at %s.", cached)
            reference_paths, labels = self._turn_images(root, session, message)
            prompt = build_turn_prompt(
                session, message=message, base_revision=base_revision, labels=labels,
            )
            self.store.text(turn_dir, "prompt.md", prompt)
            answer, response = self.runtime.text_provider.propose(
                prompt, schema_name=ASSISTANT_SCHEMA, reference_paths=reference_paths or None,
            )
            answer = validate_turn_answer(answer)
            self.store.json(turn_dir, "response.json", response)
            return answer


    def _commit_turn(
            self, session: PromptSessionRecord, answer: dict[str, Any], turn_id: str, message: dict,
        ) -> dict[str, Any] | None:
            """Commit a proposal only against the revision it was written for."""
            pending = session["pending_turn"]
            base_revision_id = pending.get("base_revision_id")
            proposal = answer["proposed_prompt"]
            revision = None
            conflict = False
            if proposal is not None:
                if session.get("current_prompt_revision_id") != base_revision_id:
                    conflict = True
                else:
                    revision = new_revision(
                        session, proposal, "assistant_revision",
                        parent_revision_id=base_revision_id, source_message_id=message["id"],
                        source_turn_id=turn_id,
                    )
            session["text_turns"].append({
                "id": turn_id, "kind": "chat", "message_id": message["id"],
                "base_revision_id": base_revision_id, "status": "completed",
                "reply": answer["reply"], "proposed_prompt": proposal,
                "edit_instruction": answer["edit_instruction"],
                "proposed_revision_id": revision["id"] if revision else None,
                "conflict": conflict,
                "model_input": f"turns/{turn_id}/prompt.md",
                "raw_response": f"turns/{turn_id}/response.json",
                "created_at": now(),
            })
            session["messages"].append({
                "id": new_id("msg"), "role": "assistant", "text": answer["reply"],
                "attachment_ids": [], "attachment_names": [],
                "in_reply_to": message["id"], "turn_id": turn_id,
                "proposed_prompt": proposal, "edit_instruction": answer["edit_instruction"],
                "proposed_revision_id": revision["id"] if revision else None,
                "conflict": conflict, "created_at": now(),
            })
            session["pending_turn"] = None
            session["format_version"] = max(FORMAT_VERSION, session["format_version"])
            return revision


    @serialized_session
    def run_prompt_extraction(self, run_id: str) -> RunResult:
            """Derive revision 1 from one source image with a vision text model."""
            root, session, _ = self._prompt_session(run_id)
            pending = session.get("pending_turn") or {}
            if pending.get("kind") != "extraction":
                raise ValueError("There is no pending image extraction to run.")
            self._assert_model_binding(root)
            turn_id = pending["turn_id"]
            upload = find_upload(session, pending["upload_id"])
            turn_dir = root / "turns" / turn_id
            self.store.update(root, "extracting", error=None)
            try:
                source = verified_image(root, upload["path"], upload["sha256"])
                answer = self._extraction_answer(turn_dir, source, upload)
                existing = next(
                    (item for item in session["prompt_revisions"]
                     if item.get("source_turn_id") == turn_id),
                    None,
                )
                if existing is None:
                    new_revision(
                        session, answer["prompt_text"], "vision_extraction",
                        source_image_id=upload["id"], note=answer["observations"],
                        negative_prompt=answer.get("negative_prompt"),
                        source_turn_id=turn_id,
                    )
                session["text_turns"].append({
                    "id": turn_id, "kind": "extraction", "status": "completed",
                    "source_image_id": upload["id"],
                    "model_input": f"turns/{turn_id}/prompt.md",
                    "raw_response": f"turns/{turn_id}/response.json",
                    "created_at": now(),
                })
                session["pending_turn"] = None
                self._save(root, session)
                self.store.update(
                    root, "prompt_ready", error=None,
                    current_prompt_revision_id=session["current_prompt_revision_id"],
                )
            except Exception as exc:
                self.store.json(turn_dir, "error.json", {
                    "status": "failed", "error_type": type(exc).__name__, "message": str(exc),
                })
                self.store.fail(root, exc)
                raise
            return self._result(run_id)


    def _extraction_answer(
            self, turn_dir: Path, source: Path, upload: dict[str, Any],
        ) -> dict[str, Any]:
            cached = turn_dir / "answer.json"
            if cached.is_file():
                try:
                    return validate_extraction(read_json(cached))
                except (OSError, ValueError):
                    LOGGER.warning("Ignoring an invalid cached extraction at %s.", cached)
            prompt = build_extraction_prompt(source_name=upload["name"])
            self.store.text(turn_dir, "prompt.md", prompt)
            answer, response = self.runtime.text_provider.propose(
                prompt, schema_name=EXTRACTION_SCHEMA, reference_paths=[source],
            )
            answer = validate_extraction(answer)
            self.store.json(turn_dir, "response.json", response)
            self.store.json(turn_dir, "answer.json", answer)
            return answer


    def continue_prompt_session(self, run_id: str) -> RunResult:
            """Resume the one pending text step, if any; never repeat an image call."""
            root, session, manifest = self._prompt_session(run_id)
            pending = session.get("pending_turn")
            if not pending:
                if manifest["status"] != "prompt_ready":
                    self.store.update(root, "prompt_ready", error=None)
                return self._result(run_id)
            if pending.get("kind") == "extraction":
                return self.run_prompt_extraction(run_id)
            return self.run_session_turn(run_id)
