"""The open-context graphic-design profile."""

from .models import DesignProfile
from .objectives import GENERAL_DESIGN


GENERAL_PROFILE = DesignProfile(
    name="general-graphic",
    objective="general-design.v1",
    brief_schema="graphic-design-brief.schema.json",
    proposal_schema="graphic-design-proposal.schema.json",
    description="General graphic design for an open delivery context.",
    objective_reference=GENERAL_DESIGN,
    canvas_mode="brief",
    default_size="1024x1024",
    output_ratio=(1, 1),
)
