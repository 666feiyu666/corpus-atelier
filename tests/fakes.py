"""Offline providers for deterministic graph tests."""

import json
from pathlib import Path

from PIL import Image

from corpus_atelier.artifacts.hashing import digest_file
from corpus_atelier.artifacts.records import write_json, write_text


class FakeTextProvider:
    model = "fake-text"

    def __init__(self):
        self.reference_calls = []
        self.reference_evidence_ids = []

    def plan_references(self, prompt: str, image_paths: list[Path], *, schema_name: str):
        self.reference_calls.append({
            "prompt": prompt, "image_paths": list(image_paths), "schema_name": schema_name,
        })
        package = json.loads(prompt.split("order shown here:\n\n", 1)[1])
        reference_ids = [row["id"] for row in package["references"]]
        knowledge_ids = [row["id"] for row in package["knowledge"]]
        self.reference_evidence_ids = reference_ids + knowledge_ids
        evidence_ids = (reference_ids + knowledge_ids)[:2]
        if schema_name == "style-grounded-plan.schema.json":
            value = {
                "mode": "style_grounded",
                "summary": "A cross-reference commercial style system for human review.",
                "style_invariants": [
                    {
                        "claim": "Curved framing organizes the figure and product.",
                        "evidence_ids": evidence_ids,
                        "application": "Use a new circular watch-led hierarchy.",
                    },
                    {
                        "claim": "Display lettering participates in the composition.",
                        "evidence_ids": evidence_ids,
                        "application": "Integrate the short brand copy into a new frame.",
                    },
                ],
                "allowed_variations": ["The product and gesture may be newly composed."],
                "content_mapping_rules": ["Map the watch face to a new circular focal system."],
                "work_specific_features_to_exclude": ["Do not copy any complete reference layout."],
                "human_review_questions": ["Are the claimed patterns visible across references?"],
            }
        else:
            value = {
                "mode": "style_inspired",
                "independent_concept": "Time represented as controlled organic growth.",
                "inspiration_mappings": [
                    {
                        "evidence_ids": reference_ids[:1],
                        "source_attribute": "mechanical-organic contrast",
                        "transformation": "Turn it into clean trajectories around the watch.",
                        "destination": "background motion system",
                    }
                ],
                "features_not_carried_forward": [
                    "full-length period figure", "complete ornamental border",
                ],
                "human_review_questions": ["Is the contemporary concept visibly independent?"],
            }
        return value, {"status": "completed", "provider": "fake"}

    def propose(self, prompt: str, *, schema_name: str):
        visible = ["CORPUS ATELIER"] if schema_name.startswith("poster") else [
            "从语料到视觉论证", "Corpus Atelier"
        ]
        value = {
            "status": "ready",
            "brief_interpretation": "A focused communication task.",
            "chosen_direction": "Layered archival forms become a clear visual argument.",
            "design_rationale": "The hierarchy connects evidence, transformation, and invitation.",
            "evidence_ids": self.reference_evidence_ids[:1] or [
                "mucha-commercial-lettering-image-integration"
            ],
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
        self.reference_paths = []
        self.fail = fail

    def generate(self, prompt: str, *, size: str, output: Path,
                 reference_paths: list[Path] | None = None):
        self.calls += 1
        self.reference_paths = list(reference_paths or [])
        write_json(output / "request.json", {
            "prompt": prompt, "size": size, "model": self.model,
            "references": [str(path) for path in self.reference_paths],
        })
        write_text(output / "prompt.md", prompt)
        if self.fail:
            write_json(output / "response.json", {"status": "failed", "error_type": "RuntimeError"})
            raise RuntimeError("deliberate fake provider failure")
        target = output / "image.png"
        Image.new("RGB", (94, 60), (235, 224, 196)).save(target, format="PNG")
        response = {"status": "generated", "file": "image.png", "sha256": digest_file(target)}
        write_json(output / "response.json", response)
        return response
