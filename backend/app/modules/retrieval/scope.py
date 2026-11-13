from datetime import datetime
from typing import Any

from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase

from app.core.ids import to_oid
from app.modules.vector_search.base import Scope


async def resolve_scope(
    db: AsyncDatabase,
    workspace_id: ObjectId,
    *,
    document_ids: list[str] | None = None,
    collection_ids: list[str] | None = None,
    knowledge_base_ids: list[str] | None = None,
    category: str | None = None,
    tags: list[str] | None = None,
    mime_type: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> Scope:
    """Turn user-supplied filters into an explicit list of document ids the caller may search.

    This is the permission-filtering step: ids are always intersected with the caller's workspace
    and with non-deleted documents, so a foreign or deleted id can never widen the scope.
    With no filters the whole workspace is searched (document_ids=None)."""
    filtered = any(
        [
            document_ids,
            collection_ids,
            knowledge_base_ids,
            category,
            tags,
            mime_type,
            created_from,
            created_to,
        ]
    )
    if not filtered:
        return Scope(workspace_id=workspace_id)

    q: dict[str, Any] = {"workspace_id": workspace_id, "deleted_at": None}
    if document_ids:
        q["_id"] = {"$in": [to_oid(i, "Document") for i in document_ids]}
    if collection_ids:
        q["collection_ids"] = {"$in": [to_oid(i, "Collection") for i in collection_ids]}
    if category:
        q["category"] = category
    if tags:
        q["tags"] = {"$all": [t.lower() for t in tags]}
    if mime_type:
        q["mime_type"] = mime_type
    if created_from or created_to:
        q["created_at"] = {
            **({"$gte": created_from} if created_from else {}),
            **({"$lte": created_to} if created_to else {}),
        }
    if knowledge_base_ids:
        kb_docs: set[ObjectId] = set()
        async for kb in db.knowledge_bases.find(
            {
                "_id": {"$in": [to_oid(i, "Knowledge base") for i in knowledge_base_ids]},
                "workspace_id": workspace_id,
            }
        ):
            kb_docs.update(kb.get("document_ids", []))
        q["_id"] = (
            {"$in": list(kb_docs & set(q["_id"]["$in"]))} if "_id" in q else {"$in": list(kb_docs)}
        )

    ids = [d["_id"] async for d in db.documents.find(q, {"_id": 1}).limit(5000)]
    return Scope(workspace_id=workspace_id, document_ids=ids)
