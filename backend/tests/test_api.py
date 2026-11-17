import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

API = "/api/v1"


@pytest.fixture
def client(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path, qdrant_in_memory=True, jobs_inline=True)
    with TestClient(create_app(settings)) as c:
        yield c


def make_repo(client, name="مخزن آزمایشی", **similarity):
    config = {"similarity": similarity} if similarity else {}
    res = client.post(f"{API}/repos", json={"name": name, "config": config})
    assert res.status_code == 201, res.text
    return res.json()


def ingest_lines(client, repo_id, lines, mode="check_and_index"):
    res = client.post(
        f"{API}/repos/{repo_id}/ingest",
        data={"input_kind": "text", "split": "lines", "mode": mode, "text": "\n".join(lines)},
    )
    assert res.status_code == 202, res.text
    job = res.json()
    assert job["status"] == "done", job
    return job


def records(client, job_id, **params):
    res = client.get(f"{API}/jobs/{job_id}/records", params={"sort": "ordinal", **params})
    return res.json()["items"]


def test_first_load_has_nothing_to_match(client):
    repo = make_repo(client)
    job = ingest_lines(client, repo["id"], ["قرارداد خرید تجهیزات شبکه", "گزارش مالی فصل بهار"])
    items = records(client, job["id"])
    assert items[0]["max_score"] == 0  # nothing existed before the first record
    assert all(i["status"] == "unique" for i in items)


def test_duplicate_within_same_load_is_detected(client):
    """Record N is compared with records 1..N-1 of the same load."""
    repo = make_repo(client)
    job = ingest_lines(
        client,
        repo["id"],
        ["قرارداد خرید تجهیزات شبکه", "گزارش مالی فصل بهار", "قرارداد خرید تجهیزات شبکه"],
    )
    items = records(client, job["id"])
    assert items[2]["status"] == "duplicate"
    assert items[2]["max_score"] > 0.99


def test_later_load_matches_earlier_one_with_arabic_variants(client):
    repo = make_repo(client)
    ingest_lines(client, repo["id"], ["کتاب علی درباره یادگیری ماشین"])
    job = ingest_lines(client, repo["id"], ["كتاب علي درباره يادگيري ماشين", "هواشناسی فردا"])
    items = records(client, job["id"])
    assert items[0]["status"] == "duplicate"
    assert items[1]["max_score"] < items[0]["max_score"]

    matches = client.get(f"{API}/records/{items[0]['id']}/matches").json()
    assert matches[0]["matched_text"] == "کتاب علی درباره یادگیری ماشین"
    assert matches[0]["matched_repo_name"] == repo["name"]

    summary = client.get(f"{API}/jobs/{job['id']}/summary").json()
    assert summary["total"] == 2 and summary["duplicate"] == 1


def test_check_only_does_not_index(client):
    repo = make_repo(client)
    ingest_lines(client, repo["id"], ["متن پایه برای مقایسه"])
    ingest_lines(client, repo["id"], ["متن پایه برای مقایسه"], mode="check_only")
    # A third identical load must still see exactly one indexed hit.
    job = ingest_lines(client, repo["id"], ["متن پایه برای مقایسه"], mode="check_only")
    assert records(client, job["id"])[0]["match_count"] == 1
    assert client.get(f"{API}/repos/{repo['id']}").json()["record_count"] == 1


def test_cross_repo_scope(client):
    base = make_repo(client, "پایه")
    ingest_lines(client, base["id"], ["آیین‌نامه ایمنی کارگاه ساختمانی"])
    isolated = make_repo(client, "جدا")
    job = ingest_lines(client, isolated["id"], ["آیین‌نامه ایمنی کارگاه ساختمانی"])
    assert records(client, job["id"])[0]["status"] == "unique"

    linked = make_repo(client, "همه", scope="all")
    job = ingest_lines(client, linked["id"], ["آیین‌نامه ایمنی کارگاه ساختمانی"])
    item = records(client, job["id"])[0]
    assert item["status"] == "duplicate"
    matches = client.get(f"{API}/records/{item['id']}/matches").json()
    assert {m["matched_repo_name"] for m in matches} == {"پایه", "جدا"}


@pytest.mark.parametrize("scale", [1.0, 7.0])
def test_every_distance_metric_scores_on_the_same_scale(client, monkeypatch, scale):
    """Same statuses and scores under cosine, dot and euclid — also when the
    model returns vectors that are not unit length."""
    from app.services.embeddings import HashEmbedder

    unit = HashEmbedder.embed
    monkeypatch.setattr(
        HashEmbedder,
        "embed",
        lambda self, texts: [[x * scale for x in v] for v in unit(self, texts)],
    )
    base = "قرارداد خرید تجهیزات شبکه برای دفتر مرکزی شرکت"
    probes = [base, base.replace("شرکت", "سازمان"), "هواشناسی فردا بارانی است"]
    seen = {}
    for distance in ("cosine", "dot", "euclid"):
        res = client.post(
            f"{API}/repos", json={"name": distance, "config": {"embedding": {"distance": distance}}}
        )
        repo = res.json()
        ingest_lines(client, repo["id"], [base])
        items = records(client, ingest_lines(client, repo["id"], probes)["id"])
        assert [i["status"] for i in items] == ["duplicate", "similar", "unique"], distance
        assert items[2]["match_count"] == 0, distance  # below the storage floor
        hits = client.post(f"{API}/repos/{repo['id']}/search", json={"query": probes[1]}).json()
        seen[distance] = [i["max_score"] for i in items] + [h["score"] for h in hits]
    assert seen["dot"] == pytest.approx(seen["cosine"], abs=1e-4)
    assert seen["euclid"] == pytest.approx(seen["cosine"], abs=1e-4)


def test_mean_aggregation_scores_a_half_known_record_lower(client):
    known = "قرارداد خرید تجهیزات شبکه منعقد شد."
    half = f"{known} هواشناسی فردا بارانی و سرد خواهد بود."
    scores = {}
    for aggregation in ("max", "mean"):
        config = {
            "chunking": {"strategy": "sentence", "chunk_size": 40, "overlap": 0},
            "similarity": {"aggregation": aggregation},
        }
        repo = client.post(f"{API}/repos", json={"name": aggregation, "config": config}).json()
        ingest_lines(client, repo["id"], [known])
        item = records(client, ingest_lines(client, repo["id"], [half])["id"])[0]
        assert item["chunk_count"] == 2
        scores[aggregation] = item["max_score"]
    assert scores["max"] > 0.99
    assert 0.4 < scores["mean"] < 0.75


def test_threshold_change_is_retroactive_and_index_change_needs_reindex(client):
    repo = make_repo(client)
    ingest_lines(client, repo["id"], ["گزارش عملکرد سالانه شرکت"])
    job = ingest_lines(client, repo["id"], ["گزارش عملکرد ماهانه شرکت"])
    score = records(client, job["id"])[0]["max_score"]
    assert 0.3 < score < 0.99

    config = repo["config"]
    config["similarity"]["similar_threshold"] = 0.01
    config["similarity"]["duplicate_threshold"] = min(score, 0.99) - 0.01
    res = client.patch(f"{API}/repos/{repo['id']}", json={"config": config})
    assert res.json()["needs_reindex"] is False
    assert records(client, job["id"])[0]["status"] == "duplicate"

    config["chunking"] = {"strategy": "fixed", "chunk_size": 20, "overlap": 5, "min_chars": 3}
    res = client.patch(f"{API}/repos/{repo['id']}", json={"config": config})
    assert res.json()["needs_reindex"] is True
    blocked = client.post(
        f"{API}/repos/{repo['id']}/ingest", data={"input_kind": "text", "text": "x y z"}
    )
    assert blocked.status_code == 409

    assert client.post(f"{API}/repos/{repo['id']}/reindex").json()["status"] == "done"
    after = client.get(f"{API}/repos/{repo['id']}").json()
    assert after["needs_reindex"] is False
    assert after["chunk_count"] > after["record_count"]


def test_file_preview_ingest_and_source_delete(client):
    repo = make_repo(client)
    csv_bytes = "کد,شرح\n1,نصب دوربین مداربسته\n2,نصب دوربین مدار بسته\n".encode()
    preview = client.post(
        f"{API}/sources/preview", files={"file": ("items.csv", csv_bytes, "text/csv")}
    ).json()
    assert preview["columns"] == ["کد", "شرح"] and preview["total_rows"] == 2

    res = client.post(
        f"{API}/repos/{repo['id']}/ingest",
        data={"input_kind": "file", "options": '{"text_columns": ["شرح"]}'},
        files={"file": ("items.csv", csv_bytes, "text/csv")},
    )
    job = res.json()
    items = records(client, job["id"])
    assert items[0]["text"] == "نصب دوربین مداربسته"
    assert items[1]["max_score"] > 0.6

    export = client.get(f"{API}/jobs/{job['id']}/export.csv")
    assert export.text.startswith("﻿") and "نصب دوربین" in export.text

    sources = client.get(f"{API}/repos/{repo['id']}/sources").json()
    assert sources[0]["last_job_id"] == job["id"]
    assert client.delete(f"{API}/sources/{sources[0]['id']}").status_code == 204
    assert client.get(f"{API}/repos/{repo['id']}").json()["chunk_count"] == 0
    # Vectors are gone too: the same text is unique again.
    job = ingest_lines(client, repo["id"], ["نصب دوربین مداربسته"])
    assert records(client, job["id"])[0]["status"] == "unique"


def test_validation_and_errors(client):
    repo = make_repo(client)
    assert client.post(f"{API}/repos", json={"name": repo["name"]}).status_code == 409
    bad = {"chunking": {"chunk_size": 50, "overlap": 50}}
    assert client.post(f"{API}/repos", json={"name": "x", "config": bad}).status_code == 422
    empty = client.post(
        f"{API}/repos/{repo['id']}/ingest", data={"input_kind": "text", "text": "  \n "}
    )
    assert empty.status_code == 400 and empty.json()["detail"] == "empty_input"
    unsupported = client.post(
        f"{API}/sources/preview", files={"file": ("a.exe", b"abc", "application/octet-stream")}
    )
    assert unsupported.json()["detail"] == "unsupported_file_type"


def test_search_and_index_status(client):
    repo = make_repo(client)
    empty = client.get(f"{API}/repos/{repo['id']}/index").json()
    assert empty["searchable"] is False and empty["problem"] == "index_empty"
    assert client.post(f"{API}/repos/{repo['id']}/search", json={"query": "هر چیزی"}).json() == []

    ingest_lines(client, repo["id"], ["قرارداد خرید تجهیزات شبکه", "گزارش مالی فصل بهار"])
    status = client.get(f"{API}/repos/{repo['id']}/index").json()
    assert status["searchable"] is True and status["points"] == 2
    assert status["vector_size"] == 512 and status["distance"] == "cosine"

    # The query is normalized like indexed text: Arabic letter forms still hit.
    hits = client.post(
        f"{API}/repos/{repo['id']}/search", json={"query": "قرارداد خريد تجهيزات شبكه", "top_k": 1}
    ).json()
    assert len(hits) == 1 and hits[0]["text"] == "قرارداد خرید تجهیزات شبکه"
    assert hits[0]["score"] > 0.99 and hits[0]["source_name"]

    config = repo["config"]
    config["embedding"]["model"] = "char-ngram-1024"
    client.patch(f"{API}/repos/{repo['id']}", json={"config": config})
    assert client.get(f"{API}/repos/{repo['id']}/index").json()["problem"] == "repo_needs_reindex"
    blocked = client.post(f"{API}/repos/{repo['id']}/search", json={"query": "x"})
    assert blocked.status_code == 409

    client.post(f"{API}/repos/{repo['id']}/reindex")
    status = client.get(f"{API}/repos/{repo['id']}/index").json()
    assert status["searchable"] is True and status["vector_size"] == 1024


def test_browse_chunks(client):
    repo = make_repo(client)
    url = f"{API}/repos/{repo['id']}/chunks"
    assert client.get(url).json()["total"] == 0

    config = repo["config"]
    config["chunking"] = {"strategy": "fixed", "chunk_size": 20, "overlap": 5, "min_chars": 3}
    client.patch(f"{API}/repos/{repo['id']}", json={"config": config})
    long_line = " ".join(f"واژه{i}" for i in range(60))
    ingest_lines(client, repo["id"], [long_line, "گزارش کوتاه"])
    ingest_lines(client, repo["id"], ["منبع دوم"])
    ingest_lines(client, repo["id"], ["فقط بررسی"], mode="check_only")

    page = client.get(url).json()
    assert page["total"] == 3  # check-only records are not in the index
    first = page["items"][0]
    order = [(i["source_id"] == first["source_id"], i["ordinal"]) for i in page["items"]]
    assert order == [(True, 1), (True, 2), (False, 1)]  # oldest source first, then rows
    assert first["chunk_count"] > 5 and first["source_name"]
    assert [c["chunk_index"] for c in first["chunks"]] == [0, 1, 2, 3, 4]
    short = page["items"][1]["chunks"]
    assert [(c["chunk_index"], c["text"]) for c in short] == [(0, "گزارش کوتاه")]

    # The rest of a long record is read in order, a window at a time.
    rest = client.get(f"{API}/records/{first['record_id']}/chunks", params={"offset": 5}).json()
    assert [c["chunk_index"] for c in rest] == list(range(5, first["chunk_count"]))
    assert client.get(f"{API}/records/{'0' * 32}/chunks").status_code == 404

    second = client.get(url, params={"page": 2, "page_size": 2}).json()
    assert [i["chunks"][0]["text"] for i in second["items"]] == ["منبع دوم"]
    only = client.get(url, params={"source_id": second["items"][0]["source_id"]}).json()
    assert only["total"] == 1 and only["items"][0]["record_id"] == second["items"][0]["record_id"]

    # Text search: matching chunks only, grouped by record, most matches first.
    ingest_lines(client, repo["id"], ["Annual Report"])
    found = client.get(url, params={"q": " واژه1 "}).json()
    assert found["total"] == 1 and not found["truncated"]
    hit = found["items"][0]
    assert hit["record_id"] == first["record_id"] and hit["chunk_count"] == first["chunk_count"]
    assert hit["match_count"] == len(hit["chunks"]) >= 2
    assert all("واژه1" in c["text"] for c in hit["chunks"])
    assert [c["chunk_index"] for c in hit["chunks"]] == sorted(
        c["chunk_index"] for c in hit["chunks"]
    )
    assert client.get(url, params={"q": "annual report"}).json()["total"] == 1  # other casing
    assert client.get(url, params={"q": "report annual"}).json()["total"] == 0  # a phrase
    assert client.get(url, params={"q": "منبع"}).json()["total"] == 1
    assert (
        client.get(url, params={"q": "منبع", "source_id": first["source_id"]}).json()["total"] == 0
    )
    assert client.get(url, params={"q": "بررسی"}).json()["total"] == 0  # check-only: not indexed
    assert client.get(url, params={"q": "نیست"}).json() == {
        "items": [],
        "total": 0,
        "page": 1,
        "page_size": 20,
        "truncated": False,
    }
    assert client.get(url, params={"q": "   "}).json()["total"] == 4  # blank: no search
    assert client.get(url, params={"q": "x" * 201}).status_code == 422


def test_edit_delete_and_add_chunks(client):
    repo = make_repo(client)
    config = repo["config"]
    config["chunking"] = {"strategy": "fixed", "chunk_size": 20, "overlap": 5, "min_chars": 3}
    client.patch(f"{API}/repos/{repo['id']}", json={"config": config})
    long_line = " ".join(f"واژه{i}" for i in range(60))
    ingest_lines(client, repo["id"], [long_line, "گزارش مالی فصل بهار"])
    url = f"{API}/repos/{repo['id']}/chunks"
    long, short = client.get(url).json()["items"]
    rid, total = long["record_id"], long["chunk_count"]
    chunks_url = f"{API}/records/{rid}/chunks"
    search = f"{API}/repos/{repo['id']}/search"
    new_text = "قرارداد خرید تجهیزات شبکه"

    def texts():
        got = client.get(chunks_url, params={"limit": 200}).json()
        assert [c["chunk_index"] for c in got] == list(range(len(got)))  # no gaps
        return [c["text"] for c in got]

    def best(query):
        return client.post(search, json={"query": query, "top_k": 1}).json()[0]

    before = texts()
    target = long["chunks"][1]

    # Edit: the text is replaced in place and searchable under its new wording.
    res = client.patch(f"{chunks_url}/{target['id']}", json={"text": f"  {new_text}  "})
    assert res.status_code == 200, res.text
    assert res.json() == {"id": target["id"], "chunk_index": 1, "text": new_text}
    assert texts() == [before[0], new_text, *before[2:]]
    hit = best(new_text)
    assert hit["score"] > 0.99 and hit["record_id"] == rid and hit["chunk_index"] == 1

    assert client.patch(f"{chunks_url}/{target['id']}", json={"text": "   "}).status_code == 422
    assert client.patch(f"{chunks_url}/not-an-id", json={"text": "x"}).status_code == 404
    other = f"{API}/records/{short['record_id']}/chunks/{target['id']}"
    assert client.patch(other, json={"text": "x"}).json()["detail"] == "chunk_not_found"
    assert client.delete(other).status_code == 404

    # Delete: later chunks move up, counts follow, and it no longer matches.
    assert client.delete(f"{chunks_url}/{target['id']}").status_code == 204
    assert texts() == [before[0], *before[2:]]
    assert client.delete(f"{chunks_url}/{target['id']}").status_code == 404
    after = client.get(url).json()["items"][0]
    assert after["chunk_count"] == total - 1 and len(after["chunks"]) == 5
    assert client.get(f"{API}/repos/{repo['id']}").json()["chunk_count"] == total
    assert best(new_text)["score"] < 0.99

    # Add: the new chunk goes to the end of the record and is searchable.
    res = client.post(chunks_url, json={"text": f" {new_text} "})
    assert res.status_code == 201, res.text
    added = res.json()
    assert (added["chunk_index"], added["text"]) == (total - 1, new_text)
    assert texts() == [before[0], *before[2:], new_text]
    assert client.get(url).json()["items"][0]["chunk_count"] == total
    assert client.get(f"{API}/repos/{repo['id']}").json()["chunk_count"] == total + 1
    hit = best(new_text)
    assert hit["score"] > 0.99 and hit["chunk_index"] == total - 1
    assert client.post(chunks_url, json={"text": " "}).status_code == 422
    assert client.post(f"{API}/records/{'0' * 32}/chunks", json={"text": "x"}).status_code == 404

    # A record can lose its last chunk and get a new first one.
    short_url = f"{API}/records/{short['record_id']}/chunks"
    assert client.delete(f"{short_url}/{short['chunks'][0]['id']}").status_code == 204
    emptied = client.get(url).json()["items"][1]
    assert emptied["chunk_count"] == 0 and emptied["chunks"] == []
    assert client.post(short_url, json={"text": "متن تازه"}).json()["chunk_index"] == 0

    # Records that were only checked are not in the index and take no chunks.
    job = ingest_lines(client, repo["id"], ["فقط بررسی"], mode="check_only")
    unindexed = client.post(
        f"{API}/records/{records(client, job['id'])[0]['id']}/chunks", json={"text": "x"}
    )
    assert unindexed.status_code == 409 and unindexed.json()["detail"] == "record_not_indexed"

    # Edits are refused while the stored vectors no longer match the config.
    config["embedding"]["model"] = "char-ngram-1024"
    client.patch(f"{API}/repos/{repo['id']}", json={"config": config})
    blocked = client.patch(f"{chunks_url}/{long['chunks'][0]['id']}", json={"text": "متن تازه"})
    assert blocked.status_code == 409 and blocked.json()["detail"] == "repo_needs_reindex"
    assert client.post(chunks_url, json={"text": "متن تازه"}).status_code == 409


def test_results_are_paged_in_score_order(client):
    repo = make_repo(client)
    lines = [f"سند شماره {i} درباره موضوع {i * 7}" for i in range(1, 31)]
    ingest_lines(client, repo["id"], lines, mode="index_only")
    job = ingest_lines(client, repo["id"], lines[:10] + ["متن کاملا بی ربط xyz"], mode="check_only")
    url = f"{API}/jobs/{job['id']}/records"
    first = client.get(url, params={"page_size": 5, "page": 1}).json()
    second = client.get(url, params={"page_size": 5, "page": 2}).json()
    third = client.get(url, params={"page_size": 5, "page": 3}).json()
    scores = [r["max_score"] for p in (first, second, third) for r in p["items"]]
    assert first["total"] == 11 and len(scores) == 11
    assert scores == sorted(scores, reverse=True)
    ids = {r["id"] for p in (first, second, third) for r in p["items"]}
    assert len(ids) == 11  # no row repeated or dropped across pages
    assert client.get(f"{API}/stats").json()["chunks"] == 30


def test_legacy_sqlite_is_imported_once(tmp_path):
    import sqlite3

    db = tmp_path / "similarityly.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE repos (id, name, description, config, vector_size, needs_reindex, created_at);
        CREATE TABLE sources (id, repo_id, name, kind, record_count, indexed, created_at);
        CREATE TABLE records (id, repo_id, source_id, ordinal, text, meta, chunk_count,
                              max_score, match_count);
        CREATE TABLE jobs (id, repo_id, source_id, kind, mode, status, total, processed, error,
                           created_at, finished_at);
        CREATE TABLE matches (id, job_id, record_id, chunk_index, chunk_text, score,
                              matched_repo_id, matched_source_id, matched_record_id,
                              matched_chunk_index, matched_text);
        """
    )
    r, s, j = "a" * 32, "b" * 32, "c" * 32
    r1, r2, m = "d" * 32, "e" * 32, "f" * 32
    ts = "2026-11-15 20:00:00.000000"
    conn.execute("INSERT INTO repos VALUES (?,?,?,?,?,?,?)", (r, "قدیمی", "", "{}", None, 0, ts))
    conn.execute("INSERT INTO sources VALUES (?,?,?,?,?,?,?)", (s, r, "منبع", "list", 2, 1, ts))
    conn.execute(
        "INSERT INTO records VALUES (?,?,?,?,?,?,?,?,?)", (r1, r, s, 1, "الف", "{}", 1, None, 0)
    )
    conn.execute(
        "INSERT INTO records VALUES (?,?,?,?,?,?,?,?,?)", (r2, r, s, 2, "ب", "{}", 1, 0.95, 1)
    )
    conn.execute(
        "INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (j, r, s, "ingest", "check_and_index", "done", 2, 2, None, ts, ts),
    )
    conn.execute(
        "INSERT INTO matches VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (m, j, r2, 0, "ب", 0.95, r, s, r1, 0, "الف"),
    )
    conn.commit()
    conn.close()

    settings = Settings(_env_file=None, data_dir=tmp_path, qdrant_in_memory=True, jobs_inline=True)
    with TestClient(create_app(settings)) as c:
        assert [x["name"] for x in c.get(f"{API}/repos").json()] == ["قدیمی"]
        items = records(c, j)
        assert [i["status"] for i in items] == ["unique", "duplicate"]
        match = c.get(f"{API}/records/{r2}/matches").json()[0]
        assert match["matched_text"] == "الف" and match["matched_source_name"] == "منبع"
        assert "الف" in c.get(f"{API}/jobs/{j}/export.csv").text
    assert not db.exists() and (tmp_path / "similarityly.db.migrated").exists()
