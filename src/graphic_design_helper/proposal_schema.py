"""Structured design proposal contract and validation."""

TEXT_FIELDS = ("brief_interpretation", "chosen_direction", "design_rationale",
               "sign_relationships", "graphic_decisions", "revision_summary", "production_prompt")
LIST_FIELDS = ("alternatives", "assumptions", "uncertainties", "review_criteria", "source_requirements")
PROPOSAL_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "status": {"type": "string", "enum": ["ready", "needs_sources"]},
        **{key: {"type": "string"} for key in TEXT_FIELDS},
        **{key: {"type": "array", "items": {"type": "string"}} for key in LIST_FIELDS},
    },
    "required": ["status", *TEXT_FIELDS, *LIST_FIELDS],
}


def validate_proposal(proposal):
    if not isinstance(proposal, dict) or set(proposal) != set(PROPOSAL_SCHEMA["required"]):
        raise ValueError("Incomplete or unexpected proposal fields.")
    if proposal["status"] not in {"ready", "needs_sources"}:
        raise ValueError("Invalid proposal status.")
    if any(not isinstance(proposal[k], str) for k in TEXT_FIELDS):
        raise ValueError("Proposal explanations must be text.")
    if any(not isinstance(proposal[k], list) or
           any(not isinstance(v, str) for v in proposal[k]) for k in LIST_FIELDS):
        raise ValueError("Proposal lists must contain text.")
    if proposal["status"] == "ready":
        if not proposal["production_prompt"].strip() or proposal["source_requirements"]:
            raise ValueError("A ready proposal needs a prompt and no outstanding sources.")
    elif proposal["production_prompt"].strip() or not proposal["source_requirements"]:
        raise ValueError("A source-dependent proposal must list requirements and omit the prompt.")
    return proposal


