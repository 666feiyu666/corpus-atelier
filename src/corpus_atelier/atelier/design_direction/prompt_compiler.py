"""Compile a frozen brief into a category-led direction request."""

import json

from ...language import compile_language_policy
from ...config.skill_loader import load_skill, load_skill_reference
from .validation import (
    load_category_guide_body,
    load_category_index_body,
    load_design_craft_body,
    load_style_space_body,
    load_style_space_index_body,
)


def compile_design_direction_prompt(
    profile, brief: dict, *, canvas: dict, candidate_limit: int,
    content_language: str | None = None,
    corpus_references: list[dict] | None = None,
    reference_image_names: list[str] | None = None,
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
        "The style space is a set of dimensions to decide in, not a menu of styles to pick from. "
        "Its rules apply to every objective; the objective's own space supplies the dimensions.\n\n"
        "# Style-space rules\n\n" + load_style_space_index_body() + "\n\n"
        f"# Visual-language dimensions for {profile.objective}\n\n"
        + load_style_space_body(profile.objective),
    ])
    if corpus_references:
        sections.append(
            "# Reference gallery slice\n\n"
            "Archived cases whose labels or wording resemble this brief. They are evidence of how "
            "similar work is described and built: borrow vocabulary, structural habits, and level "
            "of detail. Do not copy their subjects, copy, brand names, or composition into this "
            "design.\n\n"
            + json.dumps(corpus_references, ensure_ascii=False, indent=2, allow_nan=False)
        )
    if reference_image_names:
        listing = "\n".join(
            f"{index}. {name}" for index, name in enumerate(reference_image_names, start=1)
        )
        sections.append(
            "# Attached reference images\n\n"
            "These archived case images are attached in this order. Use them as evidence of "
            "craft — framing, light, density, palette discipline — never as content to reproduce.\n\n"
            + listing
        )
    sections.append(
        "# Frozen shared brief\n\n"
        "This JSON is authoritative user data. Every direction must preserve it. Explicit style, "
        "composition, subjects, and element relationships are shared invariants rather than "
        "variation axes. user_requirements contains confirmed mandatory requirements, preserved "
        "across all directions. It takes precedence over conflicting inferred constraints or preferences.\n\n"
        + json.dumps(brief, ensure_ascii=False, indent=2, allow_nan=False)
    )
    return "\n\n".join(sections)
