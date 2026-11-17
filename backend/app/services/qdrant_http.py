"""HTTP plumbing for Qdrant servers that copes with unreliable networks.

Two problems seen in practice:

* `localhost` on Windows resolves to IPv6 first. Docker publishes Qdrant on
  IPv4 only, so every new connection waits ~2 s before falling back.
  qdrant-client also disables keep-alive for local hosts, so that delay hit
  every single request. `http://localhost` is therefore rewritten to 127.0.0.1.

* Behind some proxies and NATs (seen on a PaaS egress), a request can hang with
  no answer until the timeout, while the same request on a new connection
  works. The hang can be on either side: waiting for the answer (ReadTimeout),
  or sending a large body that the peer stopped accepting (WriteTimeout, seen
  when ingesting a whole document as one point). Requests that are safe to
  send twice get a shorter first attempt and, if it stalls or the connection
  breaks, one retry on a brand-new connection:

  - reads: every GET/HEAD, and the POST endpoints that only read points
    (retrieve, query, search, scroll, count, facet);
  - point writes: upsert, delete, set/overwrite/clear payload, vectors and
    batch updates. They address points by id, so applying one twice leaves
    the same state as applying it once.

  Collection-level writes (create/delete a collection, create an index) are
  never retried: creating a collection twice is an error.
"""

import logging
import re
from collections.abc import Callable, Iterator, Sequence
from typing import TypeVar
from urllib.parse import urlsplit, urlunsplit

import httpx
from qdrant_client.http.exceptions import ResponseHandlingException

log = logging.getLogger("similarityly")

T = TypeVar("T")

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
_SAFE_METHODS = {"GET", "HEAD"}
_WRITE_METHODS = {"PUT", "POST", "DELETE"}
# POST endpoints that only read points. `/points` itself is a read on POST
# (retrieve by ids) and an upsert on PUT.
_POINT_READ = re.compile(
    r"/collections/[^/]+/(facet|points(/(query|search|recommend|discover|scroll|count)(/\w+)?)?)$"
)
# Point-level operations: idempotent, unlike collection-level ones.
_POINT_OP = re.compile(r"/collections/[^/]+/points(/[\w/]+)?$")

# A metadata read that has not answered by then is not coming; retry instead.
FIRST_READ_ATTEMPT_TIMEOUT = 15.0
# The retry is capped too, so a read that hangs twice fails in ~35 s: within a
# typical 60 s ingress timeout, so the UI receives the error instead of a cut-off.
RETRY_READ_TIMEOUT = 20.0
# Sending a body: no progress for this long means the connection is dead.
FIRST_WRITE_ATTEMPT_TIMEOUT = 15.0
# Waiting for a point write (wait=True) to be applied. Qdrant answers once the
# change is in its log, not after indexing, so this is generous; the retry
# gets the full configured timeout.
FIRST_WRITE_ANSWER_TIMEOUT = 30.0
# Errors where the connection, not the server, is the likely culprit.
_RETRYABLE = (
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.RemoteProtocolError,
    httpx.ReadError,
    httpx.WriteError,
)


def request_kind(method: str, path: str) -> str:
    """Classify a request: "read" or "point_write" (retried once), or "other"."""
    if method in _SAFE_METHODS or (method == "POST" and _POINT_READ.search(path)):
        return "read"
    if method in _WRITE_METHODS and _POINT_OP.search(path):
        return "point_write"
    return "other"


def _capped(full: float | None, cap: float) -> float:
    return cap if full is None else min(full, cap)


def prefer_ipv4_loopback(url: str) -> str:
    """http://localhost[:port] -> http://127.0.0.1[:port]. https keeps its name
    (the certificate is issued for it)."""
    parts = urlsplit(url)
    if parts.scheme != "http" or parts.hostname != "localhost":
        return url
    netloc = "127.0.0.1" + (f":{parts.port}" if parts.port else "")
    return urlunsplit(parts._replace(netloc=netloc))


class ResilientTransport(httpx.BaseTransport):
    """Connection retries, and one fresh-connection retry for stalled safe requests."""

    def __init__(self, host: str):
        self._local = host in _LOCAL_HOSTS
        # Turned on for good after the first stalled request: on that network,
        # reused connections hang while new ones answer (seen on a PaaS egress).
        # A TLS handshake per request is far cheaper than a 15 s hang each time.
        self.keepalive_disabled = False
        self._transport = self._new_transport()

    def _new_transport(self) -> httpx.HTTPTransport:
        # Keep-alive off for local hosts, as qdrant-client itself does: reused
        # local connections can add delays. `retries=1`: one more try for a failed connect.
        limits = (
            httpx.Limits(max_connections=None, max_keepalive_connections=0)
            if self._local or self.keepalive_disabled
            # httpx's own defaults; Limits() alone would mean "unlimited". Idle
            # connections expire after 5 s, before a NAT or proxy drops them.
            else httpx.Limits(max_connections=100, max_keepalive_connections=20, keepalive_expiry=5)
        )
        return httpx.HTTPTransport(retries=1, limits=limits)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        kind = request_kind(request.method, request.url.path)
        if kind == "other":
            return self._transport.handle_request(request)

        timeout = dict(request.extensions.get("timeout") or {})
        full_read, full_write = timeout.get("read"), timeout.get("write")
        if kind == "read":
            first = {
                "read": _capped(full_read, FIRST_READ_ATTEMPT_TIMEOUT),
                "write": _capped(full_write, FIRST_WRITE_ATTEMPT_TIMEOUT),
            }
            retry = {"read": _capped(full_read, RETRY_READ_TIMEOUT), "write": full_write}
        else:
            first = {
                "read": _capped(full_read, FIRST_WRITE_ANSWER_TIMEOUT),
                "write": _capped(full_write, FIRST_WRITE_ATTEMPT_TIMEOUT),
            }
            retry = {"read": full_read, "write": full_write}

        request.extensions["timeout"] = {**timeout, **first}
        try:
            return self._transport.handle_request(request)
        except _RETRYABLE as exc:
            log.warning(
                "Qdrant %s %s failed on a pooled connection (%s); retrying on a new one",
                request.method,
                request.url.path,
                type(exc).__name__,
            )
            # Drop every kept-alive connection (one stalled, others may be too)
            # and stop keeping any: the same thing would happen on the next reuse.
            if not self.keepalive_disabled:
                log.warning(
                    "Qdrant connection reuse is unreliable on this network; "
                    "using a new connection per request from now on"
                )
                self.keepalive_disabled = True
            self._transport.close()
            self._transport = self._new_transport()
            request.extensions["timeout"] = {**timeout, **retry}
            # The body was built in memory by qdrant-client, so it can be sent again.
            return self._transport.handle_request(request)

    def close(self) -> None:
        self._transport.close()


# ---- request sizing ----------------------------------------------------------

# Qdrant refuses bodies over 32 MB by default, and a large body is what turns a
# stalled connection into a WriteTimeout. Batches stay well under both.
MAX_REQUEST_BYTES = 4 * 1024 * 1024


def batched(
    items: Sequence[T],
    size_of: Callable[[T], int],
    max_items: int,
    max_bytes: int | None = None,
) -> Iterator[list[T]]:
    """Split items into batches of at most `max_items` and about `max_bytes`.

    An item larger than `max_bytes` on its own still goes, alone in its batch.
    """
    max_bytes = MAX_REQUEST_BYTES if max_bytes is None else max_bytes
    batch: list[T] = []
    used = 0
    for item in items:
        size = size_of(item)
        if batch and (len(batch) >= max_items or used + size > max_bytes):
            yield batch
            batch, used = [], 0
        batch.append(item)
        used += size
    if batch:
        yield batch


# ---- error codes ---------------------------------------------------------------


def storage_error_code(exc: BaseException) -> str | None:
    """The stable code ("storage_timeout" / "storage_unreachable") when a Qdrant request failed in
    transit (after the retry above), else None. qdrant-client wraps every
    transport error in ResponseHandlingException, which tells a Qdrant failure
    apart from one in, say, the embedding service's HTTP client."""
    chain: list[BaseException] = []
    seen: BaseException | None = exc
    while seen is not None and len(chain) < 20:
        chain.append(seen)
        # ResponseHandlingException keeps the transport error as `source`.
        seen = getattr(seen, "source", None) or seen.__cause__ or seen.__context__
    if not any(isinstance(e, ResponseHandlingException) for e in chain):
        return None
    if any(isinstance(e, (httpx.TimeoutException, TimeoutError)) for e in chain):
        return "storage_timeout"
    return "storage_unreachable"
