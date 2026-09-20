"""Image provider port with one-call, no-retry OpenAI generation."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Protocol

from ..artifacts.hashing import digest_file


class ImageProvider(Protocol):
    def generate(self, prompt: str, *, size: str, output: Path) -> dict: ...
    def edit(self, image_path: Path, prompt: str, *, size: str, output: Path,
             mask_path: Path | None = None) -> dict: ...


class OpenAIImageProvider:
    def __init__(self, model: str = "gpt-image-2", quality: str = "medium", client=None):
        self.model = model
        self.quality = quality
        self.client = client

    def generate(self, prompt: str, *, size: str, output: Path) -> dict:
        from ..artifacts.records import write_json, write_text
        request = {"prompt": prompt, "model": self.model, "quality": self.quality,
                   "size": size, "output_format": "png", "n": 1}
        write_json(output / "request.json", request)
        write_text(output / "prompt.md", prompt)
        response_record = {"status": "requested"}
        write_json(output / "response.json", response_record)
        owned = self.client is None
        client = self.client
        try:
            if owned:
                from openai import OpenAI
                client = OpenAI(max_retries=0, timeout=600.0)
            response = client.images.generate(**request)
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

    def edit(self, image_path: Path, prompt: str, *, size: str, output: Path,
             mask_path: Path | None = None) -> dict:
        from ..artifacts.records import write_json, write_text
        request = {
            "prompt": prompt, "model": self.model, "quality": self.quality,
            "size": size, "output_format": "png", "n": 1,
            "source_file": image_path.name, "source_sha256": digest_file(image_path),
            "mask_file": mask_path.name if mask_path else None,
            "mask_sha256": digest_file(mask_path) if mask_path else None,
        }
        write_json(output / "request.json", request)
        write_text(output / "prompt.md", prompt)
        write_json(output / "response.json", {"status": "requested"})
        owned = self.client is None
        client = self.client
        try:
            if owned:
                from openai import OpenAI
                client = OpenAI(max_retries=0, timeout=600.0)
            with image_path.open("rb") as source:
                api_request = {
                    "image": source, "prompt": prompt, "model": self.model,
                    "quality": self.quality, "size": size, "output_format": "png", "n": 1,
                }
                if mask_path:
                    with mask_path.open("rb") as mask:
                        response = client.images.edit(**api_request, mask=mask)
                else:
                    response = client.images.edit(**api_request)
            if not response.data or not response.data[0].b64_json:
                raise ValueError("The image provider returned no edited image.")
            data = base64.b64decode(response.data[0].b64_json, validate=True)
            if not data.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError("The image provider did not return PNG.")
            target = output / "image.png"
            target.write_bytes(data)
            usage = getattr(response, "usage", None)
            response_record = {
                "status": "edited", "file": target.name, "sha256": digest_file(target),
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
