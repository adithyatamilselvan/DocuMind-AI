"""Small helpers shared by the async AI job handlers."""

import json
from typing import Any

from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase

from app.core.ids import utcnow
from app.modules.extraction.models import ExtractedDocument
from app.modules.ingestion.errors import PermanentError
from app.storage.base import ObjectNotFoundError, ObjectStore


async def set_job(db: AsyncDatabase, job_id: ObjectId, state: str, **fields: Any) -> None:
    await db.processing_jobs.update_one(
        {"_id": job_id}, {"$set": {"state": state, "updated_at": utcnow(), **fields}}
    )


async def load_extracted_doc(store: ObjectStore, version: dict[str, Any]) -> ExtractedDocument:
    from app.modules.ingestion.stages import extracted_key

    try:
        raw = await store.get_bytes(extracted_key(version["storage_key"]))
    except ObjectNotFoundError as e:
        raise PermanentError("The document text is not available; reprocess the document") from e
    return ExtractedDocument.from_json(json.loads(raw))


def ai_unavailable_reason(settings: Any, workspace: dict[str, Any] | None) -> str | None:
    if not settings.llm_configured:
        return "AI features are not configured on this server (missing LLM API key)."
    if settings.ai_external and not (
        workspace and workspace.get("settings", {}).get("ai_processing_consent")
    ):
        return "External AI processing is not enabled for this workspace."
    return None
