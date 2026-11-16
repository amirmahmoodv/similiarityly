from fastapi import APIRouter, Depends

from app.core.state import Services, get_services
from app.models import Match, Record, Repo, Source
from app.schemas import MetaOut, RepoConfig, RerankerInfo, StatsOut
from app.services import rerank
from app.services.embeddings import provider_infos

router = APIRouter(tags=["meta"])


def default_config(services: Services) -> RepoConfig:
    """Prefer a real multilingual model when the local provider is installed."""
    cfg = RepoConfig()
    infos = {p.id: p for p in provider_infos(services.settings)}
    if infos["fastembed"].available:
        cfg.embedding.provider = "fastembed"
        cfg.embedding.model = infos["fastembed"].models[0]
    return cfg


@router.get("/meta", response_model=MetaOut)
def meta(services: Services = Depends(get_services)):
    return MetaOut(
        providers=provider_infos(services.settings),
        rerankers=RerankerInfo(available=rerank.available(), models=rerank.SUGGESTED_MODELS),
        defaults=default_config(services),
        qdrant_mode=services.store.mode,
    )


@router.get("/stats", response_model=StatsOut)
def stats(services: Services = Depends(get_services)):
    m = services.meta
    repos = m.all(Repo)
    return StatsOut(
        repos=len(repos),
        sources=m.count(Source),
        records=m.count(Record),
        chunks=sum(services.store.count(r.id) for r in repos),
        matches=m.count(Match),
    )
