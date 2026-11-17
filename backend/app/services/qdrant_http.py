"""HTTP plumbing for Qdrant servers that copes with unreliable networks.

Two problems seen in practice:

* `localhost` on Windows resolves to IPv6 first. Docker publishes Qdrant on
  IPv4 only, so every new connection waits ~2 s before falling back.
  qdrant-client also disables keep-alive for local hosts, so that delay hit
  every single request. `http://localhost` is therefore rewritten to 127.0.0.1.

* Behind some proxies and NATs (seen on a PaaS egress), a request can hang with
  no answer until the read timeout, while the same request on a new connection
  works. Read-only requests (GET/HEAD) get a shorter first attempt and, if it
  times out or the connection breaks, one retry on a brand-new connection.
  Writes are never retried: creating a collection twice is an error.
"""

import logging
from urllib.parse import urlsplit, urlunsplit

import httpx

log = logging.getLogger("similarityly")

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
_SAFE_METHODS = {"GET", "HEAD"}
# A metadata read that has not answered by then is not coming; retry instead.
FIRST_READ_ATTEMPT_TIMEOUT = 15.0
# The retry is capped too, so a read that hangs twice fails in ~35 s: within a
# typical 60 s ingress timeout, so the UI receives the error instead of a cut-off.
RETRY_READ_TIMEOUT = 20.0
# Errors where the connection, not the server, is the likely culprit.
_RETRYABLE = (httpx.ReadTimeout, httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError)


def prefer_ipv4_loopback(url: str) -> str:
    """http://localhost[:port] -> http://127.0.0.1[:port]. https keeps its name
    (the certificate is issued for it)."""
    parts = urlsplit(url)
    if parts.scheme != "http" or parts.hostname != "localhost":
        return url
    netloc = "127.0.0.1" + (f":{parts.port}" if parts.port else "")
    return urlunsplit(parts._replace(netloc=netloc))


class ResilientTransport(httpx.BaseTransport):
    """Connection retries, and one fresh-connection retry for hanging reads."""

    def __init__(self, host: str):
        self._local = host in _LOCAL_HOSTS
        self._transport = self._new_transport()

    def _new_transport(self) -> httpx.HTTPTransport:
        # Keep-alive off for local hosts, as qdrant-client itself does: reused
        # local connections can add delays. `retries=1`: one more try for a failed connect.
        limits = (
            httpx.Limits(max_connections=None, max_keepalive_connections=0)
            if self._local
            # httpx's own defaults; Limits() alone would mean "unlimited". Idle
            # connections expire after 5 s, before a NAT or proxy drops them.
            else httpx.Limits(max_connections=100, max_keepalive_connections=20, keepalive_expiry=5)
        )
        return httpx.HTTPTransport(retries=1, limits=limits)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if request.method not in _SAFE_METHODS:
            return self._transport.handle_request(request)

        timeout = dict(request.extensions.get("timeout") or {})
        full_read = timeout.get("read")
        first_read = (
            FIRST_READ_ATTEMPT_TIMEOUT
            if full_read is None
            else min(full_read, FIRST_READ_ATTEMPT_TIMEOUT)
        )
        request.extensions["timeout"] = {**timeout, "read": first_read}
        try:
            return self._transport.handle_request(request)
        except _RETRYABLE as exc:
            log.warning(
                "Qdrant %s %s failed on a pooled connection (%s); retrying on a new one",
                request.method,
                request.url.path,
                type(exc).__name__,
            )
            # Drop every kept-alive connection: one stalled, others may be too.
            self._transport.close()
            self._transport = self._new_transport()
            retry_read = (
                RETRY_READ_TIMEOUT if full_read is None else min(full_read, RETRY_READ_TIMEOUT)
            )
            request.extensions["timeout"] = {**timeout, "read": retry_read}
            return self._transport.handle_request(request)

    def close(self) -> None:
        self._transport.close()
