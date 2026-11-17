from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from app.core.config import Settings
from app.core.runtime import save_overrides
from app.core.state import JobsRunningError, Services, get_services, swap_services
from app.schemas import (
    ConnectionTest,
    EmbeddingsSettingsIn,
    EmbeddingsSettingsOut,
    LLMSettingsIn,
    LLMSettingsOut,
    QdrantSettingsIn,
    QdrantSettingsOut,
    SettingsOut,
)
from app.services.connections import OPENAI_DEFAULT_BASE_URL, test_embeddings, test_llm, test_qdrant

router = APIRouter(tags=["settings"])


def settings_out(s: Settings) -> SettingsOut:
    return SettingsOut(
        qdrant=QdrantSettingsOut(
            mode=s.qdrant_mode,  # type: ignore[arg-type]
            url=s.qdrant_url or "",
            api_key_set=bool(s.qdrant_api_key),
        ),
        embeddings=EmbeddingsSettingsOut(
            # The stored default is OpenAI's URL; the UI shows that as "empty = default".
            base_url="" if _is_default_openai(s.openai_base_url) else s.openai_base_url,
            api_key_set=bool(s.openai_api_key),
        ),
        llm=LLMSettingsOut(
            provider=s.llm_provider,
            base_url=s.llm_base_url,
            model=s.llm_model,
            api_key_set=bool(s.llm_api_key),
        ),
    )


def _is_default_openai(url: str) -> bool:
    return url.rstrip("/") == OPENAI_DEFAULT_BASE_URL


def _key(new: str | None, saved: str | None, same_target: bool) -> str | None:
    """None keeps the saved key; "" clears it.

    The saved key is only ever reused for the endpoint it was saved for.
    Otherwise anyone able to call these endpoints could point the server at
    their own URL and receive the stored key in the Authorization header.
    """
    if new is not None:
        return new or None
    return saved if same_target else None


def _same_qdrant(url: str, s: Settings) -> bool:
    return bool(s.qdrant_url) and url.rstrip("/") == s.qdrant_url.rstrip("/")


def _same_llm(provider: str, base_url: str, s: Settings) -> bool:
    return provider == s.llm_provider and base_url.rstrip("/") == s.llm_base_url.rstrip("/")


@router.get("/settings", response_model=SettingsOut)
def read_settings(services: Services = Depends(get_services)):
    return settings_out(services.settings)


# ---- Qdrant ----------------------------------------------------------------


@router.post("/settings/qdrant/test", response_model=ConnectionTest)
def check_qdrant(body: QdrantSettingsIn, services: Services = Depends(get_services)):
    if body.mode == "embedded":  # local files, nothing to reach
        return ConnectionTest(ok=True)
    s = services.settings
    return test_qdrant(body.url, _key(body.api_key, s.qdrant_api_key, _same_qdrant(body.url, s)))


@router.put("/settings/qdrant", response_model=SettingsOut)
async def update_qdrant(
    body: QdrantSettingsIn, request: Request, services: Services = Depends(get_services)
):
    current = services.settings
    api_key = _key(body.api_key, current.qdrant_api_key, _same_qdrant(body.url, current))
    changes = {
        "qdrant_in_memory": False,
        "qdrant_url": body.url if body.mode == "server" else None,
        "qdrant_api_key": api_key if body.mode == "server" else None,
    }
    # Refuse to save a server we cannot reach: the app would come up without storage.
    if body.mode == "server":
        result = await run_in_threadpool(test_qdrant, body.url, api_key)
        if not result.ok:
            raise HTTPException(502, result.error or "qdrant_unreachable")

    candidate = current.model_copy(update=changes)
    unchanged = (
        candidate.qdrant_mode == current.qdrant_mode
        and candidate.qdrant_url == current.qdrant_url
        and candidate.qdrant_api_key == current.qdrant_api_key
    )
    if not unchanged:
        try:
            await run_in_threadpool(swap_services, request.app, candidate)
        except JobsRunningError as exc:
            raise HTTPException(409, "jobs_running") from exc
        except Exception as exc:
            raise HTTPException(502, "qdrant_unreachable") from exc
    saved = save_overrides(current, changes)
    request.app.state.services.settings = saved
    return settings_out(saved)


# ---- Embeddings (OpenAI-compatible endpoint) --------------------------------


def _embeddings_url(base_url: str) -> str:
    return base_url or OPENAI_DEFAULT_BASE_URL


def _same_embeddings(base_url: str, s: Settings) -> bool:
    return _embeddings_url(base_url).rstrip("/") == s.openai_base_url.rstrip("/")


@router.post("/settings/embeddings/test", response_model=ConnectionTest)
async def check_embeddings(body: EmbeddingsSettingsIn, services: Services = Depends(get_services)):
    s = services.settings
    api_key = _key(body.api_key, s.openai_api_key, _same_embeddings(body.base_url, s))
    return await run_in_threadpool(test_embeddings, _embeddings_url(body.base_url), api_key)


@router.put("/settings/embeddings", response_model=SettingsOut)
def update_embeddings(body: EmbeddingsSettingsIn, services: Services = Depends(get_services)):
    s = services.settings
    changes = {
        "openai_base_url": _embeddings_url(body.base_url),
        "openai_api_key": _key(body.api_key, s.openai_api_key, _same_embeddings(body.base_url, s)),
    }
    services.settings = save_overrides(services.settings, changes)
    return settings_out(services.settings)


# ---- LLM -------------------------------------------------------------------


@router.post("/settings/llm/test", response_model=ConnectionTest)
async def check_llm(body: LLMSettingsIn, services: Services = Depends(get_services)):
    s = services.settings
    api_key = _key(body.api_key, s.llm_api_key, _same_llm(body.provider, body.base_url, s))
    return await run_in_threadpool(test_llm, body.provider, body.base_url, api_key, body.model)


@router.put("/settings/llm", response_model=SettingsOut)
def update_llm(body: LLMSettingsIn, services: Services = Depends(get_services)):
    s = services.settings
    same = _same_llm(body.provider, body.base_url, s)
    changes = {
        "llm_provider": body.provider,
        "llm_base_url": body.base_url,
        "llm_model": body.model,
        "llm_api_key": _key(body.api_key, s.llm_api_key, same),
    }
    services.settings = save_overrides(services.settings, changes)
    return settings_out(services.settings)
