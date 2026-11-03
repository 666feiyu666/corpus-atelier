"""Local-first SQLite corpus store with FTS5 retrieval.

No vector database and no API key: retrieval is SQLite FTS5 over the prompt,
negative prompt, closed labels (id + bilingual labels) and translations.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from threading import Lock

from .records import normalize_record
from .taxonomy import resolve


def _searchable_text(record: dict) -> str:
    """Flatten a record into the text FTS indexes."""
    parts = [record["prompt"]]
    negative = record.get("negative_prompt")
    if negative:
        parts.append(negative)
    for tag_id in record["tags"]:
        tag = resolve(tag_id)
        parts.extend([tag.id, tag.en, tag.zh])
    translation = (record.get("translations") or {}).get("zh")
    if translation:
        parts.append(translation)
    return "\n".join(parts)


def _fts_terms(text: str, *, match_any: bool = False) -> str | None:
    """Turn free text into a safe FTS5 MATCH expression.

    Each whitespace token is quoted as a phrase so FTS operators inside it are
    inert. Terms are AND-ed by default; ``match_any`` OR-s them instead, keeping
    only tokens long enough to carry meaning, which loosens an over-specific query
    instead of returning nothing.
    """
    terms = [t for t in re.split(r"\s+", text.strip()) if t]
    if match_any:
        terms = [t for t in terms if len(t) >= 3]
    if not terms:
        return None
    joiner = " OR " if match_any else " "
    return joiner.join('"%s"' % t.replace('"', '""') for t in terms)


class CorpusStore:
    """A durable, thread-safe corpus archive with keyword and label search."""

    def __init__(self, db_path: Path | str):
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._lock = Lock()
        self._create_schema()

    def _create_schema(self) -> None:
        with self._lock, self.conn:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS records (
                    id TEXT PRIMARY KEY,
                    record TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS record_tags (
                    record_id TEXT NOT NULL,
                    tag TEXT NOT NULL,
                    PRIMARY KEY (record_id, tag)
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS records_fts USING fts5(
                    record_id UNINDEXED,
                    body
                );
                """
            )

    def add(self, record: dict) -> dict:
        """Insert or replace one record; its labels and FTS row stay in sync."""
        record = normalize_record(record)
        body = _searchable_text(record)
        with self._lock, self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO records (id, record, created_at) VALUES (?, ?, ?)",
                (record["id"], json.dumps(record, ensure_ascii=False), record["created_at"]),
            )
            self.conn.execute("DELETE FROM record_tags WHERE record_id = ?", (record["id"],))
            self.conn.executemany(
                "INSERT INTO record_tags (record_id, tag) VALUES (?, ?)",
                [(record["id"], tag) for tag in record["tags"]],
            )
            # FTS5 has no rowid-keyed upsert for UNINDEXED columns, so replace explicitly.
            self.conn.execute("DELETE FROM records_fts WHERE record_id = ?", (record["id"],))
            self.conn.execute(
                "INSERT INTO records_fts (record_id, body) VALUES (?, ?)",
                (record["id"], body),
            )
        return record

    def get(self, record_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT record FROM records WHERE id = ?", (record_id,)
        ).fetchone()
        return json.loads(row["record"]) if row else None

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) AS c FROM records").fetchone()["c"]

    def search(
        self,
        query: str | None = None,
        *,
        tags: list[str] | None = None,
        limit: int = 20,
        match_any: bool = False,
    ) -> list[dict]:
        """Keyword search (AND-ed terms) with optional AND-ed label filter.

        ``match_any`` OR-s the query terms instead, for loosening an over-specific
        query rather than returning nothing.
        """
        tags = list(tags or [])
        clauses: list[str] = []
        params: list[object] = []
        matched = False
        if query and query.strip():
            terms = _fts_terms(query, match_any=match_any)
            if terms:
                matched = True
                clauses.append("records_fts MATCH ?")
                params.append(terms)
        if tags:
            placeholders = ",".join("?" for _ in tags)
            clauses.append(
                f"r.id IN (SELECT record_id FROM record_tags WHERE tag IN ({placeholders}) "
                "GROUP BY record_id HAVING COUNT(DISTINCT tag) = ?)"
            )
            params.extend(tags)
            params.append(len(tags))
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        order = "bm25(records_fts), r.created_at DESC" if matched else "r.created_at DESC"
        sql = (
            "SELECT r.record FROM records r "
            "JOIN records_fts f ON f.record_id = r.id"
            f"{where} ORDER BY {order} LIMIT ?"
        )
        params.append(int(limit))
        rows = self.conn.execute(sql, params).fetchall()
        return [json.loads(row["record"]) for row in rows]

    def reference_slice(
        self, query: str | None, *, limit: int = 3, tags: list[str] | None = None,
    ) -> list[dict]:
        """Return compact archived prompts for advisory use by the atelier.

        Retrieval is best-effort: an empty corpus or an unusable query yields an
        empty slice instead of an error. A label filter alone is enough, which is
        how a brief with only a deliverable category still finds comparable work.
        """
        tags = list(tags or [])
        if (not query or not query.strip()) and not tags:
            return []
        try:
            records = self.search(query, tags=tags, limit=limit)
            if not records and query:
                # A long brief tailors the query too tightly for an AND match.
                records = self.search(query, tags=tags, limit=limit, match_any=True)
        except Exception:
            return []
        return [
            {
                "id": record["id"],
                "prompt": record["prompt"],
                "tags": list(record.get("tags", [])),
                "source_run_id": (record.get("source") or {}).get("run_id"),
                "note": (record.get("source") or {}).get("note"),
                "url": (record.get("source") or {}).get("url"),
                "image": (record.get("image") or {}).get("path"),
            }
            for record in records
        ]

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "CorpusStore":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
