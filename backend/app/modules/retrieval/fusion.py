import re
from dataclasses import dataclass, field
from typing import Any

from app.modules.vector_search.base import Hit

RRF_K = 60


@dataclass
class Candidate:
    chunk: dict[str, Any]
    rrf: float = 0.0
    vector_score: float | None = None
    keyword_score: float | None = None
    rerank_score: float = 0.0
    sources: set[str] = field(default_factory=set)

    @property
    def chunk_id(self) -> str:
        return self.chunk["chunk_id"]


def reciprocal_rank_fusion(
    ranked_lists: list[list[Hit]], weights: list[float] | None = None, k: int = RRF_K
) -> list[Candidate]:
    """Merge ranked lists (vector and keyword results for each query). A chunk found by several
    lists, or ranked high in any, rises. Scores of different kinds are never added directly."""
    weights = weights or [1.0] * len(ranked_lists)
    by_id: dict[str, Candidate] = {}
    for hits, w in zip(ranked_lists, weights, strict=True):
        for rank, h in enumerate(hits, start=1):
            c = by_id.setdefault(h.chunk["chunk_id"], Candidate(chunk=h.chunk))
            c.rrf += w / (k + rank)
            c.sources.add(h.source)
            if h.source == "vector":
                c.vector_score = max(c.vector_score or 0.0, h.score)
            else:
                c.keyword_score = max(c.keyword_score or 0.0, h.score)
    return sorted(by_id.values(), key=lambda c: c.rrf, reverse=True)


_WORD = re.compile(r"\w+", re.UNICODE)


def _shingles(text: str, n: int = 5) -> set[tuple[str, ...]]:
    words = _WORD.findall(text.lower())
    if len(words) < n:
        return {tuple(words)} if words else set()
    return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}


def remove_duplicates(cands: list[Candidate], threshold: float = 0.85) -> list[Candidate]:
    """Drop exact (content hash) and near-duplicate chunks, keeping the better-ranked one."""
    kept: list[Candidate] = []
    seen_hash: set[str] = set()
    kept_shingles: list[set[tuple[str, ...]]] = []
    for c in cands:
        h = c.chunk.get("content_hash")
        if h and h in seen_hash:
            continue
        sh = _shingles(c.chunk["content"])
        if any(sh and o and len(sh & o) / len(sh | o) >= threshold for o in kept_shingles):
            continue
        if h:
            seen_hash.add(h)
        kept.append(c)
        kept_shingles.append(sh)
    return kept
