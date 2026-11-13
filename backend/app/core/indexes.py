"""Standard MongoDB indexes for every collection. Idempotent; run at startup.

Atlas Vector Search / Atlas Search indexes are NOT created here: they are managed by
scripts/verify_indexes.py (Phase 8) because they require Atlas and are asynchronous.
"""

from pymongo import ASCENDING as ASC
from pymongo import DESCENDING as DESC
from pymongo import IndexModel
from pymongo.asynchronous.database import AsyncDatabase

INDEXES: dict[str, list[IndexModel]] = {
    "users": [IndexModel([("email", ASC)], unique=True, name="uq_email")],
    "sessions": [
        IndexModel([("token_hash", ASC)], unique=True, name="uq_token_hash"),
        IndexModel([("expires_at", ASC)], expireAfterSeconds=0, name="ttl_expires"),
        IndexModel([("user_id", ASC)], name="by_user"),
    ],
    "password_reset_tokens": [
        IndexModel([("token_hash", ASC)], unique=True, name="uq_token_hash"),
        IndexModel([("expires_at", ASC)], expireAfterSeconds=0, name="ttl_expires"),
    ],
    "email_verification_tokens": [
        IndexModel([("token_hash", ASC)], unique=True, name="uq_token_hash"),
        IndexModel([("expires_at", ASC)], expireAfterSeconds=0, name="ttl_expires"),
    ],
    "workspaces": [IndexModel([("slug", ASC)], unique=True, name="uq_slug")],
    "memberships": [
        IndexModel([("workspace_id", ASC), ("user_id", ASC)], unique=True, name="uq_ws_user"),
        IndexModel([("user_id", ASC)], name="by_user"),
    ],
    "documents": [
        IndexModel(
            [("workspace_id", ASC), ("status", ASC), ("created_at", DESC)], name="ws_status_created"
        ),
        IndexModel([("workspace_id", ASC), ("sha256", ASC)], name="ws_sha"),
        IndexModel([("workspace_id", ASC), ("tags", ASC)], name="ws_tags"),
        IndexModel([("workspace_id", ASC), ("collection_ids", ASC)], name="ws_collections"),
        IndexModel([("workspace_id", ASC), ("deleted_at", ASC)], name="ws_deleted"),
    ],
    "document_versions": [
        IndexModel([("document_id", ASC), ("version_no", ASC)], unique=True, name="uq_doc_ver"),
        IndexModel([("workspace_id", ASC)], name="by_ws"),
    ],
    "collections": [
        IndexModel(
            [("workspace_id", ASC), ("parent_id", ASC), ("name", ASC)], unique=True, name="uq_name"
        )
    ],
    "document_chunks": [
        IndexModel(
            [("document_version_id", ASC), ("chunk_index", ASC)], unique=True, name="uq_ver_idx"
        ),
        IndexModel([("workspace_id", ASC), ("document_id", ASC)], name="ws_doc"),
        IndexModel([("chunk_id", ASC)], unique=True, name="uq_chunk_id"),
        IndexModel([("document_id", ASC), ("document_version_id", ASC)], name="doc_ver"),
        # keyword search for VECTOR_BACKEND=local (Atlas uses its own Search index)
        IndexModel(
            [("content", "text"), ("section_heading", "text")],
            name="chunk_text",
            default_language="none",
        ),
    ],
    "document_insights": [
        IndexModel([("document_version_id", ASC), ("kind", ASC)], unique=True, name="uq_ver_kind"),
        IndexModel([("workspace_id", ASC), ("document_id", ASC)], name="ws_doc"),
    ],
    "knowledge_bases": [IndexModel([("workspace_id", ASC), ("name", ASC)], name="ws_name")],
    "conversations": [
        IndexModel(
            [("workspace_id", ASC), ("user_id", ASC), ("updated_at", DESC)], name="ws_user_updated"
        )
    ],
    "messages": [IndexModel([("conversation_id", ASC), ("created_at", ASC)], name="conv_created")],
    "processing_jobs": [
        IndexModel([("workspace_id", ASC), ("state", ASC)], name="ws_state"),
        IndexModel([("state", ASC), ("updated_at", ASC)], name="state_updated"),
        IndexModel([("document_version_id", ASC)], name="by_version"),
    ],
    "research_analyses": [
        IndexModel([("workspace_id", ASC), ("created_at", DESC)], name="ws_created")
    ],
    "document_comparisons": [
        IndexModel([("workspace_id", ASC), ("created_at", DESC)], name="ws_created")
    ],
    "reports": [IndexModel([("workspace_id", ASC), ("created_at", DESC)], name="ws_created")],
    "audit_logs": [IndexModel([("workspace_id", ASC), ("created_at", DESC)], name="ws_created")],
    "usage_records": [
        IndexModel([("workspace_id", ASC), ("created_at", DESC)], name="ws_created"),
        IndexModel(
            [("workspace_id", ASC), ("kind", ASC), ("created_at", DESC)], name="ws_kind_created"
        ),
    ],
    "search_history": [
        IndexModel(
            [("workspace_id", ASC), ("user_id", ASC), ("created_at", DESC)], name="ws_user_created"
        )
    ],
}


async def ensure_indexes(db: AsyncDatabase) -> None:
    for name, models in INDEXES.items():
        await db[name].create_indexes(models)
