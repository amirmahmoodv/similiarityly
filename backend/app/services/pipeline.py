"""Background jobs: ingest (check + index) and reindex.

Ingest is incremental: record N is compared against every chunk that existed
before the load *and* against records 1..N-1 of the same load, because each
record is written to Qdrant right after it has been scored.
"""

import logging
import time
from dataclasses import dataclass

import numpy as np

from app.core.state import Services
from app.models import Job, Match, Record, Repo, Source, now
from app.schemas import RepoConfig, SimilarityConfig
from app.services.chunking import chunk_text
from app.services.embeddings import EmbeddingError, get_embedder
from app.services.normalize import normalize
from app.services.qdrant_http import storage_error_code
from app.services.rerank import RerankError, get_reranker
from app.services.vector_store import ChunkPoint, Hit, VectorConfigError, to_similarity

log = logging.getLogger("similarityly.jobs")


@dataclass
class Prepared:
    chunks: list[str]
    vectors: list[list[float]]


def embed_texts(texts: list[str], cfg: RepoConfig, services: Services) -> list[list[float]]:
    """Normalize + embed under one repo config. The single path to the embedder,
    so indexed chunks and search queries are always encoded identically."""
    if not texts:
        return []
    normalized = [normalize(t, cfg.normalization) for t in texts]
    return unit_vectors(get_embedder(cfg.embedding, services.settings).embed(normalized))


def unit_vectors(vectors: list[list[float]]) -> list[list[float]]:
    """Scale every vector to length 1 (a zero vector stays zero).

    Not every model returns unit vectors. On unit vectors dot product equals
    cosine and euclidean distance is a function of it, so `to_similarity` can
    put all three metrics on one 0..1 scale.
    """
    arr = np.asarray(vectors, dtype=np.float64)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    return (arr / np.where(norms == 0, 1.0, norms)).tolist()


def prepare(texts: list[str], cfg: RepoConfig, services: Services) -> list[Prepared]:
    """Chunk + normalize + embed a batch of record texts under one repo config."""
    per_record = [chunk_text(t, cfg.chunking) for t in texts]
    vectors = embed_texts([c for chunks in per_record for c in chunks], cfg, services)
    out: list[Prepared] = []
    pos = 0
    for chunks in per_record:
        out.append(Prepared(chunks, vectors[pos : pos + len(chunks)]))
        pos += len(chunks)
    return out


@dataclass
class Scored:
    hit: Hit
    score: float  # final 0..1 score: the second stage's when one ran
    vector_score: float | None = None  # first-stage score, kept when a second stage ran

    @property
    def retrieval_score(self) -> float:
        """What the storage floor applies to: always the vector score, because
        a second stage scores on its own scale."""
        return self.score if self.vector_score is None else self.vector_score


def score_hits(
    queries: list[str],
    results: list[list[Hit]],
    distance: str,
    sim: SimilarityConfig,
    services: Services,
) -> list[list[Scored]]:
    """Final score of every hit, best first. `queries[i]` is the text whose
    vector produced `results[i]`. The single path from raw Qdrant hits to
    scores, so job results and search agree."""
    scored = [[Scored(h, to_similarity(h.score, distance)) for h in hits] for hits in results]
    if sim.rerank == "none":
        return scored
    reranker = get_reranker(sim.rerank_model, services.settings)
    pairs = [(q, s.hit.text) for q, row in zip(queries, scored, strict=True) for s in row]
    scores = iter(reranker.score(pairs))
    return [
        sorted(
            (Scored(s.hit, next(scores), s.score) for s in row),
            key=lambda s: s.score,
            reverse=True,
        )
        for row in scored
    ]


def _targets(services: Services, repo: Repo, cfg: RepoConfig) -> list[Repo]:
    """Repos a new record is compared against. Own repo first, always."""
    sim = cfg.similarity
    others: list[Repo] = []
    if sim.scope == "all":
        others = services.meta.all(Repo)
    elif sim.scope == "selected" and sim.target_repo_ids:
        others = services.meta.all(Repo, {"id": sim.target_repo_ids})
    return [repo, *(r for r in others if r.id != repo.id)]


def _batches(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def job_error_code(exc: Exception) -> str:
    """The stable code a failed job reports; the UI translates it."""
    if isinstance(exc, EmbeddingError):
        return exc.code
    if isinstance(exc, VectorConfigError):
        return "vector_config_mismatch"
    if isinstance(exc, RerankError):
        return "rerank_failed"
    return storage_error_code(exc) or "internal_error"


def _run(services: Services, job_id: str, body) -> None:
    meta = services.meta
    job = meta.get(Job, job_id)
    if job is None:
        return
    try:
        meta.patch(Job, job_id, status="running")
        body(job)
        status, error, detail = "done", None, None
    except Exception as exc:  # surfaced to the UI through the job
        log.exception("job %s failed", job_id)
        status, error = "failed", job_error_code(exc)
        detail = (getattr(exc, "detail", "") or str(exc) or type(exc).__name__)[:2000]
    fields = {
        "status": status,
        "error": error,
        "error_detail": detail,
        "finished_at": now().isoformat(),
    }
    # The outcome must land, or the job shows "running" until the next restart.
    # The transport already retried once; a Qdrant that is briefly gone gets a
    # few more seconds here.
    for attempt in range(3):
        try:
            meta.patch(Job, job_id, **fields)
            return
        except Exception:
            if attempt == 2:
                log.exception("job %s: could not record its outcome (%s)", job_id, status)
                return
            time.sleep(2.0 * (attempt + 1))


def run_ingest(services: Services, job_id: str) -> None:
    meta, store = services.meta, services.store

    def body(job: Job) -> None:
        repo = meta.get(Repo, job.repo_id)
        cfg = RepoConfig.model_validate(repo.config)
        sim = cfg.similarity
        check = job.mode != "index_only"
        index = job.mode != "check_only"
        targets = _targets(services, repo, cfg) if check else [repo]
        target_cfgs = {t.id: RepoConfig.model_validate(t.config) for t in targets}
        floor = (
            sim.match_floor if sim.match_floor is not None else services.settings.match_store_floor
        )

        records = sorted(meta.all(Record, {"source_id": job.source_id}), key=lambda r: r.ordinal)
        processed = 0
        for batch in _batches(records, services.settings.job_batch_size):
            texts = [r.text for r in batch]
            # Repos sharing an index signature share one embedding pass.
            prepared: dict[str, list[Prepared]] = {}
            for t in targets:
                sig = target_cfgs[t.id].index_signature()
                if sig not in prepared:
                    prepared[sig] = prepare(texts, target_cfgs[t.id], services)
            own = prepared[cfg.index_signature()]
            matches: list[Match] = []
            best_record: dict[str, str] = {}  # record id -> its best match's record id

            for i, rec in enumerate(batch):
                rec.chunk_count = len(own[i].chunks)
                if check:
                    best: float | None = None
                    top_hit = (0.0, "", "")
                    count = 0
                    for t in targets:
                        if t.vector_size is None or t.needs_reindex:
                            continue  # nothing comparable indexed there yet
                        tcfg = target_cfgs[t.id]
                        p = prepared[tcfg.index_signature()][i]
                        results = score_hits(
                            p.chunks,
                            store.search_batch(t.id, p.vectors, sim.top_k),
                            tcfg.embedding.distance,
                            sim,
                            services,
                        )
                        chunk_best: list[float] = []
                        for ci, hits in enumerate(results):
                            top = 0.0
                            for s in hits:
                                h, score = s.hit, s.score
                                top = max(top, score)
                                stored = s.retrieval_score >= floor
                                if stored and score > top_hit[0]:
                                    top_hit = (score, h.text, h.record_id)
                                if not stored:
                                    continue
                                count += 1
                                matches.append(
                                    Match(
                                        repo_id=rec.repo_id,
                                        source_id=rec.source_id,
                                        job_id=job.id,
                                        record_id=rec.id,
                                        chunk_index=ci,
                                        chunk_text=p.chunks[ci],
                                        score=score,
                                        vector_score=s.vector_score,
                                        matched_repo_id=t.id,
                                        matched_source_id=h.source_id,
                                        matched_record_id=h.record_id,
                                        matched_chunk_index=h.chunk_index,
                                        matched_text=h.text,
                                    )
                                )
                            chunk_best.append(top)
                        if chunk_best:
                            agg = (
                                max(chunk_best)
                                if sim.aggregation == "max"
                                else sum(chunk_best) / len(chunk_best)
                            )
                            best = agg if best is None else max(best, agg)
                    rec.max_score = best or 0.0
                    rec.match_count = count
                    rec.best_match_text = top_hit[1]
                    if top_hit[2]:
                        best_record[rec.id] = top_hit[2]

                if index and own[i].vectors:
                    if repo.vector_size is None:
                        repo.vector_size = len(own[i].vectors[0])
                        store.ensure(repo.id, repo.vector_size, cfg.embedding.distance)
                        meta.patch(Repo, repo.id, vector_size=repo.vector_size)
                    store.upsert(
                        repo.id,
                        [
                            ChunkPoint(rec.source_id, rec.id, ci, chunk, vec)
                            for ci, (chunk, vec) in enumerate(
                                zip(own[i].chunks, own[i].vectors, strict=True)
                            )
                        ],
                    )

            # Snapshot the matched side's label, like its text, so it survives
            # a later delete. One lookup per batch, not per hit.
            matched = meta.get_many(
                Record, [m.matched_record_id for m in matches] + list(best_record.values())
            )
            for m in matches:
                hit_rec = matched.get(m.matched_record_id)
                m.matched_label = hit_rec.label if hit_rec else ""
            for rec in batch:
                hit_rec = matched.get(best_record.get(rec.id, ""))
                rec.best_match_label = hit_rec.label if hit_rec else ""

            meta.put_many(matches)
            meta.put_many(batch)
            processed += len(batch)
            meta.patch(Job, job.id, processed=processed)

    _run(services, job_id, body)


def run_reindex(services: Services, job_id: str) -> None:
    """Rebuild a repo's collection from stored record text under its current config."""
    meta, store = services.meta, services.store

    def body(job: Job) -> None:
        repo = meta.get(Repo, job.repo_id)
        cfg = RepoConfig.model_validate(repo.config)
        store.drop(repo.id)
        meta.patch(Repo, repo.id, vector_size=None)
        vector_size: int | None = None

        records = sorted(
            meta.all(Record, {"repo_id": repo.id, "indexed": True}),
            key=lambda r: (r.created_ts, r.ordinal),
        )
        processed = 0
        for batch in _batches(records, services.settings.job_batch_size):
            prepared = prepare([r.text for r in batch], cfg, services)
            points: list[ChunkPoint] = []
            for rec, p in zip(batch, prepared, strict=True):
                rec.chunk_count = len(p.chunks)
                points.extend(
                    ChunkPoint(rec.source_id, rec.id, ci, chunk, vec)
                    for ci, (chunk, vec) in enumerate(zip(p.chunks, p.vectors, strict=True))
                )
            if points:
                if vector_size is None:
                    vector_size = len(points[0].vector)
                    store.ensure(repo.id, vector_size, cfg.embedding.distance)
                store.upsert(repo.id, points)
            meta.put_many(batch)
            processed += len(batch)
            meta.patch(Job, job.id, processed=processed)
        meta.patch(Repo, repo.id, vector_size=vector_size, needs_reindex=False)

    _run(services, job_id, body)


def delete_source_data(services: Services, source: Source) -> None:
    services.store.delete_source(source.repo_id, source.id)
    for entity in (Match, Record, Job):
        services.meta.delete(entity, {"source_id": source.id})
    services.meta.delete_id(Source, source.id)
