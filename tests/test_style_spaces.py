"""Structure contracts for the design-direction style spaces."""

import unittest

from corpus_atelier.atelier.design_direction.validation import (
    CATEGORY_REFERENCES,
    load_style_space_body,
    load_style_space_index_body,
    style_space_reference,
)
from corpus_atelier.config.skill_loader import load_skill_reference


GENERAL_DIMENSIONS = (
    "## 1. Medium and rendering logic",
    "## 2. Composition and hierarchy",
    "## 3. Palette and contrast",
    "## 4. Type and copy placement",
    "## 5. Material, light, and surface",
    "## 6. Density, rhythm, and address",
)
INDEX_SECTIONS = (
    "## Choose by dimension, not by family",
    "## One primary language, at most two supporting techniques",
    "## Resolve conflicts explicitly",
    "## Emit the choice as decisions",
    "## Differentiate the portfolio on these dimensions",
    "## When a style name is legitimate",
    "## Division of labour",
)
RETIRED_FAMILY_LABELS = (
    "classical and idealized",
    "observational and realist",
    "sublime and romantic",
    "atmospheric and impressionistic",
    "constructed and decorative",
    "abstract geometric",
    "collage, assemblage, and mixed media",
    "typographic and systematic",
    "documentary and editorial",
    "diagrammatic and instructional",
    "emblematic and symbolic",
    "agitational and declarative",
    "experimental and disruptive",
)


def _space_text(objective: str) -> str:
    return load_skill_reference("design-direction", style_space_reference(objective))


class StyleSpaceStructureTests(unittest.TestCase):
    def test_index_states_the_shared_selection_rules(self):
        body = load_style_space_index_body()
        for section in INDEX_SECTIONS:
            self.assertIn(section, body)

    def test_general_space_is_organized_as_observable_dimensions(self):
        body = load_style_space_body("general-design.v1")
        for dimension in GENERAL_DIMENSIONS:
            self.assertIn(dimension, body)
        self.assertIn("## Reading the dimensions as a whole", body)
        # The retired doctrines are gone rather than renamed.
        self.assertNotIn("Sign carrier and warrant", body)
        self.assertNotIn("Art-led", body)
        self.assertNotIn("Rhetoric-led", body)

    def test_spaces_no_longer_ship_a_family_catalog(self):
        body = _space_text("general-design.v1").casefold()
        for label in RETIRED_FAMILY_LABELS:
            self.assertNotIn(label, body, f"the general space still lists {label!r}")

    def test_spaces_map_choices_onto_the_schema_axes(self):
        body = load_style_space_index_body()
        for axis in ("visual_language", "image_making", "palette", "composition", "typography"):
            self.assertIn(f"`{axis}`", body)

    def test_space_bodies_drop_their_leading_heading(self):
        for body in (load_style_space_index_body(), load_style_space_body("general-design.v1")):
            self.assertFalse(body.startswith("# "))

    def test_unknown_objective_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "style space"):
            load_style_space_body("no-such-objective.v1")


class CategoryStyleDelegationTests(unittest.TestCase):
    def test_every_category_guide_delegates_style_to_the_space(self):
        for category in CATEGORY_REFERENCES:
            body = load_skill_reference(
                "design-direction", CATEGORY_REFERENCES[category],
            )
            self.assertIn("## Style vocabulary", body)
            self.assertIn("observable dimensions of the style space", body)
            self.assertNotIn("Optional style vocabulary", body)


if __name__ == "__main__":
    unittest.main()
