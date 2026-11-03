import unittest

from corpus_atelier.atelier.design_direction.prompt_compiler import (
    compile_design_direction_prompt,
)
from corpus_atelier.atelier.design_implementation.prompt_compiler import (
    compile_design_implementation_prompt,
)
from corpus_atelier.atelier.image_prompt.prompt_compiler import (
    MAX_GENERATION_PROMPT_CHARS,
    PROMPT_BUDGET_MAX,
    PROMPT_BUDGET_MIN,
    PROMPT_HARD_MAX,
    compile_generation_prompt, compile_image_prompt_prompt,
)
from corpus_atelier.atelier.image_prompt.synthesis import synthesize_image_prompt
from corpus_atelier.app.registry import get_profile
from corpus_atelier.design_support.validation import validate, validate_image_prompt
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
    def test_direction_prompt_receives_the_general_objective_for_a_poster(self):
        prompt = compile_design_direction_prompt(
            get_profile("poster"), {"task": "x"},
            canvas=CANVAS, candidate_limit=3,
        )
        self.assertIn("# Design objective", prompt)
        self.assertIn("set the balance between the two", prompt)
        self.assertIn("between one and 3 direction(s)", prompt)
        self.assertIn("Choose the visual language along the six dimensions below", prompt)
        self.assertIn("# Style-space rules", prompt)
        self.assertIn("One primary language, at most two supporting techniques", prompt)
        self.assertIn("# Visual-language dimensions for general-design.v1", prompt)
        self.assertIn("Composition and hierarchy", prompt)
        self.assertNotIn("Sign carrier and warrant", prompt)
        self.assertNotIn("Start with a coherent art direction", prompt)
        self.assertIn("# Deliverable categories", prompt)
        self.assertIn("# Design craft checklist", prompt)
        self.assertNotIn("# Legacy", prompt)
        self.assertNotIn("`swiss-style`", prompt)
        self.assertNotIn("Use a rigorous modular grid", prompt)
        self.assertNotIn("# Impressionism", prompt)
        self.assertNotIn("Supplied deliverable", prompt)
        self.assertNotIn("profile policy bundle", prompt)


    def test_direction_prompt_receives_the_general_objective(self):
        prompt = compile_design_direction_prompt(
            get_profile("general-graphic"), {"purpose": "x"},
            canvas=CANVAS, candidate_limit=3,
        )
        self.assertIn("set the balance between the two", prompt)
        self.assertIn("# Visual-language dimensions for general-design.v1", prompt)
        self.assertIn("Composition and hierarchy", prompt)
        self.assertIn("Type and copy placement", prompt)
        self.assertIn("# Style-space rules", prompt)
        self.assertNotIn("Sign carrier and warrant", prompt)
        self.assertNotIn("Communication purpose precedes sign selection", prompt)
        self.assertNotIn("Start with a coherent art direction", prompt)

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


class PromptBudgetTests(unittest.TestCase):
    """The scene prompt carries a character budget, enforced by schema and assembly."""

    @staticmethod
    def _scene_prompt(length: int) -> str:
        sentence = "The poster keeps one clear title block above a layered motif. "
        return (sentence * (length // len(sentence) + 1))[:length]

    def test_schema_accepts_a_prompt_inside_the_budget(self):
        value = validate_image_prompt(
            {**IMAGE_PROMPT, "prompt": self._scene_prompt(PROMPT_BUDGET_MAX)},
            IMAGE_PROMPT["exact_copy"],
        )
        self.assertEqual(len(value["prompt"]), PROMPT_BUDGET_MAX)

    def test_schema_rejects_an_overlong_prompt(self):
        with self.assertRaisesRegex(ValueError, "Invalid image-prompt.schema.json at prompt"):
            validate_image_prompt(
                {**IMAGE_PROMPT, "prompt": self._scene_prompt(PROMPT_HARD_MAX + 1)},
                IMAGE_PROMPT["exact_copy"],
            )

    def test_schema_rejects_an_overlong_canvas_statement(self):
        with self.assertRaisesRegex(
            ValueError, "Invalid image-prompt.schema.json at canvas_statement",
        ):
            validate_image_prompt(
                {**IMAGE_PROMPT, "canvas_statement": self._scene_prompt(241)},
                IMAGE_PROMPT["exact_copy"],
            )

    def test_writer_brief_states_the_length_budget(self):
        prompt = compile_image_prompt_prompt(
            brief={"content_language": "en", "exact_copy": ["CORPUS ATELIER"]},
            canvas=CANVAS,
            provider_profile="gpt-image-2",
        )
        self.assertIn("# Prompt length budget", prompt)
        for budget in (
            PROMPT_BUDGET_MIN, PROMPT_BUDGET_MAX, PROMPT_HARD_MAX,
            MAX_GENERATION_PROMPT_CHARS,
        ):
            self.assertIn(str(budget), prompt)

    def test_assembled_prompt_fits_when_the_scene_respects_the_budget(self):
        prompt = compile_generation_prompt(
            {**IMAGE_PROMPT, "prompt": self._scene_prompt(PROMPT_BUDGET_MAX)},
            exact_copy=["CORPUS ATELIER"],
            user_requirements=["Keep the lower-right area clear."],
        )
        self.assertLessEqual(len(prompt), MAX_GENERATION_PROMPT_CHARS)

    def test_assembled_prompt_rejects_excess_sections(self):
        with self.assertRaisesRegex(ValueError, "keep it under"):
            compile_generation_prompt(
                {**IMAGE_PROMPT, "prompt": self._scene_prompt(PROMPT_HARD_MAX)},
                exact_copy=["A long approved line " * 6],
                user_requirements=["Keep the lower-right area clear. " * 8],
            )


class AudienceSplitTests(unittest.TestCase):
    """The brief is written for a person; the prompt is written for the model."""

    @staticmethod
    def _long_text(repeat: int) -> str:
        return "The opening night runs late, so the poster has to stay legible after dark. " * repeat

    def test_writer_brief_separates_the_two_readers(self):
        prompt = compile_image_prompt_prompt(
            brief={"content_language": "en", "exact_copy": ["CORPUS ATELIER"]},
            canvas=CANVAS,
            provider_profile="gpt-image-2",
        )
        self.assertIn("# Audience split", prompt)
        self.assertIn("never sees the brief", prompt)
        self.assertIn("Translate intent into a visible decision", prompt)

    def test_brief_has_no_length_budget(self):
        brief = {
            "deliverable": "A2 poster",
            "purpose": self._long_text(20),
            "audience": self._long_text(10),
            "use_context": self._long_text(6),
            "exact_copy": ["OPENING NIGHT"],
            "constraints": [self._long_text(3)],
            "user_requirements": [],
            "preferences": [self._long_text(4)],
            "canvas": {"aspect_ratio": {"width": 3, "height": 4}},
        }
        value = validate(brief, "graphic-design-brief.schema.json")
        self.assertGreater(len(value["purpose"]), 1000)

    def test_proposal_description_may_exceed_the_prompt_budget(self):
        proposal = {**PROPOSAL, "design_description": self._long_text(40)}
        value = validate(proposal, "graphic-design-proposal.schema.json")
        self.assertGreater(len(value["design_description"]), 2000)


if __name__ == "__main__":
    unittest.main()
