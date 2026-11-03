"""Load packaged Agent Skills for deterministic LangGraph nodes."""

from importlib.resources import files


def _strip_frontmatter(text: str) -> str:
    if not text.startswith("---\n"):
        return text.strip()
    parts = text.split("---\n", 2)
    if len(parts) != 3:
        raise ValueError("Skill frontmatter is not closed.")
    return parts[2].strip()


def load_skill(name: str) -> str:
    path = files("corpus_atelier").joinpath("skills", name, "SKILL.md")
    return _strip_frontmatter(path.read_text(encoding="utf-8"))


def load_skill_reference(skill: str, relative: str) -> str:
    path = files("corpus_atelier").joinpath("skills", skill, "references", relative)
    return path.read_text(encoding="utf-8").strip()


def load_skill_reference_body(skill: str, relative: str) -> str:
    """Reference text without its leading H1, for use under a caller-supplied heading."""
    text = load_skill_reference(skill, relative)
    if text.startswith("# "):
        _, _, rest = text.partition("\n")
        return rest.strip()
    return text
