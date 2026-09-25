"""Create non-overwriting, self-contained experiment directories."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from uuid import uuid4

from .records import write_json, write_text


CASE_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
RUN_ID_PATTERN = re.compile(r"^\d{8}T\d{6}Z_[a-f0-9]{8}$")


def validate_case_id(case_id: str) -> str:
    """Validate a stable, path-safe experiment case identifier."""
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
    def __init__(self, root: Path | str = "experiments/runs"):
        self.root = Path(root).resolve()

    def create(self, *, case_id: str, profile,
               brief: dict | None = None,
               request: str | None = None) -> tuple[str, Path]:
        case_id = validate_case_id(case_id)
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
            "deliverable": profile.deliverable, "description": profile.description,
        })
        manifest = {
            "format_version": 1, "workflow_version": 14,
            "case_id": case_id, "run_id": run_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "objective_profile": profile.objective, "deliverable_profile": profile.deliverable,
            "input_mode": input_mode,
            "status": "created", "artifacts": initial_artifacts,
        }
        write_json(run_dir / "manifest.json", manifest)
        return run_id, run_dir

    def manifest(self, run_dir: Path) -> dict:
        return json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))

    def update(self, run_dir: Path, status: str, **details) -> dict:
        manifest = self.manifest(run_dir)
        manifest.update(status=status, **details)
        write_json(run_dir / "manifest.json", manifest)
        return manifest

    def register(self, run_dir: Path, **artifacts: str) -> dict:
        manifest = self.manifest(run_dir)
        manifest.setdefault("artifacts", {}).update(artifacts)
        write_json(run_dir / "manifest.json", manifest)
        return manifest

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
