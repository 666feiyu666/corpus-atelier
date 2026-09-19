"""Select a small, diverse evidence bundle."""


def select(candidates: list[dict], *, per_kind: int = 3) -> list[dict]:
    selected = []
    counts: dict[str, int] = {}
    seen_titles = set()
    for row in candidates:
        kind = row["kind"]
        if counts.get(kind, 0) >= per_kind or row["title"].casefold() in seen_titles:
            continue
        selected.append(row)
        counts[kind] = counts.get(kind, 0) + 1
        seen_titles.add(row["title"].casefold())
    return selected
