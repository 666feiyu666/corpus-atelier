"""Create non-overwriting, self-contained product task directories."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
from typing import Callable
from uuid import uuid4

from .records import read_json, write_json, write_text


LOGGER = logging.getLogger(__name__)
CASE_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
RUN_ID_PATTERN = re.compile(r"^\d{8}T\d{6}Z_[a-f0-9]{8}$")


def validate_case_id(case_id: str) -> str:
    """Validate a stable, path-safe task case identifier."""
    if not isinstance(case_id, str) or not CASE_ID_PATTERN.fullmatch(case_id):
        raise ValueError(
            "Case ID must use lowercase letters, digits, and single hyphens."
        )
    return case_id


def validate_run_id(run_id: str) -> str:
    """Validate the generated identifier used beneath one case directory."""
    if not isinstance(run_id, str) or not RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError("Run ID must use the generated timestamp_hash format.")
    return run_id


class ArtifactStore:
    def __init__(
        self,
        root: Path | str = ".atelier/tasks",
        *,
        status_callback: Callable[[str, str], None] | None = None,
    ):
        self.root = Path(root).resolve()
        self.status_callback = status_callback

    def create(self, *, case_id: str, profile,
               brief: dict | None = None,
               request: str | None = None,
               title: str | None = None,
               models: dict | None = None,
               candidate_limit: int | None = None,
               is_conversation: bool = False,
               conversation_parent_id: str | None = None,
               conversation_revision: int | None = None,
               conversation_state: dict | None = None,
               conversation_snapshot: dict | None = None) -> tuple[str, Path]:
        case_id = validate_case_id(case_id)
        if is_conversation and not isinstance(conversation_state, dict):
            raise ValueError("A conversation requires an initial conversation state.")
        if (brief is None) == (request is None):
            raise ValueError(
                "A run requires exactly one structured brief or natural-language request."
            )
        case_root = self.root / case_id
        case_root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        while True:
            run_id = f"{stamp}_{uuid4().hex[:8]}"
            run_dir = case_root / run_id
            try:
                run_dir.mkdir()
                break
            except FileExistsError:
                continue
        if brief is not None:
            write_json(run_dir / "brief.json", brief)
            input_mode = "structured_brief"
            initial_artifacts = {"brief": "brief.json"}
        else:
            write_text(run_dir / "input/request.txt", request)
            input_mode = "natural_language"
            initial_artifacts = {"user_request": "input/request.txt"}
        write_json(run_dir / "profile.json", {
            "name": profile.name, "objective": profile.objective,
            "description": profile.description,
        })
        now = datetime.now(timezone.utc).isoformat()
        manifest = {
            "format_version": 2, "workflow_version": 18,
            "case_id": case_id, "run_id": run_id,
            "title": title or case_id,
            "created_at": now,
            "updated_at": now,
            "objective_profile": profile.objective,
            "input_mode": input_mode,
            "status": "created", "artifacts": initial_artifacts,
        }
        if models is not None:
            manifest["models"] = models
        if candidate_limit is not None:
            manifest["candidate_limit"] = candidate_limit
        if is_conversation:
            manifest.update(is_conversation=True, status="discussing")
            write_json(run_dir / "conversation.json", conversation_state)
            manifest["artifacts"]["conversation"] = "conversation.json"
        if conversation_parent_id is not None:
            manifest.update(conversation_parent_id=conversation_parent_id,
                            conversation_revision=conversation_revision)
        if conversation_snapshot is not None:
            write_json(run_dir / "conversation/snapshot.json", conversation_snapshot)
            manifest["artifacts"]["conversation_snapshot"] = "conversation/snapshot.json"
            if conversation_snapshot.get("design_brief") is not None:
                write_json(run_dir / "brief.json", conversation_snapshot["design_brief"])
                manifest["artifacts"]["brief"] = "brief.json"
        write_json(run_dir / "manifest.json", manifest)
        return run_id, run_dir

    def manifest(self, run_dir: Path) -> dict:
        return read_json(run_dir / "manifest.json")

    def update(self, run_dir: Path, status: str, **details) -> dict:
        manifest = self.manifest(run_dir)
        manifest.update(
            status=status,
            updated_at=datetime.now(timezone.utc).isoformat(),
            **details,
        )
        write_json(run_dir / "manifest.json", manifest)
        if self.status_callback is not None:
            try:
                self.status_callback(manifest["run_id"], status)
            except Exception:
                LOGGER.exception("Task status callback failed.")
        return manifest

    def register(self, run_dir: Path, **artifacts: str) -> dict:
        manifest = self.manifest(run_dir)
        manifest.setdefault("artifacts", {}).update(artifacts)
        manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
        write_json(run_dir / "manifest.json", manifest)
        return manifest

    def find_run(self, run_id: str) -> Path:
        """Resolve one task by its globally unique generated run id."""
        run_id = validate_run_id(run_id)
        matches = [
            path.parent
            for path in self.root.glob(f"*/{run_id}/manifest.json")
            if path.is_file()
        ]
        if len(matches) != 1:
            raise FileNotFoundError(f"Task {run_id!r} was not found.")
        run_dir = matches[0].resolve(strict=True)
        if self.root not in run_dir.parents:
            raise ValueError("Task path escapes the task store.")
        return run_dir

    def list_runs(self) -> list[tuple[Path, dict]]:
        """Return saved tasks newest-first without loading graph checkpoints."""
        tasks = []
        if not self.root.exists():
            return tasks
        for path in self.root.glob("*/*/manifest.json"):
            if not path.is_file():
                continue
            try:
                manifest = read_json(path)
                validate_case_id(manifest["case_id"])
                validate_run_id(manifest["run_id"])
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
            if manifest.get("is_conversation") and manifest["status"] != "failed":
                conversation_path = path.parent / "conversation.json"
                if conversation_path.is_file() and read_json(conversation_path).get("pending"):
                    manifest["status"] = "discussing_request"
            tasks.append((path.parent.resolve(), manifest))
        tasks.sort(
            key=lambda item: item[1].get(
                "updated_at", item[1].get("created_at", ""),
            ),
            reverse=True,
        )
        return tasks

    def json(self, run_dir: Path, relative: str, value: object) -> str:
        path = run_dir / relative
        write_json(path, value)
        return str(path.resolve())

    def text(self, run_dir: Path, relative: str, value: str) -> str:
        path = run_dir / relative
        write_text(path, value)
        return str(path.resolve())

    def next_attempt(self, run_dir: Path, kind: str) -> Path:
        root = run_dir / kind
        root.mkdir(parents=True, exist_ok=True)
        number = 1
        while True:
            path = root / f"attempt_{number:02d}"
            try:
                path.mkdir()
                return path
            except FileExistsError:
                number += 1
