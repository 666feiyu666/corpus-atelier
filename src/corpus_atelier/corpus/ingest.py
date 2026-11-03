"""User-driven ingest: turn one finished prompt-session result into a corpus record.

Archiving is always an explicit user decision — nothing is auto-archived. This
module only provides the programmatic entry the UI calls on the user's behalf,
with the labels the user picked.
"""

from __future__ import annotations

from pathlib import Path
import shutil

from ..artifacts.hashing import digest_file
from ..artifacts.store import read_manifest
from ..prompt_session.records import find_attempt, find_result, load_session
from .index import CorpusStore
from .records import CorpusRecord, new_record


def image_size(path: Path) -> tuple[int | None, int | None]:
    """Return an image's pixel size, or (None, None) when it cannot be read."""
    try:
        from PIL import Image

        with Image.open(path) as img:
            return img.width, img.height
    except Exception:
        return None, None


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


def from_prompt_session(
    run_dir: Path | str,
    *,
    tags: list[str],
    image_id: str | None = None,
    source_note: str | None = None,
    translations: dict[str, str | None] | None = None,
    record_id: str | None = None,
) -> CorpusRecord:
    """Build a record from one verified prompt-session result.

    The archived prompt is the exact text sent for that image, which for an edit
    is the visible edit instruction rather than the full-scene prompt.
    """
    run_dir = Path(run_dir)
    manifest = read_manifest(run_dir / "manifest.json")
    if not manifest.get("is_prompt_session"):
        raise ValueError("Only a prompt session can be archived through this path.")
    session = load_session(run_dir)
    image = (
        find_result(session, image_id) if image_id is not None
        else next(
            (item for item in reversed(session["image_results"])
             if item["id"] == session.get("active_image_id")),
            session["image_results"][-1] if session["image_results"] else None,
        )
    )
    if image is None:
        raise ValueError("The prompt session has no result image to archive.")
    source = run_dir / image["image_path"]
    if not source.is_file():
        raise ValueError(f"The result image is missing: {image['image_path']}")
    if digest_file(source) != image["sha256"]:
        raise ValueError("The result image changed after it was generated.")
    attempt = find_attempt(session, image["attempt_id"])
    record = {
        "path": source.resolve().as_posix(),
        "sha256": image["sha256"],
    }
    width, height = image_size(source)
    if width is not None:
        record["width"] = width
    if height is not None:
        record["height"] = height
    meta = {}
    settings = attempt.get("settings") or {}
    for key in ("model", "quality", "size"):
        if settings.get(key):
            meta[key] = settings[key]
    return new_record(
        prompt=attempt["request_text"],
        tags=tags,
        source_kind="atelier",
        image=record,
        source_run_id=manifest["run_id"],
        source_note=source_note,
        meta=meta,
        translations=translations,
        record_id=record_id,
    )


def ingest_prompt_session(
    store: CorpusStore,
    run_dir: Path | str,
    *,
    tags: list[str],
    media_root: Path | str,
    image_id: str | None = None,
    source_note: str | None = None,
    translations: dict[str, str | None] | None = None,
    record_id: str | None = None,
) -> CorpusRecord:
    """Archive one prompt-session result and copy its verified image."""
    record = from_prompt_session(
        run_dir,
        tags=tags,
        image_id=image_id,
        source_note=source_note,
        translations=translations,
        record_id=record_id,
    )
    record = _copy_media(record, Path(media_root))
    store.add(record)
    return record
