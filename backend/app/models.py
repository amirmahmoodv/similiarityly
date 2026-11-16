"""Metadata entities. Each is stored as the payload of one point in a
payload-only Qdrant collection (see services/meta_store.py); chunk vectors live
in one vector collection per repo (services/vector_store.py).

`INDEXES` lists the payload fields that are filtered or ordered on. Qdrant can
only order by an indexed field and filters unindexed fields by full scan, so
every field used in a `where`/`order_by` must appear here.
"""

import uuid
from datetime import UTC, datetime
from typing import ClassVar

from pydantic import BaseModel, Field, model_validator


def new_id() -> str:
    return uuid.uuid4().hex


def now() -> datetime:
    return datetime.now(UTC)


class Entity(BaseModel):
    KIND: ClassVar[str]
    INDEXES: ClassVar[dict[str, str]] = {}

    id: str = Field(default_factory=new_id)
    created_at: datetime = Field(default_factory=now)
    # Epoch seconds mirror of created_at: a float index gives reliable ordering.
    created_ts: float = 0.0

    @model_validator(mode="after")
    def _fill_created_ts(self):
        if not self.created_ts:
            self.created_ts = self.created_at.timestamp()
        return self


class Repo(Entity):
    KIND = "repos"
    INDEXES = {"name": "keyword", "created_ts": "float"}

    name: str
    description: str = ""
    config: dict
    # Known once the first vector is written; None means "no collection yet".
    vector_size: int | None = None
    # Set when embedding/chunking/normalization changed after data was indexed.
    needs_reindex: bool = False


class Source(Entity):
    KIND = "sources"
    INDEXES = {"repo_id": "keyword", "created_ts": "float"}

    repo_id: str
    name: str
    kind: str  # excel | csv | document | list | paste
    record_count: int = 0
    # False for check-only loads: records are scored but never added to the repo.
    indexed: bool = False


class Record(Entity):
    KIND = "records"
    INDEXES = {
        "repo_id": "keyword",
        "source_id": "keyword",
        "indexed": "bool",
        "ordinal": "integer",
        "max_score": "float",
    }

    repo_id: str
    source_id: str
    ordinal: int
    text: str
    meta: dict = {}
    # Copy of the source's flag so "records in this repo" is a single filter.
    indexed: bool = False
    chunk_count: int = 0
    # Best similarity (0..1) against everything loaded before this record.
    # Always present: Qdrant's order_by skips points that lack the key.
    max_score: float = 0.0
    match_count: int = 0
    best_match_text: str = ""


class Job(Entity):
    KIND = "jobs"
    INDEXES = {
        "repo_id": "keyword",
        "source_id": "keyword",
        "status": "keyword",
        "created_ts": "float",
    }

    repo_id: str
    source_id: str | None = None
    kind: str  # ingest | reindex
    mode: str = "check_and_index"
    status: str = "queued"
    total: int = 0
    processed: int = 0
    error: str | None = None
    finished_at: datetime | None = None


class Match(Entity):
    KIND = "matches"
    INDEXES = {
        "repo_id": "keyword",
        "source_id": "keyword",
        "record_id": "keyword",
        "score": "float",
    }

    # The checked side (owner of the match).
    repo_id: str
    source_id: str
    job_id: str
    record_id: str
    chunk_index: int
    chunk_text: str
    score: float
    # First-stage (vector) score; set only when a second stage produced `score`.
    vector_score: float | None = None
    # The matched side is snapshotted so results survive later deletions.
    matched_repo_id: str
    matched_source_id: str
    matched_record_id: str
    matched_chunk_index: int
    matched_text: str


ENTITIES: list[type[Entity]] = [Repo, Source, Record, Job, Match]
