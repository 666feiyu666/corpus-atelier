"""Assemble editable designer instructions and experiment context."""
import json
from .prompt_files import load_prompt


def designer_prompt(brief, revision=None):
    stage = "designer-proposal.md" if revision is None else "designer-review.md"
    return (load_prompt("designer.md") + "\n" + load_prompt(stage)
            + "\nMacro brief and revision context:\n" + json.dumps(
                {"brief": brief, "revision": revision}, ensure_ascii=False, indent=2))
