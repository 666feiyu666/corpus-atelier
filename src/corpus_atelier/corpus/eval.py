"""Small labeled retrieval regression benchmark.

Kept small and deterministic: a fixed seed corpus plus labeled queries whose
expected top hits are asserted, so retrieval changes cannot silently regress.
"""

from __future__ import annotations

from dataclasses import dataclass

from .index import CorpusStore
from .records import new_record


@dataclass(frozen=True)
class QueryCase:
    query: str
    tags: tuple[str, ...]
    expected: tuple[str, ...]  # expected top-N record ids, in order


_SEED = (
    ("c-poster", "A vintage city travel poster with a skyline",
     ["poster", "warm", "swiss-style"], "2026-01-01T00:00:01+00:00"),
    ("c-album", "A muted album cover for a jazz record",
     ["album-cover", "cool", "monochrome"], "2026-01-01T00:00:02+00:00"),
    ("c-card", "A flat vector social card for a product launch",
     ["social-card", "flat-vector", "vibrant"], "2026-01-01T00:00:03+00:00"),
    ("c-book", "A dark book cover with surrealist imagery",
     ["book-cover", "dark", "surrealism"], "2026-01-01T00:00:04+00:00"),
)


def seed_corpus(store: CorpusStore) -> None:
    """Load the deterministic benchmark corpus."""
    for record_id, prompt, tags, created_at in _SEED:
        store.add(new_record(
            prompt=prompt,
            tags=tags,
            source_kind="manual",
            record_id=record_id,
            created_at=created_at,
        ))


CASES: tuple[QueryCase, ...] = (
    QueryCase("vintage city travel poster", (), ("c-poster",)),
    QueryCase("jazz album", (), ("c-album",)),
    QueryCase("瑞士风格", (), ("c-poster",)),
    QueryCase("surrealist", (), ("c-book",)),
    QueryCase("", ("poster",), ("c-poster",)),
    QueryCase("cover", ("monochrome",), ("c-album",)),
    QueryCase("flat vector", ("social-card",), ("c-card",)),
)


def run_eval(store: CorpusStore, *, seed: bool = True) -> dict:
    """Run the benchmark; return per-case detail plus a pass/fail summary."""
    if seed:
        seed_corpus(store)
    results = []
    for case in CASES:
        hits = store.search(
            case.query or None,
            tags=list(case.tags),
            limit=len(case.expected),
        )
        got = tuple(hit["id"] for hit in hits)
        results.append({
            "query": case.query,
            "tags": list(case.tags),
            "expected": list(case.expected),
            "got": list(got),
            "ok": got == case.expected,
        })
    passed = sum(1 for result in results if result["ok"])
    return {"total": len(results), "passed": passed, "results": results}
