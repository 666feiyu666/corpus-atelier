"""Read editable prompt resources afresh for each request preparation."""
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PROMPT_DIR = PACKAGE_DIR / "prompts"
# Wheels carry templates inside the package; source checkouts use the root folder.
TEMPLATE_DIR = PACKAGE_DIR / "templates"
if not TEMPLATE_DIR.is_dir():
    TEMPLATE_DIR = PACKAGE_DIR.parents[1] / "templates"


def load_prompt(name):
    text = (PROMPT_DIR / name).read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"Prompt file is empty: {name}")
    return text


def load_template(name):
    text = (TEMPLATE_DIR / name).read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"Template file is empty: {name}")
    return text
