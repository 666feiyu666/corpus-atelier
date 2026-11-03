"""Offline providers for deterministic prompt-session tests."""

from pathlib import Path

from PIL import Image

from corpus_atelier.artifacts.hashing import digest_file
from corpus_atelier.artifacts.records import write_json, write_text


class FakeTextProvider:
    model = "fake-text"

    def __init__(self):
        self.design_calls = []

    def propose(self, prompt: str, *, schema_name: str,
                reference_paths: list[Path] | None = None):
        reference_paths = list(reference_paths or [])
        self.design_calls.append({
            "prompt": prompt,
            "reference_paths": reference_paths,
            "schema_name": schema_name,
        })
        if schema_name == "prompt-extraction.schema.json":
            value = {
                "prompt_text": (
                    "A painterly snowy urban alley with a large blue-gray wolfdog and a "
                    "hooded woman facing each other, cold blue palette, soft side light."
                ),
                "observations": None,
            }
            return value, {"status": "completed", "provider": "fake"}
        value = {
            "reply": "Here is the prompt you asked for.",
            "proposed_prompt": None,
            "edit_instruction": None,
        }
        return value, {"status": "completed", "provider": "fake"}


class FakeImageProvider:
    model = "fake-image"
    quality = "test"

    def __init__(self, fail=False):
        self.calls = 0
        self.reference_paths = []
        self.last_size = None
        self.fail = fail

    def describe_request(self, prompt: str, *, size: str,
                         reference_paths: list[Path] | None = None,
                         mask_path: Path | None = None):
        reference_paths = list(reference_paths or [])
        request = {
            "prompt": prompt,
            "model": self.model,
            "quality": self.quality,
            "size": size,
            "output_format": "png",
            "n": 1,
            "operation": "reference_generation" if reference_paths else "generation",
            "references": [
                {"file": path.name, "sha256": digest_file(path)}
                for path in reference_paths
            ],
        }
        if mask_path is not None:
            request["operation"] = "mask_edit"
            request["mask"] = {
                "file": Path(mask_path).name, "sha256": digest_file(mask_path),
            }
        return request

    def generate(self, prompt: str, *, size: str, output: Path,
                 reference_paths: list[Path] | None = None,
                 mask_path: Path | None = None):
        self.calls += 1
        self.last_size = size
        self.reference_paths = list(reference_paths or [])
        self.mask_path = mask_path
        write_json(output / "request.json", self.describe_request(
            prompt, size=size, reference_paths=self.reference_paths,
            mask_path=mask_path,
        ))
        write_text(output / "prompt.md", prompt)
        if self.fail:
            write_json(output / "response.json", {"status": "failed", "error_type": "RuntimeError"})
            raise RuntimeError("deliberate fake provider failure")
        target = output / "image.png"
        Image.new("RGB", (94, 60), (235, 224, 196)).save(target, format="PNG")
        response = {"status": "generated", "file": "image.png", "sha256": digest_file(target)}
        write_json(output / "response.json", response)
        return response
