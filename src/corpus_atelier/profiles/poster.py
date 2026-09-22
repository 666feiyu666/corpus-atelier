"""Rhetoric-led poster profile."""

from .deliverables import GRAPHIC_DESIGN, POSTER, POSTER_REVIEW
from .models import DesignProfile
from .objectives import RHETORIC_LED

PROFILE = DesignProfile(
    name="rhetoric-poster", objective="rhetoric-led.v1", deliverable="poster.v1",
    brief_schema="poster-brief.schema.json", proposal_schema="poster-proposal.schema.json",
    review_schema="poster-review.schema.json",
    description="Rhetoric-first portrait poster with semiotic review.",
    objective_prompt=RHETORIC_LED, deliverable_prompts=(GRAPHIC_DESIGN, POSTER),
    review_prompt=POSTER_REVIEW,
    default_size="1024x1536",
    output_ratio=(2, 3),
)
