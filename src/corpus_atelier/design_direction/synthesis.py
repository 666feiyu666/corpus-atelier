"""Single-call objective-led direction design."""

from .prompt_compiler import compile_design_direction_prompt


def synthesize_design_directions(
    profile, brief: dict, provider, *, canvas: dict, candidate_limit: int,
    design_knowledge: dict | None = None,
) -> tuple[str, dict, dict]:
    prompt = compile_design_direction_prompt(
        profile,
        brief,
        canvas=canvas,
        candidate_limit=candidate_limit,
        design_knowledge=design_knowledge,
    )
    plan, response = provider.propose(
        prompt, schema_name="design-direction-plan.schema.json",
    )
    return prompt, plan, response
