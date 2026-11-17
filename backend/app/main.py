import logging
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import router
from app.core.auth import TokenAuthMiddleware
from app.core.config import Settings
from app.core.http import BodyLimitMiddleware, CatchErrorsMiddleware, SecurityHeadersMiddleware
from app.core.runtime import apply_overrides
from app.core.state import start_services, stop_services

log = logging.getLogger("similarityly")


def configure_logging() -> None:
    """Send the app's INFO logs to stderr next to uvicorn's.

    Without a handler Python only prints WARNING and above, so setup progress
    (e.g. "qdrant setup: ...") never reached the container log.
    """
    if not any(getattr(h, "_similarityly", False) for h in log.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s: %(message)s"))
        handler._similarityly = True  # type: ignore[attr-defined]
        log.addHandler(handler)
    log.setLevel(logging.INFO)


_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
MIN_TOKEN_LENGTH = 16


def _is_local_origin(origin: str) -> bool:
    try:
        host = urlsplit(origin).hostname or ""
    except ValueError:
        return False
    return host in _LOCAL_HOSTS or host.endswith(".localhost")


def check_security(settings: Settings) -> None:
    """Refuse configurations that would publish the API without protection."""
    public_origins = [o for o in settings.cors_origins if not _is_local_origin(o)]
    if "*" in settings.cors_origins:
        raise RuntimeError("SIM_CORS_ORIGINS must list origins explicitly; '*' is not allowed.")
    if public_origins and not settings.api_token and not settings.allow_public_without_token:
        raise RuntimeError(
            f"SIM_CORS_ORIGINS allows {public_origins}, so the API is meant to be public, "
            "but SIM_API_TOKEN is not set: anyone could read and delete all data. Set "
            "SIM_API_TOKEN, or SIM_ALLOW_PUBLIC_WITHOUT_TOKEN=true if an authenticating "
            "proxy in front of the API already protects it."
        )
    if settings.api_token and len(settings.api_token) < MIN_TOKEN_LENGTH:
        log.warning(
            "SIM_API_TOKEN is shorter than %d characters; generate a longer one with "
            'python -c "import secrets; print(secrets.token_urlsafe(32))"',
            MIN_TOKEN_LENGTH,
        )


def create_app(settings: Settings | None = None) -> FastAPI:
    # Connections come from the Settings page (settings.json), not the environment.
    settings = apply_overrides(settings or Settings())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.services = start_services(settings)
        yield
        stop_services(app.state.services)

    configure_logging()
    check_security(settings)
    docs = settings.enable_docs
    app = FastAPI(
        title="Similarityly API",
        version="0.1.0",
        lifespan=lifespan,
        # Off by default: the schema maps every endpoint for anyone who asks.
        docs_url="/docs" if docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if docs else None,
    )
    # Added innermost first; see app/core/http.py for the resulting order.
    app.add_middleware(CatchErrorsMiddleware)
    # Uploads plus room for the multipart envelope and form fields.
    app.add_middleware(BodyLimitMiddleware, max_bytes=(settings.max_upload_mb + 1) * 1024 * 1024)
    if settings.api_token:
        app.add_middleware(TokenAuthMiddleware, settings=settings)
    else:
        log.warning(
            "SIM_API_TOKEN is not set: the API accepts unauthenticated requests. "
            "Only run this way on a trusted, local-only setup."
        )
    app.add_middleware(SecurityHeadersMiddleware)
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
