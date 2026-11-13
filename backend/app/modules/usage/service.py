from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase

from app.core.ids import utcnow


async def record_usage(
    db: AsyncDatabase,
    *,
    workspace_id: ObjectId,
    kind: str,  # embedding | chat | insight | research | comparison | report | rerank
    provider: str,
    model: str,
    tokens_in: int = 0,
    tokens_out: int = 0,
    latency_ms: int | None = None,
    user_id: ObjectId | None = None,
    meta: dict | None = None,
) -> None:
    """One row per external AI call. Never store prompts or document text here."""
    await db.usage_records.insert_one(
        {
            "workspace_id": workspace_id, "user_id": user_id, "kind": kind, "provider": provider,
            "model": model, "tokens_in": tokens_in, "tokens_out": tokens_out,
            "latency_ms": latency_ms, "meta": meta or {}, "created_at": utcnow(),
        }
    )  # fmt: skip
