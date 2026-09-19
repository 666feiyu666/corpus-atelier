"""Single-call design synthesis through an injected text provider."""

from .prompt_compiler import compile_design_prompt


def synthesize(profile, brief: dict, bundle: dict, provider) -> tuple[str, dict, dict]:
    prompt = compile_design_prompt(profile, brief, bundle)
    proposal, response = provider.propose(prompt, schema_name=profile.proposal_schema)
    return prompt, proposal, response
