import csv
import io

import pytest
from fastapi.testclient import TestClient

from app.api import settings as settings_api
from app.core.config import Settings
from app.main import create_app
from app.schemas import ConnectionTest

API = "/api/v1"


def make_settings(tmp_path, **kw) -> Settings:
    return Settings(
        _env_file=None, data_dir=tmp_path, qdrant_in_memory=True, jobs_inline=True, **kw
    )


# ---- token auth -------------------------------------------------------------


@pytest.fixture
def secured(tmp_path):
    with TestClient(create_app(make_settings(tmp_path, api_token="s3cret"))) as c:
        yield c


def test_token_required_when_configured(secured):
    res = secured.get(f"{API}/repos")
    assert res.status_code == 401
    assert res.json() == {"detail": "unauthorized"}


@pytest.mark.parametrize("header", ["Bearer wrong", "s3cret", "Basic s3cret", ""])
def test_wrong_token_rejected(secured, header):
    assert secured.get(f"{API}/repos", headers={"Authorization": header}).status_code == 401


def test_correct_token_accepted(secured):
    res = secured.get(f"{API}/repos", headers={"Authorization": "Bearer s3cret"})
    assert res.status_code == 200


def test_health_stays_open_for_container_checks(secured):
    assert secured.get("/health").status_code == 200


def test_no_token_configured_means_open(tmp_path):
    with TestClient(create_app(make_settings(tmp_path))) as c:
        assert c.get(f"{API}/repos").status_code == 200


# ---- saved keys are never sent to a new endpoint ---------------------------


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(make_settings(tmp_path))) as c:
        yield c


@pytest.fixture
def captured(monkeypatch):
    calls: list[tuple] = []

    def fake_llm(provider, base_url, api_key, model):
        calls.append((base_url, api_key))
        return ConnectionTest(ok=True)

    def fake_qdrant(url, api_key, prefix="sim_"):
        calls.append((url, api_key))
        return ConnectionTest(ok=True)

    monkeypatch.setattr(settings_api, "test_llm", fake_llm)
    monkeypatch.setattr(settings_api, "test_qdrant", fake_qdrant)
    return calls


def test_saved_llm_key_not_sent_to_other_url(client, captured):
    saved = {"provider": "openai", "base_url": "https://llm.internal/v1", "api_key": "sk-real"}
    assert client.put(f"{API}/settings/llm", json=saved).status_code == 200

    # Same endpoint, key omitted: the saved key is reused.
    client.post(f"{API}/settings/llm/test", json={**saved, "api_key": None})
    assert captured[-1] == ("https://llm.internal/v1", "sk-real")

    # A different endpoint must never receive it.
    client.post(
        f"{API}/settings/llm/test",
        json={"provider": "openai", "base_url": "https://attacker.example/v1"},
    )
    assert captured[-1] == ("https://attacker.example/v1", None)


def test_saving_new_llm_url_drops_saved_key(client, captured):
    client.put(
        f"{API}/settings/llm",
        json={"provider": "openai", "base_url": "https://a.example/v1", "api_key": "sk-real"},
    )
    body = client.put(
        f"{API}/settings/llm", json={"provider": "openai", "base_url": "https://b.example/v1"}
    ).json()
    assert body["llm"]["api_key_set"] is False


def test_saved_qdrant_key_not_sent_to_other_url(tmp_path, captured):
    # Run on in-memory Qdrant and inject a saved server config: only the
    # settings layer is under test, nothing connects.
    with TestClient(create_app(make_settings(tmp_path))) as c:
        c.app.state.services.settings = c.app.state.services.settings.model_copy(
            update={"qdrant_url": "http://qdrant:6333", "qdrant_api_key": "qk-real"}
        )
        c.post(f"{API}/settings/qdrant/test", json={"mode": "server", "url": "http://qdrant:6333"})
        assert captured[-1] == ("http://qdrant:6333", "qk-real")
        c.post(f"{API}/settings/qdrant/test", json={"mode": "server", "url": "http://evil:6333"})
        assert captured[-1] == ("http://evil:6333", None)


# ---- CSV export --------------------------------------------------------------


def test_export_neutralizes_formulas(client):
    repo = client.post(f"{API}/repos", json={"name": "csv"}).json()
    lines = ['=HYPERLINK("http://evil","x")', "+1+1", "-2", "@SUM(A1)", "plain text"]
    job = client.post(
        f"{API}/repos/{repo['id']}/ingest",
        data={"input_kind": "text", "split": "lines", "text": "\n".join(lines)},
    ).json()
    res = client.get(f"{API}/jobs/{job['id']}/export.csv")
    rows = list(csv.reader(io.StringIO(res.text.lstrip("﻿"))))[1:]
    texts = {r[0]: r[4] for r in rows}
    assert texts["1"].startswith("'=")
    assert texts["2"] == "'+1+1"
    assert texts["3"] == "'-2"
    assert texts["4"].startswith("'@")
    assert texts["5"] == "plain text"


# ---- uploads -----------------------------------------------------------------


def test_upload_over_limit_rejected(tmp_path):
    with TestClient(create_app(make_settings(tmp_path, max_upload_mb=1))) as c:
        big = b"a\n" * (600 * 1024)  # ~1.2 MB
        res = c.post(f"{API}/sources/preview", files={"file": ("big.txt", big, "text/plain")})
        assert res.status_code == 413
        assert res.json()["detail"] == "file_too_large"


# ---- startup guard -------------------------------------------------------------


@pytest.mark.parametrize(
    "origins",
    [["https://sim.example.com"], ["http://localhost:5173", "https://ui.example.org"]],
)
def test_public_origin_without_token_refuses_to_start(tmp_path, origins):
    with pytest.raises(RuntimeError, match="SIM_API_TOKEN"):
        create_app(make_settings(tmp_path, cors_origins=origins))


@pytest.mark.parametrize(
    "kw",
    [
        {"cors_origins": ["https://sim.example.com"], "api_token": "x" * 32},
        {"cors_origins": ["https://sim.example.com"], "allow_public_without_token": True},
        {
            "cors_origins": [
                "http://localhost:5173",
                "http://127.0.0.1:8080",
                "http://app.localhost",
            ]
        },
        {"cors_origins": []},
    ],
)
def test_safe_configurations_start(tmp_path, kw):
    create_app(make_settings(tmp_path, **kw))


def test_wildcard_origin_is_refused(tmp_path):
    with pytest.raises(RuntimeError, match=r"'\*'"):
        create_app(make_settings(tmp_path, cors_origins=["*"], api_token="x" * 32))


def test_short_token_is_warned_about(tmp_path, caplog):
    create_app(make_settings(tmp_path, api_token="short"))
    assert "shorter than" in caplog.text


# ---- API docs ------------------------------------------------------------------


def test_docs_are_off_by_default(client):
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404, path


def test_docs_can_be_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("SIM_ENABLE_DOCS", "true")
    s = Settings(_env_file=None, data_dir=tmp_path, qdrant_in_memory=True)
    with TestClient(create_app(s)) as c:
        assert c.get("/openapi.json").status_code == 200
        docs = c.get("/docs")
        assert docs.status_code == 200
        # Swagger UI loads scripts from a CDN, so the API's strict CSP is skipped there.
        assert "content-security-policy" not in docs.headers


# ---- security headers -------------------------------------------------------------


def test_security_headers_on_every_kind_of_response(tmp_path):
    from app.core.http import API_SECURITY_HEADERS

    app = create_app(make_settings(tmp_path, api_token="t" * 32))

    @app.get(f"{API}/boom")
    def boom():
        raise RuntimeError("boom")

    auth = {"Authorization": "Bearer " + "t" * 32}
    with TestClient(app, raise_server_exceptions=False) as c:
        responses = {
            "health": c.get("/health"),
            "ok": c.get(f"{API}/repos", headers=auth),
            "401": c.get(f"{API}/repos"),
            "404": c.get(f"{API}/repos/missing", headers=auth),
            "422": c.post(f"{API}/repos", json={}, headers=auth),
            "500": c.get(f"{API}/boom", headers=auth),
        }
    for kind, res in responses.items():
        for name, value in API_SECURITY_HEADERS.items():
            assert res.headers.get(name) == value, (kind, name)
        if kind != "health":
            assert res.headers.get("cache-control") == "no-store", kind


# ---- request body limit -----------------------------------------------------------


def test_declared_oversized_body_is_refused_before_parsing(tmp_path):
    s = make_settings(
        tmp_path,
        max_upload_mb=1,
        cors_origins=["https://sim.example.com"],
        api_token="t" * 32,
    )
    with TestClient(create_app(s)) as c:
        res = c.post(
            f"{API}/sources/preview",
            content=b"x" * (3 * 1024 * 1024),
            headers={
                "Content-Type": "application/octet-stream",
                "Origin": "https://sim.example.com",
                "Authorization": "Bearer " + "t" * 32,
            },
        )
    assert res.status_code == 413 and res.json()["detail"] == "file_too_large"
    assert res.headers["access-control-allow-origin"] == "https://sim.example.com"


def test_streamed_oversized_body_is_cut_off(tmp_path):
    def chunks():  # no Content-Length: sent chunked, as a valid multipart upload
        crlf = b"\r\n"
        yield (
            b"--zz"
            + crlf
            + b'Content-Disposition: form-data; name="file"; filename="big.txt"'
            + crlf
            + b"Content-Type: text/plain"
            + crlf * 2
        )
        for _ in range(4):
            yield b"x" * (1024 * 1024)
        yield crlf + b"--zz--" + crlf

    with TestClient(create_app(make_settings(tmp_path, max_upload_mb=1))) as c:
        res = c.post(
            f"{API}/sources/preview",
            content=chunks(),
            headers={"Content-Type": "multipart/form-data; boundary=zz"},
        )
    assert res.status_code == 413 and res.json()["detail"] == "file_too_large"


def test_body_within_limit_still_works(tmp_path):
    with TestClient(create_app(make_settings(tmp_path, max_upload_mb=1))) as c:
        res = c.post(
            f"{API}/sources/preview",
            files={"file": ("ok.txt", "یک خط متن".encode(), "text/plain")},
        )
    assert res.status_code == 200, res.text
