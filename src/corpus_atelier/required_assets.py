"""Validation, archival preparation, and deterministic required-image composition."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import json
from pathlib import Path, PurePath
from typing import Iterable

from PIL import Image, ImageChops, ImageOps, UnidentifiedImageError

from .artifacts.hashing import digest_file
from .artifacts.records import write_bytes, write_json
from .state import RequiredImage


MAX_REQUIRED_IMAGES = 3
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
SUPPORTED_FORMATS = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}
PREPARATION_VERSION = 1
COMPOSITION_VERSION = 1


@dataclass(frozen=True)
class ValidatedRequiredImage:
    asset_id: str
    original_filename: str
    content: bytes
    image_format: str
    extension: str
    width: int
    height: int


def _safe_original_name(value: str) -> str:
    name = PurePath(value.replace("\\", "/")).name.strip()
    return name or "uploaded-image"


def validate_required_images(
    images: Iterable[RequiredImage] | None,
) -> list[ValidatedRequiredImage]:
    """Validate untrusted uploads before any run directory is created."""
    values = list(images or [])
    if len(values) > MAX_REQUIRED_IMAGES:
        raise ValueError(
            f"A design may include at most {MAX_REQUIRED_IMAGES} required images."
        )
    validated: list[ValidatedRequiredImage] = []
    for index, upload in enumerate(values, start=1):
        if not isinstance(upload, RequiredImage):
            raise TypeError("Required images must use the RequiredImage input contract.")
        if not isinstance(upload.content, bytes) or not upload.content:
            raise ValueError("A required image upload is empty.")
        if len(upload.content) > MAX_UPLOAD_BYTES:
            raise ValueError("Each required image must be 10 MB or smaller.")
        try:
            with Image.open(BytesIO(upload.content)) as opened:
                image_format = (opened.format or "").upper()
                width, height = opened.size
                opened.verify()
        except (UnidentifiedImageError, OSError, SyntaxError) as exc:
            raise ValueError("A required image is not a valid supported image file.") from exc
        if image_format not in SUPPORTED_FORMATS:
            raise ValueError("Required images must be PNG, JPEG, or WebP files.")
        if width < 1 or height < 1 or width * height > MAX_IMAGE_PIXELS:
            raise ValueError("A required image has unsupported pixel dimensions.")
        validated.append(ValidatedRequiredImage(
            asset_id=f"required-{index:02d}",
            original_filename=_safe_original_name(upload.filename),
            content=upload.content,
            image_format=image_format,
            extension=SUPPORTED_FORMATS[image_format],
            width=width,
            height=height,
        ))
    return validated


def _trim_uniform_outer_margin(image: Image.Image) -> tuple[Image.Image, list[int] | None]:
    """Trim only near-uniform outer background; retain a small protective margin."""
    width, height = image.size
    alpha = image.getchannel("A")
    alpha_extrema = alpha.getextrema()
    if alpha_extrema[0] < 255:
        mask = alpha.point(lambda value: 255 if value > 4 else 0)
    else:
        corners = [
            image.getpixel((0, 0)), image.getpixel((width - 1, 0)),
            image.getpixel((0, height - 1)), image.getpixel((width - 1, height - 1)),
        ]
        background = tuple(
            sorted(pixel[channel] for pixel in corners)[len(corners) // 2]
            for channel in range(4)
        )
        flat = Image.new("RGBA", image.size, background)
        difference = ImageChops.difference(image, flat).convert("RGB").convert("L")
        mask = difference.point(lambda value: 255 if value > 12 else 0)
    box = mask.getbbox()
    if box is None:
        return image, None
    left, top, right, bottom = box
    if right - left < 8 or bottom - top < 8:
        return image, None
    padding = max(2, round(min(width, height) * 0.01))
    expanded = (
        max(0, left - padding), max(0, top - padding),
        min(width, right + padding), min(height, bottom + padding),
    )
    if expanded == (0, 0, width, height):
        return image, None
    return image.crop(expanded), list(expanded)


def _encode(image: Image.Image, image_format: str, **options) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format=image_format, **options)
    return buffer.getvalue()


def ingest_required_images(
    run_dir: Path, images: list[ValidatedRequiredImage],
) -> tuple[list[dict], list[str], dict[str, str]]:
    """Persist immutable originals plus deterministic prepared and preview derivatives."""
    records: list[dict] = []
    prepared_paths: list[str] = []
    artifacts: dict[str, str] = {}
    for upload in images:
        root = run_dir / "input" / "required-assets" / upload.asset_id
        original = root / f"original.{upload.extension}"
        prepared = root / "prepared.png"
        preview = root / "preview.webp"
        metadata = root / "asset.json"
        write_bytes(original, upload.content)

        with Image.open(BytesIO(upload.content)) as opened:
            oriented = ImageOps.exif_transpose(opened)
            rgba = oriented.convert("RGBA")
        prepared_image, crop_box = _trim_uniform_outer_margin(rgba)
        write_bytes(prepared, _encode(prepared_image, "PNG", optimize=True))
        thumbnail = prepared_image.copy()
        thumbnail.thumbnail((512, 512), Image.Resampling.LANCZOS)
        write_bytes(preview, _encode(thumbnail, "WEBP", quality=82, method=6))

        transforms: list[dict] = [
            {"operation": "exif_transpose", "version": PREPARATION_VERSION},
        ]
        if crop_box is not None:
            transforms.append({
                "operation": "trim_uniform_outer_margin",
                "crop_box": crop_box,
                "version": PREPARATION_VERSION,
            })
        transforms.append({
            "operation": "convert_color", "mode": "RGBA", "profile": "sRGB",
            "version": PREPARATION_VERSION,
        })
        record = {
            "format_version": 1,
            "asset_id": upload.asset_id,
            "role": "required_exact_image",
            "original_filename": upload.original_filename,
            "original_file": original.name,
            "original_format": upload.image_format,
            "original_sha256": digest_file(original),
            "original_size": [upload.width, upload.height],
            "prepared_file": prepared.name,
            "prepared_sha256": digest_file(prepared),
            "prepared_size": list(prepared_image.size),
            "preview_file": preview.name,
            "preview_sha256": digest_file(preview),
            "transforms": transforms,
        }
        write_json(metadata, record)
        records.append(record)
        prepared_paths.append(str(prepared.resolve()))
        key = upload.asset_id.replace("-", "_")
        relative = root.relative_to(run_dir).as_posix()
        artifacts.update({
            f"{key}_original": f"{relative}/{original.name}",
            f"{key}_prepared": f"{relative}/{prepared.name}",
            f"{key}_preview": f"{relative}/{preview.name}",
            f"{key}_metadata": f"{relative}/{metadata.name}",
        })
    return records, prepared_paths, artifacts


def validate_required_asset_integrity(
    records: list[dict], prepared_paths: list[str],
) -> None:
    if len(records) != len(prepared_paths):
        raise ValueError("Required-image records and prepared files do not match.")
    for record, value in zip(records, prepared_paths, strict=True):
        prepared = Path(value)
        original = prepared.with_name(record["original_file"])
        preview = prepared.with_name(record["preview_file"])
        metadata = prepared.with_name("asset.json")
        if (
            not original.is_file()
            or not prepared.is_file()
            or not preview.is_file()
            or not metadata.is_file()
            or digest_file(original) != record["original_sha256"]
            or digest_file(prepared) != record["prepared_sha256"]
            or digest_file(preview) != record["preview_sha256"]
            or json.loads(metadata.read_text(encoding="utf-8")) != record
        ):
            raise ValueError("A required image changed after the generation preview.")


def build_composition_plan(image_spec: dict, records: list[dict]) -> dict:
    return {
        "format_version": 1,
        "operation": "deterministic_required_image_composition",
        "assets": [
            {
                "asset_id": record["asset_id"],
                "prepared_sha256": record["prepared_sha256"],
                "prepared_size": record["prepared_size"],
            }
            for record in records
        ],
        "placements": image_spec["required_asset_placements"],
    }


def compose_required_assets(
    image_path: Path, records: list[dict], prepared_paths: list[str],
    placements: list[dict],
) -> tuple[Path, dict]:
    """Place prepared user images into approved normalized rectangles."""
    background = image_path.with_name("background.png")
    image_path.replace(background)
    with Image.open(background) as opened:
        canvas = opened.convert("RGBA")
    width, height = canvas.size
    record_by_id = {record["asset_id"]: record for record in records}
    path_by_id = {
        record["asset_id"]: Path(path)
        for record, path in zip(records, prepared_paths, strict=True)
    }
    applied: list[dict] = []
    for placement in placements:
        asset_id = placement["asset_id"]
        record = record_by_id[asset_id]
        path = path_by_id[asset_id]
        left = round(placement["left"] * width)
        top = round(placement["top"] * height)
        box_width = max(1, round(placement["width"] * width))
        box_height = max(1, round(placement["height"] * height))
        with Image.open(path) as opened:
            asset = opened.convert("RGBA")
        scale = min(box_width / asset.width, box_height / asset.height)
        target_size = (
            max(1, round(asset.width * scale)),
            max(1, round(asset.height * scale)),
        )
        resized = asset.resize(target_size, Image.Resampling.LANCZOS)
        paste_left = left + (box_width - target_size[0]) // 2
        paste_top = top + (box_height - target_size[1]) // 2
        canvas.alpha_composite(resized, (paste_left, paste_top))
        applied.append({
            "asset_id": asset_id,
            "prepared_sha256": record["prepared_sha256"],
            "normalized_box": {
                key: placement[key] for key in ("left", "top", "width", "height")
            },
            "pixel_box": [left, top, left + box_width, top + box_height],
            "paste_box": [
                paste_left, paste_top,
                paste_left + target_size[0], paste_top + target_size[1],
            ],
        })
    write_bytes(image_path, _encode(canvas, "PNG", optimize=True))
    composition = {
        "format_version": 1,
        "operation": "deterministic_required_image_composition",
        "version": COMPOSITION_VERSION,
        "background_file": background.name,
        "background_sha256": digest_file(background),
        "output_file": image_path.name,
        "output_sha256": digest_file(image_path),
        "output_size": [width, height],
        "placements": applied,
    }
    write_json(image_path.parent / "composition.json", composition)
    return image_path, composition
