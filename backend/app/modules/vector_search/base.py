from dataclasses import dataclass, field
from typing import Any, Protocol

from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase


@dataclass
class Scope:
    """Server-resolved search scope. `document_ids` is already permission-filtered
    (workspace, not deleted, selected docs/collections/KBs); None means the whole workspace."""

    workspace_id: ObjectId
    document_ids: list[ObjectId] | None = None
    extra: dict[str, Any] = field(
        default_factory=dict
    )  # additional equality filters on chunk fields


@dataclass
class Hit:
    chunk: dict[str, Any]  # chunk document without the embedding
    score: float
    source: str  # "vector" | "keyword"


class VectorStore(Protocol):
    name: str

    async def vector_search(
        self, db: AsyncDatabase, query_vector: list[float], scope: Scope, k: int
    ) -> list[Hit]: ...

    async def keyword_search(
        self, db: AsyncDatabase, query: str, scope: Scope, k: int
    ) -> list[Hit]: ...

    async def health(self, db: AsyncDatabase) -> dict[str, Any]: ...


def base_filter(scope: Scope) -> dict[str, Any]:
    """The MongoDB filter every chunk query must include (tenant + liveness)."""
    f: dict[str, Any] = {"workspace_id": scope.workspace_id, "is_current": True, **scope.extra}
    if scope.document_ids is not None:
        f["document_id"] = {"$in": scope.document_ids}
    return f
