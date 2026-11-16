from fastapi import APIRouter, Depends, HTTPException

from app.core.state import Services, get_services
from app.models import Job, Match, Record, Repo, Source
from app.schemas import (
    IndexStatus,
    JobOut,
    RepoConfig,
    RepoCreate,
    RepoOut,
    RepoUpdate,
    SourceOut,
)
from app.services.pipeline import delete_source_data, run_reindex

router = APIRouter(tags=["repos"])


def get_repo(repo_id: str, services: Services) -> Repo:
    repo = services.meta.get(Repo, repo_id)
    if repo is None:
        raise HTTPException(404, "repo_not_found")
    return repo


def repo_out(repo: Repo, services: Services) -> RepoOut:
    out = RepoOut.model_validate(repo)
    out.source_count = services.meta.count(Source, {"repo_id": repo.id})
    out.record_count = services.meta.count(Record, {"repo_id": repo.id, "indexed": True})
    out.chunk_count = services.store.count(repo.id)  # the vectors actually searchable
    return out


def job_out(job: Job, services: Services) -> JobOut:
    out = JobOut.model_validate(job)
    repo = services.meta.get(Repo, job.repo_id)
    source = services.meta.get(Source, job.source_id)
    out.repo_name = repo.name if repo else ""
    out.source_name = source.name if source else ""
    return out


def _name_taken(services: Services, name: str, except_id: str | None = None) -> bool:
    return any(r.id != except_id for r in services.meta.all(Repo, {"name": name}))


@router.get("/repos", response_model=list[RepoOut])
def list_repos(services: Services = Depends(get_services)):
    repos = services.meta.find(Repo, order_by="created_ts", desc=True, limit=500)
    return [repo_out(r, services) for r in repos]


@router.post("/repos", response_model=RepoOut, status_code=201)
def create_repo(body: RepoCreate, services: Services = Depends(get_services)):
    name = body.name.strip()
    if _name_taken(services, name):
        raise HTTPException(409, "repo_name_taken")
    repo = Repo(name=name, description=body.description, config=body.config.model_dump())
    services.meta.put(repo)
    return repo_out(repo, services)


@router.get("/repos/{repo_id}", response_model=RepoOut)
def read_repo(repo_id: str, services: Services = Depends(get_services)):
    return repo_out(get_repo(repo_id, services), services)


@router.patch("/repos/{repo_id}", response_model=RepoOut)
def update_repo(repo_id: str, body: RepoUpdate, services: Services = Depends(get_services)):
    repo = get_repo(repo_id, services)
    if body.name is not None:
        name = body.name.strip()
        if _name_taken(services, name, repo.id):
            raise HTTPException(409, "repo_name_taken")
        repo.name = name
    if body.description is not None:
        repo.description = body.description
    if body.config is not None:
        old = RepoConfig.model_validate(repo.config)
        # Similarity settings apply immediately; anything that changes the
        # stored vectors needs a rebuild once data exists.
        if repo.vector_size is not None and old.index_signature() != body.config.index_signature():
            repo.needs_reindex = True
        repo.config = body.config.model_dump()
    services.meta.put(repo)
    return repo_out(repo, services)


@router.delete("/repos/{repo_id}", status_code=204)
def delete_repo(repo_id: str, services: Services = Depends(get_services)):
    repo = get_repo(repo_id, services)
    services.store.drop(repo.id)
    for entity in (Match, Record, Job, Source):
        services.meta.delete(entity, {"repo_id": repo.id})
    services.meta.delete_id(Repo, repo.id)


@router.post("/repos/{repo_id}/reindex", response_model=JobOut, status_code=202)
def reindex_repo(repo_id: str, services: Services = Depends(get_services)):
    repo = get_repo(repo_id, services)
    total = services.meta.count(Record, {"repo_id": repo.id, "indexed": True})
    job = Job(repo_id=repo.id, kind="reindex", mode="index_only", total=total)
    services.meta.put(job)
    services.submit(run_reindex, job.id)
    return job_out(services.meta.get(Job, job.id), services)


@router.get("/repos/{repo_id}/index", response_model=IndexStatus)
def index_status(repo_id: str, services: Services = Depends(get_services)):
    """Is this repo's Qdrant collection in a state that can be searched?"""
    repo = get_repo(repo_id, services)
    cfg = RepoConfig.model_validate(repo.config)
    info = services.store.info(repo.id)
    status = IndexStatus(configured_distance=cfg.embedding.distance, mode=services.store.mode)
    if info is None:
        status.problem = "index_empty"
        return status
    status.exists = True
    status.points = info.points
    status.vector_size = info.vector_size
    status.distance = info.distance
    status.collection_status = info.status
    status.indexed_fields = info.indexed_fields
    if repo.needs_reindex:
        status.problem = "repo_needs_reindex"
    elif info.distance != cfg.embedding.distance or info.vector_size != repo.vector_size:
        status.problem = "vector_config_mismatch"
    elif info.points == 0:
        status.problem = "index_empty"
    elif info.status == "red":
        status.problem = "collection_unhealthy"
    status.searchable = status.problem is None
    return status


@router.get("/repos/{repo_id}/sources", response_model=list[SourceOut])
def list_sources(repo_id: str, services: Services = Depends(get_services)):
    get_repo(repo_id, services)
    sources = services.meta.find(
        Source, {"repo_id": repo_id}, order_by="created_ts", desc=True, limit=1000
    )
    out = []
    for s in sources:
        item = SourceOut.model_validate(s)
        last = services.meta.find(
            Job, {"source_id": s.id}, order_by="created_ts", desc=True, limit=1
        )
        item.last_job_id = last[0].id if last else None
        out.append(item)
    return out


@router.delete("/sources/{source_id}", status_code=204)
def delete_source(source_id: str, services: Services = Depends(get_services)):
    source = services.meta.get(Source, source_id)
    if source is None:
        raise HTTPException(404, "source_not_found")
    delete_source_data(services, source)
