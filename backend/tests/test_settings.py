import json

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

API = "/api/v1"


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, data_dir=tmp_path, qdrant_in_memory=True, jobs_inline=True)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as c:
        yield c


def test_defaults_never_expose_keys(client):
    body = client.get(f"{API}/settings").json()
    assert body["qdrant"] == {"mode": "memory", "url": "", "api_key_set": False}
    assert body["llm"]["provider"] == "openai" and body["llm"]["api_key_set"] is False


def test_llm_settings_persist_and_survive_restart(client, settings):
    res = client.put(
        f"{API}/settings/llm",
        json={"provider": "anthropic", "base_url": "", "api_key": "sk-test", "model": "m1"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["llm"] == {
        "provider": "anthropic",
        "base_url": "",
        "model": "m1",
        "api_key_set": True,
    }
    assert "sk-test" not in res.text

    # Omitting the key keeps it; "" clears it.
    res = client.put(f"{API}/settings/llm", json={"provider": "anthropic", "model": "m2"})
    assert res.json()["llm"]["api_key_set"] is True
    saved = json.loads(settings.runtime_settings_path.read_text(encoding="utf-8"))
    assert saved["llm_api_key"] == "sk-test" and saved["llm_model"] == "m2"

    with TestClient(create_app(settings)) as again:
        assert again.get(f"{API}/settings").json()["llm"]["model"] == "m2"

    res = client.put(f"{API}/settings/llm", json={"provider": "openai", "api_key": ""})
    assert res.json()["llm"]["api_key_set"] is False


def test_llm_rejects_bad_url(client):
    res = client.put(f"{API}/settings/llm", json={"provider": "openai", "base_url": "ftp://x"})
    assert res.status_code == 422


def test_llm_test_reports_unreachable(client):
    res = client.post(
        f"{API}/settings/llm/test",
        json={"provider": "openai", "base_url": "http://127.0.0.1:9/v1", "model": "x"},
    )
    body = res.json()
    assert res.status_code == 200 and body["ok"] is False
    assert body["error"] == "llm_unreachable"


def test_qdrant_unreachable_server_is_not_saved(client, settings):
    payload = {"mode": "server", "url": "http://127.0.0.1:9"}
    test = client.post(f"{API}/settings/qdrant/test", json=payload).json()
    assert test["ok"] is False and test["error"] == "qdrant_unreachable"

    res = client.put(f"{API}/settings/qdrant", json=payload)
    assert res.status_code == 502
    assert not settings.runtime_settings_path.exists()
    assert client.get(f"{API}/settings").json()["qdrant"]["mode"] == "memory"


def test_switch_to_embedded_reconnects_live(client, settings):
    res = client.put(f"{API}/settings/qdrant", json={"mode": "embedded"})
    assert res.status_code == 200, res.text
    assert res.json()["qdrant"]["mode"] == "embedded"
    assert client.get(f"{API}/meta").json()["qdrant_mode"] == "embedded"

    # The new store works end to end.
    assert client.post(f"{API}/repos", json={"name": "r"}).status_code == 201
    assert (settings.data_dir / "qdrant").exists()
