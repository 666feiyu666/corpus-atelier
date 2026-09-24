"""Text/vision provider port with a non-retrying OpenAI adapter."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Protocol

from ..design.validation import load_schema, validate


def _schema_for_openai(schema_name: str) -> dict:
    """Return the local schema adapted to OpenAI's supported JSON Schema subset."""
    schema = load_schema(schema_name)

    def strip_unsupported_keywords(value):
        if isinstance(value, dict):
            return {
                key: strip_unsupported_keywords(item)
                for key, item in value.items()
                if key != "uniqueItems"
            }
        if isinstance(value, list):
            return [strip_unsupported_keywords(item) for item in value]
        return value

    return strip_unsupported_keywords(schema)


class TextProvider(Protocol):
    def propose(self, prompt: str, *, schema_name: str,
                reference_paths: list[Path] | None = None) -> tuple[dict, dict]: ...


class OpenAITextProvider:
    def __init__(self, model: str = "gpt-5.6-luna", reasoning_effort: str = "medium", client=None):
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.client = client

    def _client(self):
        if self.client is not None:
            return self.client, False
        from openai import OpenAI
        return OpenAI(max_retries=0, timeout=600.0), True

    def _call(self, input_value, schema_name: str) -> tuple[dict, dict]:
        client, owned = self._client()
        try:
            response = client.responses.create(
                model=self.model, reasoning={"effort": self.reasoning_effort}, store=False,
                input=input_value, text={"format": {
                    "type": "json_schema", "name": schema_name.removesuffix(".schema.json").replace("-", "_"),
                    "strict": True, "schema": _schema_for_openai(schema_name),
                }},
            )
            if getattr(response, "status", "completed") != "completed" or not response.output_text:
                raise ValueError("The provider did not return a completed structured response.")
            value = json.loads(response.output_text)
            validate(value, schema_name)
            usage = getattr(response, "usage", None)
            record = {
                "status": "completed", "response_id": getattr(response, "id", None),
                "request_id": getattr(response, "_request_id", None),
                "usage": usage.model_dump(mode="json") if usage else None,
                "raw_output": response.output_text,
            }
            return value, record
        finally:
            if owned:
                client.close()

    def propose(self, prompt: str, *, schema_name: str,
                reference_paths: list[Path] | None = None) -> tuple[dict, dict]:
        reference_paths = list(reference_paths or [])
        if not reference_paths:
            return self._call(prompt, schema_name)
        content = [{"type": "input_text", "text": prompt}]
        for index, path in enumerate(reference_paths, start=1):
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            suffix = path.suffix.lower().lstrip(".")
            media_type = "jpeg" if suffix in {"jpg", "jpeg"} else suffix
            content.extend([
                {"type": "input_text", "text": f"Complete reference image {index}:"},
                {"type": "input_image", "image_url":
                 f"data:image/{media_type};base64,{encoded}"},
            ])
        return self._call([{"role": "user", "content": content}], schema_name)
