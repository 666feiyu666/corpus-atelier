"""Deterministic validation and GPT Image 2 canvas resolution."""

from __future__ import annotations

from math import ceil, gcd, isqrt


MIN_PIXELS = 655_360
MAX_PIXELS = 8_294_400
MAX_EDGE = 3_840
TARGET_PIXELS = 1_572_864


def reduce_ratio(width: int, height: int) -> tuple[int, int]:
    """Return a positive reduced ratio accepted by GPT Image 2."""
    if isinstance(width, bool) or isinstance(height, bool):
        raise ValueError("Canvas ratio values must be integers.")
    if not isinstance(width, int) or not isinstance(height, int):
        raise ValueError("Canvas ratio values must be integers.")
    if width < 1 or height < 1:
        raise ValueError("Canvas ratio values must be positive.")
    divisor = gcd(width, height)
    ratio = (width // divisor, height // divisor)
    if max(ratio) > 3 * min(ratio):
        raise ValueError("GPT Image 2 canvas aspect ratio must be between 1:3 and 3:1.")
    return ratio


def resolve_image_size(ratio: tuple[int, int]) -> tuple[str, tuple[int, int]]:
    """Resolve an exact ratio to a supported, moderate GPT Image 2 pixel size."""
    x_ratio, y_ratio = reduce_ratio(*ratio)
    unit_pixels = 256 * x_ratio * y_ratio
    minimum_scale = ceil((MIN_PIXELS / unit_pixels) ** 0.5)
    maximum_scale = min(
        MAX_EDGE // (16 * x_ratio),
        MAX_EDGE // (16 * y_ratio),
        isqrt(MAX_PIXELS // unit_pixels),
    )
    if minimum_scale > maximum_scale:
        raise ValueError("No supported GPT Image 2 size preserves this exact ratio.")
    target_scale = round((TARGET_PIXELS / unit_pixels) ** 0.5)
    scale = min(max(target_scale, minimum_scale), maximum_scale)
    width, height = 16 * x_ratio * scale, 16 * y_ratio * scale
    return f"{width}x{height}", (x_ratio, y_ratio)


def resolve_canvas(image_spec: dict, brief: dict) -> tuple[str, tuple[int, int], dict]:
    """Validate a model-proposed canvas and enforce any user-fixed ratio."""
    try:
        plan = image_spec["canvas_plan"]
        proposed = plan["aspect_ratio"]
        ratio = reduce_ratio(proposed["width"], proposed["height"])
    except (KeyError, TypeError) as exc:
        raise ValueError("A ready general graphic proposal requires canvas_plan.") from exc

    requested = brief["canvas"]
    if requested["mode"] == "fixed":
        fixed = requested["aspect_ratio"]
        fixed_ratio = reduce_ratio(fixed["width"], fixed["height"])
        if ratio != fixed_ratio:
            raise ValueError("The proposed canvas ratio does not match the user-fixed ratio.")

    size, ratio = resolve_image_size(ratio)
    record = {
        "size": size,
        "ratio": list(ratio),
        "mode": requested["mode"],
        "format": plan["format"],
        "orientation": plan["orientation"],
        "viewing_context": plan["viewing_context"],
        "safe_area": plan["safe_area"],
        "size_rationale": plan["size_rationale"],
    }
    return size, ratio, record
