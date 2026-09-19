"""Profile contracts compose an objective with a deliverable."""

from dataclasses import dataclass


@dataclass(frozen=True)
class DesignProfile:
    name: str
    objective: str
    deliverable: str
    brief_schema: str
    proposal_schema: str
    review_schema: str
    description: str
    objective_prompt: str
    deliverable_prompt: str
    review_prompt: str
    default_size: str
    output_ratio: tuple[int, int]
