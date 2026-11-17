"""Live checks for the Qdrant server and the LLM endpoint.

A check never raises: it returns a result with a stable `error` code the UI
translates, plus the raw `detail` for troubleshooting.
"""

import time

import anthropic
import httpx
from qdrant_client import QdrantClient

from app.schemas import ConnectionTest

OPENAI_DEFAULT_BASE_URL = "https://api.openai.com/v1"
_TIMEOUT = 10.0


def _ms(start: float) -> int:
    return round((time.perf_counter() - start) * 1000)


def test_qdrant(url: str, api_key: str | None) -> ConnectionTest:
    start = time.perf_counter()
    client = None
    try:
        client = QdrantClient(
            url=url, api_key=api_key or None, timeout=int(_TIMEOUT), check_compatibility=False
        )
        collections = client.get_collections().collections
        version = None
        try:
            version = client.info().version
        except Exception:  # older servers have no root info endpoint
            pass
        return ConnectionTest(
            ok=True, latency_ms=_ms(start), version=version, collections=len(collections)
        )
    except Exception as exc:
        text = str(exc)
        code = (
            "qdrant_auth_failed"
            if "401" in text or "403" in text or "Unauthorized" in text
            else "qdrant_unreachable"
        )
        return ConnectionTest(ok=False, latency_ms=_ms(start), error=code, detail=text[:500])
    finally:
        if client is not None:
            client.close()


def _openai_models(base_url: str, api_key: str | None) -> list[str]:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    url = (base_url or OPENAI_DEFAULT_BASE_URL).rstrip("/") + "/models"
    res = httpx.get(url, headers=headers, timeout=_TIMEOUT)
    res.raise_for_status()
    return [m["id"] for m in res.json().get("data", []) if "id" in m]


def _anthropic_models(base_url: str, api_key: str | None) -> list[str]:
    client = anthropic.Anthropic(
        api_key=api_key or None, base_url=base_url or None, timeout=_TIMEOUT, max_retries=0
    )
    try:
        return [m.id for m in client.models.list(limit=100).data]
    finally:
        client.close()


def test_embeddings(base_url: str, api_key: str | None) -> ConnectionTest:
    """Lists the endpoint's models, like the LLM check, with its own error codes."""
    start = time.perf_counter()

    def fail(code: str, exc: Exception) -> ConnectionTest:
        return ConnectionTest(ok=False, latency_ms=_ms(start), error=code, detail=str(exc)[:500])

    try:
        models = _openai_models(base_url, api_key)
    except httpx.HTTPStatusError as exc:
        auth = exc.response.status_code in (401, 403)
        return fail("embeddings_auth_failed" if auth else "embeddings_http_error", exc)
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        return fail("embeddings_unreachable", exc)
    return ConnectionTest(ok=True, latency_ms=_ms(start), models=sorted(models))


def test_llm(provider: str, base_url: str, api_key: str | None, model: str) -> ConnectionTest:
    """Lists the endpoint's models: proves reachability and auth without spending tokens."""
    start = time.perf_counter()

    def fail(code: str, exc: Exception) -> ConnectionTest:
        return ConnectionTest(ok=False, latency_ms=_ms(start), error=code, detail=str(exc)[:500])

    try:
        if provider == "anthropic":
            models = _anthropic_models(base_url, api_key)
        else:
            models = _openai_models(base_url, api_key)
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
        return fail("llm_auth_failed", exc)
    except anthropic.APIStatusError as exc:
        return fail("llm_http_error", exc)
    except anthropic.APIConnectionError as exc:
        return fail("llm_unreachable", exc)
    except anthropic.AnthropicError as exc:  # e.g. no API key configured
        return fail("llm_auth_failed", exc)
    except httpx.HTTPStatusError as exc:
        auth = exc.response.status_code in (401, 403)
        return fail("llm_auth_failed" if auth else "llm_http_error", exc)
    except (httpx.HTTPError, ValueError) as exc:
        return fail("llm_unreachable", exc)
    models = sorted(models)
    return ConnectionTest(
        ok=True,
        latency_ms=_ms(start),
        models=models,
        model_found=(model in models) if model else None,
    )
