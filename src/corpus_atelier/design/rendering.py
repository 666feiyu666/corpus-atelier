"""Deterministic final-canvas normalization while preserving model output."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from ..artifacts.hashing import digest_file
from ..artifacts.records import write_json


def normalize_canvas(image_path: Path, ratio: tuple[int, int]) -> tuple[Path, dict]:
    """Center-crop to an exact integer ratio; keep the provider image as source.png."""
    with Image.open(image_path) as opened:
        width, height = opened.size
        x_ratio, y_ratio = ratio
        if width * y_ratio == height * x_ratio:
            record = {
                "operation": "identity", "source_file": image_path.name,
                "source_sha256": digest_file(image_path), "output_file": image_path.name,
                "output_sha256": digest_file(image_path), "output_size": [width, height],
                "ratio": [x_ratio, y_ratio],
            }
            write_json(image_path.parent / "render.json", record)
            return image_path, record
        scale = min(width // x_ratio, height // y_ratio)
        if scale < 1:
            raise ValueError("Provider image is too small for the requested output ratio.")
        target_width, target_height = x_ratio * scale, y_ratio * scale
        left = (width - target_width) // 2
        top = (height - target_height) // 2
        cropped = opened.crop((left, top, left + target_width, top + target_height))
        source = image_path.with_name("source.png")
        image_path.replace(source)
        cropped.save(image_path, format="PNG")
    record = {
        "operation": "center_crop", "source_file": source.name,
        "source_sha256": digest_file(source), "source_size": [width, height],
        "output_file": image_path.name, "output_sha256": digest_file(image_path),
        "output_size": [target_width, target_height], "ratio": [x_ratio, y_ratio],
        "crop_box": [left, top, left + target_width, top + target_height],
    }
    write_json(image_path.parent / "render.json", record)
    return image_path, record
