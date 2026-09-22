import unittest

from corpus_atelier.design.prompt_compiler import (
    compile_design_prompt, compile_generation_prompt,
)
from corpus_atelier.registry import get_profile
from tests.fakes import FakeTextProvider


class PromptTests(unittest.TestCase):
    def test_deliverable_prompts_compose_foundation_before_specialization(self):
        cases = {
            "rhetoric-poster": "Produce a portrait poster.",
            "art-article-cover": "Produce an exact 47:20 WeChat article cover.",
        }
        for profile_name, specialization in cases.items():
            with self.subTest(profile=profile_name):
                prompt = compile_design_prompt(
                    get_profile(profile_name), {"task": "x"}, None,
                )
                foundation = "Produce a graphic design for the delivery"
                self.assertIn("# Deliverable foundation", prompt)
                self.assertIn("# Deliverable specialization", prompt)
                self.assertLess(prompt.index(foundation), prompt.index(specialization))

        general_prompt = compile_design_prompt(
            get_profile("rhetoric-graphic"), {"task": "x"}, None,
        )
        self.assertIn("# Deliverable foundation", general_prompt)
        self.assertNotIn("# Deliverable specialization", general_prompt)

    def test_designer_receives_gpt_image_2_authoring_knowledge(self):
        prompt = compile_design_prompt(
            get_profile("rhetoric-poster"), {"topic": "x"},
            None,
        )
        self.assertIn("GPT Image 2 authoring knowledge", prompt)
        self.assertIn("image_spec", prompt)
        self.assertIn("own without the design_rationale", prompt)
        self.assertIn("focal subject and supporting elements", prompt)
        self.assertNotIn("Untrusted selected visual reference", prompt)

    def test_selected_reference_adds_only_the_mode_instruction(self):
        prompt = compile_design_prompt(
            get_profile("rhetoric-poster"),
            {"topic": "x"},
            {"reference": {"id": "ref-1", "title": "Example"}},
            "style_inspired",
        )
        self.assertIn("Style-inspired reference relationship", prompt)
        self.assertNotIn("Untrusted selected visual reference", prompt)
        self.assertNotIn("ref-1", prompt)
        self.assertNotIn("Example", prompt)
        self.assertNotIn("State the reference ID", prompt)
        self.assertNotIn("prominent source conventions", prompt)

    def test_generation_receives_spec_not_rationale(self):
        proposal, _ = FakeTextProvider().propose("", schema_name="poster-proposal.schema.json")
        prompt = compile_generation_prompt(proposal)
        self.assertIn("Approved image specification", prompt)
        self.assertNotIn(proposal["design_rationale"], prompt)
        self.assertNotIn("GPT Image 2 authoring knowledge", prompt)
        self.assertIn(proposal["image_spec"]["composition"], prompt)

    def test_generation_receives_the_reference_relationship(self):
        proposal, _ = FakeTextProvider().propose("", schema_name="poster-proposal.schema.json")
        prompt = compile_generation_prompt(proposal, "style_inspired")
        self.assertIn("Approved reference relationship", prompt)
        self.assertIn("creative inspiration", prompt)
