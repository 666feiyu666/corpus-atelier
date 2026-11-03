"""Validation of user-supplied prompt text and one session's frozen settings."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..config.models import IMAGE_QUALITIES
from ..design_support.canvas import canvas_from_source, reduce_ratio, resolve_image_size
from .records import MAX_PROMPT_LENGTH


def validate_prompt_text(prompt_text: object) -> str:
    """Keep the user's prompt byte-for-byte; only emptiness and length are checked."""
    if not isinstance(prompt_text, str) or not prompt_text.strip():
        raise ValueError("Write a prompt before continuing.")
    if len(prompt_text) > MAX_PROMPT_LENGTH:
        raise ValueError(f"A prompt must be at most {MAX_PROMPT_LENGTH} characters.")
    return prompt_text


def _canvas_record(value: object, *, label: str) -> dict[str, int] | None:
    """Read one ``{width, height}`` canvas record, rejecting malformed values."""
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must provide integer width and height.")
    try:
        width, height = int(value["width"]), int(value["height"])  # type: ignore[index]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{label} must provide integer width and height.") from exc
    if width < 1 or height < 1:
        raise ValueError(f"{label} must use positive dimensions.")
    return {"width": width, "height": height}


def _ratio(value: object) -> tuple[int, int]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError("An aspect ratio requires exactly two integers.")
    if isinstance(value[0], bool) or isinstance(value[1], bool):
        raise ValueError("An aspect ratio requires exactly two integers.")
    try:
        width, height = int(value[0]), int(value[1])
    except (TypeError, ValueError) as exc:
        raise ValueError("An aspect ratio requires exactly two integers.") from exc
    return width, height


def resolve_canvas_settings(value: dict | None) -> dict[str, Any]:
    """Resolve the source canvas, the requested output, and the provider size.

    An image-started session keeps the source image's exact ratio unless the user
    explicitly requests another canvas. When no supported provider size keeps the
    requested ratio, ``size`` stays ``None`` and ``canvas_note`` explains why, so
    the interface must ask for an explicit choice before generating.
    """
    value = dict(value or {})
    source_canvas = _canvas_record(value.get("source_canvas"), label="The source canvas")
    requested_canvas = _canvas_record(value.get("requested_canvas"), label="The requested canvas")
    fallback = _ratio(value.get("aspect_ratio") or (1, 1))

    origin = "default"
    candidate: tuple[int, int] | None = None
    if requested_canvas is not None:
        origin = "user"
        candidate = (requested_canvas["width"], requested_canvas["height"])
    elif source_canvas is not None:
        origin = "source"
        candidate = (source_canvas["width"], source_canvas["height"])

    if candidate is None:
        size, ratio, note = None, None, None
        try:
            size, ratio = resolve_image_size(reduce_ratio(*fallback))
        except ValueError as exc:
            note = str(exc)
    else:
        size, ratio, note = canvas_from_source(*candidate)

    return {
        "aspect_ratio": list(ratio) if ratio else list(fallback),
        "size": size,
        "source_canvas": source_canvas,
        "requested_canvas": requested_canvas,
        "canvas_origin": origin,
        "canvas_note": note,
    }


def validate_session_settings(value: dict | None) -> dict[str, Any]:
    """Validate the quality once and resolve the canvas the session will use."""
    value = dict(value or {})
    quality = value.get("image_quality") or "medium"
    if quality not in IMAGE_QUALITIES:
        raise ValueError(f"Unsupported image quality: {quality!r}.")
    return {"image_quality": quality, **resolve_canvas_settings(value)}
