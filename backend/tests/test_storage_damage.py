"""Stored data Qdrant can no longer decode (a crash or full disk cut a write
short): reported with a stable code, skipped where a page can do without it,
and removable without touching what still reads fine."""

import uuid

import httpx
import pytest
from fastapi.testclient import TestClient
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse

from app.core.config import Settings
from app.main import create_app
from app.models import Record, Source
from app.services import pipeline
from app.services.qdrant_http import StorageIntegrityError, storage_error_code

API = "/api/v1"
RECORDS = "sim_meta_records"
LINES = ["قرارداد خرید تجهیزات شبکه", "گزارش مالی فصل بهار", "صورتجلسه هیئت مدیره شرکت"]


@pytest.fixture
def client(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path, qdrant_in_memory=True, jobs_inline=True)
    with TestClient(create_app(settings), raise_server_exceptions=False) as c:
        yield c


def decode_failure() -> UnexpectedResponse:
    """What Qdrant answered in production for a damaged payload."""
    body = (
        b'{"status":{"error":"Service internal error: 1 of 1 read operations failed:\\n'
        b"  Service internal error: Failed to decode value: Failed to decompress LZ4 value: "
        b'0 is not a valid match offset"},"time":0.0}'
    )
    return UnexpectedResponse(500, "Internal Server Error", body, None)


def _hex(point_id) -> str:
    return uuid.UUID(str(point_id)).hex


def damage(client, monkeypatch, record_ids):
    """Make every read that has to decode one of these records' payloads fail,
    as Qdrant does; reads that do not load the payload still work."""
    bad = {_hex(i) for i in record_ids}
    qdrant = client.app.state.services.client
    real_query, real_retrieve, real_scroll = qdrant.query_points, qdrant.retrieve, qdrant.scroll

    def check(collection, with_payload, ids):
        if collection == RECORDS and with_payload and any(_hex(i) in bad for i in ids):
            raise decode_failure()

    def query_points(collection, **kw):
        res = real_query(collection, **kw)
        check(collection, kw.get("with_payload"), [p.id for p in res.points])
        return res

    def retrieve(collection, ids, **kw):
        check(collection, kw.get("with_payload"), ids)
        return real_retrieve(collection, ids=ids, **kw)

    def scroll(collection, **kw):
        points, offset = real_scroll(collection, **kw)
        check(collection, kw.get("with_payload"), [p.id for p in points])
        return points, offset

    monkeypatch.setattr(qdrant, "query_points", query_points)
    monkeypatch.setattr(qdrant, "retrieve", retrieve)
    monkeypatch.setattr(qdrant, "scroll", scroll)


def loaded_repo(client):
    repo = client.post(f"{API}/repos", json={"name": "r", "config": {}}).json()
    res = client.post(
        f"{API}/repos/{repo['id']}/ingest",
        data={"input_kind": "text", "split": "lines", "text": "\n".join(LINES)},
    )
    job = res.json()
    assert job["status"] == "done", job
    items = client.get(f"{API}/jobs/{job['id']}/records", params={"sort": "ordinal"}).json()
    return repo, job, [i["id"] for i in items["items"]]


def test_error_codes():
    assert storage_error_code(decode_failure()) == "storage_corrupt"
    assert storage_error_code(StorageIntegrityError("x")) == "storage_corrupt"
    other = UnexpectedResponse(500, "Internal Server Error", b'{"status":{"error":"oom"}}', None)
    assert storage_error_code(other) == "storage_error"
    # A refused request is the caller's problem, not the storage's.
    denied = UnexpectedResponse(403, "Forbidden", b'{"status":{"error":"read only"}}', None)
    assert storage_error_code(denied) is None
    assert pipeline.job_error_code(decode_failure()) == "storage_corrupt"


def test_a_damaged_record_is_reported_with_a_code_not_as_a_crash(client, monkeypatch):
    _, job, ids = loaded_repo(client)
    damage(client, monkeypatch, [ids[1]])
    res = client.get(f"{API}/jobs/{job['id']}/records")
    assert res.status_code == 503, res.text
    detail = res.json()["detail"]
    assert detail["code"] == "storage_corrupt" and "decompress" in detail["message"]


def test_chunk_browser_leaves_damaged_records_out_and_says_so(client, monkeypatch):
    repo, _, ids = loaded_repo(client)
    damage(client, monkeypatch, [ids[1]])
    res = client.get(f"{API}/repos/{repo['id']}/chunks")
    assert res.status_code == 200, res.text
    page = res.json()
    assert [r["record_id"] for r in page["items"]] == [ids[0], ids[2]]
    assert page["unreadable"] == 1


def test_healthy_page_reports_nothing_unreadable(client):
    repo, _, ids = loaded_repo(client)
    page = client.get(f"{API}/repos/{repo['id']}/chunks").json()
    assert len(page["items"]) == len(ids) and page["unreadable"] == 0


def test_repair_removes_only_what_cannot_be_read(client, monkeypatch):
    repo, job, ids = loaded_repo(client)
    services = client.app.state.services
    chunks_before = client.get(f"{API}/repos/{repo['id']}").json()["chunk_count"]
    damage(client, monkeypatch, [ids[1]])

    res = client.post(f"{API}/repos/{repo['id']}/repair")
    assert res.status_code == 200, res.text
    assert res.json() == {"records_removed": 1, "matches_removed": 0}

    # Everything reads again, without the damaged record or its chunks.
    items = client.get(f"{API}/jobs/{job['id']}/records", params={"sort": "ordinal"}).json()
    assert [i["id"] for i in items["items"]] == [ids[0], ids[2]]
    assert client.get(f"{API}/repos/{repo['id']}").json()["chunk_count"] < chunks_before
    assert services.store.chunks(repo["id"], [ids[1]], 0, 100) == []
    # Paging walks the sources by their record counts, so they must follow.
    (source,) = services.meta.all(Source, {"repo_id": repo["id"]})
    assert source.record_count == 2
    page = client.get(f"{API}/repos/{repo['id']}/chunks").json()
    assert page["total"] == 2 and page["unreadable"] == 0

    # Nothing left to do the second time.
    again = client.post(f"{API}/repos/{repo['id']}/repair").json()
    assert again == {"records_removed": 0, "matches_removed": 0}


def test_repair_leaves_a_healthy_repo_alone(client):
    repo, _, ids = loaded_repo(client)
    res = client.post(f"{API}/repos/{repo['id']}/repair")
    assert res.json() == {"records_removed": 0, "matches_removed": 0}
    services = client.app.state.services
    assert len(services.meta.all(Record, {"repo_id": repo["id"]})) == len(ids)


@pytest.mark.parametrize("failure", ["outage", "other_500"])
def test_repair_never_mistakes_an_outage_for_damage(client, monkeypatch, failure):
    """Only a decode failure marks a record as lost; anything else stops the repair."""
    repo, _, ids = loaded_repo(client)
    services = client.app.state.services

    def broken(*args, **kwargs):
        if failure == "outage":
            req = httpx.Request("POST", "https://q.example.com/collections/x/points")
            raise ResponseHandlingException(httpx.ConnectError("refused", request=req))
        raise UnexpectedResponse(500, "Internal Server Error", b'{"status":{"error":"oom"}}', None)

    with monkeypatch.context() as patched:
        patched.setattr(services.client, "retrieve", broken)
        res = client.post(f"{API}/repos/{repo['id']}/repair")
    assert res.status_code == 503
    assert res.json()["detail"]["code"] in {"storage_unreachable", "storage_error"}
    assert len(services.meta.all(Record, {"repo_id": repo["id"]})) == len(ids)


def test_a_write_that_cannot_be_read_back_fails_the_load(client, monkeypatch):
    """Against a server, each batch is read back right after it is written."""
    repo = client.post(f"{API}/repos", json={"name": "r", "config": {}}).json()
    services = client.app.state.services
    monkeypatch.setattr(services.meta, "_server", True)
    real_retrieve = services.client.retrieve

    def retrieve(collection, ids, **kw):
        if collection == RECORDS:
            raise decode_failure()
        return real_retrieve(collection, ids=ids, **kw)

    monkeypatch.setattr(services.client, "retrieve", retrieve)
    res = client.post(
        f"{API}/repos/{repo['id']}/ingest",
        data={"input_kind": "text", "split": "lines", "text": "\n".join(LINES)},
    )
    assert res.status_code == 503, res.text
    assert res.json()["detail"]["code"] == "storage_corrupt"
    # The half-stored load is removed again.
    assert services.meta.all(Source, {"repo_id": repo["id"]}) == []
    assert services.meta.count(Record, {"repo_id": repo["id"]}) == 0


def test_points_missing_after_a_write_are_an_integrity_error(client, monkeypatch):
    services = client.app.state.services
    monkeypatch.setattr(services.meta, "_server", True)
    monkeypatch.setattr(services.client, "retrieve", lambda *a, **k: [])
    with pytest.raises(StorageIntegrityError):
        services.meta.put(Source(repo_id="r", name="s", kind="list"))
