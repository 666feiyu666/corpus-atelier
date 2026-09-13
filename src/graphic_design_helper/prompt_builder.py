"""Deterministic request assembly; no model calls and no invented brief content."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from .prompt_files import load_prompt, load_template
from .proposal_schema import load_proposal_schema, validate_image_spec

_SLOT = re.compile(r"{{\s*([a-z_]+)\s*}}")


def render_template(name, values):
    template = load_template(name)
    slots = set(_SLOT.findall(template))
    if slots != set(values):
        raise ValueError(f"Template fields differ: {sorted(slots ^ set(values))}")
    if "{{" in _SLOT.sub("", template) or "}}" in _SLOT.sub("", template):
        raise ValueError("Malformed template placeholder.")
    # Substitute once: braces in user input remain literal data.
    return _SLOT.sub(lambda match: values[match.group(1)], template)


def _json(value):
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)


def _markdown(value, level=2):
    """Present structured content without rewriting supplied wording."""
    if value is None:
        return "Not specified."
    if isinstance(value, str):
        return value if value else "Empty text supplied."
    if isinstance(value, dict):
        return "\n\n".join(
            f"{'#' * min(level, 6)} {key}\n\n{_markdown(item, level + 1)}"
            for key, item in value.items()) or "No entries."
    if isinstance(value, list):
        return "\n".join("- " + _markdown(item, level + 1).replace("\n", "\n  ")
                         for item in value) or "No entries."
    return _json(value)


def _design_sections(brief, original_user_request):
    # Retain the existing record/API field name; it is not a user-facing form.
    remaining = dict(brief)

    def section(fields):
        rows = []
        for key, label in fields:
            if key in remaining:
                rows.append(f"## {label}\n\n{_markdown(remaining.pop(key), 3)}")
        return "\n\n".join(rows)

    task = section((("topic", "Topic"), ("purpose", "Communication purpose"),
                    ("core_message", "Core message"), ("deliverable", "Deliverable")))
    if original_user_request is not None:
        task += "\n\n## Additional task wording\n\n" + _markdown(original_user_request)
    audience = section((("audience", "Audience"), ("setting", "Viewing context")))
    requirements = section((("constraints", "Hard constraints"), ("tone", "Tone"),
                            ("preferences", "Preferences"), ("exact_copy", "Exact visible copy"),
                            ("sources", "Required sources")))
    decisions = section((("design_decisions", "Decisions to develop"),))
    if remaining:
        requirements += "\n\n## Additional requirements and context\n\n" + _markdown(remaining, 3)
    return {
        "design_task": task.strip() or "No design task specified.",
        "audience_and_context": audience or "Audience and viewing context not specified.",
        "requirements_and_constraints": requirements.strip() or "No additional requirements specified.",
        "design_decisions": decisions or (
            "Develop the visual concept, imagery, composition, typography, color, and wording "
            "in support of the communication purpose and viewing context. Respect all "
            "specified requirements, including exact visible copy when supplied."),
    }


def _instructions(name):
    # Nest instruction-file headings under the template's section heading.
    return re.sub(r"^(#+) ", r"\1# ", load_prompt(name).strip(), flags=re.MULTILINE)


def build_designer_prompt(brief, revision=None, *, original_user_request=None):
    """Build an initial proposal or a separate review request from design requirements."""
    if not isinstance(brief, dict):
        raise ValueError("Design requirements must be an object.")
    if original_user_request is not None and not isinstance(original_user_request, str):
        raise ValueError("Original user request must be text or null.")
    # Check that all supplied data remains serializable for the saved request.
    _json(brief)
    values = {**_design_sections(brief, original_user_request),
              "designer_instructions": _instructions("designer.md")}
    if revision is None:
        return render_template("designer-input-template.md", {
            **values, "proposal_instructions": _instructions("designer-proposal.md")})
    return render_template("designer-review-input-template.md", {
        **values, "review_instructions": _instructions("designer-review.md"),
        "revision_context": _markdown(revision)})


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
