"""Build a deterministic package of complete visual references for model input."""

from __future__ import annotations

from pathlib import Path

from .atlas_snapshot import load_snapshot


def build_reference_package(snapshot: Path | str, *, scope: str,
                            selected: list[dict], count: int) -> tuple[dict, list[Path]]:
    """Return canonical metadata and paths for ranked, selected evidence."""
    if scope != "retrieved_snapshot_images":
        raise ValueError(f"Unsupported reference scope: {scope!r}.")
    if not 1 <= count <= 3:
        raise ValueError("Reference count must be between 1 and 3.")
    root = Path(snapshot).resolve(strict=True)
    manifest, candidates = load_snapshot(root)
    by_id = {candidate.id: candidate for candidate in candidates}
    reference_ids = [
        row["id"] for row in selected if row["kind"] == "reference"
    ][:count]
    knowledge_ids = [
        row["id"] for row in selected if row["kind"] == "knowledge"
    ]
    if len(reference_ids) != count:
        raise ValueError(f"Retrieval supplied only {len(reference_ids)} reference images.")

    records = []
    paths = []
    for candidate_id in reference_ids:
        candidate = by_id.get(candidate_id)
        if candidate is None:
            raise ValueError(f"Selected evidence {candidate_id!r} is absent from the snapshot.")
        if candidate.kind != "reference" or candidate.metadata.get("modality") != "image":
            raise ValueError(f"Selected evidence {candidate.id!r} is not an image reference.")
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
    knowledge = []
    for candidate_id in knowledge_ids:
        candidate = by_id.get(candidate_id)
        if candidate is None:
            raise ValueError(f"Selected evidence {candidate_id!r} is absent from the snapshot.")
        if candidate.kind != "knowledge":
            raise ValueError(f"Selected evidence {candidate.id!r} is not knowledge.")
        knowledge.append(candidate.serializable())

    package = {
        "format_version": 1,
        "snapshot_id": manifest["snapshot_id"],
        "scope": scope,
        "reference_count": count,
        "interpretation_status": "unreviewed_model_input",
        "knowledge": knowledge,
        "references": records,
    }
    return package, paths
