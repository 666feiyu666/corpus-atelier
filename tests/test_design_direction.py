import unittest

from corpus_atelier.atelier.design_direction.validation import (
    validate_design_direction_plan,
)


def direction(label="Direction", *, axis="composition",
              category="typography-and-posters"):
    return {
        "label": label,
        "asset_category": category,
        "style_anchors": ["editorial type-led composition"],
        "design_thesis": f"A complete thesis for {label}.",
        "objective_strategy": f"A complete objective strategy for {label}.",
        "direction_decisions": [{
            "axis": axis,
            "decision": f"A consequential {axis} decision for {label}.",
        }],
        "implementation_freedom": ["Resolve exact spacing."],
        "portfolio_role": f"The distinct role of {label}.",
    }


class DesignDirectionTests(unittest.TestCase):
    def test_convergent_plan_may_return_one_below_the_limit(self):
        plan = {
            "planning_mode": "convergent",
            "directions": [direction()],
        }
        self.assertIs(
            validate_design_direction_plan(
                plan, 3, objective="rhetoric-led.v1",
            ),
            plan,
        )

    def test_plan_cannot_exceed_candidate_limit(self):
        plan = {
            "planning_mode": "open",
            "directions": [direction("One"), direction("Two", axis="palette")],
        }
        with self.assertRaisesRegex(ValueError, "limit is 1"):
            validate_design_direction_plan(
                plan, 1, objective="rhetoric-led.v1",
            )

    def test_direction_cannot_repeat_a_decision_axis(self):
        item = direction()
        item["direction_decisions"].append({
            "axis": "composition",
            "decision": "A second composition decision.",
        })
        plan = {"planning_mode": "open", "directions": [item]}
        with self.assertRaisesRegex(ValueError, "repeat a decision axis"):
            validate_design_direction_plan(
                plan, 3, objective="rhetoric-led.v1",
            )

    def test_plan_cannot_change_the_brief_category(self):
        plan = {
            "planning_mode": "open",
            "directions": [direction(category="editorial-and-covers")],
        }
        with self.assertRaisesRegex(ValueError, "changed the brief's deliverable category"):
            validate_design_direction_plan(
                plan, 3, objective="rhetoric-led.v1",
                asset_category="typography-and-posters",
            )

    def test_directions_must_share_one_category(self):
        plan = {
            "planning_mode": "open",
            "directions": [direction("One"), direction("Two", category="editorial-and-covers")],
        }
        with self.assertRaisesRegex(ValueError, "share one deliverable category"):
            validate_design_direction_plan(plan, 3, objective="rhetoric-led.v1")

    def test_unknown_category_is_rejected(self):
        plan = {
            "planning_mode": "open",
            "directions": [direction(category="not-a-category")],
        }
        with self.assertRaisesRegex(
            ValueError, "not one of|Unknown deliverable category",
        ):
            validate_design_direction_plan(plan, 3, objective="rhetoric-led.v1")

if __name__ == "__main__":
    unittest.main()
