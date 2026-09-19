"""Load JSONL without treating corpus text as instructions."""

import json
from pathlib import Path

from .models import Candidate


def load_jsonl(path: Path, kind: str) -> list[Candidate]:
    rows = []
    if not path.exists():
        return rows
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        rows.append(Candidate(
            id=str(value["id"]), kind=kind, title=value["title"],
            text=value.get("text", ""), tags=tuple(value.get("tags", [])),
            metadata={key: item for key, item in value.items()
                      if key not in {"id", "title", "text", "tags"}},
        ))
    return rows
