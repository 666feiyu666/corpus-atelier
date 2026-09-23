import unittest

from corpus_atelier.design.prompt_compiler import compile_design_prompt
from corpus_atelier.image_prompt.prompt_compiler import (
    compile_generation_prompt, compile_image_spec_prompt,
)
from corpus_atelier.registry import get_profile
from tests.fakes import FakeTextProvider


class PromptTests(unittest.TestCase):
    def test_deliverable_references_compose_foundation_before_specialization(self):
        cases = {
            "rhetoric-poster": "Produce a portrait poster.",
            "art-article-cover": "Produce an exact 47:20 WeChat article cover.",
        }
        for profile_name, specialization in cases.items():
            with self.subTest(profile=profile_name):
                prompt = compile_design_prompt(
                    get_profile(profile_name), {"task": "x"},
                )
                foundation = "Produce a graphic design for the delivery"
                self.assertIn("# Deliverable foundation", prompt)
                self.assertIn("# Deliverable specialization", prompt)
                self.assertLess(prompt.index(foundation), prompt.index(specialization))

        general_prompt = compile_design_prompt(
            get_profile("rhetoric-graphic"), {"task": "x"},
        )
        self.assertIn("# Deliverable foundation", general_prompt)
        self.assertNotIn("# Deliverable specialization", general_prompt)

    def test_designer_receives_design_skill_without_image_model_knowledge(self):
        prompt = compile_design_prompt(
            get_profile("rhetoric-poster"), {"topic": "x"},
        )
        self.assertIn("coherent mental image", prompt)
        self.assertIn("design_description", prompt)
        self.assertNotIn("GPT Image 2 compilation guidance", prompt)
        self.assertNotIn("Untrusted selected visual reference", prompt)
        for unrelated_example_term in ("Mucha", "watch", "wrist"):
            self.assertNotIn(unrelated_example_term.lower(), prompt.lower())

    def test_design_prompt_has_no_predefined_reference_relationship(self):
        prompt = compile_design_prompt(
            get_profile("rhetoric-poster"),
            {"topic": "x"},
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
        self.assertIn("Visual-semantic failure reference", compiler_prompt)

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
