"""Optional shared-token authentication for the API.

A header token (not a cookie) is used on purpose: browsers never attach it on
their own, so cross-site requests and DNS-rebinding pages cannot use it.
"""

import hmac

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import Settings


class TokenAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, settings: Settings):
        super().__init__(app)
        self._token = (settings.api_token or "").encode()

    async def dispatch(self, request: Request, call_next):
        # CORS preflights carry no credentials; the CORS middleware answers them.
        if (
            self._token
            and request.url.path.startswith("/api/")
            and request.method != "OPTIONS"
            and not self._valid(request.headers.get("authorization", ""))
        ):
            return JSONResponse(
                {"detail": "unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        return await call_next(request)

    def _valid(self, header: str) -> bool:
        scheme, _, value = header.partition(" ")
        given = value.strip().encode()
        return scheme.lower() == "bearer" and hmac.compare_digest(given, self._token)
