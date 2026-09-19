"""Profile registry used by every UI adapter."""

from .profiles.article_cover import PROFILE as ARTICLE_COVER
from .profiles.poster import PROFILE as POSTER

PROFILES = {profile.name: profile for profile in (POSTER, ARTICLE_COVER)}


def get_profile(name: str):
    try:
        return PROFILES[name]
    except KeyError as exc:
        raise ValueError(f"Unknown profile {name!r}. Choose one of: {', '.join(PROFILES)}") from exc
