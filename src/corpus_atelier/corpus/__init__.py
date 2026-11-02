"""The corpus layer: a local-first archive of traceable prompt-image records.

This package provides the closed visual taxonomy, the corpus record schema,
full-text retrieval, and the user-driven ingest path. It is intentionally
separate from the atelier (generation) layer; the only bridge is that finished
atelier runs may be saved into the corpus by explicit user decision.
"""

from .taxonomy import (
    FACETS,
    TAGS,
    TAXONOMY_VERSION,
    Tag,
    facet_label,
    normalize_tags,
    resolve,
    tag_ids,
    tags_of,
)

__all__ = [
    "FACETS",
    "TAGS",
    "TAXONOMY_VERSION",
    "Tag",
    "facet_label",
    "normalize_tags",
    "resolve",
    "tag_ids",
    "tags_of",
]
