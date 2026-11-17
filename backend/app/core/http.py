"""HTTP-level protections that wrap every request (pure ASGI middlewares).

Order in create_app, outermost first:
  CORS -> SecurityHeaders -> TokenAuth -> BodyLimit -> CatchErrors -> app
Everything inside CORS gets CORS headers on its responses, errors included.
"""

import logging

from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

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


async def _too_large(scope: Scope, receive: Receive, send: Send) -> None:
    await JSONResponse({"detail": "file_too_large"}, status_code=413)(scope, receive, send)


class BodyLimitMiddleware:
    """Caps request bodies before anything parses them.

    uvicorn has no body limit, and multipart parsing spools the whole upload to
    disk before the handler's own size check runs. With the API on its own
    domain there may be no nginx in front, so the cap lives here too. Declared
    lengths are refused up front; chunked bodies are counted as they stream.
    """

    def __init__(self, app: ASGIApp, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = -1
                if declared < 0 or declared > self.max_bytes:
                    await _too_large(scope, receive, send)
                    return
        seen = 0
        started = False
        rejected = False

        async def guarded_send(message: Message) -> None:
            nonlocal started
            if rejected:  # the 413 already went out; drop what the app says after
                return
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        async def counting_receive() -> Message:
            nonlocal seen, rejected
            if rejected:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > self.max_bytes and not started:
                    # Raising would not help: FastAPI turns any error while
                    # reading the body into its own 400. Answer here instead and
                    # make the app see a disconnect, which stops the parsing.
                    await _too_large(scope, receive, send)
                    rejected = True
                    return {"type": "http.disconnect"}
            return message

        await self.app(scope, counting_receive, guarded_send)


# A JSON API never renders HTML, so the strictest policy fits every response.
API_SECURITY_HEADERS = {
    "content-security-policy": "default-src 'none'; frame-ancestors 'none'",
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
    "cross-origin-resource-policy": "same-site",
    # Ignored by browsers on plain http, so harmless on local setups.
    "strict-transport-security": "max-age=31536000",
}
# Interactive docs (only when SIM_ENABLE_DOCS) load Swagger UI from a CDN.
_DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope.get("path", "")

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in API_SECURITY_HEADERS.items():
                    if name == "content-security-policy" and path.startswith(_DOCS_PATHS):
                        continue
                    headers.setdefault(name, value)
                if path.startswith("/api/"):
                    # Repository data and settings: never keep a copy in a cache.
                    headers.setdefault("cache-control", "no-store")
            await send(message)

        await self.app(scope, receive, send_with_headers)
