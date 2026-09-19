"""Deliverable-specific production and review policies."""

from importlib.resources import files


def _load(name: str) -> str:
    return files("corpus_atelier").joinpath("prompts", "deliverables", name).read_text(
        encoding="utf-8"
    ).strip()


POSTER = _load("poster.md")
ARTICLE_COVER = _load("article-cover.md")
POSTER_REVIEW = """Review rhetorical clarity, hierarchy, legibility, sign relations,
copy accuracy, composition, and visible defects. Separate observations from interpretations."""
COVER_REVIEW = """Review thumbnail readability, crop safety, focal clarity, stylistic
coherence, copy accuracy, and whether the visual invitation suits an article cover."""
