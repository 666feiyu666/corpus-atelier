"""Deterministic request assembly; no model calls and no invented brief content."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from .prompt_files import load_prompt
from .proposal_schema import load_proposal_schema, validate_image_spec

_SLOT = re.compile(r"{{\s*([a-z_]+)\s*}}")


def render_template(name, values):
    template = load_prompt(name)
    slots = set(_SLOT.findall(template))
    if slots != set(values):
        raise ValueError(f"Template fields differ: {sorted(slots ^ set(values))}")
    if "{{" in _SLOT.sub("", template) or "}}" in _SLOT.sub("", template):
        raise ValueError("Malformed template placeholder.")
    # Substitute once: braces in user input remain literal data.
    return _SLOT.sub(lambda match: values[match.group(1)], template)


def _json(value):
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)


def build_designer_prompt(brief, revision=None, *, original_user_request=None):
    if not isinstance(brief, dict):
        raise ValueError("The brief must be an object.")
    if original_user_request is not None and not isinstance(original_user_request, str):
        raise ValueError("Original user request must be text or null.")
    stage = "designer-proposal.md" if revision is None else "designer-review.md"
    return render_template("designer-input-template.md", {
        "designer_instructions": load_prompt("designer.md"),
        "brief_intake": load_prompt("brief-intake.md"),
        "stage_instructions": load_prompt(stage),
        "original_user_request": _json(original_user_request), "brief": _json(brief),
        "revision_context": "Initial proposal. No previous poster." if revision is None else _json(revision),
    })


def build_designer_request(brief, revision=None, *, original_user_request=None,
                           image_path=None, model="gpt-5.6-luna", reasoning_effort="medium"):
    if (revision is None) != (image_path is None):
        raise ValueError("Self-review requires both revision context and the actual poster.")
    if not model.strip() or not reasoning_effort.strip():
        raise ValueError("Designer model and reasoning effort are required.")
    request = {"prompt": build_designer_prompt(brief, revision, original_user_request=original_user_request),
               "model": model, "reasoning_effort": reasoning_effort,
               "response_schema": load_proposal_schema(),
               "designer_input": deepcopy({"brief": brief, "revision": revision,
                                           "original_user_request": original_user_request})}
    if image_path is not None:
        path = Path(image_path).resolve(strict=True)
        data = path.read_bytes()
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("Self-review requires a PNG poster.")
        request.update(image_path=str(path), image_sha256=hashlib.sha256(data).hexdigest())
    return request


def build_image_prompt(image_spec):
    validate_image_spec(image_spec)
    fields = {key: _json(value) if isinstance(value, list) else value for key, value in image_spec.items()}
    return render_template("image-generation-input-template.md", {
        "rendering_instructions": load_prompt("image-generation.md"), **fields})


def request_token(request):
    return hashlib.sha256(json.dumps(request, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False).encode("utf-8")).hexdigest()
