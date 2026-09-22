"""Create non-overwriting, self-contained experiment directories."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

from .records import write_json, write_text


class ArtifactStore:
    def __init__(self, root: Path | str = "experiments/runs"):
        self.root = Path(root).resolve()

    def create(self, *, brief: dict, profile, generation_mode: str,
               snapshot: Path | None = None) -> tuple[str, Path]:
        self.root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        while True:
            run_id = f"{stamp}_{uuid4().hex[:8]}"
            run_dir = self.root / run_id
            try:
                run_dir.mkdir()
                break
            except FileExistsError:
                continue
        write_json(run_dir / "brief.json", brief)
        write_json(run_dir / "profile.json", {
            "name": profile.name, "objective": profile.objective,
            "deliverable": profile.deliverable, "description": profile.description,
        })
        manifest = {
            "format_version": 1, "workflow_version": 4, "run_id": run_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "objective_profile": profile.objective, "deliverable_profile": profile.deliverable,
            "generation_mode": generation_mode,
            "status": "created", "artifacts": {},
        }
        if generation_mode == "with_corpus":
            if snapshot is None:
                raise ValueError("Corpus-grounded runs require an atlas snapshot.")
            manifest.update(
                corpus_source="atlas_snapshot",
                materials_mode="explicit-selection",
                atlas_snapshot=str(snapshot.resolve()),
            )
        if brief.get("reference_mode"):
            manifest.update(
                reference_mode=brief["reference_mode"],
                reference_scope=brief["reference_scope"],
                reference_count=brief["reference_count"],
            )
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
