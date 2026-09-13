"""Read editable prompt resources afresh for each request preparation."""
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"


def load_prompt(name):
    text = (PROMPT_DIR / name).read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"Prompt file is empty: {name}")
    return text
