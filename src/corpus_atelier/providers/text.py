"""Text/vision provider port with a non-retrying OpenAI adapter."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Protocol

from ..design.validation import load_schema, validate


class TextProvider(Protocol):
    def propose(self, prompt: str, *, schema_name: str) -> tuple[dict, dict]: ...
    def plan_references(self, prompt: str, image_paths: list[Path], *,
                        schema_name: str) -> tuple[dict, dict]: ...
    def review(self, image_path: Path, prompt: str, *, schema_name: str) -> tuple[dict, dict]: ...
    def review_revision(self, before_path: Path, after_path: Path, prompt: str,
                        *, schema_name: str) -> tuple[dict, dict]: ...


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

    def plan_references(self, prompt: str, image_paths: list[Path], *,
                        schema_name: str) -> tuple[dict, dict]:
        content = [{"type": "input_text", "text": prompt}]
        for index, path in enumerate(image_paths, start=1):
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            suffix = path.suffix.lower().lstrip(".")
            media_type = "jpeg" if suffix in {"jpg", "jpeg"} else suffix
            content.extend([
                {"type": "input_text", "text": f"Complete reference image {index}:"},
                {"type": "input_image", "image_url":
                 f"data:image/{media_type};base64,{encoded}"},
            ])
        return self._call([{"role": "user", "content": content}], schema_name)

    def review(self, image_path: Path, prompt: str, *, schema_name: str) -> tuple[dict, dict]:
        data = image_path.read_bytes()
        encoded = base64.b64encode(data).decode("ascii")
        return self._call([{"role": "user", "content": [
            {"type": "input_text", "text": prompt},
            {"type": "input_image", "image_url": f"data:image/png;base64,{encoded}"},
        ]}], schema_name)

    def review_revision(self, before_path: Path, after_path: Path, prompt: str,
                        *, schema_name: str) -> tuple[dict, dict]:
        before = base64.b64encode(before_path.read_bytes()).decode("ascii")
        after = base64.b64encode(after_path.read_bytes()).decode("ascii")
        return self._call([{"role": "user", "content": [
            {"type": "input_text", "text": prompt},
            {"type": "input_text", "text": "Baseline image:"},
            {"type": "input_image", "image_url": f"data:image/png;base64,{before}"},
            {"type": "input_text", "text": "Edited image:"},
            {"type": "input_image", "image_url": f"data:image/png;base64,{after}"},
        ]}], schema_name)
