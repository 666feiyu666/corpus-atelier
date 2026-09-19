"""Create a deterministic query from the user brief."""

import re


def build_query(brief: dict, profile: str) -> dict:
    text = " ".join(_flatten(brief))
    terms = []
    for term in re.findall(r"[\w\-]+", text.lower(), flags=re.UNICODE):
        if len(term) > 1 and term not in terms:
            terms.append(term)
    return {"profile": profile, "text": text, "terms": terms}


def _flatten(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _flatten(item)
    elif isinstance(value, list):
        for item in value:
            yield from _flatten(item)
