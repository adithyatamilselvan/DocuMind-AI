import asyncio
import math
import re
from collections import Counter
from typing import Protocol

from app.core.config import Settings
from app.modules.retrieval.fusion import Candidate

_WORD = re.compile(r"\w+", re.UNICODE)
_STOP = frozenset(
    "a an the and or of to in on for with is are was were be been it its this that as at by from "
    "what which who how why when where do does did can could should would about into than then".split()
)


def _tokens(text: str) -> list[str]:
    return [t for t in _WORD.findall(text.lower()) if t not in _STOP]


class Reranker(Protocol):
    name: str

    async def rerank(self, query: str, candidates: list[Candidate]) -> list[float]:
        """Return one relevance score in [0, 1] per candidate (same order)."""
        ...


class NoReranker:
    name = "none"

    async def rerank(self, query: str, candidates: list[Candidate]) -> list[float]:
        top = max((c.rrf for c in candidates), default=1.0) or 1.0
        return [c.rrf / top for c in candidates]


class LexicalReranker:
    """Okapi BM25 over the candidate set (IDF computed from the candidates themselves) blended with
    the fused retrieval rank. Cheap, deterministic and model-free; a real cross-encoder is
    available via RERANKER=cross_encoder."""

    name = "lexical"

    def __init__(self, k1: float = 1.4, b: float = 0.75) -> None:
        self.k1, self.b = k1, b

    async def rerank(self, query: str, candidates: list[Candidate]) -> list[float]:
        if not candidates:
            return []
        q_terms = set(_tokens(query))
        docs = [
            Counter(_tokens(f"{c.chunk.get('section_heading') or ''} {c.chunk['content']}"))
            for c in candidates
        ]
        n = len(docs)
        avg_len = (sum(sum(d.values()) for d in docs) / n) or 1.0
        df = Counter(t for d in docs for t in d if t in q_terms)
        scores = []
        for d in docs:
            length = sum(d.values()) or 1
            s = 0.0
            for t in q_terms:
                if t not in d:
                    continue
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                tf = d[t]
                s += (
                    idf
                    * tf
                    * (self.k1 + 1)
                    / (tf + self.k1 * (1 - self.b + self.b * length / avg_len))
                )
            scores.append(s)
        top = max(scores) or 1.0
        top_rrf = max((c.rrf for c in candidates), default=1.0) or 1.0
        return [
            0.6 * (s / top) + 0.4 * (c.rrf / top_rrf)
            for s, c in zip(scores, candidates, strict=True)
        ]


class CrossEncoderReranker:
    """Cross-encoder (e.g. BAAI/bge-reranker-v2-m3). Needs `pip install sentence-transformers`."""

    name = "cross_encoder"

    def __init__(self, model: str) -> None:
        self.model_name = model
        self._model = None

    def _predict(self, query: str, texts: list[str]) -> list[float]:
        if self._model is None:
            try:
                from sentence_transformers import CrossEncoder
            except ImportError as e:
                raise RuntimeError(
                    "RERANKER=cross_encoder needs the 'sentence-transformers' package"
                ) from e
            self._model = CrossEncoder(self.model_name)
        raw = self._model.predict([(query, t) for t in texts])
        return [1 / (1 + math.exp(-float(x))) for x in raw]

    async def rerank(self, query: str, candidates: list[Candidate]) -> list[float]:
        if not candidates:
            return []
        return await asyncio.to_thread(
            self._predict, query, [c.chunk["content"] for c in candidates]
        )


def build_reranker(settings: Settings) -> Reranker:
    if settings.reranker == "cross_encoder":
        return CrossEncoderReranker(settings.reranker_model)
    if settings.reranker == "none":
        return NoReranker()
    return LexicalReranker()
