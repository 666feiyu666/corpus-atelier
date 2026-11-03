"""Validate user-supplied generation inputs: reference images and an inpaint mask."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image


SUFFIXES = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp"}
MAX_BYTES = 10 * 1024 * 1024


def validate_reference_images(
    images: list[tuple[str, bytes]] | tuple[tuple[str, bytes], ...],
) -> list[tuple[str, bytes, str]]:
    """Return ``(name, data, suffix)`` for up to three supported images."""
    images = list(images)
    if len(images) > 3:
        raise ValueError("Attach at most three reference images.")
    normalized: list[tuple[str, bytes, str]] = []
    for name, data in images:
        if len(data) > MAX_BYTES:
            raise ValueError("Each reference image must be at most 10 MB.")
        with Image.open(BytesIO(data)) as image:
            if image.format not in SUFFIXES:
                raise ValueError("Reference images must be PNG, JPEG, or WebP.")
            if image.width * image.height > 20_000_000:
                raise ValueError("Reference images must be at most 20 megapixels.")
            image.load()
            normalized.append((Path(name).name, data, SUFFIXES[image.format]))
    return normalized


def validate_mask(
    mask: tuple[str, bytes] | None,
    references: list[tuple[str, bytes, str]],
) -> tuple[str, bytes] | None:
    """Return ``(name, data)`` for one PNG mask paired with exactly one reference."""
    if mask is None:
        return None
    name, data = mask
    if len(data) > MAX_BYTES:
        raise ValueError("The mask must be at most 10 MB.")
    with Image.open(BytesIO(data)) as image:
        if image.format != "PNG" or image.mode != "RGBA":
            raise ValueError("The mask must be a PNG with an alpha channel.")
        image.load()
    if len(references) != 1:
        raise ValueError("Mask inpainting requires exactly one reference image.")
    return Path(name).name, data
