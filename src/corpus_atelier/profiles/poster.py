"""Rhetoric-led poster profile."""

from .models import DesignProfile
from .objectives import RHETORIC_LED

PROFILE = DesignProfile(
    name="rhetoric-poster", objective="rhetoric-led.v1",
    brief_schema="poster-brief.schema.json", proposal_schema="poster-proposal.schema.json",
    description="Rhetoric-first portrait poster.",
    objective_reference=RHETORIC_LED,
    canvas_mode="fixed",
    default_size="1024x1536",
    output_ratio=(2, 3),
)
