"""Live checks for the Qdrant server and the LLM endpoint.

A check never raises: it returns a result with a stable `error` code the UI
translates, plus the raw `detail` for troubleshooting.
"""

import importlib.metadata
import time

import anthropic
import httpx

from app.schemas import ConnectionStep, ConnectionTest
from app.services.vector_store import server_client

OPENAI_DEFAULT_BASE_URL = "https://api.openai.com/v1"
_TIMEOUT = 10.0


def _ms(start: float) -> int:
    return round((time.perf_counter() - start) * 1000)


QDRANT_STEPS = ("version", "list_collections", "collection_lookup", "new_connection_lookup")


def _is_timeout(exc: BaseException) -> bool:
    seen: BaseException | None = exc
    while seen is not None:
        if isinstance(seen, (httpx.TimeoutException, TimeoutError)):
            return True
        if "timed out" in str(seen):
            return True
        seen = seen.__cause__ or seen.__context__
    return False


def _is_auth(exc: BaseException) -> bool:
    text = str(exc)
    return getattr(exc, "status_code", None) in (401, 403) or any(
        s in text for s in ("401", "403", "Unauthorized", "Forbidden")
    )


def _client_version() -> str | None:
    try:
        return importlib.metadata.version("qdrant-client")
    except importlib.metadata.PackageNotFoundError:
        return None


def test_qdrant(url: str, api_key: str | None, prefix: str = "sim_") -> ConnectionTest:
    """Run the same requests switching to this server makes, each timed.

    Saving connects with a version check and then looks up and creates
    collections over one kept-alive connection. Checking only a single list call
    let a server pass here and then hang on save, so every step is repeated:
    the version, a listing, a collection lookup on the same connection, and the
    same lookup on a brand-new connection (which tells a broken keep-alive path
    apart from a server that does not answer at all). Nothing is written.
    """
    start = time.perf_counter()
    steps: list[ConnectionStep] = []
    first_failure: tuple[str, str, BaseException] | None = None
    version: str | None = None
    collections: int | None = None
    lookup = f"{prefix}meta_repos"

    def run(name: str, fn):
        nonlocal first_failure
        t = time.perf_counter()
        try:
            result = fn()
        except Exception as exc:
            steps.append(ConnectionStep(name=name, ok=False, ms=_ms(t), error=str(exc)[:300]))
            if first_failure is None:
                first_failure = (name, str(exc), exc)
            return None
        steps.append(ConnectionStep(name=name, ok=True, ms=_ms(t)))
        return result

    clients = []
    try:
        client = server_client(url, api_key, timeout=int(_TIMEOUT), check_compatibility=False)
        clients.append(client)
        info = run("version", client.info)
        version = getattr(info, "version", None)
        listed = run("list_collections", client.get_collections)
        if listed is not None:
            collections = len(listed.collections)
        # Keep going only past timeouts: the later steps then show where the path
        # breaks. A refused connection or a rejected key would just repeat itself.
        if first_failure is None or _is_timeout(first_failure[2]):
            run("collection_lookup", lambda: client.collection_exists(lookup))
            fresh = server_client(url, api_key, timeout=int(_TIMEOUT), check_compatibility=False)
            clients.append(fresh)
            run("new_connection_lookup", lambda: fresh.collection_exists(lookup))
    except Exception as exc:  # e.g. an invalid URL: the client cannot even be built
        first_failure = first_failure or ("client", str(exc), exc)
    finally:
        for c in clients:
            c.close()

    common = {
        "latency_ms": _ms(start),
        "version": version,
        "collections": collections,
        "client_version": _client_version(),
        "steps": steps,
    }
    if first_failure is None:
        return ConnectionTest(ok=True, **common)
    name, text, exc = first_failure
    if _is_auth(exc):
        code = "qdrant_auth_failed"
    elif _is_timeout(exc):
        code = "qdrant_timeout"
    else:
        code = "qdrant_unreachable"
    return ConnectionTest(ok=False, error=code, detail=f"{name}: {text}"[:500], **common)


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
