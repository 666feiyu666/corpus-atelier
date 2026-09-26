"""Single-call implementation of one approved design direction."""

from pathlib import Path

from .prompt_compiler import compile_design_implementation_prompt


def synthesize_design_implementation(
    profile, brief: dict, provider,
    reference_paths: list[Path] | None = None,
    canvas: dict | None = None,
    direction_seed: dict | None = None,
    historical_knowledge: list[str] | None = None,
) -> tuple[str, dict, dict]:
    if canvas is None or direction_seed is None:
        raise ValueError("Design implementation requires a canvas and approved direction seed.")
    prompt = compile_design_implementation_prompt(
        brief,
        canvas=canvas,
        direction_seed=direction_seed,
        historical_knowledge=historical_knowledge,
    )
    proposal, response = provider.propose(
        prompt,
        schema_name=profile.proposal_schema,
        reference_paths=reference_paths,
    )
    return prompt, proposal, response
