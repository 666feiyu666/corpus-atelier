"""Offline providers for deterministic graph tests."""

import json
from pathlib import Path
import re

from PIL import Image

from corpus_atelier.artifacts.hashing import digest_file
from corpus_atelier.artifacts.records import write_json, write_text


def _json_section(prompt: str, marker: str) -> dict:
    """Read the first JSON object inside a prompt section."""
    section = prompt.split(marker, 1)[1]
    return json.JSONDecoder().raw_decode(section[section.index("{"):])[0]


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
        if schema_name == "reverse-prompt.schema.json":
            value = {
                "positive_prompt": (
                    "A painterly snowy urban alley with a large blue-gray wolfdog "
                    "and a hooded woman facing each other."
                ),
                "negative_prompt": "photorealistic, flat vector, readable text, watermark",
            }
            return value, {"status": "completed", "provider": "fake"}
        if schema_name == "image-prompt.schema.json":
            target = _json_section(prompt, "# Compilation target\n\n")
            design = _json_section(prompt, "# Approved design\n\n")
            visible = target["exact_copy"]
            description = design.get(
                "design_description",
                design.get("topic")
                or design.get("deliverable")
                or design.get("article_title")
                or "A resolved graphic design.",
            )
            quoted = " / ".join(f'"{item}"' for item in visible)
            value = {
                "asset_kind": "poster",
                "canvas_statement": (
                    "Create a vertical poster with a dominant title block above a central motif."
                ),
                "prompt": (
                    f"A layered editorial composition. {description} "
                    "Flat organic forms, warm paper texture, and soft side light. "
                    f"Render exactly these strings: {quoted}."
                ),
                "exact_copy": visible,
                "preserve": [],
                "avoid": ["No logos", "No additional copy"],
                "visual_qa": [
                    "Every approved string renders exactly as written.",
                    "The title block stays dominant and the margins stay quiet.",
                ],
            }
            return value, {"status": "completed", "provider": "fake"}
        if schema_name == "design-direction-plan.schema.json":
            match = re.search(r"between one and ([1-3]) direction", prompt)
            count = int(match.group(1)) if match else 1
            directions = []
            palettes = [
                "Warm paper, charcoal, and one vermilion accent.",
                "Deep blue, pale cyan, and bright acidic yellow.",
                "Near-black, cool white, and muted lavender.",
            ]
            for index in range(count):
                directions.append({
                    "label": f"Direction {index + 1}",
                    "asset_category": "typography-and-posters",
                    "style_anchors": ["editorial type-led composition"],
                    "design_thesis": f"A distinct visual argument number {index + 1}.",
                    "objective_strategy": (
                        f"Apply the active objective through hierarchy strategy {index + 1}."
                    ),
                    "direction_decisions": [
                        {
                            "axis": "composition" if index % 2 == 0 else "palette",
                            "decision": (
                                f"Use strategy {index + 1} with a distinct hierarchy and "
                                f"{palettes[index]}"
                            ),
                        },
                    ],
                    "implementation_freedom": [
                        "Resolve exact spacing and material texture while preserving the strategy."
                    ],
                    "portfolio_role": f"This direction differs through strategy {index + 1}.",
                })
            return {
                "planning_mode": "open",
                "directions": directions,
            }, {"status": "completed", "provider": "fake"}
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
        candidate_match = re.search(r'"candidate_id"\s*:\s*"(c0[1-3])"', prompt)
        candidate_id = candidate_match.group(1) if candidate_match else "c01"
        value = {
            "candidate_id": candidate_id,
            "brief_interpretation": "A focused communication task.",
            "chosen_direction": (
                "A figure-led product-use composition grounded in the selected direction."
                if grounded else
                f"{candidate_id}: layered archival forms become a clear visual argument."
            ),
            "design_description": description,
            "design_rationale": (
                "The selected figure-product affordance informs a new watch-wearing gesture "
                "without copying JOB, smoking imagery, or the source composition."
                if grounded else
                f"The {candidate_id} hierarchy connects evidence, transformation, and invitation."
            ),
            "review_criteria": ["Exact copy is visible", "The focal hierarchy is clear"],
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
