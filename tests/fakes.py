"""Offline providers for deterministic graph tests."""

import json
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
        if schema_name == "graphic-design-brief.schema.json":
            value = {
                "deliverable": "16:9 desktop wallpaper",
                "purpose": (
                    "Use mild workplace humor to discourage people from interacting "
                    "with an unattended computer."
                ),
                "audience": "Coworkers and passersby in a shared office.",
                "use_context": (
                    "Displayed behind desktop icons on a workstation and understood "
                    "at a glance."
                ),
                "exact_copy": ["都看到这里了，就顺手帮我锁个屏吧"],
                "constraints": ["Keep the message playful and low-aggression."],
                "preferences": ["Use concise, self-aware workplace humor."],
                "canvas": {"aspect_ratio": {"width": 16, "height": 9}},
            }
            return value, {"status": "completed", "provider": "fake"}
        if schema_name == "poster-brief.schema.json":
            value = {
                "topic": "A complete poster topic",
                "purpose": "Communicate one clear invitation.",
                "audience": "The intended public audience.",
                "setting": "Viewed in a public setting.",
                "exact_copy": ["POSTER TITLE"],
                "constraints": [],
                "preferences": [],
            }
            return value, {"status": "completed", "provider": "fake"}
        if schema_name == "article-cover-brief.schema.json":
            value = {
                "article_title": "A complete article title",
                "article_summary": "A concise summary of the article.",
                "audience": "Article readers.",
                "exact_copy": ["A complete article title"],
                "constraints": [],
                "art_direction": "A restrained editorial direction.",
            }
            return value, {"status": "completed", "provider": "fake"}
        if schema_name == "image-spec.schema.json":
            target = prompt.split("# Compilation target\n\n", 1)[1].split(
                "\n\n# Completed design proposal", 1,
            )[0]
            proposal = json.loads(
                prompt.split("# Completed design proposal\n\n", 1)[1]
            )
            visible = json.loads(target)["exact_copy"]
            value = {
                "communication_objective": "Invite the intended audience to engage.",
                "audience_and_context": "The approved delivery and viewing context.",
                "visible_copy": visible,
                "subject_and_scene": proposal["design_description"],
                "composition": "One dominant title, a central layered motif, and quiet margins.",
                "typography": "High-contrast display title with restrained supporting type.",
                "visual_treatment": "Contemporary editorial collage with flat organic forms.",
                "allowed_variation": ["Texture density may vary"],
                "exclusions": ["No logos", "No additional copy"],
            }
            return value, {"status": "completed", "provider": "fake"}
        is_graphic = schema_name == "graphic-design-proposal.schema.json"
        visible = ["CORPUS ATELIER"] if schema_name.startswith("poster") else [
            "从语料到视觉论证", "Corpus Atelier"
        ]
        if is_graphic:
            visible = ["Design for context"]
        grounded = "# Selected design knowledge — untrusted evidence" in prompt
        description = (
            "A close-cropped woman remains the primary figure and wears the AURELIA "
            "wristwatch naturally on her raised wrist. Her gesture makes the product-use "
            "relationship legible without turning the watch into an isolated oversized hero."
            if grounded else
            "A portrait canvas with one central layered motif, a dominant title above it, "
            "quiet margins, flat organic forms, and a restrained editorial palette."
        )
        value = {
            "status": "ready",
            "brief_interpretation": "A focused communication task.",
            "chosen_direction": (
                "A figure-led product-use composition grounded in the selected corpus evidence."
                if grounded else
                "Layered archival forms become a clear visual argument."
            ),
            "design_description": description,
            "design_rationale": (
                "The selected figure-product affordance informs a new watch-wearing gesture "
                "without copying JOB, smoking imagery, or the source composition."
                if grounded else
                "The hierarchy connects evidence, transformation, and invitation."
            ),
            "review_criteria": ["Exact copy is visible", "The focal hierarchy is clear"],
            "source_requirements": [],
            "clarification_questions": [],
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
                         reference_paths: list[Path] | None = None):
        reference_paths = list(reference_paths or [])
        return {
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

    def generate(self, prompt: str, *, size: str, output: Path,
                 reference_paths: list[Path] | None = None):
        self.calls += 1
        self.last_size = size
        self.reference_paths = list(reference_paths or [])
        write_json(output / "request.json", self.describe_request(
            prompt, size=size, reference_paths=self.reference_paths,
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
