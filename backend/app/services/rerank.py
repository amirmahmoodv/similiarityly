"""Second-stage scoring: a cross-encoder reads both texts together.

Vector search (stage one) finds candidates cheaply; the cross-encoder then
judges each candidate pair, which separates "about the same thing" from
"shares some vocabulary" far better than an embedding distance can. It is too
slow to run against a whole repo, so it only sees the top-k candidates.
"""

import importlib.util
import math
import threading
from pathlib import Path
from typing import Protocol

from app.core.config import Settings

# Multilingual (Persian included), Apache-2.0. The int8 build is ~0.6 GB.
SUGGESTED_MODELS = ["BAAI/bge-reranker-v2-m3-int8", "BAAI/bge-reranker-v2-m3"]


class RerankError(RuntimeError):
    pass


class Reranker(Protocol):
    def score(self, pairs: list[tuple[str, str]]) -> list[float]: ...


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, x))))


class CrossEncoderReranker:
    def __init__(self, model: str, cache_dir: Path):
        try:
            from fastembed.rerank.cross_encoder import TextCrossEncoder
        except ImportError as exc:
            raise RerankError("provider_unavailable:fastembed") from exc
        try:
            self._model = TextCrossEncoder(model_name=model, cache_dir=str(cache_dir))
        except Exception as exc:  # unknown model name, download failure
            raise RerankError(f"rerank_model_failed: {exc}") from exc

    def score(self, pairs: list[tuple[str, str]]) -> list[float]:
        """0..1 relevance per pair.

        These models are trained as query -> passage, so (a, b) and (b, a)
        score differently. Matching two records is symmetric, so both
        directions are scored and the better one is kept.
        """
        if not pairs:
            return []
        both = pairs + [(b, a) for a, b in pairs]
        raw = [_sigmoid(float(s)) for s in self._model.rerank_pairs(both)]
        n = len(pairs)
        return [max(raw[i], raw[n + i]) for i in range(n)]


_cache: dict[str, Reranker] = {}
_lock = threading.Lock()


def get_reranker(model: str, settings: Settings) -> Reranker:
    with _lock:
        if model not in _cache:
            _cache[model] = CrossEncoderReranker(model, settings.models_dir)
        return _cache[model]


def available() -> bool:
    return importlib.util.find_spec("fastembed") is not None
