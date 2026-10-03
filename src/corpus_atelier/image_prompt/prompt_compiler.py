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
        "# Design contract invariants\n\n"
        "The compilation target includes brief constraints and confirmed user_requirements. "
        "Preserve these requirements in the image specification even if the proposal omitted or "
        "weakened them. Confirmed user_requirements take precedence over conflicting inferred "
        "preferences. Requirement descriptions are not additional visible copy; only exact_copy "
        "is approved wording for the image.",
        "# Compilation target\n\n" + json.dumps({
            "provider_profile": provider_profile,
            "canvas": canvas,
            "exact_copy": brief.get("exact_copy", []),
            "constraints": brief.get("constraints", []),
            "user_requirements": brief.get("user_requirements", []),
        }, ensure_ascii=False, indent=2, allow_nan=False),
        "# Completed design proposal\n\n" + json.dumps(
            proposal, ensure_ascii=False, indent=2, allow_nan=False,
        ),
    ])
    return "\n\n".join(sections)


def compile_generation_prompt(image_spec: dict, *, user_requirements: list[str] | None = None) -> str:
    sections = [
        load_skill_reference("image-llm-prompt", "generation-boundaries.md"),
        "# Approved image specification\n\n" + json.dumps(
            image_spec, ensure_ascii=False, indent=2, allow_nan=False,
        ),
    ]
    if user_requirements:
        sections.append(
            "# Confirmed user requirements\n\n"
            "Every item below is mandatory for the finished design and takes precedence over "
            "conflicting visual details in the specification. Requirement descriptions are not "
            "additional text to render; render only visible_copy exactly as approved.\n\n"
            + json.dumps(user_requirements, ensure_ascii=False, indent=2, allow_nan=False)
        )
    return "\n\n".join(sections)
