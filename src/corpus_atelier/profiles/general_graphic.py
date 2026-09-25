"""Open-context graphic-design profiles."""

from .models import DesignProfile
from .objectives import ART_LED, RHETORIC_LED


RHETORIC_PROFILE = DesignProfile(
    name="rhetoric-graphic",
    objective="rhetoric-led.v1",
    brief_schema="graphic-design-brief.schema.json",
    proposal_schema="graphic-design-proposal.schema.json",
    description="Rhetoric-led graphic design for an open delivery context.",
    objective_reference=RHETORIC_LED,
    canvas_mode="brief",
    default_size="1024x1024",
    output_ratio=(1, 1),
)


ART_PROFILE = DesignProfile(
    name="art-graphic",
    objective="art-led.v1",
    brief_schema="graphic-design-brief.schema.json",
    proposal_schema="graphic-design-proposal.schema.json",
    description="Art-direction-led graphic design for an open delivery context.",
    objective_reference=ART_LED,
    canvas_mode="brief",
    default_size="1024x1024",
    output_ratio=(1, 1),
)
