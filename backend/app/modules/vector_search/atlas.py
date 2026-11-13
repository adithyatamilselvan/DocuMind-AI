from typing import Any

from pymongo.asynchronous.database import AsyncDatabase

from app.core.config import Settings
from app.modules.vector_search.base import Hit, Scope, base_filter
from app.modules.vector_search.definitions import TEXT_INDEX, VECTOR_INDEX


class AtlasVectorStore:
    """MongoDB Atlas Vector Search ($vectorSearch) and Atlas Search ($search).
    Requires the indexes from definitions.py; verify them with scripts/verify_indexes.py."""

    name = "atlas"

    def __init__(self, settings: Settings) -> None:
        self.dim = settings.embedding_dim

    async def vector_search(
        self, db: AsyncDatabase, query_vector: list[float], scope: Scope, k: int
    ) -> list[Hit]:
        stage = {
            "$vectorSearch": {
                "index": VECTOR_INDEX, "path": "embedding", "queryVector": query_vector,
                "numCandidates": max(k * 15, 150), "limit": k, "filter": base_filter(scope),
            }
        }  # fmt: skip
        pipeline = [
            stage,
            {"$addFields": {"score": {"$meta": "vectorSearchScore"}}},
            {"$project": {"embedding": 0}},
        ]
        return [
            Hit(d, float(d.pop("score")), "vector")
            async for d in await db.document_chunks.aggregate(pipeline)
        ]

    async def keyword_search(
        self, db: AsyncDatabase, query: str, scope: Scope, k: int
    ) -> list[Hit]:
        if not query.strip():
            return []
        filters: list[dict[str, Any]] = [
            {"equals": {"path": "workspace_id", "value": scope.workspace_id}},
            {"equals": {"path": "is_current", "value": True}},
        ]
        if scope.document_ids is not None:
            filters.append({"in": {"path": "document_id", "value": scope.document_ids}})
        for path, value in scope.extra.items():
            filters.append({"equals": {"path": path, "value": value}})
        pipeline = [
            {
                "$search": {
                    "index": TEXT_INDEX,
                    "compound": {
                        "must": [
                            {"text": {"query": query, "path": ["content", "section_heading"]}}
                        ],
                        "filter": filters,
                    },
                }
            },
            {"$limit": k},
            {"$addFields": {"score": {"$meta": "searchScore"}}},
            {"$project": {"embedding": 0}},
        ]
        return [
            Hit(d, float(d.pop("score")), "keyword")
            async for d in await db.document_chunks.aggregate(pipeline)
        ]

    async def health(self, db: AsyncDatabase) -> dict[str, Any]:
        """Verify (never assume) that both search indexes exist and are queryable."""
        found = {i["name"]: i async for i in await db.document_chunks.list_search_indexes()}
        status = {}
        for name in (VECTOR_INDEX, TEXT_INDEX):
            idx = found.get(name)
            status[name] = {
                "exists": idx is not None,
                "queryable": bool(idx and idx.get("queryable")),
                "status": idx.get("status") if idx else None,
            }
        ready = all(v["queryable"] for v in status.values())
        return {"backend": "atlas", "ready": ready, "indexes": status, "production_ready": ready}
