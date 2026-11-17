import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api import router
from app.core.auth import TokenAuthMiddleware
from app.core.config import Settings
from app.core.runtime import apply_overrides
from app.core.state import start_services, stop_services

log = logging.getLogger("similarityly")


class CatchErrorsMiddleware:
    """Turns an unhandled exception into a JSON 500 inside the CORS layer.

    Starlette builds its own 500 in the outermost middleware, outside CORS, so
    the response has no CORS headers. A UI on another origin then cannot read
    it and only sees a network error. Answering here keeps the CORS headers and
    gives the UI a stable error code; the traceback goes to the log.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception:
            log.exception("unhandled error: %s %s", scope.get("method"), scope.get("path"))
            if started:  # headers already sent; nothing better to do
                raise
            response = JSONResponse({"detail": "internal_error"}, status_code=500)
            await response(scope, receive, send)


def create_app(settings: Settings | None = None) -> FastAPI:
    # Connections come from the Settings page (settings.json), not the environment.
    settings = apply_overrides(settings or Settings())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.services = start_services(settings)
        yield
        stop_services(app.state.services)

    app = FastAPI(title="Similarityly API", version="0.1.0", lifespan=lifespan)
    # Innermost of the custom middlewares, so its 500s still pass through CORS.
    app.add_middleware(CatchErrorsMiddleware)
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
