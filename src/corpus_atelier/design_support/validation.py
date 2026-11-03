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
