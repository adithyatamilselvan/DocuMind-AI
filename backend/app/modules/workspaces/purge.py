"""Permanent removal of a workspace's data (database records and stored files)."""

from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase

from app.storage.base import ObjectStore

# Collections keyed by workspace_id that are removed entirely.
_WORKSPACE_COLLECTIONS = (
    "document_chunks", "document_insights", "document_versions", "documents", "collections",
    "knowledge_bases", "conversations", "messages", "processing_jobs", "research_analyses",
    "document_comparisons", "reports", "search_history", "usage_records", "memberships",
)  # fmt: skip


async def purge_workspace(db: AsyncDatabase, store: ObjectStore, workspace_id: ObjectId) -> dict[str, int]:
    """Delete stored objects first (so nothing is orphaned if a later step fails), then records.
    Audit logs are kept but detached from content (they hold no document text)."""
    keys: list[str] = []
    async for v in db.document_versions.find({"workspace_id": workspace_id}, {"storage_key": 1}):
        base = v["storage_key"].rsplit("/", 1)[0]
        keys += [v["storage_key"], base + "/extracted.json"]
    async for r in db.reports.find({"workspace_id": workspace_id}, {"exports": 1}):
        keys += [e["storage_key"] for e in r.get("exports", [])]
    for k in keys:
        await store.delete(k)
    counts: dict[str, int] = {"objects": len(keys)}
    for name in _WORKSPACE_COLLECTIONS:
        counts[name] = (await db[name].delete_many({"workspace_id": workspace_id})).deleted_count
    await db.workspaces.delete_one({"_id": workspace_id})
    return counts
