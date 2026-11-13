import heapq
import logging
from typing import Any

import numpy as np
from pymongo.asynchronous.database import AsyncDatabase

from app.modules.vector_search.base import Hit, Scope, base_filter

log = logging.getLogger("documind.vector.local")
BLOCK = 2000


class LocalVectorStore:
    """Development-only backend (plain MongoDB, no Atlas): workspace-filtered scan with cosine
    similarity in numpy, hard-capped at `scan_limit` chunks, plus a `$text` keyword search.
    Not for production: use AtlasVectorStore."""

    name = "local"

    def __init__(self, scan_limit: int = 20000) -> None:
        self.scan_limit = scan_limit

    async def vector_search(
        self, db: AsyncDatabase, query_vector: list[float], scope: Scope, k: int
    ) -> list[Hit]:
        q = np.asarray(query_vector, dtype=np.float32)
        qn = float(np.linalg.norm(q)) or 1.0
        top: list[tuple[float, int, dict[str, Any]]] = []
        scanned, counter = 0, 0
        ids: list[Any] = []
        mats: list[list[float]] = []

        async def score_block() -> None:
            nonlocal counter
            if not mats:
                return
            m = np.asarray(mats, dtype=np.float32)
            sims = (m @ q) / ((np.linalg.norm(m, axis=1) * qn) + 1e-12)
            for sim, doc in zip(sims.tolist(), ids, strict=True):
                counter += 1
                item = (sim, counter, doc)
                if len(top) < k:
                    heapq.heappush(top, item)
                elif sim > top[0][0]:
                    heapq.heapreplace(top, item)
            mats.clear()
            ids.clear()

        filt = {**base_filter(scope), "embedding": {"$ne": None}}
        async for doc in db.document_chunks.find(filt).limit(self.scan_limit):
            scanned += 1
            vec = doc.pop("embedding")
            if len(vec) != len(query_vector):
                continue  # chunk from another embedding model/dimension: never mix
            mats.append(vec)
            ids.append(doc)
            if len(mats) >= BLOCK:
                await score_block()
        await score_block()
        if scanned >= self.scan_limit:
            log.warning(
                "Local vector scan hit its cap (%s); results may be incomplete", self.scan_limit
            )
        return [Hit(d, s, "vector") for s, _, d in sorted(top, reverse=True)]

    async def keyword_search(
        self, db: AsyncDatabase, query: str, scope: Scope, k: int
    ) -> list[Hit]:
        if not query.strip():
            return []
        filt = {**base_filter(scope), "$text": {"$search": query}}
        cursor = (
            db.document_chunks.find(filt, {"embedding": 0, "score": {"$meta": "textScore"}})
            .sort([("score", {"$meta": "textScore"})])
            .limit(k)
        )
        return [Hit(d, float(d.pop("score")), "keyword") async for d in cursor]

    async def health(self, db: AsyncDatabase) -> dict[str, Any]:
        return {
            "backend": "local",
            "ready": True,
            "scan_limit": self.scan_limit,
            "production_ready": False,
        }
