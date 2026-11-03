"""Parse the upstream GPT-Image2-Skill reference gallery into corpus seed data.

The gallery is a set of Markdown category files, one per visual collection. Each
entry names an image, records its metadata, and carries the prompt in a fenced
text block. This module turns that prose into structured records so the corpus
layer can index and search them; the original Markdown stays upstream.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..artifacts.hashing import digest_file
from .index import CorpusStore
from .ingest import image_size
from .records import CorpusRecord, new_record
from .taxonomy import tag_ids


SEED_FORMAT_VERSION = 1
UPSTREAM_REPOSITORY = "https://github.com/wuyoscar/GPT-Image2-Skill"
UPSTREAM_LICENSE = "MIT"

# Extra closed-taxonomy labels that hold for a whole collection. Only mappings
# that are certain from the collection's own name are listed; everything else is
# left to the reader of the prompt.
COLLECTION_EXTRA_TAGS: dict[str, tuple[str, ...]] = {
    "gallery-typography-and-posters": ("typographic",),
    "gallery-brand-systems-and-identity": ("typographic",),
    "gallery-infographics-and-field-guides": ("typographic",),
    "gallery-data-visualization": ("typographic",),
    "gallery-research-paper-figures": ("typographic",),
    "gallery-ui-ux-mockups": ("typographic",),
    "gallery-photography": ("photography",),
    "gallery-fashion-editorial": ("photography",),
    "gallery-cinematic-film-references": ("photography",),
    "gallery-beauty-and-lifestyle": ("photography",),
    "gallery-screen-photography": ("photography",),
    "gallery-watercolor": ("painterly",),
    "gallery-fine-art-painting": ("painterly",),
    "gallery-ink-and-chinese": ("painterly",),
    "gallery-illustration": ("illustration",),
    "gallery-anime-and-manga": ("illustration",),
    "gallery-gaming": ("illustration",),
    "gallery-pixel-art": ("illustration",),
    "gallery-isometric": ("illustration",),
    "gallery-technical-illustration": ("illustration",),
    "gallery-scientific-and-educational": ("illustration",),
    "gallery-more-illustration-styles": ("illustration",),
    "gallery-character-design": ("illustration",),
    "gallery-tattoo-design": ("illustration",),
    "gallery-architecture-and-interior": ("3d-render",),
    "gallery-events-and-experience": ("poster",),
}

_ENTRY = re.compile(r"^### No\. (\d+) · (.+)$")
_IMAGE = re.compile(r"^- Image: `([^`]+)`")
_FENCE = re.compile(r"^```")
_SOURCE = re.compile(r"Source: \[[^\]]*\]\(([^)]+)\)")
_AUTHOR = re.compile(r"Author: ([^·]+)")
_DIMENSION = re.compile(r"^\d+x\d+$")
_ASPECTS = {"portrait", "landscape", "square"}


def collection_tags(collection: str) -> list[str]:
    """Return the closed labels a collection contributes, collection id first."""
    extra = COLLECTION_EXTRA_TAGS.get(collection, ())
    return [collection, *extra]


def parse_gallery_markdown(text: str, collection: str) -> list[dict]:
    """Parse one gallery category file into seed entries."""
    if collection not in tag_ids("collection"):
        raise ValueError(f"Unknown gallery collection {collection!r}.")

    entries: list[dict] = []
    current: dict | None = None
    in_fence = False
    prompt_lines: list[str] = []

    for raw in text.splitlines():
        line = raw.rstrip()
        heading = _ENTRY.match(line)
        if heading and not in_fence:
            current = {
                "id": f"gallery-no-{int(heading.group(1)):03d}",
                "number": int(heading.group(1)),
                "title": heading.group(2).strip(),
                "collection": collection,
                "tags": collection_tags(collection),
                "size": None,
                "aspect": None,
                "author": None,
                "source_url": None,
                "image_source": None,
                "prompt": "",
            }
            entries.append(current)
            continue
        if current is None:
            continue
        if _FENCE.match(line):
            if in_fence:
                current["prompt"] = "\n".join(prompt_lines).strip()
                prompt_lines = []
                in_fence = False
            else:
                in_fence = True
            continue
        if in_fence:
            prompt_lines.append(raw)
            continue
        image = _IMAGE.match(line)
        if image and current["image_source"] is None:
            current["image_source"] = image.group(1).strip()
            continue
        if line.startswith("- Metadata:"):
            _apply_metadata(current, line)
    return [entry for entry in entries if entry["prompt"]]


def _apply_metadata(entry: dict, line: str) -> None:
    source = _SOURCE.search(line)
    if source:
        entry["source_url"] = source.group(1).strip()
    author = _AUTHOR.search(line)
    if author:
        entry["author"] = author.group(1).strip()
    for token in re.findall(r"`([^`]+)`", line):
        if token in _ASPECTS:
            entry["aspect"] = token
        elif _DIMENSION.match(token):
            entry["size"] = token


def build_seed(gallery_dir: Path | str) -> dict:
    """Build the whole seed document from a gallery reference directory."""
    gallery_dir = Path(gallery_dir)
    records: list[dict] = []
    for path in sorted(gallery_dir.glob("gallery-*.md")):
        if path.name == "gallery.md":
            continue
        collection = f"gallery-{path.stem[len('gallery-'):]}"
        if collection not in tag_ids("collection"):
            raise ValueError(
                f"Gallery file {path.name} has no matching collection label."
            )
        records.extend(parse_gallery_markdown(path.read_text(encoding="utf-8"), collection))
    records.sort(key=lambda entry: entry["number"])
    return {
        "format_version": SEED_FORMAT_VERSION,
        "source": {
            "repository": UPSTREAM_REPOSITORY,
            "license": UPSTREAM_LICENSE,
            "note": (
                "Prompts and metadata from the GPT-Image2-Skill Reference Gallery. "
                "Images stay in the upstream repository and are copied into the local "
                "corpus media root at import time."
            ),
        },
        "records": records,
    }


def load_seed(path: Path | str) -> dict:
    """Load and validate a seed document."""
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("format_version") != SEED_FORMAT_VERSION:
        raise ValueError("Unsupported gallery seed format.")
    records = document.get("records")
    if not isinstance(records, list) or not records:
        raise ValueError("The gallery seed has no records.")
    for record in records:
        for field in ("id", "prompt", "collection", "tags", "title"):
            if not record.get(field):
                raise ValueError(f"Gallery seed record is missing {field!r}: {record!r}")
        if record["collection"] not in tag_ids("collection"):
            raise ValueError(f"Unknown collection in seed: {record['collection']!r}")
    return document


SEED_EPOCH = datetime(2024, 1, 1, tzinfo=timezone.utc)


@dataclass(frozen=True)
class ImportReport:
    """What one seed import changed, so the caller can report it honestly."""

    total: int
    imported: int
    copied_media: int
    missing_media: tuple[str, ...]
    entries_without_image: tuple[str, ...]


def _seed_created_at(number: int) -> str:
    """A stable timestamp per entry, so retrieval order follows the gallery."""
    return (SEED_EPOCH + timedelta(seconds=number)).isoformat()


def _seed_image(
    entry: dict, media_root: Path, source_root: Path | None,
) -> tuple[dict | None, str]:
    """Copy one entry's image into the media root; return (image, state)."""
    relative = entry.get("image_source")
    if not relative:
        return None, "none"
    if source_root is None:
        return None, "missing"
    source = source_root / relative
    if not source.is_file():
        return None, "missing"
    target_relative = f"{entry['id']}/{source.name}"
    target = media_root / target_relative
    digest = digest_file(source)
    state = "reused"
    if not target.is_file() or digest_file(target) != digest:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        state = "copied"
    image: dict = {"path": target_relative.replace("\\", "/"), "sha256": digest}
    width, height = image_size(target)
    if width is not None:
        image["width"] = width
    if height is not None:
        image["height"] = height
    return image, state


def _seed_record(
    entry: dict, media_root: Path, source_root: Path | None,
) -> tuple[CorpusRecord, str]:
    image, state = _seed_image(entry, media_root, source_root)
    record = new_record(
        prompt=entry["prompt"],
        tags=list(entry["tags"]),
        source_kind="import",
        image=image,
        source_url=entry.get("source_url"),
        source_note=f"No. {entry['number']} · {entry['title']}",
        meta={"size": entry.get("size")},
        record_id=entry["id"],
        created_at=_seed_created_at(entry["number"]),
    )
    return record, state


def import_seed(
    store: CorpusStore,
    seed: dict,
    *,
    media_root: Path | str,
    source_root: Path | str | None = None,
) -> ImportReport:
    """Import every seed entry into the corpus, copying images from the upstream clone.

    Idempotent: record ids come from the seed and are replaced in place, and an
    image is only copied when the destination is missing or its digest differs.
    ``source_root`` is the upstream repository checkout that still holds the
    images; without it the prompts are archived and the images stay missing.
    """
    media_root = Path(media_root)
    source = Path(source_root) if source_root is not None else None
    copied = 0
    missing: list[str] = []
    without_image: list[str] = []
    imported = 0
    for entry in seed["records"]:
        record, state = _seed_record(entry, media_root, source)
        store.add(record)
        imported += 1
        if state == "copied":
            copied += 1
        elif state == "missing":
            missing.append(entry["id"])
        elif state == "none":
            without_image.append(entry["id"])
    return ImportReport(
        total=len(seed["records"]),
        imported=imported,
        copied_media=copied,
        missing_media=tuple(missing),
        entries_without_image=tuple(without_image),
    )


def packaged_seed_path() -> Path:
    """Return the seed document shipped inside the package."""
    from importlib.resources import files

    return Path(str(files("corpus_atelier").joinpath("corpus", "seed", "gallery.json")))


GALLERY_SEED_ENTRY_ID = "gallery-no-001"


def ensure_gallery_seed(
    store: CorpusStore, *, media_root: Path | str, source_root: Path | str | None = None,
) -> ImportReport | None:
    """Import the packaged seed once; return None when it is already archived.

    The gallery view calls this on first use so a fresh archive is searchable
    without a manual step. Images are only copied when ``source_root`` points at
    an upstream checkout that still holds them.
    """
    if store.get(GALLERY_SEED_ENTRY_ID) is not None:
        return None
    return import_seed(
        store,
        load_seed(packaged_seed_path()),
        media_root=media_root,
        source_root=source_root,
    )
