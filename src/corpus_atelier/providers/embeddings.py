"""Optional embeddings interface; lexical retrieval remains the offline default."""

from typing import Protocol


class EmbeddingProvider(Protocol):
    def score(self, query: str, documents: dict[str, str]) -> dict[str, float]: ...
