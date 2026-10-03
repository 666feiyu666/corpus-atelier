"""Task content language, independent of interface and source languages."""

import json
import re


LANGUAGE_TAG_PATTERN = r"^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$"


def validate_content_language(language: str | None) -> str | None:
    if language is not None and (not isinstance(language, str)
                                 or not re.fullmatch(LANGUAGE_TAG_PATTERN, language)):
        raise ValueError("Content language must be a language tag such as zh-CN or en.")
    return language


def compile_language_policy(content_language: str | None, *,
                            source_request: str | None = None,
                            conversation: bool = False) -> str:
    """Keep generated prose consistent without translating authoritative sources."""
    validate_content_language(content_language)
    rules = (
        "# Task content language\n\n"
        "The task content language is independent of the interface language, the English prompt "
        "templates, and the language of source material. Write all newly authored natural-language "
        "values in the task content language, including summaries, brief descriptions, constraints, "
        "preferences, questions, reference findings, interpretations, direction labels, design "
        "descriptions, rationale, review criteria, and image-spec descriptions. English instructions "
        "or historical examples do not select English for the output. JSON keys, enum values, IDs, "
        "technical identifiers, proper names, and canonical terminology remain unchanged. Preserve "
        "exact_copy, visible_copy, user_requirements, suggested requirement sources, and original "
        "quotations verbatim in their source languages. These sources do not determine the task "
        "language. Label translations and paraphrases; never present them as original quotations. "
        "An article_title supplied as source wording must also remain verbatim.\n\n"
        "When content_language is null, determine a language tag (for example zh-CN or en) from "
        "the user's explicit preference for discussion/design explanations, otherwise from the "
        "initial substantive design request. Ignore quoted copy, reference excerpts, filenames, "
        "identifiers, and isolated technical terms when determining that language. A request for "
        "English lettering on a Chinese-language task does not select English explanations. "
        "For a structured brief without an initial request, use its descriptive prose, excluding "
        "source wording. Return the resolved tag in content_language when the output schema has "
        "that field.\n\n"
    )
    if conversation:
        rules += (
            "Once set, retain the task language across turns, including brief refreshes and feedback "
            "written in another language. Change it only when the latest discussion message "
            "explicitly requests a different language for discussion or design explanations. "
            "Return language_change_quote as the exact supporting substring of that message only "
            "when changing an established language; otherwise return null. Requirements updates "
            "and brief refresh operations never implicitly change the task language.\n\n"
        )
    else:
        rules += (
            "When a tag is supplied, use it exactly; do not infer a new language from downstream "
            "context. Preserve existing brief meaning while rephrasing authored descriptions into "
            "this language; preserving a field does not require preserving an old output language.\n\n"
        )
    return rules + json.dumps({
        "content_language": content_language,
        "initial_design_request": source_request,
    }, ensure_ascii=False, indent=2, allow_nan=False)


def bind_brief_language(brief: dict, content_language: str | None) -> dict:
    """Reject conflicting language metadata; accept legacy briefs without it."""
    returned = validate_content_language(brief.get("content_language"))
    if content_language is not None and returned not in (None, content_language):
        raise ValueError("The brief changed the task content language.")
    selected = content_language or returned
    return {**brief, "content_language": selected} if selected else brief
