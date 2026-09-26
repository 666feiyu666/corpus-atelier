"""Compile a frozen brief into an objective-led direction request."""

import json

from ..skill_loader import load_skill, load_skill_reference
from .validation import (
    historical_index_reference,
    historical_reference_catalog,
    style_space_reference,
)


def _historical_catalog(objective: str) -> str:
    cards = [
        load_skill_reference("design-direction", relative)
        for relative in historical_reference_catalog(objective).values()
    ]
    return "\n\n---\n\n".join(cards)


def compile_design_direction_prompt(
    profile, brief: dict, *, canvas: dict, candidate_limit: int,
) -> str:
    sections = [
        load_skill("design-direction"),
        "# Design objective\n\n" + load_skill_reference(
            "design-direction", profile.objective_reference,
        ),
        "# Portfolio size\n\n"
        f"Return between one and {candidate_limit} direction(s). This is an upper bound, not a "
        "quota. Return fewer when the brief does not permit meaningful alternatives.",
        "# Resolved canvas\n\n" + json.dumps(
            canvas, ensure_ascii=False, indent=2, allow_nan=False,
        ),
        "# Visual-language style space\n\n"
        "Use this map to consider broad stylistic possibilities. It is not exhaustive and does "
        "not require a historical label. Choose or combine only the visual principles that "
        "serve the brief and design objective.\n\n"
        + load_skill_reference(
            "design-direction", style_space_reference(profile.objective),
        ),
        "# Optional historical knowledge catalog\n\n"
        "The index and cards provide objective-appropriate historical working knowledge. Use "
        "an ID only when its principles genuinely shape a direction. Historical labels never "
        "override the brief or substitute for visual decisions.\n\n"
        + load_skill_reference(
            "design-direction", historical_index_reference(profile.objective),
        )
        + "\n\n## Historical reference cards\n\n"
        + _historical_catalog(profile.objective),
    ]
    sections.append(
        "# Frozen shared brief\n\n"
        "This JSON is authoritative user data. Every direction must preserve it. Explicit style, "
        "composition, subjects, and element relationships are shared invariants rather than "
        "variation axes.\n\n"
        + json.dumps(brief, ensure_ascii=False, indent=2, allow_nan=False)
    )
    return "\n\n".join(sections)
