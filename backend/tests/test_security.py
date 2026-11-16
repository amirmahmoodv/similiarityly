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

    def fake_qdrant(url, api_key):
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
