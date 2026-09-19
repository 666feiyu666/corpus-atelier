"""Transparent lexical ranking with an optional externally supplied embedding score."""


def rank(query: dict, candidates: list, embedding_scores: dict[str, float] | None = None) -> list[dict]:
    embedding_scores = embedding_scores or {}
    terms = set(query["terms"])
    ranked = []
    for candidate in candidates:
        haystack = f"{candidate.title} {candidate.text} {' '.join(candidate.tags)}".lower()
        matched = sorted(term for term in terms if term in haystack)
        lexical = len(matched) / max(len(terms), 1)
        embedding = float(embedding_scores.get(candidate.id, 0.0))
        score = lexical * 0.7 + embedding * 0.3
        row = candidate.serializable()
        row.update(score=score, lexical_score=lexical,
                   embedding_score=embedding, matched_terms=matched)
        ranked.append(row)
    return sorted(ranked, key=lambda row: (-row["score"], row["id"]))
