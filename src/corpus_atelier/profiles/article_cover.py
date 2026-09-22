"""Art-led WeChat article-cover profile."""

from .deliverables import ARTICLE_COVER, GRAPHIC_DESIGN
from .models import DesignProfile
from .objectives import ART_LED

PROFILE = DesignProfile(
    name="art-article-cover", objective="art-led.v1", deliverable="article-cover.v1",
    brief_schema="article-cover-brief.schema.json",
    proposal_schema="article-cover-direction.schema.json",
    description="Art-direction-first WeChat article cover.",
    objective_prompt=ART_LED, deliverable_prompts=(GRAPHIC_DESIGN, ARTICLE_COVER),
    default_size="1536x1024",
    output_ratio=(47, 20),
)
