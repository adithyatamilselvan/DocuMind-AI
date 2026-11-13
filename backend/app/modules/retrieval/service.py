import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase

from app.ai.providers.embeddings import EmbeddingProvider
from app.core.config import Settings
from app.modules.retrieval.fusion import Candidate, reciprocal_rank_fusion, remove_duplicates
from app.modules.retrieval.rerank import Reranker
from app.modules.vector_search.base import Scope, VectorStore

Mode = Literal["hybrid", "semantic", "keyword"]


@dataclass
class RetrievedChunk:
    chunk_id: str
    document_id: ObjectId
    document_title: str
    version_id: ObjectId
    page_number: int | None
    section_heading: str | None
    chunk_index: int
    content: str
    token_count: int
    score: float
    vector_score: float | None
    keyword_score: float | None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RetrievalResult:
    chunks: list[RetrievedChunk]
    debug: dict[str, Any]


async def retrieve(
    *,
    db: AsyncDatabase,
    store: VectorStore,
    embedder: EmbeddingProvider,
    reranker: Reranker,
    settings: Settings,
    scope: Scope,
    queries: list[str],
    mode: Mode = "hybrid",
    candidates: int | None = None,
    rerank_query: str | None = None,
    min_vector_score: float | None = None,
) -> RetrievalResult:
    """Hybrid retrieval: (vector + keyword) x queries -> RRF -> threshold -> dedupe -> rerank."""
    t0 = time.monotonic()
    queries = [q.strip() for q in dict.fromkeys(queries) if q and q.strip()]
    if not queries or (scope.document_ids is not None and not scope.document_ids):
        return RetrievalResult(
            [], {"queries": queries, "candidates": 0, "reason": "empty scope or query"}
        )
    k = candidates or settings.rag_candidates
    threshold = settings.rag_min_vector_score if min_vector_score is None else min_vector_score

    tasks = []
    if mode in ("hybrid", "semantic"):
        vectors = await embedder.embed_documents(queries)
        tasks += [store.vector_search(db, v, scope, k) for v in vectors]
    if mode in ("hybrid", "keyword"):
        tasks += [store.keyword_search(db, q, scope, k) for q in queries]
    lists = await asyncio.gather(*tasks)
    # The first query is the (rewritten) user question: weight it above the expansions.
    n_q = len(queries)
    weights = [1.5 if i % n_q == 0 else 1.0 for i in range(len(lists))]
    fused = reciprocal_rank_fusion(list(lists), weights)
    raw = len(fused)

    # Similarity threshold: a chunk must be a close vector match OR have a keyword hit.
    fused = [
        c for c in fused
        if mode == "keyword" or c.keyword_score is not None or (c.vector_score or 0.0) >= threshold
    ]  # fmt: skip
    after_threshold = len(fused)
    fused = remove_duplicates(fused)[:k]

    scores = await reranker.rerank(rerank_query or queries[0], fused)
    for c, s in zip(fused, scores, strict=True):
        c.rerank_score = s
    fused.sort(key=lambda c: c.rerank_score, reverse=True)

    titles = {
        d["_id"]: d["title"]
        async for d in db.documents.find(
            {"_id": {"$in": list({c.chunk["document_id"] for c in fused})}}, {"title": 1}
        )
    }
    chunks = [_to_chunk(c, titles) for c in fused]
    return RetrievalResult(
        chunks,
        {
            "queries": queries, "mode": mode, "backend": store.name, "reranker": reranker.name,
            "raw_candidates": raw, "after_threshold": after_threshold, "final_candidates": len(chunks),
            "latency_ms": int((time.monotonic() - t0) * 1000),
        },
    )  # fmt: skip


def _to_chunk(c: Candidate, titles: dict[ObjectId, str]) -> RetrievedChunk:
    ch = c.chunk
    return RetrievedChunk(
        chunk_id=ch["chunk_id"], document_id=ch["document_id"],
        document_title=titles.get(ch["document_id"], "Untitled"),
        version_id=ch["document_version_id"], page_number=ch.get("page_number"),
        section_heading=ch.get("section_heading"), chunk_index=ch["chunk_index"],
        content=ch["content"], token_count=ch.get("token_count", 0), score=c.rerank_score,
        vector_score=c.vector_score, keyword_score=c.keyword_score, metadata=ch.get("metadata", {}),
    )  # fmt: skip
