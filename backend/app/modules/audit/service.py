from typing import Any

from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase

from app.core.ids import utcnow
from app.core.request_context import request_id_var


async def record(
    db: AsyncDatabase,
    *,
    action: str,
    actor_id: ObjectId | None,
    workspace_id: ObjectId | None = None,
    target: dict[str, Any] | None = None,
    ip: str | None = None,
) -> None:
    """Append an audit entry. Never put secrets or document contents in `target`."""
    await db.audit_logs.insert_one(
        {
            "workspace_id": workspace_id,
            "actor_id": actor_id,
            "action": action,
            "target": target or {},
            "ip": ip,
            "request_id": request_id_var.get(),
            "created_at": utcnow(),
        }
    )
