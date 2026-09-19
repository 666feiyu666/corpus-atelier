"""Offline providers for deterministic graph tests."""

from pathlib import Path

from PIL import Image

from corpus_atelier.artifacts.hashing import digest_file
from corpus_atelier.artifacts.records import write_json, write_text


class FakeTextProvider:
    model = "fake-text"

    def propose(self, prompt: str, *, schema_name: str):
        visible = ["CORPUS ATELIER"] if schema_name.startswith("poster") else [
            "从语料到视觉论证", "Corpus Atelier"
        ]
        value = {
            "status": "ready",
            "brief_interpretation": "A focused communication task.",
            "chosen_direction": "Layered archival forms become a clear visual argument.",
            "design_rationale": "The hierarchy connects evidence, transformation, and invitation.",
            "evidence_ids": ["art-direction-coherence"],
            "review_criteria": ["Exact copy is visible", "The focal hierarchy is clear"],
            "source_requirements": [],
            "clarification_questions": [],
            "image_spec": {
                "communication_objective": "Invite the intended audience to engage.",
                "audience_and_context": "Mobile and public display contexts.",
                "visible_copy": visible,
                "composition": "One dominant title, a central layered motif, and quiet margins.",
                "typography": "High-contrast display title with restrained supporting type.",
                "visual_treatment": "Contemporary editorial collage with flat organic forms.",
                "allowed_variation": ["Texture density may vary"],
                "exclusions": ["No logos", "No additional copy"],
            },
        }
        return value, {"status": "completed", "provider": "fake"}

    def review(self, image_path: Path, prompt: str, *, schema_name: str):
        return {
            "verdict": "accept",
            "observations": ["The title is dominant and the central motif is visible."],
            "interpretations": ["The layered motif can suggest evidence becoming form."],
            "copy_check": "Expected copy is represented in the test artifact.",
            "priority_actions": [],
            "uncertainties": ["A real review must verify small-size text rendering."],
        }, {"status": "completed", "provider": "fake"}


class FakeImageProvider:
    model = "fake-image"

    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail

    def generate(self, prompt: str, *, size: str, output: Path):
        self.calls += 1
        write_json(output / "request.json", {"prompt": prompt, "size": size, "model": self.model})
        write_text(output / "prompt.md", prompt)
        if self.fail:
            write_json(output / "response.json", {"status": "failed", "error_type": "RuntimeError"})
            raise RuntimeError("deliberate fake provider failure")
        target = output / "image.png"
        Image.new("RGB", (94, 60), (235, 224, 196)).save(target, format="PNG")
        response = {"status": "generated", "file": "image.png", "sha256": digest_file(target)}
        write_json(output / "response.json", response)
        return response
