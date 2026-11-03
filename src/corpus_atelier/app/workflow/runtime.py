"""The workflow runtime: stage mixins composed into one entry point."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ...artifacts.store import ArtifactStore
from ...corpus.index import CorpusStore
from ...corpus.taxonomy import tag_ids
from ...providers.image import ImageProvider
from ...providers.text import TextProvider
from ..state import AtelierState

from .intake import IntakeMixin
from .directions import DirectionsMixin
from .candidates import CandidatesMixin
from .approval import ApprovalMixin
from .generation import GenerationMixin

LOGGER = logging.getLogger(__name__)


class WorkflowRuntime(IntakeMixin, DirectionsMixin, CandidatesMixin, ApprovalMixin, GenerationMixin):
    """Execute workflow stages; the application owns task and checkpoint lifecycle."""

    MAX_EDITABLE_PROMPT_CHARS = 20000

    def __init__(self, store: ArtifactStore, text_provider: TextProvider,
                 image_provider: ImageProvider,
                 corpus_db_path: Path | str | None = None,
                 corpus_media_root: Path | str | None = None) -> None:
        self.store = store
        self.text_provider = text_provider
        self.image_provider = image_provider
        self.corpus_db_path = Path(corpus_db_path) if corpus_db_path is not None else None
        self.corpus_media_root = (
            Path(corpus_media_root) if corpus_media_root is not None else None
        )

    @staticmethod
    def _dir(state: AtelierState) -> Path:
        return Path(state["run_dir"])

    def _corpus_references(
        self, state: AtelierState, *, limit: int = 3,
    ) -> list[dict[str, Any]]:
        """Advisory archived prompts for this brief; retrieval never blocks a run."""
        if self.corpus_db_path is None:
            return []
        brief = state["brief"]
        query = " ".join(
            str(value) for value in (
                brief.get("topic"), brief.get("article_title"), brief.get("deliverable"),
                *brief.get("preferences", []),
            ) if value
        ).strip()
        collection = self._gallery_collection(brief.get("asset_category"))
        if not query and collection is None:
            return []
        try:
            store = CorpusStore(self.corpus_db_path)
            try:
                tags = [collection] if collection else None
                records = store.reference_slice(query, limit=limit, tags=tags)
                if not records and collection:
                    # The brief may be in a language the archive does not use; the
                    # deliverable category still identifies comparable work.
                    records = store.reference_slice(None, limit=limit, tags=tags)
                return records
            finally:
                store.close()
        except Exception as exc:  # retrieval is advisory, never fatal
            LOGGER.warning("Corpus reference retrieval failed: %s", exc)
            return []

    @staticmethod
    def _gallery_collection(asset_category: str | None) -> str | None:
        """Map a deliverable category to the gallery collection that mirrors it."""
        if not asset_category:
            return None
        candidate = f"gallery-{asset_category}"
        return candidate if candidate in tag_ids("collection") else None

    def _corpus_reference_images(self, references: list[dict[str, Any]]) -> list[Path]:
        """Resolve the reference images that actually exist in the media root."""
        if self.corpus_media_root is None:
            return []
        images = []
        for reference in references:
            relative = reference.get("image")
            if not relative:
                continue
            path = self.corpus_media_root / relative
            if path.is_file():
                images.append(path)
        return images

    def _corpus_image_relatives(self, references: list[dict[str, Any]]) -> list[str]:
        """The attachments' paths relative to the media root, in prompt order."""
        if self.corpus_media_root is None:
            return []
        relatives = []
        for reference in references:
            relative = reference.get("image")
            if relative and (self.corpus_media_root / relative).is_file():
                relatives.append(relative)
        return relatives
