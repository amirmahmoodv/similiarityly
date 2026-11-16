"""Pluggable embedding providers.

- hash:      deterministic character n-gram hashing. No model download; good for
             near-duplicate / typo-level similarity, and used by the tests.
- fastembed: local multilingual ONNX models (install the `local` extra).
- openai:    any OpenAI-compatible /embeddings endpoint (OpenAI, Ollama, TEI, ...).
"""

import importlib.util
import threading
import zlib
from pathlib import Path
from typing import Protocol

import httpx
import numpy as np

from app.core.config import Settings
from app.schemas import EmbeddingConfig, ProviderInfo

SUGGESTED_MODELS: dict[str, list[str]] = {
    "fastembed": [
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
        "intfloat/multilingual-e5-large",
    ],
    "openai": ["text-embedding-3-small", "text-embedding-3-large"],
    "hash": ["char-ngram-512", "char-ngram-1024"],
}


class EmbeddingError(RuntimeError):
    pass


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashEmbedder:
    def __init__(self, model: str):
        try:
            self.dim = int(model.rsplit("-", 1)[-1])
        except ValueError as exc:
            raise EmbeddingError(f"invalid hash model: {model}") from exc

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
            raise EmbeddingError("provider_unavailable:fastembed") from exc
        self._model = TextEmbedding(model_name=model, cache_dir=str(cache_dir))
        self._batch_size = batch_size
        # e5 models expect an instruction prefix; "query: " is the symmetric choice.
        self._prefix = "query: " if "e5" in model.lower() else ""

    def embed(self, texts: list[str]) -> list[list[float]]:
        inputs = [self._prefix + t for t in texts]
        return [v.tolist() for v in self._model.embed(inputs, batch_size=self._batch_size)]


class OpenAIEmbedder:
    def __init__(self, model: str, batch_size: int, settings: Settings):
        self._model = model
        self._batch_size = batch_size
        headers = {}
        if settings.openai_api_key:
            headers["Authorization"] = f"Bearer {settings.openai_api_key}"
        self._client = httpx.Client(
            base_url=settings.openai_base_url.rstrip("/"), headers=headers, timeout=120
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for i in range(0, len(texts), self._batch_size):
            batch = texts[i : i + self._batch_size]
            try:
                res = self._client.post("/embeddings", json={"model": self._model, "input": batch})
                res.raise_for_status()
            except httpx.HTTPError as exc:
                raise EmbeddingError(f"embedding_request_failed: {exc}") from exc
            data = sorted(res.json()["data"], key=lambda d: d["index"])
            vectors.extend(d["embedding"] for d in data)
        return vectors


_cache: dict[tuple, Embedder] = {}
_lock = threading.Lock()


def get_embedder(cfg: EmbeddingConfig, settings: Settings) -> Embedder:
    key = (cfg.provider, cfg.model, cfg.batch_size, settings.openai_base_url)
    with _lock:
        if key not in _cache:
            if cfg.provider == "hash":
                _cache[key] = HashEmbedder(cfg.model)
            elif cfg.provider == "fastembed":
                _cache[key] = FastEmbedEmbedder(cfg.model, cfg.batch_size, settings.models_dir)
            else:
                _cache[key] = OpenAIEmbedder(cfg.model, cfg.batch_size, settings)
        return _cache[key]


def provider_infos(settings: Settings) -> list[ProviderInfo]:
    default_openai = "api.openai.com" in settings.openai_base_url
    available = {
        "fastembed": importlib.util.find_spec("fastembed") is not None,
        # A self-hosted compatible endpoint usually needs no key.
        "openai": bool(settings.openai_api_key) or not default_openai,
        "hash": True,
    }
    return [
        ProviderInfo(id=pid, available=available[pid], models=models)  # type: ignore[arg-type]
        for pid, models in SUGGESTED_MODELS.items()
    ]
