"""Semantic validation and knowledge loading for direction plans."""

from ..design.validation import validate
from ..skill_loader import load_skill_reference


MOVEMENT_REFERENCES = {
    "art-nouveau": "movements/art-nouveau.md",
    "constructivism": "movements/constructivism.md",
    "de-stijl": "movements/de-stijl.md",
    "bauhaus-new-typography": "movements/bauhaus-new-typography.md",
    "swiss-style": "movements/swiss-style.md",
    "art-deco": "movements/art-deco.md",
    "psychedelic": "movements/psychedelic.md",
    "postmodern-memphis": "movements/postmodern-memphis.md",
}


def validate_direction_plan(value: dict, candidate_count: int) -> dict:
    validate(value, "direction-plan.schema.json")
    directions = value["directions"]
    if len(directions) != candidate_count:
        raise ValueError(
            f"Direction plan returned {len(directions)} directions; expected {candidate_count}."
        )
    labels = [direction["label"].strip().casefold() for direction in directions]
    if len(set(labels)) != len(labels):
        raise ValueError("Direction labels must be distinct.")
    signatures = []
    for direction in directions:
        axes = direction["primary_variation_axes"]
        if len(set(axes)) != len(axes):
            raise ValueError("A direction cannot repeat a primary variation axis.")
        unknown = set(direction["movement_references"]) - MOVEMENT_REFERENCES.keys()
        if unknown:
            raise ValueError(f"Unknown movement references: {', '.join(sorted(unknown))}.")
        signatures.append((
            tuple(sorted(axes)),
            tuple(direction["variation_plan"].values()),
            tuple(direction["movement_references"]),
        ))
    if len(set(signatures)) != len(signatures):
        raise ValueError("Directions must differ in their concrete variation plans.")
    return value


def load_movement_cards(ids: list[str]) -> list[str]:
    return [
        load_skill_reference("direction-planning", MOVEMENT_REFERENCES[movement_id])
        for movement_id in ids
    ]
