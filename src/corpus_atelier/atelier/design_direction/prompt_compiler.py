"""Compile a frozen brief into a category-led direction request."""

import json

from ...language import compile_language_policy
from ...skill_loader import load_skill, load_skill_reference, load_skill_reference_body
from .validation import (
    load_category_guide_body,
    load_category_index_body,
    load_design_craft_body,
    style_space_reference,
)


def compile_design_direction_prompt(
    profile, brief: dict, *, canvas: dict, candidate_limit: int,
    content_language: str | None = None,
) -> str:
    asset_category = brief.get("asset_category")
    sections = [
        load_skill("design-direction"),
        compile_language_policy(content_language or brief.get("content_language")),
        "# Design objective\n\n" + load_skill_reference(
            "design-direction", profile.objective_reference,
        ),
        "# Deliverable categories\n\n"
        "Classify the deliverable before choosing any visual language. Read the matching category "
        "guide only; a second guide is justified only for a genuine hybrid.\n\n"
        + load_category_index_body(),
    ]
    guide = load_category_guide_body(asset_category)
    if guide is not None:
        sections.append(
            f"# Deliverable category: {asset_category}\n\n"
            "This category sets what the artifact must get right. Its optional style vocabulary "
            "does not select a style by itself.\n\n" + guide
        )
    else:
        sections.append(
            "# Deliverable category\n\n"
            "The brief has not fixed a category. Classify the deliverable against the index above, "
            "read that category guide, and return the same `asset_category` for every direction."
        )
    sections.extend([
        "# Design craft checklist\n\n" + load_design_craft_body(),
        "# Portfolio size\n\n"
        f"Return between one and {candidate_limit} direction(s). This is an upper bound, not a "
        "quota. Return fewer when the brief does not permit meaningful alternatives.",
        "# Resolved canvas\n\n" + json.dumps(
            canvas, ensure_ascii=False, indent=2, allow_nan=False,
        ),
        "# Visual-language style space\n\n"
        "Use this map to consider broad stylistic possibilities. It is not exhaustive and does "
        "not require a historical label. Choose or combine only the visual principles that serve "
        "the brief, the category requirements, and the design objective.\n\n"
        + load_skill_reference_body(
            "design-direction", style_space_reference(profile.objective),
        ),
    ])
    sections.append(
        "# Frozen shared brief\n\n"
        "This JSON is authoritative user data. Every direction must preserve it. Explicit style, "
        "composition, subjects, and element relationships are shared invariants rather than "
        "variation axes. user_requirements contains confirmed mandatory requirements, preserved "
        "across all directions. It takes precedence over conflicting inferred constraints or preferences.\n\n"
        + json.dumps(brief, ensure_ascii=False, indent=2, allow_nan=False)
    )
    return "\n\n".join(sections)
