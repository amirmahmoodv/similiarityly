from fastapi import APIRouter, Depends, HTTPException

from app.api.repos import get_repo
from app.core.state import Services, get_services
from app.models import Source
from app.schemas import RepoConfig, SearchHit, SearchRequest
from app.services.embeddings import EmbeddingError
from app.services.pipeline import embed_texts, score_hits
from app.services.rerank import RerankError

router = APIRouter(tags=["search"])


@router.post("/repos/{repo_id}/search", response_model=list[SearchHit])
def search_repo(repo_id: str, body: SearchRequest, services: Services = Depends(get_services)):
    """Free-text similarity search over a repo's indexed chunks.

    The query goes through the repo's own normalization and embedding model, so
    it is scored exactly the way loaded records are.
    """
    repo = get_repo(repo_id, services)
    if repo.needs_reindex:
        raise HTTPException(409, "repo_needs_reindex")
    if repo.vector_size is None:
        return []
    cfg = RepoConfig.model_validate(repo.config)
    try:
        vector = embed_texts([body.query], cfg, services)[0]
    except EmbeddingError as exc:
        raise HTTPException(502, "embedding_failed") from exc
    if len(vector) != repo.vector_size:
        raise HTTPException(409, "vector_config_mismatch")

    raw = services.store.search_batch(repo.id, [vector], body.top_k)
    try:
        hits = score_hits([body.query], raw, cfg.embedding.distance, cfg.similarity, services)[0]
    except RerankError as exc:
        raise HTTPException(502, "rerank_failed") from exc
    names: dict[str, str] = {}
    out = []
    for s in hits:
        h = s.hit
        if h.source_id not in names:
            source = services.meta.get(Source, h.source_id)
            names[h.source_id] = source.name if source else ""
        out.append(
            SearchHit(
                score=s.score,
                vector_score=s.vector_score,
                text=h.text,
                record_id=h.record_id,
                chunk_index=h.chunk_index,
                source_id=h.source_id,
                source_name=names[h.source_id],
            )
        )
    return out
