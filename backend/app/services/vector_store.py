"""Chunk vectors on Qdrant. One collection per repo: `<prefix><repo_id>`."""

import threading
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from qdrant_client import QdrantClient
from qdrant_client import models as qm

from app.core.config import Settings
from app.services.qdrant_http import ResilientTransport, prefer_ipv4_loopback

_DISTANCE = {
    "cosine": qm.Distance.COSINE,
    "dot": qm.Distance.DOT,
    "euclid": qm.Distance.EUCLID,
}
_DISTANCE_NAME = {v: k for k, v in _DISTANCE.items()}

# Payload fields that are filtered on (source deletion, search scoping).
_PAYLOAD_INDEXES = ("source_id", "record_id")


def server_client(url: str, api_key: str | None, **kwargs: Any) -> QdrantClient:
    """A client for a Qdrant server URL, with the port the URL actually means.

    qdrant-client fills in 6333 when the URL has no port, so
    "https://qdrant.example.com" would silently go to :6333 instead of :443 and
    time out behind a reverse proxy. Use the scheme's standard port instead, as
    browsers and curl do. A trailing "/" is dropped; it would become a "//" prefix.
    """
    # Requests go through ResilientTransport (app/services/qdrant_http.py): no
    # Windows localhost IPv6 delay, and one fresh-connection retry for a hanging read.
    url = prefer_ipv4_loopback(url.strip().rstrip("/"))
    parts = urlsplit(url)
    port = parts.port or (443 if parts.scheme == "https" else 80)
    kwargs.setdefault("transport", ResilientTransport(parts.hostname or ""))
    return QdrantClient(url=url, port=port, api_key=api_key or None, **kwargs)


def connect(settings: Settings) -> tuple[QdrantClient, str]:
    """One client per process; embedded mode locks its directory."""
    if settings.qdrant_in_memory:
        return QdrantClient(":memory:"), "memory"
    if settings.qdrant_url:
        client = server_client(
            settings.qdrant_url, settings.qdrant_api_key, timeout=settings.qdrant_timeout
        )
        return client, "server"
    path = settings.data_dir / "qdrant"
    path.mkdir(parents=True, exist_ok=True)
    return QdrantClient(path=str(path)), "embedded"


def to_similarity(score: float, distance: str) -> float:
    """Map a raw Qdrant score to a 0..1 similarity (higher = more similar).

    Stored and query vectors are unit length (see `pipeline.unit_vectors`), so
    every metric lands on the cosine scale and thresholds mean the same thing.
    """
    if distance == "euclid":  # Qdrant returns a distance d; on unit vectors cos = 1 - d²/2
        score = 1.0 - score * score / 2.0
    return max(0.0, min(1.0, score))


class VectorConfigError(RuntimeError):
    """The collection on disk does not match what the repo config would produce."""


@dataclass
class ChunkPoint:
    source_id: str
    record_id: str
    chunk_index: int
    text: str
    vector: list[float]


@dataclass
class Hit:
    score: float  # raw Qdrant score
    source_id: str
    record_id: str
    chunk_index: int
    text: str
    id: str = ""  # Qdrant point id


def _hit(point, score: float = 0.0) -> Hit:
    return Hit(
        score=score,
        source_id=point.payload["source_id"],
        record_id=point.payload["record_id"],
        chunk_index=point.payload["chunk_index"],
        text=point.payload["text"],
        id=str(point.id),
    )


@dataclass
class CollectionInfo:
    points: int
    vector_size: int
    distance: str
    status: str  # green | yellow | red | grey
    indexed_fields: list[str]


class VectorStore:
    def __init__(self, client: QdrantClient, lock: threading.RLock, prefix: str, mode: str):
        self._client = client
        # Embedded Qdrant is not thread-safe; the lock is shared with MetaStore.
        self._lock = lock
        self._prefix = prefix
        self.mode = mode

    def _name(self, repo_id: str) -> str:
        return f"{self._prefix}{repo_id}"

    def ensure(self, repo_id: str, size: int, distance: str) -> None:
        """Create the collection, or verify an existing one is searchable with this config.

        A size or metric mismatch would make every query fail (or silently score
        on the wrong metric), so it is raised instead of ignored.
        """
        name = self._name(repo_id)
        with self._lock:
            if self._client.collection_exists(name):
                params = self._client.get_collection(name).config.params.vectors
                if params.size != size or params.distance != _DISTANCE[distance]:
                    raise VectorConfigError(
                        f"vector_config_mismatch: collection is {params.size}d/"
                        f"{_DISTANCE_NAME[params.distance]}, config needs {size}d/{distance}"
                    )
            else:
                self._client.create_collection(
                    name, vectors_config=qm.VectorParams(size=size, distance=_DISTANCE[distance])
                )
            self._ensure_indexes(name)

    def _ensure_indexes(self, name: str) -> None:
        if self.mode != "server":  # payload indexes are a no-op in embedded mode
            return
        existing = self._client.get_collection(name).payload_schema or {}
        for field in _PAYLOAD_INDEXES:
            if field not in existing:
                self._client.create_payload_index(
                    name, field_name=field, field_schema=qm.PayloadSchemaType.KEYWORD, wait=True
                )

    def info(self, repo_id: str) -> CollectionInfo | None:
        name = self._name(repo_id)
        with self._lock:
            if not self._client.collection_exists(name):
                return None
            info = self._client.get_collection(name)
            points = self._client.count(name, exact=True).count
        params = info.config.params.vectors
        return CollectionInfo(
            points=points,
            vector_size=params.size,
            distance=_DISTANCE_NAME[params.distance],
            status=str(getattr(info.status, "value", info.status)),
            indexed_fields=sorted((info.payload_schema or {}).keys()),
        )

    def drop(self, repo_id: str) -> None:
        with self._lock:
            self._client.delete_collection(self._name(repo_id))

    def count(self, repo_id: str) -> int:
        name = self._name(repo_id)
        with self._lock:
            if not self._client.collection_exists(name):
                return 0
            return self._client.count(name, exact=True).count

    def upsert(self, repo_id: str, points: list[ChunkPoint]) -> None:
        if not points:
            return
        structs = [
            qm.PointStruct(
                id=uuid.uuid4().hex,
                vector=p.vector,
                payload={
                    "source_id": p.source_id,
                    "record_id": p.record_id,
                    "chunk_index": p.chunk_index,
                    "text": p.text,
                },
            )
            for p in points
        ]
        with self._lock:
            self._client.upsert(self._name(repo_id), points=structs, wait=True)

    def search_batch(self, repo_id: str, vectors: list[list[float]], limit: int) -> list[list[Hit]]:
        if not vectors:
            return []
        requests = [qm.QueryRequest(query=v, limit=limit, with_payload=True) for v in vectors]
        with self._lock:
            responses = self._client.query_batch_points(self._name(repo_id), requests=requests)
        return [[_hit(p, p.score) for p in res.points] for res in responses]

    def chunks(self, repo_id: str, record_ids: list[str], start: int, stop: int) -> list[Hit]:
        """Stored chunks of these records with start <= chunk_index < stop.

        Unordered (callers sort); `score` is 0 because nothing was queried.
        """
        name = self._name(repo_id)
        if not record_ids or stop <= start:
            return []
        flt = qm.Filter(
            must=[
                qm.FieldCondition(key="record_id", match=qm.MatchAny(any=record_ids)),
                qm.FieldCondition(key="chunk_index", range=qm.Range(gte=start, lt=stop)),
            ]
        )
        out: list[Hit] = []
        offset = None
        with self._lock:
            if not self._client.collection_exists(name):
                return []
            while True:
                points, offset = self._client.scroll(
                    name,
                    scroll_filter=flt,
                    limit=256,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                out.extend(_hit(p) for p in points)
                if offset is None:
                    return out

    def find_text(
        self, repo_id: str, query: str, source_id: str | None, limit: int
    ) -> tuple[list[Hit], bool]:
        """Chunks whose text contains `query`, unordered, at most `limit`.

        The flag says more matched than were returned. A substring scan, not a
        vector search; Latin letters also match in their other common casings.
        """
        name = self._name(repo_id)
        variants = {query, query.lower(), query.upper(), query.title(), query.capitalize()}
        must: list = [
            qm.Filter(
                should=[
                    qm.FieldCondition(key="text", match=qm.MatchText(text=v))
                    for v in sorted(variants)
                ]
            )
        ]
        if source_id is not None:
            must.append(qm.FieldCondition(key="source_id", match=qm.MatchValue(value=source_id)))
        needle = query.casefold()
        out: list[Hit] = []
        offset = None
        with self._lock:
            if not self._client.collection_exists(name):
                return [], False
            while True:
                points, offset = self._client.scroll(
                    name,
                    scroll_filter=qm.Filter(must=must),
                    limit=256,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                # Embedded Qdrant matches word by word; keep whole-phrase hits only.
                out.extend(h for h in map(_hit, points) if needle in h.text.casefold())
                if len(out) > limit:
                    return out[:limit], True
                if offset is None:
                    return out, False

    def get_chunk(self, repo_id: str, chunk_id: str) -> Hit | None:
        name = self._name(repo_id)
        with self._lock:
            if not self._client.collection_exists(name):
                return None
            points = self._client.retrieve(name, ids=[chunk_id], with_payload=True)
        return _hit(points[0]) if points else None

    def add_chunk(
        self, repo_id: str, source_id: str, record_id: str, text: str, vector: list[float]
    ) -> Hit:
        """Append one chunk after the record's stored ones."""
        name = self._name(repo_id)
        of_record = qm.Filter(
            must=[qm.FieldCondition(key="record_id", match=qm.MatchValue(value=record_id))]
        )
        with self._lock:
            index = self._client.count(name, count_filter=of_record, exact=True).count
            chunk = Hit(0.0, source_id, record_id, index, text, id=str(uuid.uuid4()))
            self.update_chunk(repo_id, chunk, text, vector)
        return chunk

    def update_chunk(self, repo_id: str, chunk: Hit, text: str, vector: list[float]) -> None:
        """Replace one chunk's text and vector in place; its position is kept."""
        point = qm.PointStruct(
            id=chunk.id,
            vector=vector,
            payload={
                "source_id": chunk.source_id,
                "record_id": chunk.record_id,
                "chunk_index": chunk.chunk_index,
                "text": text,
            },
        )
        with self._lock:
            self._client.upsert(self._name(repo_id), points=[point], wait=True)

    def delete_chunk(self, repo_id: str, chunk: Hit) -> None:
        """Remove one chunk and close the gap, so the record's chunk_index
        values stay 0..n-1 and windowed reads keep working."""
        name = self._name(repo_id)
        later = [
            c
            for c in self.chunks(repo_id, [chunk.record_id], chunk.chunk_index + 1, 2**31)
            if c.id != chunk.id
        ]
        with self._lock:
            self._client.delete(name, points_selector=qm.PointIdsList(points=[chunk.id]), wait=True)
            if later:
                self._client.batch_update_points(
                    name,
                    update_operations=[
                        qm.SetPayloadOperation(
                            set_payload=qm.SetPayload(
                                payload={"chunk_index": c.chunk_index - 1}, points=[c.id]
                            )
                        )
                        for c in later
                    ],
                    wait=True,
                )

    def delete_source(self, repo_id: str, source_id: str) -> None:
        name = self._name(repo_id)
        with self._lock:
            if not self._client.collection_exists(name):
                return
            self._client.delete(
                name,
                points_selector=qm.FilterSelector(
                    filter=qm.Filter(
                        must=[
                            qm.FieldCondition(key="source_id", match=qm.MatchValue(value=source_id))
                        ]
                    )
                ),
                wait=True,
            )
