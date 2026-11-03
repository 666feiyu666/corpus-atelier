"""Semantic validation and deliverable-category knowledge loading."""

from ...design_support.validation import validate
from ...skill_loader import load_skill_reference, load_skill_reference_body


CATEGORY_INDEX_REFERENCE = "categories/index.md"
DESIGN_CRAFT_REFERENCE = "design-craft.md"

CATEGORY_REFERENCES = {
    "typography-and-posters": "categories/typography-and-posters.md",
    "brand-systems-and-identity": "categories/brand-systems-and-identity.md",
    "editorial-and-covers": "categories/editorial-and-covers.md",
    "events-and-invitations": "categories/events-and-invitations.md",
    "product-and-food": "categories/product-and-food.md",
    "beauty-and-lifestyle": "categories/beauty-and-lifestyle.md",
    "infographics-and-field-guides": "categories/infographics-and-field-guides.md",
    "data-and-research-figures": "categories/data-and-research-figures.md",
    "uiux-and-mockups": "categories/uiux-and-mockups.md",
    "illustration-and-mediums": "categories/illustration-and-mediums.md",
    "photography-and-cinematic": "categories/photography-and-cinematic.md",
    "architecture-and-interior": "categories/architecture-and-interior.md",
    "technical-and-scientific": "categories/technical-and-scientific.md",
}

STYLE_SPACE_REFERENCES = {
    "rhetoric-led.v1": "style-spaces/rhetoric-led.md",
    "art-led.v1": "style-spaces/art-led.md",
}


def _for_objective(mapping: dict, objective: str, kind: str):
    try:
        return mapping[objective]
    except KeyError as exc:
        raise ValueError(f"No {kind} is configured for objective {objective!r}.") from exc


def category_ids() -> tuple[str, ...]:
    return tuple(CATEGORY_REFERENCES)


def category_reference(category: str) -> str:
    try:
        return CATEGORY_REFERENCES[category]
    except KeyError as exc:
        raise ValueError(
            f"Unknown deliverable category {category!r}. "
            f"Choose one of: {', '.join(CATEGORY_REFERENCES)}"
        ) from exc


def load_category_guide(category: str | None) -> str | None:
    """Return one category guide, or None when no category is fixed."""
    if not category:
        return None
    return load_skill_reference("design-direction", category_reference(category))


def load_category_guide_body(category: str | None) -> str | None:
    if not category:
        return None
    return load_skill_reference_body("design-direction", category_reference(category))


def load_category_index_body() -> str:
    return load_skill_reference_body("design-direction", CATEGORY_INDEX_REFERENCE)


def load_design_craft_body() -> str:
    return load_skill_reference_body("design-direction", DESIGN_CRAFT_REFERENCE)


def style_space_reference(objective: str) -> str:
    return _for_objective(STYLE_SPACE_REFERENCES, objective, "style space")


def validate_design_direction_plan(
    value: dict, candidate_limit: int, *, objective: str,
    asset_category: str | None = None,
) -> dict:
    validate(value, "design-direction-plan.schema.json")
    directions = value["directions"]
    if len(directions) > candidate_limit:
        raise ValueError(
            f"Direction plan returned {len(directions)} directions; limit is {candidate_limit}."
        )
    if value["planning_mode"] == "convergent" and len(directions) != 1:
        raise ValueError("A convergent direction plan must contain exactly one direction.")
    categories = {direction["asset_category"] for direction in directions}
    if len(categories) != 1:
        raise ValueError("All directions must share one deliverable category.")
    chosen_category = categories.pop()
    if chosen_category not in CATEGORY_REFERENCES:
        raise ValueError(f"Unknown deliverable category: {chosen_category}.")
    if asset_category is not None and chosen_category != asset_category:
        raise ValueError(
            "The direction plan changed the brief's deliverable category: "
            f"{asset_category} -> {chosen_category}."
        )
    labels = [direction["label"].strip().casefold() for direction in directions]
    if len(set(labels)) != len(labels):
        raise ValueError("Direction labels must be distinct.")
    signatures = []
    for direction in directions:
        axes = [decision["axis"] for decision in direction["direction_decisions"]]
        if len(set(axes)) != len(axes):
            raise ValueError("A direction cannot repeat a decision axis.")
        signatures.append((
            direction["design_thesis"].strip().casefold(),
            direction["objective_strategy"].strip().casefold(),
            tuple((item["axis"], item["decision"].strip().casefold()) for item in direction["direction_decisions"]),
        ))
    if len(set(signatures)) != len(signatures):
        raise ValueError("Directions must differ in their strategic decisions.")
    return value
