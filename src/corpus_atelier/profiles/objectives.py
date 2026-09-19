"""Objective policies kept separate from output-format policies."""

from importlib.resources import files


def _load(name: str) -> str:
    return files("corpus_atelier").joinpath("prompts", "objectives", name).read_text(
        encoding="utf-8"
    ).strip()


RHETORIC_LED = _load("rhetoric-led.md")
ART_LED = _load("art-led.md")
