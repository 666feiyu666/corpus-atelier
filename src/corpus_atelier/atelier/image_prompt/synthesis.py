"""Write one image-model prompt from an approved design."""

from pathlib import Path

from .prompt_compiler import compile_image_prompt_prompt


def synthesize_image_prompt(
    *, brief: dict, canvas: dict, provider_profile: str, provider,
    model_family: str = "gpt-image-2",
    design: dict | None = None,
    operation: str = "generation",
    reference_paths: list[Path] | None = None,
    corpus_references: list[dict] | None = None,
    content_language: str | None = None,
) -> tuple[str, dict, dict]:
    prompt = compile_image_prompt_prompt(
        brief=brief,
        canvas=canvas,
        provider_profile=provider_profile,
        model_family=model_family,
        design=design,
        operation=operation,
        reference_notes=[
            f"Reference image {index}: {Path(path).name}"
            for index, path in enumerate(reference_paths or [], start=1)
        ],
        corpus_references=corpus_references,
        content_language=content_language,
    )
    image_prompt, response = provider.propose(
        prompt,
        schema_name="image-prompt.schema.json",
        reference_paths=list(reference_paths or []) or None,
    )
    return prompt, image_prompt, response
