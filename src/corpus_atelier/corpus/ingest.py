"""User-driven ingest: turn a finished atelier run into a corpus record.

Archiving is always an explicit user decision — nothing is auto-archived. This
module only provides the programmatic entry the UI/CLI later call on the user's
behalf, with the labels the user picked.
"""

from __future__ import annotations

from pathlib import Path
import shutil

from ..artifacts.hashing import digest_file
from ..artifacts.store import read_manifest
from .index import CorpusStore
from .records import CorpusRecord, new_record


def _image_size(path: Path) -> tuple[int | None, int | None]:
    try:
        from PIL import Image

        with Image.open(path) as img:
            return img.width, img.height
    except Exception:
        return None, None


def _read_generation_prompt(run_dir: Path, manifest: dict) -> str:
    relative = (manifest.get("artifacts") or {}).get("generation_prompt")
    candidates: list[Path] = []
    if relative:
        candidates.append(run_dir / relative)
    candidates.append(run_dir / "generation" / "prompt.md")
    for path in candidates:
        if path.is_file():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                return text
    raise ValueError("The run has no generation prompt to archive.")


def from_atelier_run(
    run_dir: Path | str,
    *,
    tags: list[str],
    prompt: str | None = None,
    negative_prompt: str | None = None,
    source_note: str | None = None,
    translations: dict[str, str | None] | None = None,
    record_id: str | None = None,
) -> CorpusRecord:
    """Build a source.kind='atelier' record from a finished run directory.

    The prompt and image come from the run artifacts; the closed-taxonomy labels
    are supplied by the caller (the user's decision at archive time).
    """
    run_dir = Path(run_dir)
    manifest = read_manifest(run_dir / "manifest.json")
    if manifest["status"] != "completed":
        raise ValueError("Only a completed run can be archived into the corpus.")

    prompt = prompt or _read_generation_prompt(run_dir, manifest)

    image = None
    image_path = manifest.get("latest_image")
    if image_path:
        source = Path(image_path)
        if not source.is_file():
            raise ValueError(f"The run's image is missing: {image_path}")
        image = {"path": source.resolve().as_posix(), "sha256": digest_file(source)}
        width, height = _image_size(source)
        if width is not None:
            image["width"] = width
        if height is not None:
            image["height"] = height

    image_models = (manifest.get("models") or {}).get("image") or {}
    meta = {}
    if image_models.get("model"):
        meta["model"] = image_models["model"]
    if image_models.get("quality"):
        meta["quality"] = image_models["quality"]

    return new_record(
        prompt=prompt,
        tags=tags,
        source_kind="atelier",
        negative_prompt=negative_prompt,
        image=image,
        source_run_id=manifest["run_id"],
        source_note=source_note,
        meta=meta,
        translations=translations,
        record_id=record_id,
    )


def _copy_media(record: CorpusRecord, media_root: Path) -> CorpusRecord:
    image = record.get("image")
    if not image:
        return record
    source = Path(image["path"])
    relative = f"{record['id']}/{source.name}"
    target = media_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    image["path"] = relative.replace("\\", "/")
    return record


def ingest_run(
    store: CorpusStore,
    run_dir: Path | str,
    *,
    tags: list[str],
    media_root: Path | str,
    prompt: str | None = None,
    negative_prompt: str | None = None,
    source_note: str | None = None,
    translations: dict[str, str | None] | None = None,
    record_id: str | None = None,
) -> CorpusRecord:
    """Archive a finished run: build the record, copy its image into the media
    root, and add it to the store. Returns the stored record."""
    record = from_atelier_run(
        run_dir,
        tags=tags,
        prompt=prompt,
        negative_prompt=negative_prompt,
        source_note=source_note,
        translations=translations,
        record_id=record_id,
    )
    record = _copy_media(record, Path(media_root))
    store.add(record)
    return record
