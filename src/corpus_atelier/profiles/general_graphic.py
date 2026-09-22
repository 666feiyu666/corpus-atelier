"""Open-deliverable graphic-design profiles."""

from .deliverables import GRAPHIC_DESIGN
from .models import DesignProfile
from .objectives import ART_LED, RHETORIC_LED


RHETORIC_PROFILE = DesignProfile(
    name="rhetoric-graphic",
    objective="rhetoric-led.v1",
    deliverable="graphic-design.v1",
    brief_schema="graphic-design-brief.schema.json",
    proposal_schema="graphic-design-proposal.schema.json",
    description="Rhetoric-led graphic design for an open delivery context.",
    objective_prompt=RHETORIC_LED,
    deliverable_prompts=(GRAPHIC_DESIGN,),
    default_size="1024x1024",
    output_ratio=(1, 1),
)


ART_PROFILE = DesignProfile(
    name="art-graphic",
    objective="art-led.v1",
    deliverable="graphic-design.v1",
    brief_schema="graphic-design-brief.schema.json",
    proposal_schema="graphic-design-proposal.schema.json",
    description="Art-direction-led graphic design for an open delivery context.",
    objective_prompt=ART_LED,
    deliverable_prompts=(GRAPHIC_DESIGN,),
    default_size="1024x1024",
    output_ratio=(1, 1),
)
