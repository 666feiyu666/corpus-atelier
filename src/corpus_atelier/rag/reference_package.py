"""Build a deterministic package of complete visual references for model input."""

from __future__ import annotations

from pathlib import Path

from .atlas_snapshot import load_snapshot


def build_reference_package(snapshot: Path | str, *, scope: str) -> tuple[dict, list[Path]]:
    """Return stable metadata and paths without interpreting the images."""
    if scope != "all_snapshot_images":
        raise ValueError(f"Unsupported reference scope: {scope!r}.")
    root = Path(snapshot).resolve(strict=True)
    manifest, candidates = load_snapshot(root)
    records = []
    knowledge = []
    paths = []
    for candidate in candidates:
        if candidate.kind == "knowledge":
            knowledge.append(candidate.serializable())
            continue
        if candidate.kind != "reference" or candidate.metadata.get("modality") != "image":
            continue
        relative = candidate.metadata.get("file")
        sha256 = candidate.metadata.get("sha256")
        if not relative or not sha256:
            raise ValueError(f"Visual reference {candidate.id!r} lacks a file or sha256.")
        path = (root / relative).resolve(strict=True)
        records.append({
            "id": candidate.id,
            "title": candidate.title,
            "collection": candidate.metadata.get("collection"),
            "file": relative,
            "sha256": sha256,
        })
        paths.append(path)
    if not records:
        raise ValueError("The snapshot contains no complete visual references.")
    package = {
        "format_version": 1,
        "snapshot_id": manifest["snapshot_id"],
        "scope": scope,
        "interpretation_status": "unreviewed_model_input",
        "knowledge": knowledge,
        "references": records,
    }
    return package, paths
