import unittest

from corpus_atelier.design_direction.prompt_compiler import (
    compile_design_direction_prompt,
)
from corpus_atelier.design_implementation.prompt_compiler import (
    compile_design_implementation_prompt,
)
from corpus_atelier.image_prompt.prompt_compiler import (
    compile_generation_prompt, compile_image_spec_prompt,
)
from corpus_atelier.registry import get_profile
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
    "movement_references": [],
    "portfolio_role": "The clearest direct strategy.",
}
CANVAS = {"size": "1024x1536", "ratio": [2, 3]}


class PromptTests(unittest.TestCase):
    def test_direction_prompt_receives_complete_rhetoric_objective(self):
        prompt = compile_design_direction_prompt(
            get_profile("rhetoric-poster"), {"task": "x"},
            canvas=CANVAS, candidate_limit=3,
        )
        self.assertIn("# Design objective", prompt)
        self.assertIn("Communication purpose precedes sign selection", prompt)
        self.assertIn("between one and 3 direction(s)", prompt)
        self.assertIn("# Rhetoric-led visual-language space", prompt)
        self.assertIn("# Art Nouveau", prompt)
        self.assertIn("# Swiss Style", prompt)
        self.assertNotIn("# Impressionism", prompt)
        self.assertNotIn("Supplied deliverable", prompt)
        self.assertNotIn("profile policy bundle", prompt)

    def test_direction_prompt_receives_complete_art_objective(self):
        prompt = compile_design_direction_prompt(
            get_profile("art-graphic"), {"purpose": "x"},
            canvas=CANVAS, candidate_limit=2,
        )
        self.assertIn("Start with a coherent art direction", prompt)
        self.assertIn("# Art-led visual-language space", prompt)
        self.assertIn("# Neoclassicism", prompt)
        self.assertIn("# Impressionism", prompt)
        self.assertIn("# Post-Impressionism", prompt)
        self.assertNotIn("# Swiss Style", prompt)
        self.assertNotIn("# Bauhaus and New Typography", prompt)
        self.assertNotIn("Communication purpose precedes sign selection", prompt)

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

    def test_generation_receives_spec_not_rationale(self):
        provider = FakeTextProvider()
        proposal, _ = provider.propose("", schema_name="poster-proposal.schema.json")
        compiler_prompt = compile_image_spec_prompt(
            proposal,
            brief={"exact_copy": ["CORPUS ATELIER"]},
            canvas={"size": "1024x1536", "ratio": [2, 3]},
            provider_profile="gpt-image-2",
        )
        spec, _ = provider.propose(
            compiler_prompt, schema_name="image-spec.schema.json",
        )
        prompt = compile_generation_prompt(spec)
        self.assertIn("Approved image specification", prompt)
        self.assertNotIn(proposal["design_rationale"], prompt)
        self.assertIn(spec["subject_and_scene"], prompt)
        self.assertIn("Visual-semantic disambiguation guidance", compiler_prompt)

    def test_image_spec_compiler_makes_exact_copy_exhaustive(self):
        provider = FakeTextProvider()
        proposal, _ = provider.propose("", schema_name="poster-proposal.schema.json")
        compiler_prompt = compile_image_spec_prompt(
            proposal,
            brief={"exact_copy": ["Approved title", "Approved label"]},
            canvas={"size": "1024x1536", "ratio": [2, 3]},
            provider_profile="gpt-image-2",
        )

        self.assertIn("# Exact-copy invariant", compiler_prompt)
        self.assertIn("preserving every string and its order", compiler_prompt)
        self.assertIn("Any additional wording", compiler_prompt)

    def test_image_spec_compiler_does_not_inject_example_scene_content(self):
        provider = FakeTextProvider()
        proposal, _ = provider.propose(
            "", schema_name="graphic-design-proposal.schema.json",
        )
        compiler_prompt = compile_image_spec_prompt(
            proposal,
            brief={"exact_copy": ["Design for context"]},
            canvas={"size": "1536x1024", "ratio": [3, 2]},
            provider_profile="gpt-image-2",
        )

        for unrelated_example_term in (
            "Mucha", "woman", "watch", "wrist", "detached display hand",
        ):
            self.assertNotIn(unrelated_example_term.lower(), compiler_prompt.lower())

    def test_generation_prompt_has_no_predefined_reference_relationship(self):
        provider = FakeTextProvider()
        proposal, _ = provider.propose("", schema_name="poster-proposal.schema.json")
        compiler_prompt = compile_image_spec_prompt(
            proposal,
            brief={"exact_copy": ["CORPUS ATELIER"]},
            canvas={"size": "1024x1536", "ratio": [2, 3]},
            provider_profile="gpt-image-2",
        )
        spec, _ = provider.propose(
            compiler_prompt, schema_name="image-spec.schema.json",
        )
        prompt = compile_generation_prompt(spec)
        self.assertNotIn("reference relationship", prompt.lower())
