"""Process-wide services, built once per app and shared with background jobs."""

import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from fastapi import Request
from qdrant_client import QdrantClient

from app.core.config import Settings
from app.models import Job, Repo, now
from app.schemas import RepoConfig
from app.services.legacy_import import import_legacy_sqlite
from app.services.meta_store import MetaStore
from app.services.vector_store import VectorConfigError, VectorStore, connect

log = logging.getLogger("similarityly")


@dataclass
class Services:
    settings: Settings
    client: QdrantClient
    meta: MetaStore  # repos, sources, records, jobs, matches
    store: VectorStore  # chunk vectors, one collection per repo
    # One worker: jobs run in submission order, which is what makes
    # "compare against everything loaded before" well defined.
    executor: ThreadPoolExecutor = field(
        default_factory=lambda: ThreadPoolExecutor(max_workers=1, thread_name_prefix="job")
    )

    def submit(self, fn: Callable[["Services", str], None], job_id: str) -> None:
        if self.settings.jobs_inline:
            fn(self, job_id)
        else:
            self.executor.submit(fn, self, job_id)


def build_services(settings: Settings) -> Services:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    client, mode = connect(settings)
    lock = threading.RLock()
    prefix = settings.collection_prefix
    return Services(
        settings=settings,
        client=client,
        meta=MetaStore(client, lock, prefix, mode),
        store=VectorStore(client, lock, prefix, mode),
    )


def start_services(settings: Settings) -> Services:
    """Build services and bring the store they point at up to date."""
    services = build_services(settings)
    try:
        import_legacy_sqlite(settings.legacy_sqlite_path, services.meta)

        # Jobs are in-process; anything unfinished at startup died with the old process.
        for job in services.meta.all(Job, {"status": ["queued", "running"]}):
            services.meta.patch(
                Job, job.id, status="failed", error="interrupted", finished_at=now().isoformat()
            )

        # Bring every existing vector collection up to the current search setup
        # (payload indexes) and flag any whose shape no longer matches its repo.
        for repo in services.meta.all(Repo):
            if repo.vector_size is None or repo.needs_reindex:
                continue
            distance = RepoConfig.model_validate(repo.config).embedding.distance
            try:
                services.store.ensure(repo.id, repo.vector_size, distance)
            except VectorConfigError as exc:
                log.warning("repo %s flagged for reindex: %s", repo.id, exc)
                services.meta.patch(Repo, repo.id, needs_reindex=True)
    except Exception:
        services.client.close()
        raise
    return services


def stop_services(services: Services, wait: bool = False) -> None:
    services.executor.shutdown(wait=wait, cancel_futures=not wait)
    services.client.close()


class JobsRunningError(RuntimeError):
    pass


class StorageDownError(RuntimeError):
    """Switching Qdrant failed and the previous connection could not be restored."""


_swap_lock = threading.Lock()


def swap_services(app, settings: Settings) -> Services:
    """Reconnect to a different Qdrant. Refused while a job is queued or running.

    The old client is closed first (embedded Qdrant locks its directory). If the
    new connection fails, the previous one is restored and the error re-raised.
    """
    with _swap_lock:
        old: Services = app.state.services
        if old.meta.count(Job, {"status": ["queued", "running"]}):
            raise JobsRunningError("jobs_running")
        stop_services(old, wait=True)
        try:
            app.state.services = start_services(settings)
        except Exception as exc:
            try:
                app.state.services = start_services(old.settings)
            except Exception as restore_exc:
                log.exception("could not reconnect to the previous Qdrant")
                raise StorageDownError(str(restore_exc)) from exc
            raise
        return app.state.services


def get_services(request: Request) -> Services:
    return request.app.state.services
