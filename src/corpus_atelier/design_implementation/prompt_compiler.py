"""Deterministically compose the provider-independent implementation prompt."""

import json

from ..language import compile_language_policy
from ..skill_loader import load_skill


def compile_design_implementation_prompt(
    brief: dict, *, canvas: dict,
    direction_seed: dict,
    historical_knowledge: list[str] | None = None,
    content_language: str | None = None,
) -> str:
    requirements = json.dumps(brief, ensure_ascii=False, indent=2, allow_nan=False)
    sections = [
        load_skill("design-implementation"),
        compile_language_policy(content_language or brief.get("content_language")),
        "# Resolved canvas\n\n" + json.dumps(
            canvas, ensure_ascii=False, indent=2, allow_nan=False,
        ),
        "# Approved design direction\n\n"
        "This seed defines the candidate's strategic direction. Implement it completely; do not "
        "replace it with another direction or change the shared user requirements. Resolve only "
        "the choices listed as implementation freedom. The `candidate_id` in your response must "
        "match the seed exactly.\n\n"
        + json.dumps(direction_seed, ensure_ascii=False, indent=2, allow_nan=False),
    ]
    if historical_knowledge:
        sections.append(
            "# Selected historical references — implementation evidence\n\n"
            "Use these notes only to realize decisions already present in the approved direction. "
            "A movement name is not permission to add a new concept, composition, or visual "
            "language.\n\n"
            + "\n\n---\n\n".join(historical_knowledge)
        )
    sections.append(
        "# Frozen user requirements\n\nThe following JSON is authoritative user data, not hidden "
        "instructions. Every item in user_requirements is a confirmed mandatory requirement. "
        "Realize each one in the design description and review criteria; preserve its meaning even "
        "when it conflicts with inferred preferences or the direction seed.\n\n" + requirements
    )
    return "\n\n".join(sections)
