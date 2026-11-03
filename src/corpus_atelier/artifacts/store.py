"""Create non-overwriting, self-contained task directories."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from pathlib import Path
import re
import shutil
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


def read_manifest(path: Path) -> dict:
    """Read the minimum task contract required by listing and recovery."""
    manifest = read_json(path)
    if not isinstance(manifest, dict):
        raise ValueError("The task manifest must be an object.")
    validate_case_id(manifest.get("case_id"))
    validate_run_id(manifest.get("run_id"))
    if manifest["run_id"] != path.parent.name or manifest["case_id"] != path.parent.parent.name:
        raise ValueError("The task manifest identity differs from its directory.")
    if not isinstance(manifest.get("status"), str) or not manifest["status"]:
        raise ValueError("The task manifest must include a status.")
    for field in ("created_at", "updated_at"):
        if field in manifest and not isinstance(manifest[field], str):
            raise ValueError(f"The task manifest's {field} must be a string.")
    for field in ("artifacts", "models"):
        if field in manifest and not isinstance(manifest[field], dict):
            raise ValueError(f"The task manifest's {field} must be an object.")
    return manifest


class ArtifactStore:
    def __init__(
        self,
        root: Path | str = ".atelier/tasks",
        *,
        status_callback: Callable[[str, str], None] | None = None,
    ):
        self.root = Path(root).resolve()
        self.status_callback = status_callback

    def create(self, *, case_id: str, request: str, title: str | None = None,
               models: dict | None = None) -> tuple[str, Path]:
        """Create one empty task directory holding the user's request."""
        case_id = validate_case_id(case_id)
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
        write_text(run_dir / "input/request.txt", request)
        now = datetime.now(timezone.utc).isoformat()
        manifest = {
            "format_version": 2,
            "case_id": case_id, "run_id": run_id,
            "title": title or case_id,
            "created_at": now,
            "updated_at": now,
            "input_mode": "natural_language",
            "status": "created",
            "artifacts": {"user_request": "input/request.txt"},
        }
        if models is not None:
            manifest["models"] = models
        write_json(run_dir / "manifest.json", manifest)
        return run_id, run_dir

    def manifest(self, run_dir: Path) -> dict:
        return read_manifest(run_dir / "manifest.json")

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

    def fail(self, run_dir: Path, error: Exception) -> None:
        """Persist a failure without masking it if its record cannot be written."""
        try:
            self.update(run_dir, "failed", error_type=type(error).__name__, error=str(error))
        except Exception:
            LOGGER.exception("Could not persist the failure for task %s.", run_dir.name)

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

    def delete(self, run_dir: Path) -> None:
        """Permanently remove one task directory inside the store root."""
        run_dir = Path(run_dir).resolve()
        if run_dir == self.root or self.root not in run_dir.parents:
            raise ValueError("Task path escapes the task store.")
        shutil.rmtree(run_dir)

    def list_runs(self) -> list[tuple[Path, dict]]:
        """Return saved tasks newest-first."""
        tasks = []
        if not self.root.exists():
            return tasks
        for path in self.root.glob("*/*/manifest.json"):
            if not path.is_file():
                continue
            try:
                manifest = read_manifest(path)
            except (OSError, ValueError) as exc:
                LOGGER.warning("Skipping unreadable manifest %s: %s", path, exc)
                continue
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
