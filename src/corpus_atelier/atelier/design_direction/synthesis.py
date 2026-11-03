"""Single-call objective-led direction design."""

from pathlib import Path

from .prompt_compiler import compile_design_direction_prompt


def synthesize_design_directions(
    profile, brief: dict, provider, *, canvas: dict, candidate_limit: int,
    content_language: str | None = None,
    corpus_references: list[dict] | None = None,
    reference_paths: list[Path] | None = None,
) -> tuple[str, dict, dict]:
    """Write the direction request and ask the model for a bounded portfolio.

    ``corpus_references`` are archived cases offered as textual evidence;
    ``reference_paths`` are their images, attached in the same order so the model
    can look at how comparable work is actually made.
    """
    reference_paths = list(reference_paths or [])
    prompt = compile_design_direction_prompt(
        profile,
        brief,
        canvas=canvas,
        candidate_limit=candidate_limit,
        content_language=content_language,
        corpus_references=corpus_references,
        reference_image_names=[Path(path).name for path in reference_paths],
    )
    plan, response = provider.propose(
        prompt,
        schema_name="design-direction-plan.schema.json",
        reference_paths=reference_paths or None,
    )
    return prompt, plan, response
