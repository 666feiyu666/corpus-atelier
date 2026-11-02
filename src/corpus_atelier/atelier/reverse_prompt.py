"""Reverse-engineer a reusable (positive, negative) prompt pair from an image.

Mirrors the ``get-prompt-from-image`` capability of GPT-Image2-Skill: a
vision-capable text provider reads one image and returns a self-contained
positive prompt plus a short, targeted negative prompt.
"""

from __future__ import annotations

from pathlib import Path

from ..providers.text import OpenAITextProvider


def reverse_prompt_instruction() -> str:
    """The deterministic extraction instruction (no injected scene content)."""
    return (
        "Extract a reusable positive prompt and a short, targeted negative prompt from "
        "the reference image. The positive prompt must describe what the image shows and "
        "how it is made — medium, style, palette, lighting, composition — as one "
        "self-contained English instruction, without inventing entities the image does "
        "not contain. The negative prompt must list only plausible misreadings of this "
        "specific image, not a generic defect catalogue. Do not name the reference file "
        "or refer to 'the image' inside the prompts; write them to stand alone."
    )


def reverse_prompt(
    provider: OpenAITextProvider,
    image_path: Path,
) -> tuple[dict, dict]:
    """Extract a ``{positive_prompt, negative_prompt}`` pair from one image."""
    return provider.propose(
        reverse_prompt_instruction(),
        schema_name="reverse-prompt.schema.json",
        reference_paths=[image_path],
    )
