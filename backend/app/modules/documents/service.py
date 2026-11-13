import re
from typing import Any

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING
from pymongo.asynchronous.database import AsyncDatabase

from app.core.errors import bad_request, conflict, not_found
from app.core.ids import to_oid, utcnow
from app.modules.documents.schemas import BulkIn, DocumentQuery, UpdateDocumentIn
from app.modules.documents.states import TRANSITIONS, DocumentStatus


def _live(workspace_id: ObjectId) -> dict[str, Any]:
    return {"workspace_id": workspace_id, "deleted_at": None}


async def create_document(
    db: AsyncDatabase,
    *,
    workspace_id: ObjectId,
    owner_id: ObjectId,
    filename: str,
    title: str,
    mime_type: str,
    size_bytes: int,
    sha256: str,
    storage_key: str,
    status: DocumentStatus = DocumentStatus.UPLOADING,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Insert a document and its first version. Returns (document, version)."""
    now = utcnow()
    doc: dict[str, Any] = {
        "workspace_id": workspace_id, "owner_id": owner_id, "title": title,
        "filename": filename, "mime_type": mime_type, "size_bytes": size_bytes,
        "sha256": sha256, "status": status.value, "error": None, "category": None,
        "tags": [], "collection_ids": [], "page_count": None, "language": None,
        "current_version_id": None, "version_count": 1, "access_count": 0,
        "last_accessed_at": None, "deleted_at": None, "created_at": now, "updated_at": now,
    }  # fmt: skip
    doc["_id"] = (await db.documents.insert_one(doc)).inserted_id
    version: dict[str, Any] = {
        "document_id": doc["_id"], "workspace_id": workspace_id, "version_no": 1,
        "storage_key": storage_key, "sha256": sha256, "size_bytes": size_bytes,
        "mime_type": mime_type, "filename": filename, "created_by": owner_id,
        "created_at": now,
    }  # fmt: skip
    version["_id"] = (await db.document_versions.insert_one(version)).inserted_id
    await db.documents.update_one(
        {"_id": doc["_id"]}, {"$set": {"current_version_id": version["_id"]}}
    )
    doc["current_version_id"] = version["_id"]
    return doc, version


async def set_status(
    db: AsyncDatabase, document_id: ObjectId, new: DocumentStatus, **fields: Any
) -> bool:
    """Atomic validated transition: only applies if the current status may move to `new`."""
    allowed_from = [s.value for s, targets in TRANSITIONS.items() if new in targets]
    update: dict[str, Any] = {"status": new.value, "updated_at": utcnow(), **fields}
    if new != DocumentStatus.FAILED:
        update.setdefault("error", None)
    res = await db.documents.update_one(
        {"_id": document_id, "status": {"$in": allowed_from}, "deleted_at": None}, {"$set": update}
    )
    return res.modified_count == 1


def _build_filter(workspace_id: ObjectId, q: DocumentQuery) -> dict[str, Any]:
    f = _live(workspace_id)
    if q.q:
        rx = {"$regex": re.escape(q.q.strip()), "$options": "i"}
        f["$or"] = [{"title": rx}, {"filename": rx}]
    if q.status:
        f["status"] = q.status.value
    if q.category:
        f["category"] = q.category
    if q.tag:
        f["tags"] = q.tag.lower()
    if q.collection_id:
        f["collection_ids"] = to_oid(q.collection_id, "Collection")
    if q.mime_type:
        f["mime_type"] = q.mime_type
    if q.created_from or q.created_to:
        rng: dict[str, Any] = {}
        if q.created_from:
            rng["$gte"] = q.created_from
        if q.created_to:
            rng["$lte"] = q.created_to
        f["created_at"] = rng
    return f


async def list_documents(
    db: AsyncDatabase, workspace_id: ObjectId, q: DocumentQuery, skip: int, limit: int
) -> tuple[list[dict[str, Any]], int]:
    f = _build_filter(workspace_id, q)
    direction = ASCENDING if q.order == "asc" else DESCENDING
    cursor = (
        db.documents.find(f).sort([(q.sort, direction), ("_id", direction)]).skip(skip).limit(limit)
    )
    return [d async for d in cursor], await db.documents.count_documents(f)


async def get_document(
    db: AsyncDatabase, workspace_id: ObjectId, document_id: str, *, touch: bool = False
) -> dict[str, Any]:
    oid = to_oid(document_id, "Document")
    update = (
        {"$inc": {"access_count": 1}, "$set": {"last_accessed_at": utcnow()}} if touch else None
    )
    if update:
        doc = await db.documents.find_one_and_update(
            {"_id": oid, **_live(workspace_id)}, update, return_document=True
        )
    else:
        doc = await db.documents.find_one({"_id": oid, **_live(workspace_id)})
    if not doc:
        raise not_found("Document not found")
    return doc


async def _valid_collection_ids(
    db: AsyncDatabase, workspace_id: ObjectId, ids: list[str]
) -> list[ObjectId]:
    oids = [to_oid(i, "Collection") for i in dict.fromkeys(ids)]
    found = await db.collections.count_documents(
        {"_id": {"$in": oids}, "workspace_id": workspace_id}
    )
    if found != len(oids):
        raise bad_request("Unknown collection", "invalid_collection")
    return oids


async def update_document(
    db: AsyncDatabase, workspace_id: ObjectId, document_id: str, body: UpdateDocumentIn
) -> dict[str, Any]:
    patch: dict[str, Any] = {"updated_at": utcnow()}
    fields = body.model_fields_set
    if "title" in fields and body.title is not None:
        patch["title"] = body.title.strip()
    if "category" in fields:
        patch["category"] = (body.category or "").strip() or None
    if "tags" in fields and body.tags is not None:
        patch["tags"] = body.tags
    if "collection_ids" in fields and body.collection_ids is not None:
        patch["collection_ids"] = await _valid_collection_ids(db, workspace_id, body.collection_ids)
    doc = await db.documents.find_one_and_update(
        {"_id": to_oid(document_id, "Document"), **_live(workspace_id)},
        {"$set": patch},
        return_document=True,
    )
    if not doc:
        raise not_found("Document not found")
    return doc


async def delete_documents(db: AsyncDatabase, workspace_id: ObjectId, ids: list[ObjectId]) -> int:
    """Soft-delete documents and IMMEDIATELY hard-delete their chunks/insights so deleted
    content can never be retrieved. Object-store purge is handled by a background job."""
    now = utcnow()
    res = await db.documents.update_many(
        {"_id": {"$in": ids}, **_live(workspace_id)},
        {"$set": {"deleted_at": now, "updated_at": now}},
    )
    if res.modified_count:
        scope = {"workspace_id": workspace_id, "document_id": {"$in": ids}}
        await db.document_chunks.delete_many(scope)
        await db.document_insights.delete_many(scope)
        await db.knowledge_bases.update_many(
            {"workspace_id": workspace_id}, {"$pull": {"document_ids": {"$in": ids}}}
        )
    return res.modified_count


async def bulk(db: AsyncDatabase, workspace_id: ObjectId, body: BulkIn) -> int:
    ids = [to_oid(i, "Document") for i in dict.fromkeys(body.ids)]
    scope = {"_id": {"$in": ids}, **_live(workspace_id)}
    now = utcnow()
    match body.action:
        case "delete":
            return await delete_documents(db, workspace_id, ids)
        case "add_tags" | "remove_tags":
            if not body.tags:
                raise bad_request("tags are required", "missing_tags")
            op = "$addToSet" if body.action == "add_tags" else "$pullAll"
            val: Any = {"tags": {"$each": body.tags}} if op == "$addToSet" else {"tags": body.tags}
            res = await db.documents.update_many(scope, {op: val, "$set": {"updated_at": now}})
        case "add_to_collection" | "remove_from_collection":
            if not body.collection_id:
                raise bad_request("collection_id is required", "missing_collection")
            (cid,) = await _valid_collection_ids(db, workspace_id, [body.collection_id])
            op = "$addToSet" if body.action == "add_to_collection" else "$pull"
            res = await db.documents.update_many(
                scope, {op: {"collection_ids": cid}, "$set": {"updated_at": now}}
            )
        case "set_category":
            res = await db.documents.update_many(
                scope,
                {"$set": {"category": (body.category or "").strip() or None, "updated_at": now}},
            )
    return res.matched_count


async def ensure_not_in_progress(doc: dict[str, Any]) -> None:
    from app.modules.documents.states import IN_PROGRESS

    if DocumentStatus(doc["status"]) in IN_PROGRESS:
        raise conflict("Document is still being processed", "in_progress")
