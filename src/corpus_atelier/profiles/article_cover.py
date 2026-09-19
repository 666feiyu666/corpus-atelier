"""Art-led WeChat article-cover profile."""

from .deliverables import ARTICLE_COVER, COVER_REVIEW
from .models import DesignProfile
from .objectives import ART_LED

PROFILE = DesignProfile(
    name="art-article-cover", objective="art-led.v1", deliverable="article-cover.v1",
    brief_schema="article-cover-brief.schema.json",
    proposal_schema="article-cover-direction.schema.json",
    review_schema="article-cover-review.schema.json",
    description="Art-direction-first WeChat article cover with crop-aware review.",
    objective_prompt=ART_LED, deliverable_prompt=ARTICLE_COVER, review_prompt=COVER_REVIEW,
    default_size="1536x1024",
    output_ratio=(47, 20),
)
