"""Load the response contract and enforce readiness beyond JSON field types."""
import json
from jsonschema import Draft202012Validator, ValidationError
from .prompt_files import load_prompt


def load_proposal_schema():
    schema = json.loads(load_prompt("designer-response.schema.json"))
    Draft202012Validator.check_schema(schema)
    return schema


# Compatibility names for callers; live requests load the schema afresh.
PROPOSAL_SCHEMA = load_proposal_schema()
TEXT_FIELDS = tuple(k for k, v in PROPOSAL_SCHEMA["properties"].items()
                    if v.get("type") == "string" and k != "status")
LIST_FIELDS = tuple(k for k, v in PROPOSAL_SCHEMA["properties"].items() if v.get("type") == "array")


def _validate(value, schema):
    try:
        Draft202012Validator(schema).validate(value)
    except ValidationError as exc:
        raise ValueError("Invalid response structure: " + exc.message) from exc


def validate_image_spec(spec, schema=None):
    schema = schema if schema is not None else load_proposal_schema()
    contract = schema["properties"]["image_spec"]["anyOf"][0]
    _validate(spec, contract)
    for key, field in contract["properties"].items():
        if field.get("type") == "string" and not spec[key].strip():
            raise ValueError(f"Image specification needs {key}.")
        if field.get("type") == "array" and any(not v.strip() for v in spec[key]):
            raise ValueError(f"Image specification has empty {key} entries.")
    return spec


def validate_proposal(proposal, schema=None):
    schema = schema if schema is not None else load_proposal_schema()
    _validate(proposal, schema)
    if proposal["status"] == "ready":
        if proposal["source_requirements"] or proposal["clarification_questions"]:
            raise ValueError("Ready proposals cannot have outstanding sources or clarification questions.")
        validate_image_spec(proposal["image_spec"], schema)
    else:
        if proposal["image_spec"] is not None:
            raise ValueError("Non-ready proposals must withhold image_spec.")
        required = "source_requirements" if proposal["status"] == "needs_sources" else "clarification_questions"
        if not proposal[required] or any(not item.strip() for item in proposal[required]):
            raise ValueError(f"This proposal must list {required}.")
    return proposal
