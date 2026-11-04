"""Corpus search, taxonomy, media, and explicit archiving of a result."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Response

from ..artifacts.hashing import digest_file
from ..corpus import FACETS, facet_label, tags_of
from ..corpus.gallery import ensure_gallery_seed
from ..corpus.index import CorpusStore
from ..corpus.ingest import ingest_prompt_session
from ..media import content_type
from . import projections
from .deps import RuntimeDep
from .errors import invalid, not_found
from .schemas import ArchiveCreate


MAX_RESULTS = 500

router = APIRouter(prefix="/api/v1", tags=["corpus"])


def _open_store(runtime: RuntimeDep) -> CorpusStore:
    db_path = runtime.paths.corpus_db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    runtime.paths.corpus_media_root.mkdir(parents=True, exist_ok=True)
    return CorpusStore(db_path)


def _media_path(media_root: Path, record: dict) -> Path:
    """Resolve one record's archived image inside the media root, digest checked."""
    image = record.get("image") or {}
    relative = image.get("path")
    if not isinstance(relative, str) or not relative:
        raise not_found("That corpus record has no archived image.")
    try:
        path = (media_root / relative).resolve(strict=True)
    except OSError:
        raise not_found("That corpus image is missing.") from None
    if media_root not in path.parents or not path.is_file():
        raise not_found("That corpus image is missing.")
    expected = image.get("sha256")
    if isinstance(expected, str) and digest_file(path) != expected:
        raise not_found("That corpus image changed after it was archived.")
    return path


@router.get("/corpus/search")
def search_corpus(
    response: Response,
    runtime: RuntimeDep,
    q: str | None = None,
    tags: str | None = None,
    limit: int = 20,
    page: int = 0,
) -> dict:
    limit = max(1, min(int(limit), MAX_RESULTS))
    page = max(0, int(page))
    known = set(tags_of("collection")) | {tag.id for facet in FACETS for tag in tags_of(facet)}
    wanted = [
        item for item in (tags or "").split(",") if item.strip() and item.strip() in known
    ]
    store = _open_store(runtime)
    try:
        seeded = ensure_gallery_seed(store, media_root=runtime.paths.corpus_media_root)
        records = store.search(q or None, tags=wanted or None, limit=MAX_RESULTS)
    finally:
        store.close()
    if seeded is not None:
        response.headers["X-Corpus-Seeded"] = "1"
    start = page * limit
    return {
        "total": len(records),
        "page": page,
        "limit": limit,
        "records": [
            projections.record_view(record) for record in records[start:start + limit]
        ],
    }


@router.get("/corpus/taxonomy")
def corpus_taxonomy() -> dict:
    return {
        "facets": [
            {
                "id": facet,
                "label": {"en": facet_label(facet)[0], "zh": facet_label(facet)[1]},
                "tags": [
                    {"id": tag.id, "en": tag.en, "zh": tag.zh} for tag in tags_of(facet)
                ],
            }
            for facet in FACETS
        ]
    }


@router.get("/corpus/media/{record_id}")
def read_corpus_media(record_id: str, runtime: RuntimeDep) -> Response:
    store = _open_store(runtime)
    try:
        record = store.get(record_id)
    finally:
        store.close()
    if record is None:
        raise not_found("That corpus record does not exist.")
    path = _media_path(runtime.paths.corpus_media_root, record)
    return Response(
        content=path.read_bytes(),
        media_type=content_type(path),
        headers={"Cache-Control": "private, max-age=0, must-revalidate"},
    )


@router.post("/tasks/{run_id}/archive", status_code=201)
def archive_result(run_id: str, body: ArchiveCreate, runtime: RuntimeDep) -> dict:
    if not body.tags:
        raise invalid("Choose at least one corpus label to archive this result.")
    summary = runtime.summary(run_id)
    if not summary.manifest.get("is_prompt_session"):
        raise invalid("Only a prompt session can be archived.")
    runtime.paths.corpus_media_root.mkdir(parents=True, exist_ok=True)
    store = _open_store(runtime)
    try:
        record = ingest_prompt_session(
            store,
            summary.run_dir,
            tags=body.tags,
            media_root=runtime.paths.corpus_media_root,
            image_id=body.image_id,
            source_note=body.source_note,
        )
    finally:
        store.close()
    return {"record": projections.record_view(record)}
