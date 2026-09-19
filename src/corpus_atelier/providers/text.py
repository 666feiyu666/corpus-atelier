"""Text/vision provider port with a non-retrying OpenAI adapter."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Protocol

from ..design.validation import load_schema, validate


class TextProvider(Protocol):
    def propose(self, prompt: str, *, schema_name: str) -> tuple[dict, dict]: ...
    def review(self, image_path: Path, prompt: str, *, schema_name: str) -> tuple[dict, dict]: ...


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
                    "strict": True, "schema": load_schema(schema_name),
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

    def propose(self, prompt: str, *, schema_name: str) -> tuple[dict, dict]:
        return self._call(prompt, schema_name)

    def review(self, image_path: Path, prompt: str, *, schema_name: str) -> tuple[dict, dict]:
        data = image_path.read_bytes()
        encoded = base64.b64encode(data).decode("ascii")
        return self._call([{"role": "user", "content": [
            {"type": "input_text", "text": prompt},
            {"type": "input_image", "image_url": f"data:image/png;base64,{encoded}"},
        ]}], schema_name)
