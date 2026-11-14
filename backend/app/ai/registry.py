"""Cached provider instances. Keyed by the settings that define them, so a model that loads weights
(local embeddings, cross-encoder) is created once, and a changed setting yields a new instance."""

from app.ai.providers.embeddings import EmbeddingProvider, build_embedder
from app.ai.providers.llm import LLMProvider, build_llm
from app.core.config import Settings
from app.modules.retrieval.rerank import Reranker, build_reranker

_cache: dict[tuple, object] = {}


def _get(key: tuple, factory):  # noqa: ANN001, ANN202
    if key not in _cache:
        _cache[key] = factory()
    return _cache[key]


def get_embedder(s: Settings) -> EmbeddingProvider:
    key = (
        "emb",
        s.embedding_provider,
        s.embedding_model,
        s.embedding_dim,
        s.embedding_version,
        s.env,
    )
    return _get(key, lambda: build_embedder(s))  # type: ignore[return-value]


def get_llm(s: Settings) -> LLMProvider:
    key = (
        "llm",
        s.llm_provider,
        s.anthropic_model,
        s.llm_effort,
        s.anthropic_api_key.get_secret_value(),
        s.cohere_model,
        s.cohere_api_key.get_secret_value(),
        s.env,
    )
    return _get(key, lambda: build_llm(s))  # type: ignore[return-value]


def get_reranker_for(s: Settings) -> Reranker:
    return _get(("rr", s.reranker, s.reranker_model), lambda: build_reranker(s))  # type: ignore[return-value]
