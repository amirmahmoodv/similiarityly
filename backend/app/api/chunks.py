import uuid

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.repos import get_repo
from app.core.state import Services, get_services
from app.models import Record, Repo, Source
from app.schemas import ChunkOut, ChunkPage, ChunkUpdate, RecordChunks, RepoConfig
from app.services.embeddings import EmbeddingError
from app.services.pipeline import embed_texts
from app.services.vector_store import Hit

router = APIRouter(tags=["chunks"])

# Chunks returned inline per record; the rest is fetched per record on demand,
# so one long document cannot blow up a page.
PREVIEW_CHUNKS = 5
# A text search scans at most this many matching chunks, and shows at most
# MATCH_CHUNKS of them per record.
SEARCH_SCAN_LIMIT = 5000
MATCH_CHUNKS = 20


@router.get("/repos/{repo_id}/chunks", response_model=ChunkPage)
def browse_chunks(
    repo_id: str,
    source_id: str | None = None,
    q: str | None = Query(None, max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    services: Services = Depends(get_services),
):
    """What is stored in the repo's index, read back from Qdrant.

    Paged by record (oldest source first, then row order) with each record's
    chunks grouped under it, so a split document reads in sequence. With `q`,
    only records with a chunk containing that text, and only those chunks.
    """
    repo = get_repo(repo_id, services)
    sources = [
        s
        for s in services.meta.find(Source, {"repo_id": repo.id}, order_by="created_ts", limit=1000)
        if s.indexed and (source_id is None or s.id == source_id)
    ]
    names = {s.id: s.name for s in sources}

    q = (q or "").strip()
    if q:
        return _search_chunks(repo.id, q, source_id, names, page, page_size, services)

    total = sum(s.record_count for s in sources)

    # Walk the sources to the one holding the page's first record.
    skip = (page - 1) * page_size
    records: list[Record] = []
    for s in sources:
        if len(records) >= page_size:
            break
        if skip >= s.record_count:
            skip -= s.record_count
            continue
        records.extend(
            services.meta.find(
                Record,
                {"source_id": s.id},
                order_by="ordinal",
                limit=page_size - len(records),
                offset=skip,
            )
        )
        skip = 0

    by_record: dict[str, list[ChunkOut]] = {r.id: [] for r in records}
    for c in services.store.chunks(repo.id, list(by_record), 0, PREVIEW_CHUNKS):
        by_record[c.record_id].append(ChunkOut(id=c.id, chunk_index=c.chunk_index, text=c.text))

    items = [
        RecordChunks(
            record_id=r.id,
            ordinal=r.ordinal,
            source_id=r.source_id,
            source_name=names.get(r.source_id, ""),
            chunk_count=r.chunk_count,
            chunks=sorted(by_record[r.id], key=lambda c: c.chunk_index),
        )
        for r in records
    ]
    return ChunkPage(items=items, total=total, page=page, page_size=page_size)


def _search_chunks(
    repo_id: str,
    q: str,
    source_id: str | None,
    names: dict[str, str],
    page: int,
    page_size: int,
    services: Services,
) -> ChunkPage:
    """Records with chunks containing `q`, most matching chunks first."""
    hits, truncated = services.store.find_text(repo_id, q, source_id, SEARCH_SCAN_LIMIT)
    matches: dict[str, list[Hit]] = {}
    for h in hits:
        if h.source_id in names:
            matches.setdefault(h.record_id, []).append(h)
    rank = {sid: i for i, sid in enumerate(names)}
    order = sorted(
        matches, key=lambda rid: (-len(matches[rid]), rank[matches[rid][0].source_id], rid)
    )
    start = (page - 1) * page_size
    items = []
    for rid in order[start : start + page_size]:
        record = services.meta.get(Record, rid)
        if record is None:
            continue
        found = sorted(matches[rid], key=lambda h: h.chunk_index)
        items.append(
            RecordChunks(
                record_id=record.id,
                ordinal=record.ordinal,
                source_id=record.source_id,
                source_name=names.get(record.source_id, ""),
                chunk_count=record.chunk_count,
                chunks=[
                    ChunkOut(id=h.id, chunk_index=h.chunk_index, text=h.text)
                    for h in found[:MATCH_CHUNKS]
                ],
                match_count=len(found),
            )
        )
    return ChunkPage(
        items=items, total=len(order), page=page, page_size=page_size, truncated=truncated
    )


@router.get("/records/{record_id}/chunks", response_model=list[ChunkOut])
def record_chunks(
    record_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    services: Services = Depends(get_services),
):
    """A window of one record's chunks, in chunk order."""
    record = services.meta.get(Record, record_id)
    if record is None:
        raise HTTPException(404, "record_not_found")
    hits = services.store.chunks(record.repo_id, [record.id], offset, offset + limit)
    return [
        ChunkOut(id=h.id, chunk_index=h.chunk_index, text=h.text)
        for h in sorted(hits, key=lambda h: h.chunk_index)
    ]


def _get_chunk(record_id: str, chunk_id: str, services: Services) -> tuple[Record, Hit]:
    record = services.meta.get(Record, record_id)
    if record is None:
        raise HTTPException(404, "record_not_found")
    try:
        uuid.UUID(chunk_id)
    except ValueError:
        raise HTTPException(404, "chunk_not_found") from None
    chunk = services.store.get_chunk(record.repo_id, chunk_id)
    if chunk is None or chunk.record_id != record.id:
        raise HTTPException(404, "chunk_not_found")
    return record, chunk


def _embed(text: str, repo: Repo, services: Services) -> list[float]:
    """One chunk's vector under the repo's config, or the reason it cannot be stored."""
    if repo.needs_reindex:
        raise HTTPException(409, "repo_needs_reindex")
    cfg = RepoConfig.model_validate(repo.config)
    try:
        vector = embed_texts([text], cfg, services)[0]
    except EmbeddingError as exc:
        raise HTTPException(502, exc.code) from exc
    if repo.vector_size is not None and len(vector) != repo.vector_size:
        raise HTTPException(409, "vector_config_mismatch")
    return vector


@router.post("/records/{record_id}/chunks", response_model=ChunkOut, status_code=201)
def add_chunk(record_id: str, body: ChunkUpdate, services: Services = Depends(get_services)):
    """Index one more chunk at the end of a record.

    Like an edit, it lives only in the index: a reindex rebuilds the record's
    chunks from its original text and drops this one.
    """
    record = services.meta.get(Record, record_id)
    if record is None:
        raise HTTPException(404, "record_not_found")
    if not record.indexed:
        raise HTTPException(409, "record_not_indexed")
    repo = get_repo(record.repo_id, services)
    vector = _embed(body.text, repo, services)
    if repo.vector_size is None:  # every earlier chunk was removed with its collection
        cfg = RepoConfig.model_validate(repo.config)
        services.store.ensure(repo.id, len(vector), cfg.embedding.distance)
        services.meta.patch(Repo, repo.id, vector_size=len(vector))
    chunk = services.store.add_chunk(repo.id, record.source_id, record.id, body.text, vector)
    services.meta.patch(Record, record.id, chunk_count=chunk.chunk_index + 1)
    return ChunkOut(id=chunk.id, chunk_index=chunk.chunk_index, text=chunk.text)


@router.patch("/records/{record_id}/chunks/{chunk_id}", response_model=ChunkOut)
def update_chunk(
    record_id: str,
    chunk_id: str,
    body: ChunkUpdate,
    services: Services = Depends(get_services),
):
    """Replace a stored chunk's text and re-embed it under the repo's config.

    Only the index changes: the record keeps its original text, so a reindex
    rebuilds the chunk from that and discards the edit.
    """
    record, chunk = _get_chunk(record_id, chunk_id, services)
    repo = get_repo(record.repo_id, services)
    vector = _embed(body.text, repo, services)
    if body.text != chunk.text:
        services.store.update_chunk(repo.id, chunk, body.text, vector)
    return ChunkOut(id=chunk.id, chunk_index=chunk.chunk_index, text=body.text)


@router.delete("/records/{record_id}/chunks/{chunk_id}", status_code=204)
def delete_chunk(record_id: str, chunk_id: str, services: Services = Depends(get_services)):
    """Remove one chunk from the index; later chunks of the record move up."""
    record, chunk = _get_chunk(record_id, chunk_id, services)
    services.store.delete_chunk(record.repo_id, chunk)
    services.meta.patch(Record, record.id, chunk_count=max(0, record.chunk_count - 1))
