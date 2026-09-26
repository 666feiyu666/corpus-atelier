import unittest

from corpus_atelier.design_direction.validation import (
    validate_design_direction_plan,
)


def direction(label="Direction", *, axis="composition", movement=None):
    return {
        "label": label,
        "design_thesis": f"A complete thesis for {label}.",
        "objective_strategy": f"A complete objective strategy for {label}.",
        "direction_decisions": [{
            "axis": axis,
            "decision": f"A consequential {axis} decision for {label}.",
        }],
        "implementation_freedom": ["Resolve exact spacing."],
        "movement_references": list(movement or []),
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

    def test_unknown_movement_is_rejected(self):
        plan = {
            "planning_mode": "open",
            "directions": [direction(movement=["unknown-movement"])],
        }
        with self.assertRaisesRegex(ValueError, "Unknown historical references"):
            validate_design_direction_plan(
                plan, 3, objective="rhetoric-led.v1",
            )

    def test_art_objective_rejects_design_movement_reference(self):
        plan = {
            "planning_mode": "open",
            "directions": [direction(movement=["swiss-style"])],
        }
        with self.assertRaisesRegex(ValueError, "Unknown historical references"):
            validate_design_direction_plan(
                plan, 3, objective="art-led.v1",
            )

    def test_art_objective_accepts_art_movement_reference(self):
        plan = {
            "planning_mode": "open",
            "directions": [direction(movement=["impressionism"])],
        }
        self.assertIs(
            validate_design_direction_plan(
                plan, 3, objective="art-led.v1",
            ),
            plan,
        )


if __name__ == "__main__":
    unittest.main()
