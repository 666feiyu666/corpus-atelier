"""Prepare, submit, discard, and settle one frozen image request."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PIL import Image

from ..artifacts.hashing import digest_file
from ..artifacts.paths import verified_image
from ..app.locking import serialized_run as serialized_session
from ..app.state import RunResult
from .records import (
    FORMAT_VERSION,
    MAX_INSTRUCTION_LENGTH,
    PromptSessionRecord,
    canonical_digest,
    current_revision,
    find_attempt,
    find_result,
    image_record,
    load_session,
    new_id,
    now,
)
from .uploads import MAX_REFERENCES
from .validation import resolve_canvas_settings

LOGGER = logging.getLogger(__name__)

_UNKNOWN_OUTCOME_TOKENS = ("timeout", "connection", "interrupt")

# How a selected reference image is meant to influence the result.
REFERENCE_ROLES = ("subject", "composition", "palette", "style")
DEFAULT_REFERENCE_ROLE = "subject"


def _reference_guidance(
    action: str, reference_ids: list[str], roles: dict[str, str],
) -> str | None:
    """Number the references and state the role each one plays, in the prompt itself."""
    if action == "generate":
        if not reference_ids:
            return None
        parts = [
            f"{index} = {roles.get(image_id, DEFAULT_REFERENCE_ROLE)}"
            for index, image_id in enumerate(reference_ids, start=1)
        ]
        return "Reference images: " + ", ".join(parts) + "."
    if len(reference_ids) < 2:
        return None
    parts = [
        f"{index} = {roles.get(image_id, DEFAULT_REFERENCE_ROLE)}"
        for index, image_id in enumerate(reference_ids[1:], start=2)
    ]
    return "Additional references to the image to edit: " + ", ".join(parts) + "."


def outcome_unknown(exc: BaseException) -> bool:
    """A timeout or interruption may have reached the provider: never auto-retry."""
    if isinstance(exc, (KeyboardInterrupt, TimeoutError, ConnectionError)):
        return True
    name = type(exc).__name__.lower()
    return any(token in name for token in _UNKNOWN_OUTCOME_TOKENS)


def _validate_mask(mask_path: Path, source_path: Path) -> None:
    """A mask must be a PNG with transparency and the source image's exact size."""
    with Image.open(mask_path) as image:
        if image.format != "PNG" or image.mode != "RGBA":
            raise ValueError("The mask must be a PNG with an alpha channel.")
        mask_size = image.size
        if image.getchannel("A").getextrema() == (255, 255):
            raise ValueError("The mask needs a transparent region to regenerate.")
    with Image.open(source_path) as image:
        if image.size != mask_size:
            raise ValueError("The mask must match the source image dimensions.")


class ImageAttemptMixin:
    """One frozen request per attempt, executed at most once."""


    @serialized_session
    def prepare_image_action(
            self, run_id: str, *, action: str, edit_instruction: str | None = None,
            source_image_id: str | None = None, reference_image_ids: list[str] | None = None,
            reference_roles: dict[str, str] | None = None,
            mask_image_id: str | None = None, expected_revision: str | None = None,
        ) -> dict[str, Any]:
            """Freeze one exact, reviewable image request and return its attempt record."""
            root, session, _ = self._prompt_session(run_id)
            if action not in {"generate", "edit"}:
                raise ValueError("An image action must be generate or edit.")
            revision = current_revision(session)
            if revision is None:
                raise ValueError("Write the prompt before preparing an image request.")
            if expected_revision is not None and expected_revision != revision["id"]:
                raise ValueError(
                    "The prompt changed after this request was prepared. Review the current prompt."
                )
            reference_ids = [item for item in (reference_image_ids or []) if item]
            instruction = None
            if action == "generate":
                if source_image_id is not None:
                    raise ValueError("Generating a new image never sends an implicit source image.")
                request_text = revision["prompt_text"]
            else:
                if not source_image_id:
                    raise ValueError("Choose the image to edit.")
                if not isinstance(edit_instruction, str) or not edit_instruction.strip():
                    raise ValueError("Write the edit instruction you want the image model to receive.")
                if len(edit_instruction) > MAX_INSTRUCTION_LENGTH:
                    raise ValueError(
                        f"An edit instruction must be at most {MAX_INSTRUCTION_LENGTH} characters."
                    )
                instruction = edit_instruction
                request_text = edit_instruction
                reference_ids = [source_image_id, *[i for i in reference_ids if i != source_image_id]]
            if len(reference_ids) > MAX_REFERENCES:
                raise ValueError(f"An image request accepts at most {MAX_REFERENCES} reference images.")
            roles = dict(reference_roles or {})
            for role in roles.values():
                if role not in REFERENCE_ROLES:
                    raise ValueError(
                        "A reference role must be one of: "
                        + ", ".join(REFERENCE_ROLES)
                        + "."
                    )
            guidance = _reference_guidance(action, reference_ids, roles)
            if guidance:
                request_text = f"{request_text}\n\n{guidance}"
            references = []
            for image_id in reference_ids:
                record = image_record(session, image_id)
                path = verified_image(root, record["path"], record["sha256"])
                references.append({
                    "id": image_id, "path": record["path"],
                    "sha256": record["sha256"], "file": path.name,
                })
            mask = None
            if mask_image_id is not None:
                record = image_record(session, mask_image_id)
                verified_image(root, record["path"], record["sha256"])
                mask = {"id": mask_image_id, "path": record["path"], "sha256": record["sha256"]}
            if mask is not None and len(references) != 1:
                raise ValueError("Mask inpainting requires exactly one reference image.")
            if mask is not None:
                _validate_mask(root / mask["path"], root / references[0]["path"])
            settings = session["settings"]
            size = settings.get("size")
            if not size:
                size = resolve_canvas_settings(settings).get("size")
            if not size:
                raise ValueError(
                    "Choose an output size before generating: no supported size "
                    "keeps this canvas ratio."
                )
            request = self.runtime.image_provider.describe_request(
                request_text, size=size,
                reference_paths=[root / item["path"] for item in references] or None,
                mask_path=root / mask["path"] if mask else None,
            )
            attempt_id = new_id("att")
            digest = canonical_digest({
                "action": action, "request": request, "prompt_revision_id": revision["id"],
                "source_image_id": source_image_id, "reference_image_ids": reference_ids,
                "mask_image_id": mask_image_id,
            })
            attempt = {
                "id": attempt_id,
                "action": action,
                "prompt_revision_id": revision["id"],
                "request_text": request_text,
                "edit_instruction": instruction,
                "source_image_id": source_image_id,
                "reference_image_ids": reference_ids,
                "mask_image_id": mask_image_id,
                "references": references,
                "reference_roles": [
                    {
                        "index": index,
                        "image_id": image_id,
                        "role": roles.get(image_id, DEFAULT_REFERENCE_ROLE),
                    }
                    for index, image_id in enumerate(reference_ids, start=1)
                ],
                "reference_guidance": guidance,
                "mask": mask,
                "settings": {
                    "model": request.get("model"), "quality": request.get("quality"),
                    "size": request.get("size"), "output_format": request.get("output_format"),
                },
                "request_digest": digest,
                "request_path": f"image-attempts/{attempt_id}/request.json",
                "status": "prepared",
                "created_at": now(),
            }
            attempt_dir = self._attempt_dir(root, attempt_id)
            attempt_dir.mkdir(parents=True, exist_ok=False)
            self.store.json(attempt_dir, "request.json", request)
            self.store.text(attempt_dir, "prompt.md", request_text)
            self._write_attempt(root, attempt)
            session["image_attempts"].append(attempt)
            self._save(root, session)
            self.store.update(root, "prompt_ready", error=None)
            return attempt


    def _write_attempt(self, root: Path, attempt: dict[str, Any]) -> None:
            attempt_dir = self._attempt_dir(root, attempt["id"])
            self.store.json(attempt_dir, "record.json", attempt)


    @serialized_session
    def discard_image_action(self, run_id: str, attempt_id: str) -> RunResult:
            """Abandon one prepared request without calling the provider."""
            root, session, _ = self._prompt_session(run_id)
            attempt = find_attempt(session, attempt_id)
            if attempt["status"] != "prepared":
                raise ValueError("Only an unsubmitted image request can be discarded.")
            attempt["status"] = "discarded"
            self._write_attempt(root, attempt)
            self._save(root, session)
            return self._result(run_id)


    @serialized_session
    def submit_image_action(
            self, run_id: str, attempt_id: str, *, expected_digest: str,
        ) -> RunResult:
            """Execute one frozen request exactly once; stale or repeated submits fail."""
            root, session, _ = self._prompt_session(run_id)
            attempt = find_attempt(session, attempt_id)
            if attempt["status"] != "prepared":
                raise ValueError(
                    "This image request was already submitted. Prepare a new request to try again."
                )
            if attempt["request_digest"] != expected_digest:
                raise ValueError(
                    "This image request changed. Review the exact request before submitting."
                )
            if attempt["prompt_revision_id"] != session.get("current_prompt_revision_id"):
                raise ValueError(
                    "The prompt changed after this request was prepared. Prepare the image action again."
                )
            self._assert_model_binding(root)
            attempt["status"] = "submitting"
            attempt["submitted_at"] = now()
            self._write_attempt(root, attempt)
            self._save(root, session)
            self.store.update(root, "generating_image", error=None)
            reference_paths = [
                verified_image(root, item["path"], item["sha256"]) for item in attempt["references"]
            ]
            mask_path = None
            if attempt.get("mask"):
                mask_path = verified_image(
                    root, attempt["mask"]["path"], attempt["mask"]["sha256"],
                )
            attempt_dir = self._attempt_dir(root, attempt["id"])
            try:
                response = self.runtime.image_provider.generate(
                    attempt["request_text"], size=attempt["settings"]["size"],
                    output=attempt_dir, reference_paths=reference_paths or None,
                    mask_path=mask_path,
                )
            except BaseException as exc:  # noqa: BLE001 - every outcome must be recorded
                unknown = outcome_unknown(exc)
                attempt["status"] = "outcome_unknown" if unknown else "failed"
                attempt["error"] = {"type": type(exc).__name__, "message": str(exc)}
                attempt["response_path"] = f"image-attempts/{attempt['id']}/response.json"
                self._write_attempt(root, attempt)
                self._save(root, session)
                self.store.update(
                    root, "outcome_unknown" if unknown else "failed",
                    error_type=type(exc).__name__, error=str(exc),
                )
                raise
            image_path = (attempt_dir / response["file"]).resolve()
            if digest_file(image_path) != response.get("sha256"):
                attempt["status"] = "failed"
                attempt["error"] = {"type": "ImageIntegrityError", "message": "The result image changed."}
                self._write_attempt(root, attempt)
                self._save(root, session)
                self.store.update(root, "failed", error="The generated image did not match its digest.")
                raise ValueError("The generated image did not match its digest.")
            result = {
                "id": new_id("img"),
                "image_path": image_path.relative_to(root).as_posix(),
                "sha256": response["sha256"],
                "attempt_id": attempt["id"],
                "parent_image_id": attempt["source_image_id"] if attempt["action"] == "edit" else None,
                "prompt_revision_id": attempt["prompt_revision_id"],
                "request_text": attempt["request_text"],
                "action": attempt["action"],
                "label": f"{attempt['action']} {len(session['image_results']) + 1}",
                "created_at": now(),
            }
            attempt["status"] = "succeeded"
            attempt["result_image_id"] = result["id"]
            attempt["response_path"] = f"image-attempts/{attempt['id']}/response.json"
            self._write_attempt(root, attempt)
            session["image_results"].append(result)
            session["active_image_id"] = result["id"]
            self._save(root, session)
            self.store.update(
                root, "prompt_ready", error=None,
                latest_image=str(image_path), image_sha256=result["sha256"],
                current_prompt_revision_id=session["current_prompt_revision_id"],
            )
            return self._result(run_id)


    @serialized_session
    def select_prompt_result(self, run_id: str, image_id: str) -> RunResult:
            """Mark one result active without changing any earlier request or prompt."""
            root, session, _ = self._prompt_session(run_id)
            find_result(session, image_id)
            session["active_image_id"] = image_id
            self._save(root, session)
            return self._result(run_id)


    @serialized_session
    def reconcile_prompt_session(self, run_id: str) -> RunResult:
            """Mark an interrupted submission as an unknown remote outcome."""
            root = self.store.find_run(run_id)
            manifest = self.store.manifest(root)
            if not manifest.get("is_prompt_session"):
                return self._result(run_id)
            session = load_session(root)
            if manifest["status"] != "generating_image":
                return self._result(run_id)
            if all(attempt["status"] != "outcome_unknown" for attempt in session["image_attempts"]):
                return self._result(run_id)
            self._save(root, session)
            for attempt in session["image_attempts"]:
                self._write_attempt(root, attempt)
            self.store.update(
                root, "outcome_unknown",
                error="The image request was interrupted before its outcome was known.",
            )
            return self._result(run_id)
