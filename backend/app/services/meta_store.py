"""Metadata persistence on Qdrant.

One payload-only collection per entity kind (`<prefix>meta_<kind>`, created
with an empty vectors config). Points are addressed by the entity id; filters
and ordering run on payload indexes declared on each entity class.
"""

import json
import logging
import threading
from collections.abc import Iterable
from typing import Any, TypeVar

from qdrant_client import QdrantClient
from qdrant_client import models as qm
from qdrant_client.http.exceptions import UnexpectedResponse

from app.models import ENTITIES, Entity
from app.services.qdrant_http import StorageIntegrityError, batched, storage_error_code

log = logging.getLogger("similarityly")

E = TypeVar("E", bound=Entity)

_SCHEMA = {
    "keyword": qm.PayloadSchemaType.KEYWORD,
    "float": qm.PayloadSchemaType.FLOAT,
    "integer": qm.PayloadSchemaType.INTEGER,
    "bool": qm.PayloadSchemaType.BOOL,
}
_BATCH = 256
# Records can hold whole documents; a rebuild moves them a few at a time.
_COPY_PAGE = 32
_REBUILD_SUFFIX = "_rebuild"

# Reads one small field: Qdrant still has to decode the whole stored payload,
# so a damaged one fails, but almost nothing travels back.
_ID_ONLY = qm.PayloadSelectorInclude(include=["id"])

Where = dict[str, Any]
Ranges = dict[str, dict[str, float]]


def build_filter(where: Where | None = None, ranges: Ranges | None = None) -> qm.Filter | None:
    """`where`: equality (a list value means "any of").
    `ranges`: {"field": {"gte": 0.5, "lt": 1}}."""
    must: list[qm.FieldCondition] = []
    for key, value in (where or {}).items():
        match = qm.MatchAny(any=value) if isinstance(value, list) else qm.MatchValue(value=value)
        must.append(qm.FieldCondition(key=key, match=match))
    for key, bounds in (ranges or {}).items():
        must.append(qm.FieldCondition(key=key, range=qm.Range(**bounds)))
    return qm.Filter(must=must) if must else None


def _payload_bytes(point: qm.PointStruct) -> int:
    return len(json.dumps(point.payload, ensure_ascii=False).encode()) + 64


def _corrupt(exc: Exception) -> bool:
    return storage_error_code(exc) == "storage_corrupt"


class MetaStore:
    def __init__(self, client: QdrantClient, lock: threading.RLock, prefix: str, mode: str):
        self._client = client
        self._lock = lock
        self._prefix = f"{prefix}meta_"
        self._server = mode == "server"
        for entity in ENTITIES:
            self._ensure(entity)
            self._finish_rebuild(entity)

    def _name(self, entity: type[Entity]) -> str:
        return self._prefix + entity.KIND

    def _ensure(self, entity: type[Entity]) -> None:
        """Create the collection and any missing payload index (idempotent)."""
        name = self._name(entity)
        log.info("qdrant setup: checking %s", name)
        with self._lock:
            if not self._client.collection_exists(name):
                self._client.create_collection(name, vectors_config={})
            if not self._server:  # embedded Qdrant filters/orders without indexes
                return
            existing = self._client.get_collection(name).payload_schema or {}
            for field, schema in entity.INDEXES.items():
                if field not in existing:
                    self._client.create_payload_index(
                        name, field_name=field, field_schema=_SCHEMA[schema], wait=True
                    )

    # ---- writes ------------------------------------------------------------

    def put(self, obj: Entity) -> None:
        self.put_many([obj])

    def put_many(self, objs: Iterable[Entity]) -> None:
        objs = list(objs)
        if not objs:
            return
        name = self._name(type(objs[0]))
        points = [
            qm.PointStruct(id=o.id, vector={}, payload=o.model_dump(mode="json")) for o in objs
        ]
        # Batched by size as well as count: one record can hold a whole document.
        for batch in batched(points, _payload_bytes, _BATCH):
            with self._lock:
                self._client.upsert(name, points=batch, wait=True)
            self._verify(name, [p.id for p in batch])

    def _verify(self, name: str, ids: list[str]) -> None:
        """Read back what was just written, so a write Qdrant acknowledged but
        cannot decode fails here, at the load, not on a later page view."""
        if not self._server:
            return
        with self._lock:
            found = self._client.retrieve(name, ids=ids, with_payload=_ID_ONLY, with_vectors=False)
        if len(found) != len(ids):
            raise StorageIntegrityError(
                f"{name}: wrote {len(ids)} points, only {len(found)} can be read back"
            )

    def patch(self, entity: type[E], id: str, **fields: Any) -> None:
        with self._lock:
            self._client.set_payload(self._name(entity), payload=fields, points=[id], wait=True)

    def delete(self, entity: type[Entity], where: Where) -> None:
        self._refuse_damaged(entity, where)
        with self._lock:
            self._client.delete(
                self._name(entity),
                points_selector=qm.FilterSelector(filter=build_filter(where)),
                wait=True,
            )

    def delete_id(self, entity: type[Entity], id: str) -> None:
        self.delete_ids(entity, [id])

    def delete_ids(self, entity: type[Entity], ids: list[str]) -> None:
        for i in range(0, len(ids), _BATCH):
            with self._lock:
                self._client.delete(
                    self._name(entity),
                    points_selector=qm.PointIdsList(points=ids[i : i + _BATCH]),
                    wait=True,
                )

    # ---- damaged data --------------------------------------------------------

    def _refuse_damaged(self, entity: type[Entity], where: Where) -> None:
        """Stop a delete that would touch a point Qdrant cannot decode.

        Qdrant reads a point's old payload to delete it. When that fails, the
        delete fails, and the collection then refuses every later write with
        "Not recovered from previous error". Only `rebuild` gets rid of such
        points safely.
        """
        if not self._server:
            return
        bad = self.unreadable(entity, where)
        if bad:
            raise StorageIntegrityError(
                f"{self._name(entity)}: {len(bad)} points cannot be decoded by Qdrant; "
                "repair the repository before deleting them"
            )

    def rebuild(self, entity: type[Entity]) -> list[str]:
        """Recreate the collection from the points that still decode.

        Returns the point ids left behind. Damaged points cannot be deleted
        (see `_refuse_damaged`), so the readable ones are copied to a side
        collection, the damaged collection is dropped and created again, and
        the copy is moved back. Dropping a collection decodes nothing, and it
        also clears a collection that already refuses writes.

        The lock is held throughout, so nothing else writes in between. If
        the process dies halfway, the next start finishes the move back.
        """
        name = self._name(entity)
        side = name + _REBUILD_SUFFIX
        with self._lock:
            self._finish_rebuild(entity)  # a leftover from an interrupted run
            self._client.create_collection(side, vectors_config={})
            copied, bad = self._copy(name, side)
            kept = self._client.count(side, exact=True).count
            if kept != copied:
                # The original is untouched; the next run starts over.
                raise StorageIntegrityError(
                    f"{side}: copied {copied} points, {kept} are stored; nothing was removed"
                )
            log.warning("%s: rebuilding without %d undecodable points: %s", name, len(bad), bad)
            self._move_back(entity)
        return bad

    def _finish_rebuild(self, entity: type[Entity]) -> None:
        """Deal with the side collection an interrupted rebuild left behind."""
        name = self._name(entity)
        side = name + _REBUILD_SUFFIX
        with self._lock:
            if not self._client.collection_exists(side):
                return
            kept = self._client.count(side, exact=True).count
            # The side copy never holds more than the original it was read
            # from. Fewer points in the collection therefore means the original
            # is already gone and the move back did not finish.
            if self._client.count(name, exact=True).count < kept:
                log.warning("%s: finishing an interrupted rebuild (%d points)", name, kept)
                self._move_back(entity)
            else:
                self._client.delete_collection(side)

    def _move_back(self, entity: type[Entity]) -> None:
        name = self._name(entity)
        side = name + _REBUILD_SUFFIX
        self._client.delete_collection(name)
        self._ensure(entity)
        copied, bad = self._copy(side, name)
        if bad or self._client.count(name, exact=True).count != copied:
            # The side collection still holds everything; it is kept.
            raise StorageIntegrityError(f"{name}: the rebuilt collection is incomplete")
        self._client.delete_collection(side)

    def _copy(self, src: str, dst: str) -> tuple[int, list[str]]:
        """Copy every decodable point; returns (copied, ids that do not decode)."""
        copied = 0
        bad: list[str] = []
        offset = None
        while True:
            points, offset = self._client.scroll(
                src, limit=_COPY_PAGE, offset=offset, with_payload=False, with_vectors=False
            )
            good, damaged = self._read(src, [p.id for p in points], True)
            bad.extend(damaged)
            structs = [qm.PointStruct(id=p.id, vector={}, payload=p.payload or {}) for p in good]
            for batch in batched(structs, _payload_bytes, _BATCH):
                self._client.upsert(dst, points=batch, wait=True)
                self._verify(dst, [p.id for p in batch])
            copied += len(good)
            if offset is None:
                return copied, bad

    # ---- reads -------------------------------------------------------------

    def get(self, entity: type[E], id: str | None) -> E | None:
        if not id:
            return None
        try:
            with self._lock:
                points = self._client.retrieve(self._name(entity), ids=[id], with_payload=True)
        except (ValueError, UnexpectedResponse) as exc:
            # A malformed id from a URL (rejected by the server with a 4xx, or
            # by the embedded client): treat as "not found". Anything else, a
            # timeout above all, is raised: answering 404 for an entity that
            # exists would be wrong, and the UI would drop it.
            if isinstance(exc, UnexpectedResponse) and exc.status_code not in (400, 404, 422):
                raise
            return None
        return entity.model_validate(points[0].payload) if points else None

    def get_many(self, entity: type[E], ids: list[str]) -> dict[str, E]:
        """Look up by point id in one request; missing ids are left out."""
        unique = list(dict.fromkeys(i for i in ids if i))
        if not unique:
            return {}
        with self._lock:
            points = self._client.retrieve(self._name(entity), ids=unique, with_payload=True)
        found = (entity.model_validate(p.payload) for p in points)
        return {e.id: e for e in found}

    def find(
        self,
        entity: type[E],
        where: Where | None = None,
        ranges: Ranges | None = None,
        *,
        order_by: str,
        desc: bool = False,
        limit: int = 50,
        offset: int = 0,
        skipped: list[str] | None = None,
    ) -> list[E]:
        """One ordered page. `order_by` must be listed in the entity's INDEXES.

        With `skipped`, points whose stored payload Qdrant cannot decode are
        left out and their point ids appended to it, so one damaged record
        does not take the whole page down. Without it, the error is raised.
        """
        name = self._name(entity)
        direction = qm.Direction.DESC if desc else qm.Direction.ASC
        page: dict[str, Any] = {
            "query": qm.OrderByQuery(order_by=qm.OrderBy(key=order_by, direction=direction)),
            "query_filter": build_filter(where, ranges),
            "limit": limit,
            "offset": offset,
        }
        try:
            with self._lock:
                res = self._client.query_points(name, with_payload=True, **page)
            return [entity.model_validate(p.payload) for p in res.points]
        except UnexpectedResponse as exc:
            if skipped is None or not _corrupt(exc):
                raise
        # The page's ids come from the indexes alone; then payload by payload.
        with self._lock:
            res = self._client.query_points(name, with_payload=False, **page)
        points, bad = self._read(name, [p.id for p in res.points], True)
        if bad:
            log.error("%s: %d points cannot be decoded by Qdrant: %s", name, len(bad), bad)
            skipped.extend(bad)
        return [entity.model_validate(p.payload) for p in points]

    def _read(self, name: str, ids: list, payload: Any) -> tuple[list, list[str]]:
        """Points of `ids`, in that order, and the ids Qdrant cannot decode.

        A failed batch is halved until the damaged points stand alone. Only a
        decode failure counts as damaged; any other error is raised, so an
        outage is never mistaken for lost data.
        """
        if not ids:
            return [], []
        try:
            with self._lock:
                points = self._client.retrieve(
                    name, ids=ids, with_payload=payload, with_vectors=False
                )
        except UnexpectedResponse as exc:
            if not _corrupt(exc):
                raise
            if len(ids) == 1:
                return [], [str(ids[0])]
            mid = len(ids) // 2
            left, bad_left = self._read(name, ids[:mid], payload)
            right, bad_right = self._read(name, ids[mid:], payload)
            return left + right, bad_left + bad_right
        by_id = {str(p.id): p for p in points}
        return [by_id[str(i)] for i in ids if str(i) in by_id], []

    def unreadable(self, entity: type[Entity], where: Where | None = None) -> list[str]:
        """Point ids of every match whose stored payload Qdrant cannot decode."""
        name = self._name(entity)
        flt = build_filter(where)
        bad: list[str] = []
        offset = None
        while True:
            with self._lock:
                points, offset = self._client.scroll(
                    name,
                    scroll_filter=flt,
                    limit=_BATCH,
                    offset=offset,
                    with_payload=False,
                    with_vectors=False,
                )
            bad.extend(self._read(name, [p.id for p in points], _ID_ONLY)[1])
            if offset is None:
                return bad

    def all(self, entity: type[E], where: Where | None = None) -> list[E]:
        """Every match, unordered (callers sort). Scrolls in pages."""
        out: list[E] = []
        offset = None
        flt = build_filter(where)
        while True:
            with self._lock:
                points, offset = self._client.scroll(
                    self._name(entity),
                    scroll_filter=flt,
                    limit=_BATCH,
                    offset=offset,
                    with_payload=True,
                )
            out.extend(entity.model_validate(p.payload) for p in points)
            if offset is None:
                return out

    def count(
        self, entity: type[Entity], where: Where | None = None, ranges: Ranges | None = None
    ) -> int:
        with self._lock:
            return self._client.count(
                self._name(entity), count_filter=build_filter(where, ranges), exact=True
            ).count
