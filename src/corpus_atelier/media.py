"""Image-file helpers shared by the interface adapters.

Kept out of the Streamlit package so the HTTP API can reuse them: neither module
may depend on the other.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path


CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


def content_type(path: Path) -> str:
    """Return the media type for one archived image, never guessing from data."""
    return CONTENT_TYPES.get(Path(path).suffix.lower(), "application/octet-stream")


def mask_overlay(source: Path, mask: Path) -> bytes:
    """Composite a mask over its source; red marks the pixels to regenerate."""
    from PIL import Image

    with Image.open(source) as base_image, Image.open(mask) as mask_image:
        base = base_image.convert("RGB")
        alpha = mask_image.convert("RGBA").getchannel("A").resize(base.size)
        overlay = Image.new("RGB", base.size, (196, 64, 48))
        highlight = Image.composite(overlay, base, alpha.point(lambda value: 255 - value))
        buffer = BytesIO()
        highlight.save(buffer, format="PNG")
        return buffer.getvalue()
