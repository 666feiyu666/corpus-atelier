"""Compile a completed design proposal into an image-model specification."""

from .prompt_compiler import compile_image_spec_prompt


def synthesize_image_spec(
    proposal: dict, *, brief: dict, canvas: dict, provider_profile: str, provider,
    required_assets: list[dict] | None = None,
) -> tuple[str, dict, dict]:
    prompt = compile_image_spec_prompt(
        proposal, brief=brief, canvas=canvas, provider_profile=provider_profile,
        required_assets=required_assets,
    )
    image_spec, response = provider.propose(
        prompt, schema_name="image-spec.schema.json",
    )
    return prompt, image_spec, response
