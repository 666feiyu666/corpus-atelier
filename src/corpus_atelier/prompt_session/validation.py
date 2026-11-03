"""Validation of user-supplied prompt text and one session's frozen settings."""

from __future__ import annotations

from typing import Any

from ..config.models import IMAGE_QUALITIES
from ..design_support.canvas import reduce_ratio, resolve_image_size
from .records import MAX_PROMPT_LENGTH


def validate_prompt_text(prompt_text: object) -> str:
    """Keep the user's prompt byte-for-byte; only emptiness and length are checked."""
    if not isinstance(prompt_text, str) or not prompt_text.strip():
        raise ValueError("Write a prompt before continuing.")
    if len(prompt_text) > MAX_PROMPT_LENGTH:
        raise ValueError(f"A prompt must be at most {MAX_PROMPT_LENGTH} characters.")
    return prompt_text


def validate_session_settings(value: dict | None) -> dict[str, Any]:
    """Resolve the explicit image settings a session freezes for every attempt."""
    value = dict(value or {})
    quality = value.get("image_quality") or "medium"
    if quality not in IMAGE_QUALITIES:
        raise ValueError(f"Unsupported image quality: {quality!r}.")
    ratio = value.get("aspect_ratio") or (1, 1)
    if not isinstance(ratio, (list, tuple)) or len(ratio) != 2:
        raise ValueError("An aspect ratio requires exactly two integers.")
    try:
        width, height = int(ratio[0]), int(ratio[1])
    except (TypeError, ValueError) as exc:
        raise ValueError("An aspect ratio requires exactly two integers.") from exc
    if isinstance(ratio[0], bool) or isinstance(ratio[1], bool):
        raise ValueError("An aspect ratio requires exactly two integers.")
    size, ratio = resolve_image_size(reduce_ratio(width, height))
    return {"image_quality": quality, "aspect_ratio": list(ratio), "size": size}
