"""Art-led WeChat article-cover profile."""

from .models import DesignProfile
from .objectives import ART_LED

PROFILE = DesignProfile(
    name="art-article-cover", objective="art-led.v1",
    brief_schema="article-cover-brief.schema.json",
    proposal_schema="article-cover-direction.schema.json",
    description="Art-direction-first WeChat article cover.",
    objective_reference=ART_LED,
    canvas_mode="fixed",
    default_size="1536x1024",
    output_ratio=(47, 20),
)
