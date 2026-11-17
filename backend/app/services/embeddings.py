"""Pluggable embedding providers.

- hash:      deterministic character n-gram hashing. No model download; good for
             near-duplicate / typo-level similarity, and used by the tests.
- fastembed: local multilingual ONNX models (install the `local` extra).
- openai:    any OpenAI-compatible /embeddings endpoint (OpenAI, Ollama, TEI, ...).
"""

import importlib.util
import logging
import threading
import time
import zlib
from pathlib import Path
from typing import Protocol

import httpx
import numpy as np

from app.core.config import Settings
from app.schemas import EmbeddingConfig, ProviderInfo

log = logging.getLogger("similarityly")

SUGGESTED_MODELS: dict[str, list[str]] = {
    "fastembed": [
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
        "intfloat/multilingual-e5-large",
    ],
    "openai": ["text-embedding-3-small", "text-embedding-3-large"],
    "hash": ["char-ngram-512", "char-ngram-1024"],
}


# Stable codes the UI translates (under `errors`); the raw cause goes to `detail`.
EMBEDDING_ERROR_CODES = (
    "embedding_not_configured",  # "openai" provider, OpenAI's URL, no API key
    "embedding_auth_failed",  # the endpoint rejected the key
    "embedding_unreachable",  # connection refused / DNS / timeout
    "embedding_failed",  # any other bad answer or invalid model
    "embedding_provider_unavailable",  # fastembed is not installed
    "embedding_model_unavailable",  # a local model could not be downloaded or loaded
)


class EmbeddingError(RuntimeError):
    def __init__(self, code: str, detail: str = ""):
        assert code in EMBEDDING_ERROR_CODES, code
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _is_default_openai(settings: Settings) -> bool:
    return "api.openai.com" in settings.openai_base_url


def openai_configured(settings: Settings) -> bool:
    """A self-hosted compatible endpoint usually needs no key; OpenAI itself does."""
    return bool(settings.openai_api_key) or not _is_default_openai(settings)


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashEmbedder:
    def __init__(self, model: str):
        try:
            self.dim = int(model.rsplit("-", 1)[-1])
        except ValueError as exc:
            raise EmbeddingError("embedding_failed", f"invalid hash model: {model}") from exc

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            padded = f" {text} "
            for n in (2, 3, 4):
                for i in range(len(padded) - n + 1):
                    h = zlib.crc32(padded[i : i + n].encode("utf-8"))
                    out[row, h % self.dim] += 1.0 if (h >> 31) & 1 else -1.0
            norm = np.linalg.norm(out[row])
            if norm:
                out[row] /= norm
        return out.tolist()


class FastEmbedEmbedder:
    def __init__(self, model: str, batch_size: int, cache_dir: Path):
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:
            raise EmbeddingError("embedding_provider_unavailable", "fastembed") from exc
        try:
            # Downloads the model on first use; fails offline or for an unknown name.
            self._model = TextEmbedding(model_name=model, cache_dir=str(cache_dir))
        except Exception as exc:
            raise EmbeddingError("embedding_model_unavailable", f"{model}: {exc}") from exc
        self._batch_size = batch_size
        # e5 models expect an instruction prefix; "query: " is the symmetric choice.
        self._prefix = "query: " if "e5" in model.lower() else ""

    def embed(self, texts: list[str]) -> list[list[float]]:
        inputs = [self._prefix + t for t in texts]
        try:
            return [v.tolist() for v in self._model.embed(inputs, batch_size=self._batch_size)]
        except Exception as exc:
            raise EmbeddingError("embedding_failed", str(exc)) from exc


# Embedding a batch can take a while on a CPU-bound server, but connecting or
# sending the request body should not: a stall there is a dead connection.
_TIMEOUT = httpx.Timeout(120.0, connect=10.0, write=30.0)
# Failures where the connection, not the request, is the likely culprit. An
# embedding request has no side effects, so sending it again is always safe.
_TRANSIENT_ERRORS = (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)
# Answers from an overloaded server or a proxy in front of it.
_TRANSIENT_STATUS = {429, 502, 503, 504}
_RETRY_DELAY = 1.0


class OpenAIEmbedder:
    def __init__(self, model: str, batch_size: int, settings: Settings):
        self._model = model
        self._batch_size = batch_size
        headers = {}
        if settings.openai_api_key:
            headers["Authorization"] = f"Bearer {settings.openai_api_key}"
        self._client_args = {
            "base_url": settings.openai_base_url.rstrip("/"),
            "headers": headers,
            "timeout": _TIMEOUT,
        }
        self._client = self._new_client()

    def _new_client(self) -> httpx.Client:
        return httpx.Client(**self._client_args)

    def _post(self, batch: list[str]) -> httpx.Response:
        """POST one batch; on a stalled or broken connection, or a 429/5xx from a
        proxy, try once more on a brand-new connection. The retry uses its own
        short-lived client: the shared one may be in use by another thread."""
        payload = {"model": self._model, "input": batch}
        try:
            res = self._client.post("/embeddings", json=payload)
            if res.status_code not in _TRANSIENT_STATUS:
                return res
            reason = f"HTTP {res.status_code}"
        except _TRANSIENT_ERRORS as exc:
            reason = type(exc).__name__
        log.warning("embedding request failed (%s); retrying on a new connection", reason)
        time.sleep(_RETRY_DELAY)
        with self._new_client() as fresh:
            res = fresh.post("/embeddings", json=payload)
            res.read()
            return res

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for i in range(0, len(texts), self._batch_size):
            batch = texts[i : i + self._batch_size]
            try:
                res = self._post(batch)
                res.raise_for_status()
            except httpx.HTTPStatusError as exc:
                auth = exc.response.status_code in (401, 403)
                code = "embedding_auth_failed" if auth else "embedding_failed"
                raise EmbeddingError(code, f"{exc} {exc.response.text[:300]}") from exc
            except httpx.HTTPError as exc:
                raise EmbeddingError(
                    "embedding_unreachable", str(exc) or type(exc).__name__
                ) from exc
            try:
                data = sorted(res.json()["data"], key=lambda d: d["index"])
                vectors.extend(d["embedding"] for d in data)
            except (ValueError, KeyError, TypeError) as exc:
                detail = f"unexpected response: {res.text[:300]}"
                raise EmbeddingError("embedding_failed", detail) from exc
        return vectors


_cache: dict[tuple, Embedder] = {}
_lock = threading.Lock()


def get_embedder(cfg: EmbeddingConfig, settings: Settings) -> Embedder:
    # The endpoint and key are part of the key: both can change from the Settings page.
    key = (
        cfg.provider,
        cfg.model,
        cfg.batch_size,
        settings.openai_base_url,
        settings.openai_api_key,
    )
    with _lock:
        if key not in _cache:
            if cfg.provider == "hash":
                _cache[key] = HashEmbedder(cfg.model)
            elif cfg.provider == "fastembed":
                _cache[key] = FastEmbedEmbedder(cfg.model, cfg.batch_size, settings.models_dir)
            else:
                if not openai_configured(settings):
                    raise EmbeddingError(
                        "embedding_not_configured", "set the embedding service in Settings"
                    )
                _cache[key] = OpenAIEmbedder(cfg.model, cfg.batch_size, settings)
        return _cache[key]


def provider_infos(settings: Settings) -> list[ProviderInfo]:
    available = {
        "fastembed": importlib.util.find_spec("fastembed") is not None,
        "openai": openai_configured(settings),
        "hash": True,
    }
    return [
        ProviderInfo(id=pid, available=available[pid], models=models)  # type: ignore[arg-type]
        for pid, models in SUGGESTED_MODELS.items()
    ]
