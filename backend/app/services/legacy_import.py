"""One-time import of the pre-Qdrant SQLite metadata file.

Runs on startup only when the old file exists and Qdrant holds no repos yet.
Chunk vectors were always in Qdrant, so only metadata moves. The file is
renamed afterwards and never read again.
"""

import json
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from app.models import Job, Match, Record, Repo, Source
from app.services.meta_store import MetaStore

log = logging.getLogger("similarityly")


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _json(value: str | None) -> dict:
    return json.loads(value) if value else {}


def import_legacy_sqlite(path: Path, meta: MetaStore) -> bool:
    if not path.exists() or meta.count(Repo) > 0:
        return False
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:

        def rows(table: str) -> list[sqlite3.Row]:
            return conn.execute(f"SELECT * FROM {table}").fetchall()  # noqa: S608

        sources = [
            Source(
                id=r["id"],
                created_at=_dt(r["created_at"]),
                repo_id=r["repo_id"],
                name=r["name"],
                kind=r["kind"],
                record_count=r["record_count"],
                indexed=bool(r["indexed"]),
            )
            for r in rows("sources")
        ]
        indexed = {s.id: s.indexed for s in sources}
        match_rows = rows("matches")
        best: dict[str, tuple[float, str]] = {}
        for m in match_rows:
            if m["score"] > best.get(m["record_id"], (0.0, ""))[0]:
                best[m["record_id"]] = (m["score"], m["matched_text"])

        records = [
            Record(
                id=r["id"],
                repo_id=r["repo_id"],
                source_id=r["source_id"],
                ordinal=r["ordinal"],
                text=r["text"],
                meta=_json(r["meta"]),
                indexed=indexed.get(r["source_id"], False),
                chunk_count=r["chunk_count"],
                max_score=r["max_score"] or 0.0,
                match_count=r["match_count"],
                best_match_text=best.get(r["id"], (0.0, ""))[1],
            )
            for r in rows("records")
        ]
        owner = {r.id: r for r in records}

        meta.put_many(
            Repo(
                id=r["id"],
                created_at=_dt(r["created_at"]),
                name=r["name"],
                description=r["description"],
                config=_json(r["config"]),
                vector_size=r["vector_size"],
                needs_reindex=bool(r["needs_reindex"]),
            )
            for r in rows("repos")
        )
        meta.put_many(sources)
        meta.put_many(records)
        meta.put_many(
            Job(
                id=r["id"],
                created_at=_dt(r["created_at"]),
                repo_id=r["repo_id"],
                source_id=r["source_id"],
                kind=r["kind"],
                mode=r["mode"],
                status=r["status"],
                total=r["total"],
                processed=r["processed"],
                error=r["error"],
                finished_at=_dt(r["finished_at"]),
            )
            for r in rows("jobs")
        )
        meta.put_many(
            Match(
                id=m["id"],
                repo_id=owner[m["record_id"]].repo_id,
                source_id=owner[m["record_id"]].source_id,
                job_id=m["job_id"],
                record_id=m["record_id"],
                chunk_index=m["chunk_index"],
                chunk_text=m["chunk_text"],
                score=m["score"],
                matched_repo_id=m["matched_repo_id"],
                matched_source_id=m["matched_source_id"],
                matched_record_id=m["matched_record_id"],
                matched_chunk_index=m["matched_chunk_index"],
                matched_text=m["matched_text"],
            )
            for m in match_rows
            if m["record_id"] in owner
        )
    finally:
        conn.close()
    path.rename(path.with_suffix(".db.migrated"))
    log.info("imported legacy SQLite metadata into Qdrant: %d records", len(records))
    return True
