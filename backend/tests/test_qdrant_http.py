"""The Qdrant HTTP transport: IPv4 loopback and the fresh-connection retry."""

import httpx
import pytest

from app.services import qdrant_http
from app.services.qdrant_http import (
    FIRST_READ_ATTEMPT_TIMEOUT,
    RETRY_READ_TIMEOUT,
    ResilientTransport,
    prefer_ipv4_loopback,
)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://localhost:6333", "http://127.0.0.1:6333"),
        ("http://localhost", "http://127.0.0.1"),
        ("http://localhost:6333/prefix", "http://127.0.0.1:6333/prefix"),
        # https keeps the name its certificate is issued for.
        ("https://localhost:6333", "https://localhost:6333"),
        ("http://qdrant:6333", "http://qdrant:6333"),
        ("https://qdrant.example.com", "https://qdrant.example.com"),
    ],
)
def test_prefer_ipv4_loopback(url, expected):
    assert prefer_ipv4_loopback(url) == expected


class _Scripted(httpx.BaseTransport):
    """Answers from a script: an exception class to raise, or a status code."""

    def __init__(self, script, calls):
        self.script, self.calls, self.closed = script, calls, False

    def handle_request(self, request):
        self.calls.append((request.method, request.extensions["timeout"]["read"]))
        step = self.script.pop(0)
        if isinstance(step, type) and issubclass(step, Exception):
            raise step("scripted", request=request)
        return httpx.Response(step, json={"result": {"exists": False}})

    def close(self):
        self.closed = True


def _transport(monkeypatch, script, host="qdrant.example.com"):
    calls: list = []
    made: list[_Scripted] = []

    def new(self):
        t = _Scripted(script, calls)
        made.append(t)
        return t

    monkeypatch.setattr(ResilientTransport, "_new_transport", new)
    return ResilientTransport(host), calls, made


def _client(transport):
    return httpx.Client(base_url="https://q.example.com", transport=transport, timeout=60)


def test_hanging_read_is_retried_once_on_a_new_connection(monkeypatch, caplog):
    transport, calls, made = _transport(monkeypatch, [httpx.ReadTimeout, 200])
    res = _client(transport).get("/collections/sim_meta_repos/exists")
    assert res.status_code == 200
    # Both attempts capped, so a read that hangs twice fails within an ingress timeout.
    assert calls == [("GET", FIRST_READ_ATTEMPT_TIMEOUT), ("GET", RETRY_READ_TIMEOUT)]
    assert FIRST_READ_ATTEMPT_TIMEOUT + RETRY_READ_TIMEOUT < 60
    assert made[0].closed and not made[1].closed  # stalled pool dropped
    assert "retrying on a new one" in caplog.text


@pytest.mark.parametrize("error", [httpx.RemoteProtocolError, httpx.ReadError])
def test_broken_connections_are_retried_too(monkeypatch, error):
    transport, calls, _ = _transport(monkeypatch, [error, 200])
    assert _client(transport).get("/collections").status_code == 200
    assert len(calls) == 2


def test_a_read_that_fails_twice_raises(monkeypatch):
    transport, calls, _ = _transport(monkeypatch, [httpx.ReadTimeout, httpx.ReadTimeout])
    with pytest.raises(httpx.ReadTimeout):
        _client(transport).get("/collections")
    assert len(calls) == 2


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("PUT", "/collections/x"),  # create collection
        ("DELETE", "/collections/x"),
        ("PUT", "/collections/x/index"),  # create payload index
        ("PATCH", "/collections/x"),
        ("POST", "/collections/aliases"),
    ],
)
def test_collection_writes_are_never_retried(monkeypatch, method, path):
    """Creating a collection twice is an error, so such a write fails as it is."""
    transport, calls, _ = _transport(monkeypatch, [httpx.ReadTimeout, 200])
    with pytest.raises(httpx.ReadTimeout):
        _client(transport).request(method, path, json={})
    assert calls == [(method, 60)]  # one attempt, full timeout


@pytest.mark.parametrize(
    ("method", "path", "kind"),
    [
        ("GET", "/collections/x/exists", "read"),
        ("POST", "/collections/x/points", "read"),  # retrieve by ids
        ("POST", "/collections/x/points/scroll", "read"),
        ("POST", "/collections/x/points/count", "read"),
        ("POST", "/collections/x/points/query", "read"),
        ("POST", "/collections/x/points/query/batch", "read"),
        ("POST", "/collections/x/facet", "read"),
        ("PUT", "/collections/x/points", "point_write"),  # upsert
        ("POST", "/collections/x/points/delete", "point_write"),
        ("POST", "/collections/x/points/payload", "point_write"),
        ("POST", "/collections/x/points/batch", "point_write"),
        ("PUT", "/prefix/collections/x/points", "point_write"),  # URL with a path prefix
        ("PUT", "/collections/x", "other"),
        ("PUT", "/collections/x/index", "other"),
        ("DELETE", "/collections/x", "other"),
    ],
)
def test_request_kind(method, path, kind):
    assert qdrant_http.request_kind(method, path) == kind


@pytest.mark.parametrize("error", [httpx.WriteTimeout, httpx.ReadTimeout, httpx.WriteError])
def test_stalled_upsert_is_retried_on_a_new_connection(monkeypatch, error):
    """The production failure: a large upsert body stopped being accepted."""
    transport, calls, made = _transport(monkeypatch, [error, 200])
    res = _client(transport).put("/collections/sim_meta_records/points?wait=true", json={})
    assert res.status_code == 200
    # First attempt capped, the retry gets the full configured timeout.
    assert calls == [
        ("PUT", qdrant_http.FIRST_WRITE_ANSWER_TIMEOUT),
        ("PUT", 60),
    ]
    assert made[0].closed and transport.keepalive_disabled


def test_post_reads_are_retried_with_read_caps(monkeypatch):
    transport, calls, _ = _transport(monkeypatch, [httpx.ReadTimeout, 200])
    res = _client(transport).post("/collections/x/points/scroll", json={})
    assert res.status_code == 200
    assert calls == [("POST", FIRST_READ_ATTEMPT_TIMEOUT), ("POST", RETRY_READ_TIMEOUT)]


def test_an_upsert_that_fails_twice_raises(monkeypatch):
    transport, calls, _ = _transport(monkeypatch, [httpx.WriteTimeout, httpx.WriteTimeout])
    with pytest.raises(httpx.WriteTimeout):
        _client(transport).put("/collections/x/points", json={})
    assert len(calls) == 2


def test_first_attempt_caps_the_write_timeout(monkeypatch):
    seen = []

    class Recording(httpx.BaseTransport):
        def handle_request(self, request):
            seen.append(request.extensions["timeout"]["write"])
            return httpx.Response(200, json={})

    monkeypatch.setattr(ResilientTransport, "_new_transport", lambda self: Recording())
    _client(ResilientTransport("q.example.com")).put("/collections/x/points", json={})
    assert seen == [qdrant_http.FIRST_WRITE_ATTEMPT_TIMEOUT]


def test_batched_splits_by_count_and_size():
    sizes = [1, 1, 1, 5, 1, 9, 1]
    batches = list(qdrant_http.batched(sizes, lambda n: n, max_items=3, max_bytes=6))
    # An item over the byte cap still goes, alone in its batch.
    assert batches == [[1, 1, 1], [5, 1], [9], [1]]
    assert list(qdrant_http.batched([], lambda n: n, 3)) == []


def test_storage_error_code():
    from qdrant_client.http.exceptions import ResponseHandlingException

    def wrapped(inner):
        try:
            try:
                raise inner
            except Exception as exc:
                raise ResponseHandlingException(exc) from exc
        except Exception as outer:
            return outer

    req = httpx.Request("PUT", "https://q.example.com/collections/x/points")
    assert (
        qdrant_http.storage_error_code(wrapped(httpx.WriteTimeout("t", request=req)))
        == "storage_timeout"
    )
    assert (
        qdrant_http.storage_error_code(wrapped(httpx.ConnectError("refused", request=req)))
        == "storage_unreachable"
    )
    # A timeout outside qdrant-client (e.g. the embedding service) is not a storage error.
    assert qdrant_http.storage_error_code(httpx.ReadTimeout("t", request=req)) is None
    assert qdrant_http.storage_error_code(ValueError("x")) is None


def test_short_reads_keep_their_own_timeout(monkeypatch):
    transport, calls, _ = _transport(monkeypatch, [200])
    httpx.Client(base_url="https://q.example.com", transport=transport, timeout=5).get("/")
    assert calls == [("GET", 5)]


@pytest.mark.parametrize(("host", "keepalive"), [("127.0.0.1", 0), ("qdrant.example.com", 20)])
def test_keep_alive_is_off_for_local_hosts_only(host, keepalive):
    transport = ResilientTransport(host)
    try:
        assert transport._transport._pool._max_keepalive_connections == keepalive
    finally:
        transport.close()


def test_server_client_uses_the_transport_and_ipv4_loopback():
    from app.services.vector_store import server_client

    client = server_client("http://localhost:6333", None, check_compatibility=False)
    try:
        remote = client._client
        assert remote._host == "127.0.0.1" and remote._port == 6333
        http = remote.openapi_client.client._client
        assert isinstance(http._transport, ResilientTransport)
    finally:
        client.close()


def test_qdrant_check_survives_one_stalled_lookup(monkeypatch):
    """End to end through qdrant-client: a lookup that stalls once now passes."""
    from app.services.connections import test_qdrant

    stalled = {"done": False}

    def handler(request):
        if request.url.path.endswith("/exists") and not stalled["done"]:
            stalled["done"] = True
            raise httpx.ReadTimeout("stalled", request=request)
        if request.url.path == "/":
            return httpx.Response(200, json={"title": "qdrant", "version": "1.12.5"})
        if request.url.path == "/collections":
            return httpx.Response(200, json={"result": {"collections": []}, "status": "ok"})
        if request.url.path.endswith("/points/count"):
            # The large_request step: its whole padded body arrived.
            assert len(request.content) > 500_000
            return httpx.Response(404, json={"status": {"error": "Not found"}})
        return httpx.Response(200, json={"result": {"exists": False}, "status": "ok"})

    monkeypatch.setattr(
        ResilientTransport, "_new_transport", lambda self: httpx.MockTransport(handler)
    )
    result = test_qdrant("https://q.example.com", "k")
    assert result.ok, result
    assert all(step.ok for step in result.steps)
    assert qdrant_http.FIRST_READ_ATTEMPT_TIMEOUT < 60


def test_keep_alive_is_turned_off_after_the_first_stall(monkeypatch, caplog):
    """Runflare: every reused connection stalled. After one stall, stop reusing."""
    transport = ResilientTransport("qdrant.example.com")
    assert transport._transport._pool._max_keepalive_connections == 20

    stalls = {"left": 1}
    inner_cls = qdrant_http.httpx.HTTPTransport
    real_handle = inner_cls.handle_request

    def handle(self, request):
        if stalls["left"]:
            stalls["left"] -= 1
            raise httpx.ReadTimeout("stalled", request=request)
        return httpx.Response(200, json={})

    monkeypatch.setattr(inner_cls, "handle_request", handle)
    client = httpx.Client(base_url="https://q.example.com", transport=transport, timeout=60)
    assert client.get("/collections/a/exists").status_code == 200
    assert transport.keepalive_disabled
    assert transport._transport._pool._max_keepalive_connections == 0
    assert "new connection per request from now on" in caplog.text

    # Later requests go straight through on fresh connections; the notice is logged once.
    caplog.clear()
    assert client.get("/collections/b/exists").status_code == 200
    assert "from now on" not in caplog.text
    monkeypatch.setattr(inner_cls, "handle_request", real_handle)
    transport.close()


@pytest.mark.parametrize(
    ("platform", "host", "mss", "expected"),
    [
        ("linux", "qdrant.example.com", 1200, 1200),
        ("linux", "qdrant.example.com", 0, None),  # turned off
        ("linux", "127.0.0.1", 1200, None),  # loopback has no path to break
        ("win32", "qdrant.example.com", 1200, None),  # not honoured before connect
    ],
)
def test_segment_size_is_clamped_for_remote_hosts(monkeypatch, platform, host, mss, expected):
    """Large uploads stalled even on new connections (a path that drops
    full-size packets); smaller segments get through such a path."""
    import socket

    monkeypatch.setattr(qdrant_http.sys, "platform", platform)
    monkeypatch.setattr(socket, "TCP_MAXSEG", 2, raising=False)
    transport = ResilientTransport(host, tcp_mss=mss)
    try:
        backend = transport._transport._pool._network_backend
        if expected is None:
            assert not isinstance(backend, qdrant_http.ClampedSegmentBackend)
        else:
            assert backend.mss == expected
    finally:
        transport.close()


def test_clamped_backend_sets_the_segment_size_before_connecting(monkeypatch):
    import socket

    events = []

    class FakeSocket:
        def __init__(self, *args):
            pass

        def setsockopt(self, level, name, value):
            events.append(("opt", name, value))

        def settimeout(self, t):
            pass

        def connect(self, address):
            events.append(("connect", address))

        def close(self):
            pass

    monkeypatch.setattr(socket, "TCP_MAXSEG", 2, raising=False)
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 443))],
    )
    monkeypatch.setattr(socket, "socket", FakeSocket)
    qdrant_http.ClampedSegmentBackend(1200).connect_tcp("q.example.com", 443, timeout=5)
    assert events[0] == ("opt", 2, 1200)
    assert events.index(("connect", ("10.0.0.1", 443))) > 0


def test_server_client_passes_the_segment_size(monkeypatch):
    from app.services.vector_store import server_client

    monkeypatch.setattr(qdrant_http.sys, "platform", "linux")
    client = server_client("https://q.example.com", None, check_compatibility=False, tcp_mss=1000)
    try:
        transport = client._client.openapi_client.client._client._transport
        assert transport.tcp_mss == 1000
    finally:
        client.close()
