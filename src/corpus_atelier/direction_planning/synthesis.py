"""Single-call direction planning."""

from .prompt_compiler import compile_direction_prompt


def synthesize_directions(
    brief: dict, provider, *, canvas: dict, candidate_count: int,
    design_knowledge: dict | None = None,
) -> tuple[str, dict, dict]:
    prompt = compile_direction_prompt(
        brief,
        canvas=canvas,
        candidate_count=candidate_count,
        design_knowledge=design_knowledge,
    )
    plan, response = provider.propose(
        prompt, schema_name="direction-plan.schema.json",
    )
    return prompt, plan, response
