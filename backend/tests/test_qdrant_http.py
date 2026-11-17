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


@pytest.mark.parametrize("method", ["PUT", "POST", "PATCH", "DELETE"])
def test_writes_are_never_retried(monkeypatch, method):
    """Creating a collection twice is an error, so a write fails as it is."""
    transport, calls, _ = _transport(monkeypatch, [httpx.ReadTimeout, 200])
    with pytest.raises(httpx.ReadTimeout):
        _client(transport).request(method, "/collections/x", json={})
    assert calls == [(method, 60)]  # one attempt, full timeout


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
        return httpx.Response(200, json={"result": {"exists": False}, "status": "ok"})

    monkeypatch.setattr(
        ResilientTransport, "_new_transport", lambda self: httpx.MockTransport(handler)
    )
    result = test_qdrant("https://q.example.com", "k")
    assert result.ok, result
    assert all(step.ok for step in result.steps)
    assert qdrant_http.FIRST_READ_ATTEMPT_TIMEOUT < 60
