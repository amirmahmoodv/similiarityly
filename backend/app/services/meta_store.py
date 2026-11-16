"""Metadata persistence on Qdrant.

One payload-only collection per entity kind (`<prefix>meta_<kind>`, created
with an empty vectors config). Points are addressed by the entity id; filters
and ordering run on payload indexes declared on each entity class.
"""

import threading
from collections.abc import Iterable
from typing import Any, TypeVar

from qdrant_client import QdrantClient
from qdrant_client import models as qm

from app.models import ENTITIES, Entity

E = TypeVar("E", bound=Entity)

_SCHEMA = {
    "keyword": qm.PayloadSchemaType.KEYWORD,
    "float": qm.PayloadSchemaType.FLOAT,
    "integer": qm.PayloadSchemaType.INTEGER,
    "bool": qm.PayloadSchemaType.BOOL,
}
_BATCH = 256

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


class MetaStore:
    def __init__(self, client: QdrantClient, lock: threading.RLock, prefix: str, mode: str):
        self._client = client
        self._lock = lock
        self._prefix = f"{prefix}meta_"
        self._server = mode == "server"
        for entity in ENTITIES:
            self._ensure(entity)

    def _name(self, entity: type[Entity]) -> str:
        return self._prefix + entity.KIND

    def _ensure(self, entity: type[Entity]) -> None:
        """Create the collection and any missing payload index (idempotent)."""
        name = self._name(entity)
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
        for i in range(0, len(objs), _BATCH):
            points = [
                qm.PointStruct(id=o.id, vector={}, payload=o.model_dump(mode="json"))
                for o in objs[i : i + _BATCH]
            ]
            with self._lock:
                self._client.upsert(name, points=points, wait=True)

    def patch(self, entity: type[E], id: str, **fields: Any) -> None:
        with self._lock:
            self._client.set_payload(self._name(entity), payload=fields, points=[id], wait=True)

    def delete(self, entity: type[Entity], where: Where) -> None:
        with self._lock:
            self._client.delete(
                self._name(entity),
                points_selector=qm.FilterSelector(filter=build_filter(where)),
                wait=True,
            )

    def delete_id(self, entity: type[Entity], id: str) -> None:
        with self._lock:
            self._client.delete(
                self._name(entity), points_selector=qm.PointIdsList(points=[id]), wait=True
            )

    # ---- reads -------------------------------------------------------------

    def get(self, entity: type[E], id: str | None) -> E | None:
        if not id:
            return None
        try:
            with self._lock:
                points = self._client.retrieve(self._name(entity), ids=[id], with_payload=True)
        except Exception:  # malformed id from a URL: treat as "not found"
            return None
        return entity.model_validate(points[0].payload) if points else None

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
    ) -> list[E]:
        """One ordered page. `order_by` must be listed in the entity's INDEXES."""
        direction = qm.Direction.DESC if desc else qm.Direction.ASC
        with self._lock:
            res = self._client.query_points(
                self._name(entity),
                query=qm.OrderByQuery(order_by=qm.OrderBy(key=order_by, direction=direction)),
                query_filter=build_filter(where, ranges),
                limit=limit,
                offset=offset,
                with_payload=True,
            )
        return [entity.model_validate(p.payload) for p in res.points]

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
