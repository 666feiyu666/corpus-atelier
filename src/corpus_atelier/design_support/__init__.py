"""Deterministic support shared by the design stages and adapters."""

from .canvas import reduce_ratio, resolve_image_size
from .validation import load_schema, validate

__all__ = [
    "load_schema",
    "reduce_ratio",
    "resolve_image_size",
    "validate",
]
