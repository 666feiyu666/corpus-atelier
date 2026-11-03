"""Compile an approved design into one image-model prompt.

Two deterministic-or-model steps, in this order:

1. ``compile_image_prompt_prompt`` assembles the writer brief: the packaged skill, the craft and
   model-family guidance, the exact-copy invariant, optional corpus references, and the approved
   design.
2. ``compile_generation_prompt`` turns the returned ``image_prompt`` into the single prompt that
   the image model receives. It is deterministic and has no negative-prompt section.
"""

import json

from ...language import compile_language_policy
from ...config.skill_loader import load_skill, load_skill_reference_body


MODEL_FAMILY_REFERENCES = {
    "gpt-image-2": "gpt-image-2.md",
    "gpt-image-2.5": "gpt-image-2.5.md",
}


def compile_image_prompt_prompt(
    *,
    brief: dict,
    canvas: dict,
    provider_profile: str,
    model_family: str = "gpt-image-2",
    design: dict | None = None,
    operation: str = "generation",
    reference_notes: list[str] | None = None,
    corpus_references: list[dict] | None = None,
    content_language: str | None = None,
) -> str:
    """Build the prompt-writing brief for one design.

    ``design`` is the approved design proposal, or the brief itself on the direct-generation
    route where no proposal exists. ``operation`` is ``generation``, ``reference_generation``,
    or ``mask_edit``. Corpus references are advisory evidence, never scene content.
    """
    sections = [
        load_skill("image-llm-prompt"),
        compile_language_policy(content_language or brief.get("content_language")),
        "# Prompt craft checklist\n\n" + load_skill_reference_body("image-llm-prompt", "craft.md"),
        "# Renderer output contract\n\n"
        + load_skill_reference_body("image-llm-prompt", "rendering-boundaries.md"),
    ]
    family_reference = MODEL_FAMILY_REFERENCES.get(model_family)
    if family_reference:
        sections.append(
            f"# Target image model family: {model_family}\n\n"
            + load_skill_reference_body("image-llm-prompt", family_reference)
        )
    if operation != "generation":
        sections.append(
            "# Edit and inpaint invariants\n\n"
            + load_skill_reference_body("image-llm-prompt", "editing.md")
        )
    sections.extend([
        "# Exact-copy invariant\n\n"
        "Set `exact_copy` to the compilation target's `exact_copy` array exactly, preserving "
        "every string and its order. Treat that array as exhaustive. Quote those strings verbatim "
        "inside `prompt` where they appear. Any other wording mentioned in the design is not "
        "approved visible copy: omit it rather than adding, rewriting, combining, splitting, or "
        "translating text.",
        "# Design contract invariants\n\n"
        "The compilation target includes brief constraints and confirmed user_requirements. "
        "Realize them in the prompt even if the approved design omitted or weakened them. "
        "Confirmed user_requirements take precedence over conflicting inferred preferences. "
        "Requirement descriptions are not additional visible copy; only exact_copy is approved "
        "wording for the image.",
    ])
    if corpus_references:
        sections.append(
            "# Reference gallery slice\n\n"
            "Archived prompts whose labels or wording resemble this task. Use them only as "
            "evidence about how similar work is described: borrow vocabulary, layout habits, or "
            "level of detail. Do not copy their subjects, copy, brand names, or composition into "
            "this design.\n\n"
            + json.dumps(corpus_references, ensure_ascii=False, indent=2, allow_nan=False)
        )
    sections.extend([
        "# Compilation target\n\n" + json.dumps({
            "provider_profile": provider_profile,
            "model_family": model_family,
            "operation": operation,
            "canvas": canvas,
            "exact_copy": brief.get("exact_copy", []),
            "constraints": brief.get("constraints", []),
            "user_requirements": brief.get("user_requirements", []),
            "reference_notes": list(reference_notes or []),
        }, ensure_ascii=False, indent=2, allow_nan=False),
        "# Approved design\n\n"
        "This is the design to express as a renderer prompt. Preserve its design decisions "
        "instead of restyling or extending it.\n\n"
        + json.dumps(design or brief, ensure_ascii=False, indent=2, allow_nan=False),
    ])
    return "\n\n".join(sections)


def compile_generation_prompt(
    image_prompt: dict, *,
    exact_copy: list[str] | None = None,
    user_requirements: list[str] | None = None,
) -> str:
    """Assemble the one prompt the image model receives.

    Canvas first, then the resolved scene, then the literal wording, then the confirmed
    requirements, then the edit invariants and targeted exclusions. Settings such as model, size,
    and quality stay outside the prompt.
    """
    parts: list[str] = []
    for field in ("canvas_statement", "prompt"):
        text = (image_prompt.get(field) or "").strip()
        if text:
            parts.append(text)
    copy = list(exact_copy if exact_copy is not None else image_prompt.get("exact_copy") or [])
    if copy:
        parts.append(
            "Render exactly these text strings and no other wording, each quoted evidence of the "
            "approved copy: " + " / ".join(f'"{item}"' for item in copy)
        )
    else:
        parts.append(
            "Render no text, lettering, symbols made from letters, or pseudo-text anywhere in the "
            "image."
        )
    requirements = [
        str(item).strip() for item in user_requirements or [] if str(item).strip()
    ]
    if requirements:
        parts.append(
            "The finished image must also satisfy: " + " ".join(requirements)
        )
    preserve = [str(item).strip() for item in image_prompt.get("preserve") or [] if str(item).strip()]
    if preserve:
        parts.append("Preserve without change: " + "; ".join(preserve) + ".")
    avoid = [str(item).strip() for item in image_prompt.get("avoid") or [] if str(item).strip()]
    if avoid:
        parts.append("Avoid: " + "; ".join(avoid) + ".")
    return "\n\n".join(parts)
