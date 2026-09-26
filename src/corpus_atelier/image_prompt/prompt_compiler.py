"""Compile a design proposal for an image-prompt skill and renderer."""

import json

from ..skill_loader import load_skill, load_skill_reference


def compile_image_spec_prompt(
    proposal: dict, *, brief: dict, canvas: dict, provider_profile: str,
) -> str:
    sections = [
        load_skill("image-llm-prompt"),
        "# Visual-semantic disambiguation guidance\n\n" + load_skill_reference(
            "image-llm-prompt", "semantic-disambiguation.md",
        ),
    ]
    if provider_profile == "gpt-image-2":
        sections.append(
            "# Target image model\n\n" + load_skill_reference(
                "image-llm-prompt", "gpt-image-2.md",
            )
        )
    sections.extend([
        "# Exact-copy invariant\n\n"
        "Set `visible_copy` to the compilation target's `exact_copy` array exactly, preserving "
        "every string and its order. Treat that array as exhaustive. Any additional wording "
        "mentioned in the proposal is not approved visible copy: omit it rather than adding, "
        "rewriting, combining, splitting, or translating text.",
        "# Compilation target\n\n" + json.dumps({
            "provider_profile": provider_profile,
            "canvas": canvas,
            "exact_copy": brief.get("exact_copy", []),
        }, ensure_ascii=False, indent=2, allow_nan=False),
        "# Completed design proposal\n\n" + json.dumps(
            proposal, ensure_ascii=False, indent=2, allow_nan=False,
        ),
    ])
    return "\n\n".join(sections)


def compile_generation_prompt(image_spec: dict) -> str:
    return "\n\n".join([
        load_skill_reference("image-llm-prompt", "generation-boundaries.md"),
        "# Approved image specification\n\n" + json.dumps(
            image_spec, ensure_ascii=False, indent=2, allow_nan=False,
        ),
    ])
