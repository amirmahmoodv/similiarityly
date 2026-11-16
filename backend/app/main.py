import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import router
from app.core.auth import TokenAuthMiddleware
from app.core.config import Settings
from app.core.runtime import apply_overrides
from app.core.state import start_services, stop_services

log = logging.getLogger("similarityly")


def create_app(settings: Settings | None = None) -> FastAPI:
    # Values saved from the Settings page override the SIM_ env vars.
    settings = apply_overrides(settings or Settings())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.services = start_services(settings)
        yield
        stop_services(app.state.services)

    app = FastAPI(title="Similarityly API", version="0.1.0", lifespan=lifespan)
    if settings.api_token:
        app.add_middleware(TokenAuthMiddleware, settings=settings)
    else:
        log.warning(
            "SIM_API_TOKEN is not set: the API accepts unauthenticated requests. "
            "Only run this way on a trusted, local-only setup."
        )
    # Added last so it runs first and also answers preflights / 401s with CORS headers.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.include_router(router)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()
