"""Second-stage scoring, with a stand-in for the cross-encoder model."""

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.services import pipeline, rerank

API = "/api/v1"

GOVERNANCE = "حاکمیت داده و مالکیت دارایی های داده"
QUALITY = "کیفیت داده و پایش دقت داده ها"
# Shares almost every word with GOVERNANCE but is not a correct mapping.
LOOKALIKE = "حاکمیت داده و مالکیت دارایی های ساختمان"
# Shares no vocabulary with QUALITY but is a correct mapping.
PARAPHRASE = "کاهش خطا در اطلاعات مشتریان"
MAPPED = {frozenset((PARAPHRASE, QUALITY))}


class FakeReranker:
    def __init__(self):
        self.calls: list[list[tuple[str, str]]] = []

    def score(self, pairs):
        self.calls.append(pairs)
        return [0.9 if frozenset(p) in MAPPED else 0.02 for p in pairs]


@pytest.fixture
def fake(monkeypatch):
    fake = FakeReranker()
    monkeypatch.setattr(pipeline, "get_reranker", lambda model, settings: fake)
    return fake


@pytest.fixture
def client(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path, qdrant_in_memory=True, jobs_inline=True)
    with TestClient(create_app(settings)) as c:
        yield c


def make_repo(client, **similarity):
    res = client.post(f"{API}/repos", json={"name": "dmm", "config": {"similarity": similarity}})
    assert res.status_code == 201, res.text
    return res.json()


def ingest(client, repo_id, lines, mode="check_and_index"):
    res = client.post(
        f"{API}/repos/{repo_id}/ingest",
        data={"input_kind": "text", "split": "lines", "mode": mode, "text": "\n".join(lines)},
    )
    assert res.json()["status"] == "done", res.text
    return res.json()


def records(client, job_id):
    return client.get(f"{API}/jobs/{job_id}/records", params={"sort": "ordinal"}).json()["items"]


def test_second_stage_score_replaces_the_vector_score(client, fake):
    repo = make_repo(client, rerank="cross_encoder", similar_threshold=0.3, duplicate_threshold=0.6)
    ingest(client, repo["id"], [GOVERNANCE, QUALITY], mode="index_only")
    job = ingest(client, repo["id"], [LOOKALIKE, PARAPHRASE], mode="check_only")
    lookalike, paraphrase = records(client, job["id"])

    # High word overlap, rejected by the second stage.
    assert lookalike["max_score"] == pytest.approx(0.02)
    assert lookalike["status"] == "unique"
    match = client.get(f"{API}/records/{lookalike['id']}/matches").json()[0]
    assert match["matched_text"] == GOVERNANCE
    assert match["score"] == pytest.approx(0.02)
    assert match["vector_score"] > 0.7  # the first stage alone would have flagged it

    # No word overlap, confirmed by the second stage.
    assert paraphrase["max_score"] == pytest.approx(0.9)
    assert paraphrase["status"] == "duplicate"

    assert all(len(p) == 2 for call in fake.calls for p in call)


def test_matches_are_stored_by_first_stage_floor_and_ordered_by_final_score(client, fake):
    repo = make_repo(client, rerank="cross_encoder")
    ingest(client, repo["id"], [GOVERNANCE, QUALITY], mode="index_only")
    job = ingest(client, repo["id"], [LOOKALIKE], mode="check_only")
    item = records(client, job["id"])[0]
    matches = client.get(f"{API}/records/{item['id']}/matches").json()
    # 0.02 is far below the 0.3 storage floor, yet the candidate is kept: the
    # floor applies to the vector score, which is on a different scale.
    assert [m["matched_text"] for m in matches][0] == GOVERNANCE
    assert all(m["vector_score"] >= 0.3 for m in matches)
    assert [m["score"] for m in matches] == sorted((m["score"] for m in matches), reverse=True)


def test_search_is_reranked_the_same_way(client, fake):
    repo = make_repo(client, rerank="cross_encoder")
    ingest(client, repo["id"], [GOVERNANCE, QUALITY], mode="index_only")
    query = "حاکمیت داده و مالکیت"  # the vector stage prefers GOVERNANCE
    fake_mapped = MAPPED | {frozenset((query, QUALITY))}
    fake.score = lambda pairs: [0.9 if frozenset(p) in fake_mapped else 0.02 for p in pairs]
    hits = client.post(f"{API}/repos/{repo['id']}/search", json={"query": query}).json()
    assert hits[0]["text"] == QUALITY and hits[0]["score"] == pytest.approx(0.9)
    assert hits[0]["vector_score"] < hits[1]["vector_score"]  # stage two reordered them


def test_without_a_second_stage_nothing_changes(client, fake):
    repo = make_repo(client)
    ingest(client, repo["id"], [GOVERNANCE], mode="index_only")
    job = ingest(client, repo["id"], [LOOKALIKE], mode="check_only")
    item = records(client, job["id"])[0]
    match = client.get(f"{API}/records/{item['id']}/matches").json()[0]
    assert match["vector_score"] is None and match["score"] == pytest.approx(item["max_score"])
    assert fake.calls == []


def test_meta_lists_rerankers(client):
    info = client.get(f"{API}/meta").json()["rerankers"]
    assert info["available"] is rerank.available()
    assert "BAAI/bge-reranker-v2-m3-int8" in info["models"]


def test_cross_encoder_score_is_symmetric_and_bounded():
    class Model:
        def rerank_pairs(self, pairs):
            return [4.0 if a < b else -4.0 for a, b in pairs]

    encoder = rerank.CrossEncoderReranker.__new__(rerank.CrossEncoderReranker)
    encoder._model = Model()
    forward, backward = encoder.score([("a", "b"), ("b", "a")])
    assert forward == backward == pytest.approx(1 / (1 + 2.718281828459045**-4))
    assert encoder.score([]) == []
