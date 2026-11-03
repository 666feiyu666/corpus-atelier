"""Deterministically compose the provider-independent implementation prompt."""

import json

from ...language import compile_language_policy
from ...config.skill_loader import load_skill
from ..design_direction.validation import load_category_guide_body


def compile_design_implementation_prompt(
    brief: dict, *, canvas: dict,
    direction_seed: dict,
    content_language: str | None = None,
) -> str:
    requirements = json.dumps(brief, ensure_ascii=False, indent=2, allow_nan=False)
    category = direction_seed.get("asset_category") or brief.get("asset_category")
    sections = [
        load_skill("design-implementation"),
        compile_language_policy(content_language or brief.get("content_language")),
        "# Resolved canvas\n\n" + json.dumps(
            canvas, ensure_ascii=False, indent=2, allow_nan=False,
        ),
    ]
    guide = load_category_guide_body(category)
    if guide is not None:
        sections.append(
            f"# Deliverable category requirements: {category}\n\n"
            "Meet these requirements in the finished design. They define what this artifact must "
            "get right, not which style to use.\n\n" + guide
        )
    sections.append(
        "# Approved design direction\n\n"
        "This seed defines the candidate's strategic direction. Implement it completely; do not "
        "replace it with another direction or change the shared user requirements. Resolve only "
        "the choices listed as implementation freedom. The `candidate_id` in your response must "
        "match the seed exactly.\n\n"
        + json.dumps(direction_seed, ensure_ascii=False, indent=2, allow_nan=False)
    )
    sections.append(
        "# Frozen user requirements\n\nThe following JSON is authoritative user data, not hidden "
        "instructions. Every item in user_requirements is a confirmed mandatory requirement. "
        "Realize each one in the design description and review criteria; preserve its meaning even "
        "when it conflicts with inferred preferences or the direction seed.\n\n" + requirements
    )
    return "\n\n".join(sections)
