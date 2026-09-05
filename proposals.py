"""Generate a recorded design proposal from a macro brief, without generating images."""
import base64
import hashlib
import json
from pathlib import Path
from records import save_experiment


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


def propose_design(prompt, *, model="gpt-5.6-luna", reasoning_effort="medium",
                   output_dir="outputs", image_path=None, client=None):
    """Send the exact previewed designer prompt with a structured output contract.

    No automatic retry, image call, or hidden conversation state. API refusals,
    incomplete responses, and malformed proposals fail before image generation.
    """
    if not isinstance(prompt, str) or not prompt.strip() or not model.strip():
        raise ValueError("Provide a reviewed designer prompt and model.")
    record = {"status": "requested", "kind": "design_proposal", "prompt": prompt,
              "model": model, "reasoning_effort": reasoning_effort,
              "response_schema": PROPOSAL_SCHEMA}
    request_input = prompt
    if image_path is not None:
        image_path = Path(image_path)
        image_bytes = image_path.read_bytes()
        if not image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("Designer self-review expects the generated PNG.")
        record["image_sha256"] = hashlib.sha256(image_bytes).hexdigest()
        record["kind"] = "designer_self_review"
        request_input = [{"role": "user", "content": [
            {"type": "input_text", "text": prompt},
            {"type": "input_image", "image_url": "data:image/png;base64," +
             base64.b64encode(image_bytes).decode("ascii")},
        ]}]
    folder = save_experiment(record, [image_path] if image_path else [], output_dir=output_dir)
    record["folder"] = str(folder.resolve())
    def save():
        (folder / "proposal.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    save()
    owned = client is None
    try:
        if owned:
            from openai import OpenAI
            client = OpenAI(max_retries=0, timeout=600.0)
        response = client.responses.create(
            model=model, reasoning={"effort": reasoning_effort}, store=False,
            input=request_input, text={"format": {"type": "json_schema", "name": "design_proposal",
                                          "strict": True, "schema": PROPOSAL_SCHEMA}},
        )
        record["raw_output"] = response.output_text
        record["response_id"] = getattr(response, "id", None)
        record["request_id"] = getattr(response, "_request_id", None)
        usage = getattr(response, "usage", None)
        record["usage"] = usage.model_dump(mode="json") if usage else None
        if getattr(response, "status", None) != "completed" or not response.output_text:
            raise ValueError("Designer did not return a completed proposal.")
        proposal = validate_proposal(json.loads(response.output_text))
        record.update(status="completed", proposal=proposal)
        save()
        return record
    except Exception as exc:
        record.update(status="failed", error_type=type(exc).__name__)
        save()
        raise
    finally:
        if owned and client is not None:
            client.close()
