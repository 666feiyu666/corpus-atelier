"""Rhetoric-led poster profile."""

from .deliverables import GRAPHIC_DESIGN, POSTER
from .models import DesignProfile
from .objectives import RHETORIC_LED

PROFILE = DesignProfile(
    name="rhetoric-poster", objective="rhetoric-led.v1", deliverable="poster.v1",
    brief_schema="poster-brief.schema.json", proposal_schema="poster-proposal.schema.json",
    description="Rhetoric-first portrait poster.",
    objective_prompt=RHETORIC_LED, deliverable_prompts=(GRAPHIC_DESIGN, POSTER),
    default_size="1024x1536",
    output_ratio=(2, 3),
)
