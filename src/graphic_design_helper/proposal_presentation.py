"""Render a designer's explanations for people, separately from image instructions."""
from .prompt_builder import render_template


_TEXT_FIELDS = ("brief_interpretation", "chosen_direction", "design_rationale",
                "sign_relationships", "graphic_decisions", "revision_summary", "visual_style")
_LIST_FIELDS = ("alternatives", "assumptions", "uncertainties", "review_criteria",
                "source_requirements", "clarification_questions")


def render_design_rationale(proposal):
    """Preserve the supplied explanations; never infer missing design arguments.

    Rendering is also available for historical proposals without image_spec.
    Live responses are validated by the caller before presentation.
    """
    values = {"status": proposal.get("status", "Not recorded.")}
    for key in _TEXT_FIELDS:
        values[key] = proposal.get(key) or (
            "Style direction and confirmation were not recorded."
            if key == "visual_style" else "No explanation supplied.")
    for key in _LIST_FIELDS:
        values[key] = "\n".join(
            "- " + item.replace("\n", "\n  ") for item in proposal.get(key, [])) or "None listed."
    return render_template("design-rationale-template.md", values)
