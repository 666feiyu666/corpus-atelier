"""Semantic validation and objective-specific knowledge loading."""

from ..design_support.validation import validate
from ..skill_loader import load_skill_reference


STYLE_SPACE_REFERENCES = {
    "rhetoric-led.v1": "style-spaces/rhetoric-led.md",
    "art-led.v1": "style-spaces/art-led.md",
}

HISTORICAL_INDEX_REFERENCES = {
    "rhetoric-led.v1": "design-movement-index.md",
    "art-led.v1": "art-movement-index.md",
}

HISTORICAL_REFERENCES = {
    "rhetoric-led.v1": {
        "art-nouveau": "design-movements/art-nouveau.md",
        "constructivism": "design-movements/constructivism.md",
        "de-stijl": "design-movements/de-stijl.md",
        "bauhaus-new-typography": "design-movements/bauhaus-new-typography.md",
        "swiss-style": "design-movements/swiss-style.md",
        "art-deco": "design-movements/art-deco.md",
        "psychedelic": "design-movements/psychedelic.md",
        "postmodern-memphis": "design-movements/postmodern-memphis.md",
    },
    "art-led.v1": {
        "neoclassicism": "art-movements/neoclassicism.md",
        "romanticism": "art-movements/romanticism.md",
        "realism": "art-movements/realism.md",
        "impressionism": "art-movements/impressionism.md",
        "post-impressionism": "art-movements/post-impressionism.md",
        "expressionism": "art-movements/expressionism.md",
        "surrealism": "art-movements/surrealism.md",
    },
}


def _for_objective(mapping: dict, objective: str, kind: str):
    try:
        return mapping[objective]
    except KeyError as exc:
        raise ValueError(f"No {kind} is configured for objective {objective!r}.") from exc


def historical_reference_catalog(objective: str) -> dict[str, str]:
    return _for_objective(HISTORICAL_REFERENCES, objective, "historical reference catalog")


def style_space_reference(objective: str) -> str:
    return _for_objective(STYLE_SPACE_REFERENCES, objective, "style space")


def historical_index_reference(objective: str) -> str:
    return _for_objective(HISTORICAL_INDEX_REFERENCES, objective, "historical reference index")


def validate_design_direction_plan(
    value: dict, candidate_limit: int, *, objective: str,
) -> dict:
    validate(value, "design-direction-plan.schema.json")
    reference_catalog = historical_reference_catalog(objective)
    directions = value["directions"]
    if len(directions) > candidate_limit:
        raise ValueError(
            f"Direction plan returned {len(directions)} directions; limit is {candidate_limit}."
        )
    if value["planning_mode"] == "convergent" and len(directions) != 1:
        raise ValueError("A convergent direction plan must contain exactly one direction.")
    labels = [direction["label"].strip().casefold() for direction in directions]
    if len(set(labels)) != len(labels):
        raise ValueError("Direction labels must be distinct.")
    signatures = []
    for direction in directions:
        axes = [decision["axis"] for decision in direction["direction_decisions"]]
        if len(set(axes)) != len(axes):
            raise ValueError("A direction cannot repeat a decision axis.")
        unknown = set(direction["movement_references"]) - reference_catalog.keys()
        if unknown:
            raise ValueError(
                f"Unknown historical references for {objective}: "
                f"{', '.join(sorted(unknown))}."
            )
        signatures.append((
            direction["design_thesis"].strip().casefold(),
            direction["objective_strategy"].strip().casefold(),
            tuple((item["axis"], item["decision"].strip().casefold()) for item in direction["direction_decisions"]),
            tuple(direction["movement_references"]),
        ))
    if len(set(signatures)) != len(signatures):
        raise ValueError("Directions must differ in their strategic decisions.")
    return value


def load_historical_cards(objective: str, ids: list[str]) -> list[str]:
    reference_catalog = historical_reference_catalog(objective)
    return [
        load_skill_reference("design-direction", reference_catalog[reference_id])
        for reference_id in ids
    ]
