"""Deliverable-specific production policies."""

from importlib.resources import files


def _load(name: str) -> str:
    return files("corpus_atelier").joinpath("prompts", "deliverables", name).read_text(
        encoding="utf-8"
    ).strip()


POSTER = _load("poster.md")
ARTICLE_COVER = _load("article-cover.md")
GRAPHIC_DESIGN = _load("graphic-design.md")
