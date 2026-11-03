"""The workflow runtime: stage mixins composed into one entry point."""

from __future__ import annotations

from pathlib import Path
from ...artifacts.store import ArtifactStore
from ...providers.image import ImageProvider
from ...providers.text import TextProvider
from ..state import AtelierState

from .intake import IntakeMixin
from .directions import DirectionsMixin
from .candidates import CandidatesMixin
from .approval import ApprovalMixin
from .generation import GenerationMixin

class WorkflowRuntime(IntakeMixin, DirectionsMixin, CandidatesMixin, ApprovalMixin, GenerationMixin):
    """Execute workflow stages; the application owns task and checkpoint lifecycle."""

    MAX_EDITABLE_PROMPT_CHARS = 20000

    def __init__(self, store: ArtifactStore, text_provider: TextProvider,
                 image_provider: ImageProvider,
                 corpus_db_path: Path | str | None = None) -> None:
        self.store = store
        self.text_provider = text_provider
        self.image_provider = image_provider
        self.corpus_db_path = Path(corpus_db_path) if corpus_db_path is not None else None

    @staticmethod
    def _dir(state: AtelierState) -> Path:
        return Path(state["run_dir"])
