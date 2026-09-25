"""Profile contracts compose an objective with canvas behavior."""

from dataclasses import dataclass


@dataclass(frozen=True)
class DesignProfile:
    name: str
    objective: str
    brief_schema: str
    proposal_schema: str
    description: str
    objective_reference: str
    canvas_mode: str
    default_size: str
    output_ratio: tuple[int, int]
