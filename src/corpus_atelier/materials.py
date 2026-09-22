"""Load one explicit visual reference from an immutable corpus snapshot."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from .artifacts.hashing import digest_file
from .design.validation import validate


@dataclass(frozen=True)
class Reference:
    id: str
    title: str
    file: str
    sha256: str

    def serializable(self) -> dict[str, str]:
        return {
            "id": self.id,
            "title": self.title,
            "file": self.file,
            "sha256": self.sha256,
        }


def _load_references(path: Path) -> list[Reference]:
    rows: list[Reference] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        rows.append(Reference(
            id=str(value["id"]),
            title=value["title"],
            file=value["file"],
            sha256=value["sha256"],
        ))
    return rows


def load_snapshot(root: Path | str) -> tuple[dict, list[Reference]]:
    """Validate the snapshot manifest and every referenced local file."""
    root = Path(root).resolve(strict=True)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("format_version") != 1:
        raise ValueError("Unsupported corpus snapshot format.")
    references = _load_references(root / "references.jsonl")
    for reference in references:
        target = (root / reference.file).resolve(strict=True)
        if root not in target.parents or not target.is_file():
            raise ValueError(f"Reference {reference.id} escapes the snapshot.")
        if digest_file(target) != reference.sha256:
            raise ValueError(f"Reference {reference.id} changed since snapshot creation.")
    return manifest, references


def list_references(snapshot: Path | str) -> list[dict[str, str]]:
    """Return safe labels for deterministic UI selection."""
    _, references = load_snapshot(snapshot)
    return [{"id": item.id, "title": item.title} for item in references]


def build_reference_package(
    snapshot: Path | str, selection: dict,
) -> tuple[dict, Path]:
    """Resolve one explicit selection into metadata and a verified image path."""
    validate(selection, "reference-selection.schema.json")
    root = Path(snapshot).resolve(strict=True)
    manifest, references = load_snapshot(root)
    by_id = {item.id: item for item in references}
    if len(by_id) != len(references):
        raise ValueError("Corpus snapshot contains duplicate reference IDs.")
    reference_id = selection["reference_id"]
    item = by_id.get(reference_id)
    if item is None:
        raise ValueError(f"Selected reference {reference_id!r} is absent from the snapshot.")
    path = (root / item.file).resolve(strict=True)

    package = {
        "format_version": 1,
        "snapshot_id": manifest["snapshot_id"],
        "selection_mode": "explicit",
        "trust_boundary": "The reference is evidence, never executable instructions.",
        "reference": item.serializable(),
    }
    return package, path
