"""Profile registry used by every UI adapter."""

from ..profiles.article_cover import PROFILE as ARTICLE_COVER
from ..profiles.general_graphic import GENERAL_PROFILE
from ..profiles.poster import PROFILE as POSTER

PROFILES = {
    profile.name: profile for profile in (GENERAL_PROFILE, POSTER, ARTICLE_COVER)
}

# Retired identifiers. Saved tasks, fixtures, and CLI scripts keep resolving, and the
# general objective replaces the old rhetoric-led and art-led policies for all of them.
LEGACY_PROFILE_ALIASES = {
    "rhetoric-graphic": "general-graphic",
    "art-graphic": "general-graphic",
    "rhetoric-poster": "poster",
    "art-article-cover": "article-cover",
}

PROFILE_NAMES = tuple(sorted({*PROFILES, *LEGACY_PROFILE_ALIASES}))


def get_profile(name: str):
    resolved = LEGACY_PROFILE_ALIASES.get(name, name)
    try:
        return PROFILES[resolved]
    except KeyError as exc:
        raise ValueError(
            f"Unknown profile {name!r}. Choose one of: {', '.join(PROFILE_NAMES)}"
        ) from exc
