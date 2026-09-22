"""Single-call design synthesis, optionally with one visual reference."""

from pathlib import Path

from .prompt_compiler import compile_design_prompt


def synthesize(profile, brief: dict, reference: dict | None, provider,
               reference_paths: list[Path] | None = None) -> tuple[str, dict, dict]:
    prompt = compile_design_prompt(profile, brief, reference)
    proposal, response = provider.propose(
        prompt,
        schema_name=profile.proposal_schema,
        reference_paths=reference_paths,
    )
    return prompt, proposal, response
