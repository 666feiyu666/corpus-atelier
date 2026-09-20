"""JSON Schema and cross-field validation."""

import json
from importlib.resources import files

from jsonschema import Draft202012Validator, ValidationError


def load_schema(name: str) -> dict:
    schema = json.loads(files("corpus_atelier").joinpath("schemas", name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return schema


def validate(value: object, schema_name: str):
    try:
        Draft202012Validator(load_schema(schema_name)).validate(value)
    except ValidationError as exc:
        location = ".".join(str(part) for part in exc.absolute_path)
        raise ValueError(f"Invalid {schema_name} at {location or '<root>'}: {exc.message}") from exc
    return value


def validate_proposal(value: dict, schema_name: str) -> dict:
    validate(value, schema_name)
    if value["status"] == "ready":
        if value["source_requirements"] or value["clarification_questions"]:
            raise ValueError("A ready proposal cannot have unresolved requirements.")
        if value["image_spec"] is None:
            raise ValueError("A ready proposal requires image_spec.")
    elif value["image_spec"] is not None:
        raise ValueError("A blocked proposal must withhold image_spec.")
    return value


def validate_reference_plan(value: dict, *, schema_name: str, mode: str,
                            available_ids: set[str]) -> dict:
    """Validate structure and provenance without judging artistic understanding."""
    validate(value, schema_name)
    if value["mode"] != mode:
        raise ValueError("Reference plan mode does not match the deterministic graph route.")
    if mode == "style_grounded":
        groups = [item["evidence_ids"] for item in value["style_invariants"]]
    else:
        groups = [item["evidence_ids"] for item in value["inspiration_mappings"]]
    cited = {evidence_id for group in groups for evidence_id in group}
    unknown = sorted(cited - available_ids)
    if unknown:
        raise ValueError(f"Reference plan cites unavailable evidence IDs: {unknown}.")
    return value


def validate_revision_review(value: dict, plan: dict) -> dict:
    validate(value, "revision-review.schema.json")
    expected = plan["must_preserve"]
    observed = [item["criterion"] for item in value["preservation_checks"]]
    if observed != expected:
        raise ValueError("Revision review must check every must_preserve criterion in order.")
    if value["verdict"] == "accept":
        if not value["requested_change_met"]:
            raise ValueError("An accepted revision must satisfy the requested change.")
        if not value["copy_check"]["passed"]:
            raise ValueError("An accepted revision must pass exact-copy review.")
        if not all(item["passed"] for item in value["preservation_checks"]):
            raise ValueError("An accepted revision must pass every preservation check.")
        if value["regressions"]:
            raise ValueError("An accepted revision cannot contain reported regressions.")
    return value
