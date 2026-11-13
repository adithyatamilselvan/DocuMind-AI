from datetime import datetime
from typing import Any

from bson import ObjectId
from pydantic import BaseModel, Field
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DuplicateKeyError

from app.core.errors import bad_request, conflict, not_found
from app.core.ids import PyId, to_oid, utcnow


class CollectionOut(BaseModel):
    id: PyId
    name: str
    parent_id: PyId | None
    document_count: int = 0
    created_at: datetime


class CreateCollectionIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    parent_id: str | None = None


class UpdateCollectionIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


async def list_collections(db: AsyncDatabase, workspace_id: ObjectId) -> list[CollectionOut]:
    counts: dict[ObjectId, int] = {}
    async for row in await db.documents.aggregate(
        [
            {"$match": {"workspace_id": workspace_id, "deleted_at": None}},
            {"$unwind": "$collection_ids"},
            {"$group": {"_id": "$collection_ids", "n": {"$sum": 1}}},
        ]
    ):
        counts[row["_id"]] = row["n"]
    return [
        CollectionOut(
            id=c["_id"],
            name=c["name"],
            parent_id=c.get("parent_id"),
            document_count=counts.get(c["_id"], 0),
            created_at=c["created_at"],
        )  # fmt: skip
        async for c in db.collections.find({"workspace_id": workspace_id}).sort("name", 1)
    ]


async def create_collection(
    db: AsyncDatabase, workspace_id: ObjectId, body: CreateCollectionIn
) -> dict[str, Any]:
    parent = None
    if body.parent_id:
        parent = to_oid(body.parent_id, "Collection")
        if not await db.collections.find_one({"_id": parent, "workspace_id": workspace_id}):
            raise bad_request("Unknown parent collection", "invalid_parent")
    now = utcnow()
    doc = {
        "workspace_id": workspace_id, "name": body.name.strip(), "parent_id": parent,
        "created_at": now, "updated_at": now,
    }  # fmt: skip
    try:
        doc["_id"] = (await db.collections.insert_one(doc)).inserted_id
    except DuplicateKeyError:
        raise conflict(
            "A collection with that name already exists here", "duplicate_name"
        ) from None
    return doc


async def rename_collection(
    db: AsyncDatabase, workspace_id: ObjectId, collection_id: str, name: str
) -> dict[str, Any]:
    try:
        doc = await db.collections.find_one_and_update(
            {"_id": to_oid(collection_id, "Collection"), "workspace_id": workspace_id},
            {"$set": {"name": name.strip(), "updated_at": utcnow()}},
            return_document=True,
        )
    except DuplicateKeyError:
        raise conflict(
            "A collection with that name already exists here", "duplicate_name"
        ) from None
    if not doc:
        raise not_found("Collection not found")
    return doc


async def delete_collection(db: AsyncDatabase, workspace_id: ObjectId, collection_id: str) -> None:
    oid = to_oid(collection_id, "Collection")
    if not await db.collections.find_one({"_id": oid, "workspace_id": workspace_id}):
        raise not_found("Collection not found")
    if await db.collections.find_one({"parent_id": oid, "workspace_id": workspace_id}):
        raise conflict("Delete or move the sub-collections first", "has_children")
    await db.documents.update_many(
        {"workspace_id": workspace_id}, {"$pull": {"collection_ids": oid}}
    )
    await db.collections.delete_one({"_id": oid})
