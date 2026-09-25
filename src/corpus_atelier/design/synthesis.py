"""Single-call design synthesis, optionally with one visual reference."""

from pathlib import Path

from .prompt_compiler import compile_design_prompt


def synthesize(profile, brief: dict, provider,
               reference_paths: list[Path] | None = None,
               design_knowledge: dict | None = None,
               canvas: dict | None = None,
               direction_seed: dict | None = None,
               movement_knowledge: list[str] | None = None) -> tuple[str, dict, dict]:
    prompt = compile_design_prompt(
        profile, brief, canvas=canvas, design_knowledge=design_knowledge,
        direction_seed=direction_seed, movement_knowledge=movement_knowledge,
    )
    proposal, response = provider.propose(
        prompt,
        schema_name=profile.proposal_schema,
        reference_paths=reference_paths,
    )
    return prompt, proposal, response
