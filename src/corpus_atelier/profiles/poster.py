"""Portrait poster profile."""

from .models import DesignProfile
from .objectives import GENERAL_DESIGN

PROFILE = DesignProfile(
    name="poster", objective="general-design.v1",
    brief_schema="poster-brief.schema.json", proposal_schema="poster-proposal.schema.json",
    description="Portrait poster design.",
    objective_reference=GENERAL_DESIGN,
    canvas_mode="fixed",
    default_size="1024x1536",
    output_ratio=(2, 3),
)
