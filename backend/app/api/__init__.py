from fastapi import APIRouter

from app.api import chunks, ingest, jobs, meta, repos, search, settings

router = APIRouter(prefix="/api/v1")
router.include_router(meta.router)
router.include_router(repos.router)
router.include_router(ingest.router)
router.include_router(jobs.router)
router.include_router(search.router)
router.include_router(chunks.router)
router.include_router(settings.router)
