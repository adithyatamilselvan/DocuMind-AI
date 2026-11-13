from typing import Annotated

from fastapi import Depends, Request

from app.ai import registry
from app.ai.providers.embeddings import EmbeddingProvider
from app.ai.providers.llm import LLMProvider
from app.core.config import Settings, get_settings
from app.modules.retrieval.rerank import Reranker
from app.modules.vector_search.base import VectorStore


def embedder_dep(settings: Annotated[Settings, Depends(get_settings)]) -> EmbeddingProvider:
    return registry.get_embedder(settings)


def llm_dep(settings: Annotated[Settings, Depends(get_settings)]) -> LLMProvider:
    return registry.get_llm(settings)


def reranker_dep(settings: Annotated[Settings, Depends(get_settings)]) -> Reranker:
    return registry.get_reranker_for(settings)


def vectors_dep(request: Request) -> VectorStore:
    return request.app.state.vectors


Embedder = Annotated[EmbeddingProvider, Depends(embedder_dep)]
LLM = Annotated[LLMProvider, Depends(llm_dep)]
RerankerDep = Annotated[Reranker, Depends(reranker_dep)]
Vectors = Annotated[VectorStore, Depends(vectors_dep)]
