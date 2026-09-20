"""Offline providers for deterministic graph tests."""

from pathlib import Path

from PIL import Image

from corpus_atelier.artifacts.hashing import digest_file
from corpus_atelier.artifacts.records import write_json, write_text


class FakeTextProvider:
    model = "fake-text"

    def __init__(self):
        self.reference_calls = []

    def plan_references(self, prompt: str, image_paths: list[Path], *, schema_name: str):
        self.reference_calls.append({
            "prompt": prompt, "image_paths": list(image_paths), "schema_name": schema_name,
        })
        if schema_name == "style-grounded-plan.schema.json":
            value = {
                "mode": "style_grounded",
                "summary": "A cross-reference commercial style system for human review.",
                "style_invariants": [
                    {
                        "claim": "Curved framing organizes the figure and product.",
                        "evidence_ids": ["mucha-poster-124474237", "mucha-poster-124474255"],
                        "application": "Use a new circular watch-led hierarchy.",
                    },
                    {
                        "claim": "Display lettering participates in the composition.",
                        "evidence_ids": ["mucha-poster-124474229", "mucha-poster-124474277"],
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
                        "evidence_ids": ["mucha-poster-124474273"],
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
        if schema_name == "revision-plan.schema.json":
            return {
                "requested_changes": ["Remove the unwanted lower-left writing."],
                "must_preserve": ["Preserve exact copy and the overall composition."],
                "forbidden_changes": ["Do not add copy or redesign the image."],
                "success_criteria": ["The unwanted writing is absent without regressions."],
            }, {"status": "completed", "provider": "fake"}
        visible = ["CORPUS ATELIER"] if schema_name.startswith("poster") else [
            "从语料到视觉论证", "Corpus Atelier"
        ]
        value = {
            "status": "ready",
            "brief_interpretation": "A focused communication task.",
            "chosen_direction": "Layered archival forms become a clear visual argument.",
            "design_rationale": "The hierarchy connects evidence, transformation, and invitation.",
            "evidence_ids": ["mucha-commercial-lettering-image-integration"],
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

    def review_revision(self, before_path: Path, after_path: Path, prompt: str,
                        *, schema_name: str):
        return {
            "verdict": "accept",
            "requested_change_met": True,
            "requested_change_evidence": ["The requested local change is visible."],
            "preservation_checks": [{
                "criterion": "Preserve exact copy and the overall composition.",
                "passed": True,
                "evidence": "The edited artifact retains the baseline structure.",
            }],
            "regressions": [],
            "copy_check": {
                "passed": True, "observed_copy": ["CORPUS ATELIER"],
                "notes": "No copy regression in the test artifact.",
            },
            "uncertainties": [],
        }, {"status": "completed", "provider": "fake"}


class FakeImageProvider:
    model = "fake-image"

    def __init__(self, fail=False):
        self.calls = 0
        self.edit_calls = 0
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

    def edit(self, image_path: Path, prompt: str, *, size: str, output: Path,
             mask_path: Path | None = None):
        self.edit_calls += 1
        write_json(output / "request.json", {
            "prompt": prompt, "size": size, "model": self.model,
            "source": image_path.name,
        })
        write_text(output / "prompt.md", prompt)
        if self.fail:
            write_json(output / "response.json", {
                "status": "failed", "error_type": "RuntimeError",
            })
            raise RuntimeError("deliberate fake provider failure")
        target = output / "image.png"
        Image.new("RGB", (94, 60), (225, 214, 186)).save(target, format="PNG")
        response = {"status": "edited", "file": target.name, "sha256": digest_file(target)}
        write_json(output / "response.json", response)
        return response
