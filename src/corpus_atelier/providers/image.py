"""Image provider port with one-call, no-retry OpenAI generation."""

from __future__ import annotations

import base64
from contextlib import ExitStack
from pathlib import Path
from typing import Protocol

from ..artifacts.hashing import digest_file


class ImageProvider(Protocol):
    def describe_request(self, prompt: str, *, size: str,
                         reference_paths: list[Path] | None = None) -> dict: ...

    def generate(self, prompt: str, *, size: str, output: Path,
                 reference_paths: list[Path] | None = None) -> dict: ...


class OpenAIImageProvider:
    def __init__(
        self,
        model: str = "gpt-image-2",
        quality: str = "medium",
        client=None,
        api_key: str | None = None,
    ):
        self.model = model
        self.quality = quality
        self.client = client
        self.api_key = api_key

    def describe_request(self, prompt: str, *, size: str,
                         reference_paths: list[Path] | None = None) -> dict:
        """Return the persisted, human-reviewable form of the provider request."""
        reference_paths = list(reference_paths or [])
        if len(reference_paths) > 3:
            raise ValueError("Image generation accepts at most three reference images.")
        return {
            "prompt": prompt, "model": self.model, "quality": self.quality,
            "size": size, "output_format": "png", "n": 1,
            "operation": "reference_generation" if reference_paths else "generation",
            "references": [
                {"file": path.name, "sha256": digest_file(path)}
                for path in reference_paths
            ],
        }

    def generate(self, prompt: str, *, size: str, output: Path,
                 reference_paths: list[Path] | None = None) -> dict:
        from ..artifacts.records import write_json, write_text
        reference_paths = list(reference_paths or [])
        request = self.describe_request(
            prompt, size=size, reference_paths=reference_paths,
        )
        write_json(output / "request.json", request)
        write_text(output / "prompt.md", prompt)
        response_record = {"status": "requested"}
        write_json(output / "response.json", response_record)
        owned = self.client is None
        client = self.client
        try:
            if owned:
                from openai import OpenAI
                client = OpenAI(
                    api_key=self.api_key,
                    max_retries=0,
                    timeout=600.0,
                )
            api_request = {
                "prompt": prompt, "model": self.model, "quality": self.quality,
                "size": size, "output_format": "png", "n": 1,
            }
            if reference_paths:
                with ExitStack() as stack:
                    images = [
                        stack.enter_context(path.open("rb"))
                        for path in reference_paths
                    ]
                    response = client.images.edit(image=images, **api_request)
            else:
                response = client.images.generate(**api_request)
            if not response.data or not response.data[0].b64_json:
                raise ValueError("The image provider returned no image.")
            data = base64.b64decode(response.data[0].b64_json, validate=True)
            if not data.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError("The image provider did not return PNG.")
            target = output / "image.png"
            target.write_bytes(data)
            usage = getattr(response, "usage", None)
            response_record = {
                "status": "generated", "file": target.name, "sha256": digest_file(target),
                "request_id": getattr(response, "_request_id", None),
                "usage": usage.model_dump(mode="json") if usage else None,
                "revised_prompt": getattr(response.data[0], "revised_prompt", None),
            }
            write_json(output / "response.json", response_record)
            return response_record
        except KeyboardInterrupt:
            write_json(output / "response.json", {
                "status": "interrupted", "error_type": "KeyboardInterrupt",
                "remote_outcome": "unknown",
            })
            raise
        except Exception as exc:
            write_json(output / "response.json", {
                "status": "failed", "error_type": type(exc).__name__,
            })
            raise
        finally:
            if owned and client is not None:
                client.close()
