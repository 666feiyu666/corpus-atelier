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

def validate_proposal(
    value: dict, schema_name: str, *, candidate_id: str | None = None,
) -> dict:
    validate(value, schema_name)
    internal_policy_paths = (
        "references/objectives/",
    )
    for requirement in value["source_requirements"]:
        if any(path in requirement.lower() for path in internal_policy_paths):
            raise ValueError(
                "Design proposal requested internal profile policy files that were "
                "already supplied."
            )
    if candidate_id is not None and value["candidate_id"] != candidate_id:
        raise ValueError("Design proposal changed the assigned candidate id.")
    if value["status"] == "ready":
        if value["source_requirements"] or value["clarification_questions"]:
            raise ValueError("A ready proposal cannot have unresolved requirements.")
        if not value["design_description"].strip():
            raise ValueError("A ready proposal requires a visible design description.")
    return value


def validate_image_spec(value: dict, exact_copy: list[str]) -> dict:
    validate(value, "image-spec.schema.json")
    if value["visible_copy"] != exact_copy:
        raise ValueError("The image specification changed the exact visible copy.")
    return value
