import unittest

from corpus_atelier.atelier.design_direction.prompt_compiler import (
    compile_design_direction_prompt,
)
from corpus_atelier.atelier.design_implementation.prompt_compiler import (
    compile_design_implementation_prompt,
)
from corpus_atelier.atelier.image_prompt.prompt_compiler import (
    compile_generation_prompt, compile_image_prompt_prompt,
)
from corpus_atelier.atelier.image_prompt.synthesis import synthesize_image_prompt
from corpus_atelier.app.registry import get_profile
from tests.fakes import FakeTextProvider


DIRECTION = {
    "candidate_id": "c01",
    "label": "Direct reminder",
    "design_thesis": "Use one immediately legible workplace reminder.",
    "objective_strategy": "Make the intended reading clear at a glance.",
    "direction_decisions": [
        {"axis": "composition", "decision": "Use one dominant central message."},
    ],
    "implementation_freedom": ["Resolve exact spacing and texture."],
    "portfolio_role": "The clearest direct strategy.",
}
CANVAS = {"size": "1024x1536", "ratio": [2, 3]}
PROPOSAL = {
    "candidate_id": "c01",
    "brief_interpretation": "A focused communication task.",
    "chosen_direction": "A layered archival composition.",
    "design_description": "A portrait canvas with one central layered motif.",
    "design_rationale": "The hierarchy connects evidence and invitation.",
    "review_criteria": ["Exact copy is visible"],
}
IMAGE_PROMPT = {
    "asset_kind": "poster",
    "canvas_statement": "Create a 2:3 vertical poster with a title band across the top.",
    "prompt": "A layered archival composition with one central motif.",
    "exact_copy": ["CORPUS ATELIER"],
    "preserve": [],
    "avoid": ["No logos"],
    "visual_qa": ["The title renders exactly as written."],
}


class PromptTests(unittest.TestCase):
    def test_direction_prompt_receives_complete_rhetoric_objective(self):
        prompt = compile_design_direction_prompt(
            get_profile("rhetoric-poster"), {"task": "x"},
            canvas=CANVAS, candidate_limit=3,
        )
        self.assertIn("# Design objective", prompt)
        self.assertIn("Communication purpose precedes sign selection", prompt)
        self.assertIn("between one and 3 direction(s)", prompt)
        self.assertIn("Choose the visual language along the six dimensions below", prompt)
        self.assertIn("# Style-space rules", prompt)
        self.assertIn("One primary language, at most two supporting techniques", prompt)
        self.assertIn("# Visual-language dimensions for rhetoric-led.v1", prompt)
        self.assertIn("Sign carrier and warrant", prompt)
        self.assertNotIn("Medium and rendering logic", prompt)
        self.assertIn("# Deliverable categories", prompt)
        self.assertIn("# Design craft checklist", prompt)
        self.assertNotIn("# Legacy", prompt)
        self.assertNotIn("`swiss-style`", prompt)
        self.assertNotIn("Use a rigorous modular grid", prompt)
        self.assertNotIn("# Impressionism", prompt)
        self.assertNotIn("Supplied deliverable", prompt)
        self.assertNotIn("profile policy bundle", prompt)

    def test_direction_prompt_receives_complete_art_objective(self):
        prompt = compile_design_direction_prompt(
            get_profile("art-graphic"), {"purpose": "x"},
            canvas=CANVAS, candidate_limit=2,
        )
        self.assertIn("Start with a coherent art direction", prompt)
        self.assertIn("Choose the visual language along the six dimensions below", prompt)
        self.assertIn("# Style-space rules", prompt)
        self.assertIn("# Visual-language dimensions for art-led.v1", prompt)
        self.assertIn("Medium and rendering logic", prompt)
        self.assertNotIn("Sign carrier and warrant", prompt)
        self.assertIn("# Deliverable categories", prompt)
        self.assertNotIn("Use a rigorous modular grid", prompt)
        self.assertNotIn("# Swiss Style", prompt)
        self.assertNotIn("# Bauhaus and New Typography", prompt)
        self.assertNotIn("Communication purpose precedes sign selection", prompt)


    def test_direction_prompt_uses_the_brief_category_guide(self):
        prompt = compile_design_direction_prompt(
            get_profile("rhetoric-graphic"),
            {"task": "x", "asset_category": "editorial-and-covers"},
            canvas=CANVAS, candidate_limit=2,
        )
        self.assertIn("# Deliverable category: editorial-and-covers", prompt)
        self.assertIn("The reading surface", prompt)
        self.assertNotIn("# Deliverable category: typography-and-posters", prompt)

    def test_direction_prompt_asks_for_a_category_when_none_is_fixed(self):
        prompt = compile_design_direction_prompt(
            get_profile("rhetoric-graphic"), {"task": "x"},
            canvas=CANVAS, candidate_limit=2,
        )
        self.assertIn("has not fixed a category", prompt)
        self.assertNotIn("# Deliverable category:", prompt)

    def test_implementation_prompt_carries_the_category_requirements(self):
        prompt = compile_design_implementation_prompt(
            {"topic": "x", "exact_copy": []},
            canvas=CANVAS,
            direction_seed={**DIRECTION, "asset_category": "product-and-food"},
        )
        self.assertIn("# Deliverable category requirements: product-and-food", prompt)
        self.assertIn("Decide before rendering", prompt)

    def test_implementation_prompt_without_a_category_stays_generic(self):
        prompt = compile_design_implementation_prompt(
            {"topic": "x", "exact_copy": []},
            canvas=CANVAS, direction_seed=DIRECTION,
        )
        self.assertNotIn("# Deliverable category requirements:", prompt)

    def test_implementation_receives_approved_direction_without_objective_policy(self):
        prompt = compile_design_implementation_prompt(
            {"topic": "x", "exact_copy": []},
            canvas=CANVAS, direction_seed=DIRECTION,
        )
        self.assertIn("mental image of the finished work", prompt)
        self.assertIn("design_description", prompt)
        self.assertIn("exhaustive list of readable wording", prompt)
        self.assertIn("# Approved design direction", prompt)
        self.assertIn("Direct reminder", prompt)
        self.assertNotIn("# Objective guardrail", prompt)
        self.assertNotIn("Communication purpose precedes sign selection", prompt)
        self.assertNotIn("provider and validation failures", prompt)
        self.assertNotIn("automatic design agent", prompt)
        self.assertNotIn("needs_clarification", prompt)
        self.assertNotIn("GPT Image 2 compilation guidance", prompt)
        self.assertNotIn("Untrusted selected visual reference", prompt)
        for unrelated_example_term in ("Mucha", "watch", "wrist"):
            self.assertNotIn(unrelated_example_term.lower(), prompt.lower())

    def test_implementation_prompt_has_no_predefined_reference_relationship(self):
        prompt = compile_design_implementation_prompt(
            {"topic": "x", "exact_copy": []},
            canvas=CANVAS,
            direction_seed=DIRECTION,
        )
        self.assertNotIn("reference relationship", prompt.lower())
        self.assertNotIn("Untrusted selected visual reference", prompt)


class ImagePromptCompilerTests(unittest.TestCase):
    def compile(self, **overrides):
        arguments = {
            "brief": {"exact_copy": ["CORPUS ATELIER"], "constraints": [], "user_requirements": []},
            "canvas": CANVAS,
            "provider_profile": "gpt-image-2",
            "model_family": "gpt-image-2",
            "design": PROPOSAL,
        }
        arguments.update(overrides)
        return compile_image_prompt_prompt(**arguments)

    def test_compiler_carries_skill_craft_and_output_contract(self):
        prompt = self.compile()
        self.assertIn("image-prompt writer", prompt.lower())
        self.assertIn("# Prompt craft checklist", prompt)
        self.assertIn("# Renderer output contract", prompt)
        self.assertIn("# Exact-copy invariant", prompt)
        self.assertIn("preserving every string and its order", prompt)
        self.assertIn("# Compilation target", prompt)
        self.assertIn('"operation": "generation"', prompt)
        self.assertNotIn("# Visual-semantic disambiguation guidance", prompt)

    def test_compiler_chooses_the_model_family_guidance(self):
        legacy = self.compile(model_family="gpt-image-2")
        current = self.compile(
            provider_profile="gpt-image-2.5-flare", model_family="gpt-image-2.5",
        )
        self.assertIn("Target image model family: gpt-image-2", legacy)
        self.assertIn("Camera language is an appearance cue", legacy)
        self.assertNotIn("responds well to a precise brief", legacy)
        self.assertIn("Target image model family: gpt-image-2.5", current)
        self.assertIn("responds well to a precise brief", current)
        self.assertNotIn("Camera language is an appearance cue", current)

    def test_editing_operation_adds_invariants_and_reference_notes(self):
        prompt = self.compile(
            operation="reference_generation",
            reference_notes=["Reference image 1: base.png"],
        )
        self.assertIn("# Edit and inpaint invariants", prompt)
        self.assertIn('"operation": "reference_generation"', prompt)
        self.assertIn("base.png", prompt)

    def test_generation_operation_has_no_editing_invariants(self):
        self.assertNotIn("# Edit and inpaint invariants", self.compile())

    def test_corpus_reference_slice_is_advisory_evidence(self):
        prompt = self.compile(corpus_references=[{
            "id": "record-1",
            "prompt": "A folded paper poster with a single vermilion stamp.",
            "tags": ["style.swiss"],
            "source_run_id": None,
        }])
        self.assertIn("# Reference gallery slice", prompt)
        self.assertIn("folded paper poster", prompt)
        self.assertIn("Do not copy their subjects", prompt)
        self.assertNotIn("# Reference gallery slice", self.compile())

    def test_compiler_does_not_inject_example_scene_content(self):
        prompt = self.compile(
            brief={"exact_copy": ["Design for context"]},
            design={**PROPOSAL, "design_description": "A restrained editorial cover."},
        )
        for unrelated_example_term in (
            "Mucha", "woman", "watch", "wrist", "detached display hand",
        ):
            self.assertNotIn(unrelated_example_term.lower(), prompt.lower())

    def test_synthesis_returns_the_exact_copy_and_one_prompt(self):
        provider = FakeTextProvider()
        prompt, image_prompt, _ = synthesize_image_prompt(
            brief={"exact_copy": ["CORPUS ATELIER"]},
            canvas=CANVAS,
            provider_profile="gpt-image-2",
            provider=provider,
            design=PROPOSAL,
        )
        self.assertIn("# Compilation target", prompt)
        self.assertEqual(image_prompt["exact_copy"], ["CORPUS ATELIER"])
        self.assertEqual(provider.design_calls[-1]["schema_name"], "image-prompt.schema.json")


class GenerationPromptTests(unittest.TestCase):
    def test_prompt_is_canvas_then_scene_then_copy(self):
        prompt = compile_generation_prompt(
            IMAGE_PROMPT, exact_copy=["CORPUS ATELIER"], user_requirements=[],
        )
        canvas_position = prompt.index(IMAGE_PROMPT["canvas_statement"])
        scene_position = prompt.index(IMAGE_PROMPT["prompt"])
        copy_position = prompt.index('"CORPUS ATELIER"')
        self.assertLess(canvas_position, scene_position)
        self.assertLess(scene_position, copy_position)

    def test_prompt_has_no_negative_section_or_json(self):
        prompt = compile_generation_prompt(IMAGE_PROMPT)
        self.assertNotIn("Negative prompt", prompt)
        self.assertNotIn('"asset_kind"', prompt)
        self.assertNotIn("{", prompt)
        self.assertNotIn("Approved image specification", prompt)
        self.assertNotIn("communication_objective", prompt)

    def test_prompt_quotes_copy_and_confirmed_requirements(self):
        prompt = compile_generation_prompt(
            IMAGE_PROMPT,
            exact_copy=["CORPUS ATELIER", "VOL. 2"],
            user_requirements=["Keep the lower-right area clear."],
        )
        self.assertIn('"CORPUS ATELIER" / "VOL. 2"', prompt)
        self.assertIn("Keep the lower-right area clear.", prompt)
        self.assertNotIn("must also satisfy", compile_generation_prompt(IMAGE_PROMPT))

    def test_prompt_without_copy_forbids_lettering(self):
        prompt = compile_generation_prompt({**IMAGE_PROMPT, "exact_copy": []})
        self.assertIn("Render no text", prompt)

    def test_prompt_carries_preserve_and_avoid_in_the_body(self):
        prompt = compile_generation_prompt({
            **IMAGE_PROMPT,
            "preserve": ["subject identity", "existing text"],
            "avoid": ["No logos", "No added copy"],
        })
        self.assertIn("Preserve without change: subject identity; existing text.", prompt)
        self.assertIn("Avoid: No logos; No added copy.", prompt)

    def test_prompt_omits_empty_preserve_and_avoid_sections(self):
        prompt = compile_generation_prompt({**IMAGE_PROMPT, "preserve": [], "avoid": []})
        self.assertNotIn("Preserve without change", prompt)
        self.assertNotIn("Avoid:", prompt)


if __name__ == "__main__":
    unittest.main()
