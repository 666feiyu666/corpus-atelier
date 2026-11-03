"""WeChat article-cover profile."""

from .models import DesignProfile
from .objectives import GENERAL_DESIGN

PROFILE = DesignProfile(
    name="article-cover", objective="general-design.v1",
    brief_schema="article-cover-brief.schema.json",
    proposal_schema="article-cover-proposal.schema.json",
    description="WeChat article-cover design.",
    objective_reference=GENERAL_DESIGN,
    canvas_mode="fixed",
    default_size="1536x1024",
    output_ratio=(47, 20),
)
