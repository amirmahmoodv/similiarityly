"""Failure paths: every error reaches the UI as a stable code it can translate,
with CORS headers, and nothing is half-applied."""

import re
import sys
import types
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core import runtime
from app.core.config import Settings
from app.main import create_app
from app.schemas import ConnectionTest, EmbeddingConfig
from app.services import embeddings, pipeline
from app.services.embeddings import (
    EMBEDDING_ERROR_CODES,
    EmbeddingError,
    FastEmbedEmbedder,
    OpenAIEmbedder,
    get_embedder,
)
from app.services.rerank import RerankError
from app.services.vector_store import VectorConfigError

API = "/api/v1"
ORIGIN = "https://sim.example.com"
ROOT = Path(__file__).resolve().parents[2]


def make_settings(tmp_path, **kw) -> Settings:
    return Settings(
        _env_file=None,
        data_dir=tmp_path,
        qdrant_in_memory=True,
        jobs_inline=True,
        cors_origins=[ORIGIN],
        **kw,
    )


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(make_settings(tmp_path)), raise_server_exceptions=False) as c:
        yield c


def make_repo(client, provider="hash", model="char-ngram-512"):
    config = {"embedding": {"provider": provider, "model": model}}
    res = client.post(f"{API}/repos", json={"name": f"r-{provider}-{model}", "config": config})
    assert res.status_code == 201, res.text
    return res.json()


# Long enough to produce chunks: very short lines are skipped and never embedded.
TEXT = "قرارداد خرید تجهیزات شبکه\nگزارش مالی فصل بهار"


def ingest(client, repo_id, text=TEXT):
    res = client.post(
        f"{API}/repos/{repo_id}/ingest",
        data={"input_kind": "text", "split": "lines", "text": text},
    )
    assert res.status_code == 202, res.text
    return res.json()


# ---- No / broken embedding service ----------------------------------------


def test_openai_provider_without_service_fails_job_with_code(client):
    """Nothing set in Settings: OpenAI's URL and no key."""
    meta = client.get(f"{API}/meta").json()
    assert {p["id"]: p["available"] for p in meta["providers"]}["openai"] is False

    repo = make_repo(client, "openai", "text-embedding-3-small")
    job = ingest(client, repo["id"])
    assert job["status"] == "failed"
    assert job["error"] == "embedding_not_configured"
    assert job["error_detail"]
    # The repo stays usable: nothing was indexed, no vector size was fixed.
    assert client.get(f"{API}/repos/{repo['id']}").json()["vector_size"] is None


def test_self_hosted_endpoint_needs_no_key_but_reports_unreachable(client):
    res = client.put(f"{API}/settings/embeddings", json={"base_url": "http://127.0.0.1:9/v1"})
    assert res.status_code == 200
    meta = client.get(f"{API}/meta").json()
    assert {p["id"]: p["available"] for p in meta["providers"]}["openai"] is True

    repo = make_repo(client, "openai", "nomic-embed-text")
    job = ingest(client, repo["id"])
    assert job["status"] == "failed" and job["error"] == "embedding_unreachable"


def _openai(handler) -> OpenAIEmbedder:
    s = Settings(_env_file=None, openai_api_key="k")
    emb = OpenAIEmbedder("m", 8, s)
    emb._client = httpx.Client(
        base_url="http://emb.test/v1", transport=httpx.MockTransport(handler)
    )
    return emb


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (httpx.Response(401, json={"error": "bad key"}), "embedding_auth_failed"),
        (httpx.Response(403, text="forbidden"), "embedding_auth_failed"),
        (httpx.Response(500, text="boom"), "embedding_failed"),
        (httpx.Response(404, text="no such model"), "embedding_failed"),
        (httpx.Response(200, text="<html>proxy page</html>"), "embedding_failed"),
        (httpx.Response(200, json={"object": "list"}), "embedding_failed"),
    ],
)
def test_openai_embedder_maps_responses_to_codes(response, code):
    with pytest.raises(EmbeddingError) as info:
        _openai(lambda request: response).embed(["x"])
    assert info.value.code == code and info.value.detail


def test_openai_embedder_maps_connection_errors():
    def fail(request):
        raise httpx.ConnectTimeout("timed out", request=request)

    with pytest.raises(EmbeddingError) as info:
        _openai(fail).embed(["x"])
    assert info.value.code == "embedding_unreachable"


def test_openai_embedder_success_keeps_input_order():
    def ok(request):
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0.0, 1.0]},
                    {"index": 0, "embedding": [1.0, 0.0]},
                ]
            },
        )

    assert _openai(ok).embed(["a", "b"]) == [[1.0, 0.0], [0.0, 1.0]]


def test_fastembed_not_installed(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "fastembed", None)  # import raises ImportError
    with pytest.raises(EmbeddingError) as info:
        FastEmbedEmbedder("any", 8, tmp_path)
    assert info.value.code == "embedding_provider_unavailable"


def test_fastembed_model_download_failure(monkeypatch, tmp_path):
    fake = types.ModuleType("fastembed")

    class TextEmbedding:
        def __init__(self, **kwargs):
            raise ConnectionError("huggingface.co unreachable")

    fake.TextEmbedding = TextEmbedding
    monkeypatch.setitem(sys.modules, "fastembed", fake)
    with pytest.raises(EmbeddingError) as info:
        FastEmbedEmbedder("intfloat/multilingual-e5-large", 8, tmp_path)
    assert info.value.code == "embedding_model_unavailable"
    assert "huggingface.co" in info.value.detail


def test_invalid_hash_model():
    with pytest.raises(EmbeddingError) as info:
        get_embedder(
            EmbeddingConfig(provider="hash", model="char-ngram-x"), Settings(_env_file=None)
        )
    assert info.value.code == "embedding_failed"


def test_changed_key_is_rechecked_not_served_from_cache():
    cfg = EmbeddingConfig(provider="openai", model="m")
    with_key = Settings(_env_file=None, openai_api_key="k1")
    assert isinstance(get_embedder(cfg, with_key), OpenAIEmbedder)
    without = with_key.model_copy(update={"openai_api_key": None})
    with pytest.raises(EmbeddingError) as info:
        get_embedder(cfg, without)
    assert info.value.code == "embedding_not_configured"


@pytest.mark.parametrize("code", ["embedding_unreachable", "embedding_auth_failed"])
def test_search_and_chunk_edit_return_the_embedding_code(client, monkeypatch, code):
    repo = make_repo(client)
    job = ingest(client, repo["id"])
    assert job["status"] == "done"

    class Broken:
        def embed(self, texts):
            raise EmbeddingError(code, "detail")

    monkeypatch.setattr(pipeline, "get_embedder", lambda cfg, settings: Broken())
    res = client.post(
        f"{API}/repos/{repo['id']}/search",
        json={"query": "قرارداد خرید تجهیزات"},
        headers={"Origin": ORIGIN},
    )
    assert res.status_code == 502 and res.json()["detail"] == code
    assert res.headers["access-control-allow-origin"] == ORIGIN

    record = client.get(f"{API}/jobs/{job['id']}/records").json()["items"][0]
    res = client.post(f"{API}/records/{record['id']}/chunks", json={"text": "متن تازه برای بخش"})
    assert res.status_code == 502 and res.json()["detail"] == code


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (EmbeddingError("embedding_auth_failed", "401"), "embedding_auth_failed"),
        (VectorConfigError("size"), "vector_config_mismatch"),
        (RerankError("x"), "rerank_failed"),
        (RuntimeError("anything else"), "internal_error"),
    ],
)
def test_job_error_codes(exc, code):
    assert pipeline.job_error_code(exc) == code


def test_unexpected_job_failure_is_internal_error_with_detail(client, monkeypatch):
    repo = make_repo(client)

    def explode(*args, **kwargs):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(pipeline, "embed_texts", explode)
    job = ingest(client, repo["id"])
    assert job["status"] == "failed" and job["error"] == "internal_error"
    assert "disk on fire" in job["error_detail"]


# ---- Settings that cannot be saved ------------------------------------------


def test_ensure_writable_detects_unusable_data_dir(tmp_path):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x", encoding="utf-8")
    with pytest.raises(runtime.SettingsNotWritableError):
        runtime.ensure_writable(Settings(_env_file=None, data_dir=blocker / "data"))


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/settings/llm", {"provider": "openai", "model": "m"}),
        ("/settings/embeddings", {"base_url": "http://localhost:11434/v1"}),
    ],
)
def test_unwritable_settings_return_a_code_not_a_crash(client, monkeypatch, path, body):
    def deny(*args, **kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(runtime.os, "replace", deny)
    res = client.put(f"{API}{path}", json=body, headers={"Origin": ORIGIN})
    assert res.status_code == 500 and res.json()["detail"] == "settings_not_writable"
    assert res.headers["access-control-allow-origin"] == ORIGIN


def test_qdrant_switch_is_refused_before_anything_changes_when_unwritable(client, monkeypatch):
    from app.api import settings as settings_api

    monkeypatch.setattr(settings_api, "test_qdrant", lambda url, key: ConnectionTest(ok=True))

    def deny(settings):
        raise runtime.SettingsNotWritableError("read-only")

    monkeypatch.setattr(settings_api, "ensure_writable", deny)
    swapped = []
    monkeypatch.setattr(settings_api, "swap_services", lambda *a: swapped.append(a))

    res = client.put(
        f"{API}/settings/qdrant", json={"mode": "server", "url": "https://q.example.com"}
    )
    assert res.status_code == 500 and res.json()["detail"] == "settings_not_writable"
    assert swapped == []
    assert client.get(f"{API}/settings").json()["qdrant"]["mode"] == "memory"


def test_qdrant_switch_failure_keeps_the_old_connection(client, monkeypatch):
    from app.api import settings as settings_api
    from app.core import state

    monkeypatch.setattr(settings_api, "test_qdrant", lambda url, key: ConnectionTest(ok=True))
    real_start = state.start_services

    def start(settings):
        if settings.qdrant_url:
            raise RuntimeError("collection create failed")
        return real_start(settings)

    monkeypatch.setattr(state, "start_services", start)
    res = client.put(
        f"{API}/settings/qdrant", json={"mode": "server", "url": "https://q.example.com"}
    )
    assert res.status_code == 502 and res.json()["detail"] == "qdrant_unreachable"
    # Still on the old store, and it still works.
    assert client.get(f"{API}/settings").json()["qdrant"]["mode"] == "memory"
    assert client.get(f"{API}/repos").status_code == 200


def test_qdrant_switch_that_also_cannot_restore_reports_storage_unavailable(client, monkeypatch):
    from app.api import settings as settings_api
    from app.core import state

    monkeypatch.setattr(settings_api, "test_qdrant", lambda url, key: ConnectionTest(ok=True))

    def start(settings):
        raise RuntimeError("everything is down")

    monkeypatch.setattr(state, "start_services", start)
    res = client.put(
        f"{API}/settings/qdrant",
        json={"mode": "server", "url": "https://q.example.com"},
        headers={"Origin": ORIGIN},
    )
    assert res.status_code == 503 and res.json()["detail"] == "storage_unavailable"
    assert res.headers["access-control-allow-origin"] == ORIGIN


# ---- Every kind of error is readable cross-origin ----------------------------


def test_every_error_status_carries_cors_headers(tmp_path):
    app = create_app(make_settings(tmp_path, api_token="tok"))

    @app.get(f"{API}/boom")
    def boom():
        raise RuntimeError("boom")

    auth = {"Origin": ORIGIN, "Authorization": "Bearer tok"}
    with TestClient(app, raise_server_exceptions=False) as c:
        cases = {
            401: c.get(f"{API}/repos", headers={"Origin": ORIGIN}),
            404: c.get(f"{API}/repos/nope", headers=auth),
            422: c.post(f"{API}/repos", json={}, headers=auth),
            500: c.get(f"{API}/boom", headers=auth),
        }
    for status, res in cases.items():
        assert res.status_code == status, (status, res.text)
        assert res.headers.get("access-control-allow-origin") == ORIGIN, status
        assert isinstance(res.json()["detail"], (str, list)), status


# ---- Every code the API can send has a translation ---------------------------


def _backend_codes() -> set[str]:
    codes: set[str] = set(EMBEDDING_ERROR_CODES)
    codes |= {"internal_error", "vector_config_mismatch", "rerank_failed", "unauthorized"}
    codes |= {"validation_error", "network_error", "unknown_error"}  # produced by the UI
    for path in (ROOT / "backend" / "app").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        codes |= set(re.findall(r'HTTPException\(\s*\d+\s*,\s*"([a-z_]+)"', text))
        codes |= set(re.findall(r'ParseError\(\s*"([a-z_]+)"', text))
        # ConnectionTest error codes (translated under settings.errors).
        codes |= set(
            re.findall(
                r'"((?:qdrant|llm|embeddings)_(?:unreachable|auth_failed|http_error))"', text
            )
        )
    return codes


@pytest.mark.parametrize("locale", ["en", "fa"])
def test_every_backend_error_code_is_translated(locale):
    ts = (ROOT / "frontend" / "src" / "i18n" / f"{locale}.ts").read_text(encoding="utf-8")
    keys = set(re.findall(r"^\s*([a-z_]+):", ts, flags=re.MULTILINE))
    missing = sorted(_backend_codes() - keys)
    assert not missing, f"{locale}.ts has no translation for: {missing}"


def test_embedding_codes_are_complete():
    assert set(EMBEDDING_ERROR_CODES) >= {
        "embedding_not_configured",
        "embedding_auth_failed",
        "embedding_unreachable",
    }
    assert embeddings.openai_configured(Settings(_env_file=None)) is False
